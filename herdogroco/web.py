# herdogroco/web.py
"""aiohttp app: request-id + access-log middleware, MCP endpoint and routing."""

import asyncio
import json
import logging
import secrets
import time

from aiohttp import web

from . import (
    MCP_PATH,
    OAUTH_PATH,
    RESOURCE_METADATA_PATH,
    SERVER_METADATA_PATH,
    logsetup,
    oauth_views,
    tokens,
)
from .gateway import PROTOCOLS
from .httpkit import MAX_BODY, NO_CACHE, RT, Runtime, check_origin, limit, read_json, rt

log = logging.getLogger("herdogroco.mcp")
access = logging.getLogger("herdogroco.access")
__all__ = ["Runtime", "make_app"]


def _request_id(request):
    supplied = request.headers.get("X-Request-Id", "")
    return supplied[:32] if supplied.isalnum() else secrets.token_hex(4)


@web.middleware
async def observe(request, handler):
    """Assign a request id, log one line per request (DEBUG adds safe headers) and echo the id."""
    rid = _request_id(request)
    ctx = logsetup.request_id.set(rid)
    started = time.monotonic()
    status, error = 500, None
    try:
        response = await handler(request)
        status = response.status
        response.headers["X-Request-Id"] = rid
        return response
    except web.HTTPException as err:
        status, error = err.status, type(err).__name__
        err.headers["X-Request-Id"] = rid
        raise
    except asyncio.CancelledError:
        status, error = 499, "client_disconnected"
        raise
    except Exception:
        log.exception("unhandled error")
        raise
    finally:
        level = logging.INFO if status < 400 else logging.WARNING if status < 500 else logging.ERROR
        if request.path == "/health" and status < 400:
            level = logging.DEBUG
        ip = request.headers.get("X-Forwarded-For", request.remote or "-").split(",")[0].strip()
        logsetup.event(access, "http", level, method=request.method, path=request.path, status=status,
                       ms=round((time.monotonic() - started) * 1000), ip=ip,
                       ua=request.headers.get("User-Agent", "")[:80], error=error, **_debug_headers(request))
        logsetup.request_id.reset(ctx)


def _debug_headers(request):
    if not access.isEnabledFor(logging.DEBUG):
        return {}
    keep = ("Origin", "Referer", "Accept", "Content-Type", "MCP-Protocol-Version", "Sec-Fetch-Site",
            "Sec-Fetch-Mode", "X-Forwarded-Proto", "CF-Connecting-IP")
    return {"headers": {h: request.headers[h][:120] for h in keep if h in request.headers},
            "has_auth": "Authorization" in request.headers, "has_session": "MCP-Session-Id" in request.headers,
            "query_keys": sorted(request.query)}


def bearer(request):
    check_origin(request, mcp=True)
    auth = request.headers.get("Authorization")
    principal = tokens.authenticate(rt(request).authority, auth)
    if principal is None:
        logsetup.event(log, "mcp.bearer_rejected", logging.WARNING,
                       reason="no_authorization_header" if not auth else "invalid_or_expired_token")
        raise web.HTTPUnauthorized(headers={**NO_CACHE, "WWW-Authenticate":
            f'Bearer resource_metadata="{rt(request).authority.base_url}{RESOURCE_METADATA_PATH}"'})
    if any(k in request.query for k in ("access_token", "token", "authSig")):
        logsetup.event(log, "mcp.url_credentials_rejected", logging.WARNING)
        raise web.HTTPBadRequest(text="Credentials must be in the Authorization header")
    limit(request, "mcp:" + principal, 60)
    return principal


def _describe(message):
    """Safe summary of a JSON-RPC message; task text only when LOG_CONTENT is on."""
    if not isinstance(message, dict):
        return {"rpc": "invalid"}
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    info = {"rpc": message.get("method"), "rpc_id": message.get("id")}
    if message.get("method") == "tools/call":
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        info.update(tool=params.get("name"), arg_keys=sorted(args))
        if "request" in args:
            info["request"] = logsetup.content(args["request"])
        if "task_id" in args:
            info["task_id"] = str(args["task_id"])[:50]
    elif message.get("method") == "initialize":
        info.update(protocol=params.get("protocolVersion"), client_info=params.get("clientInfo"))
    return info


async def mcp_post(request):
    principal = bearer(request)
    gw = rt(request).gateway
    session = request.headers.get("MCP-Session-Id")
    if session is not None and not gw.session_active(session, principal):
        logsetup.event(log, "mcp.session_unknown", logging.WARNING, session=logsetup.short(session))
        raise web.HTTPNotFound(text="MCP session expired", headers=NO_CACHE)
    if "application/json" not in request.headers.get("Accept", ""):
        logsetup.event(log, "mcp.not_acceptable", logging.WARNING, accept=request.headers.get("Accept", "")[:80])
        raise web.HTTPNotAcceptable(text="Client must accept application/json")
    version = request.headers.get("MCP-Protocol-Version")
    if version is not None and version not in PROTOCOLS:
        logsetup.event(log, "mcp.bad_protocol", logging.WARNING, version=version[:20])
        raise web.HTTPBadRequest(text="Unsupported MCP protocol version")
    message = await read_json(request)
    started = time.monotonic()
    logsetup.event(log, "mcp.request", client=logsetup.short(principal), session=logsetup.short(session) if session else None,
                   **_describe(message))
    # Shield: a client disconnect must not cancel a task Hermes already accepted.
    response = await asyncio.shield(asyncio.ensure_future(gw.rpc(message, principal, session)))
    ms = round((time.monotonic() - started) * 1000)
    if response is None:
        logsetup.event(log, "mcp.notification", logging.DEBUG, **_describe(message))
        return web.Response(status=202, headers=NO_CACHE)
    headers = dict(NO_CACHE)
    if isinstance(message, dict) and message.get("method") == "initialize" and "result" in response:
        headers["MCP-Session-Id"] = sid = gw.open_session(principal)
        logsetup.event(log, "mcp.session_opened", session=logsetup.short(sid), sessions=len(gw.sessions))
    logsetup.event(log, "mcp.response", logging.WARNING if "error" in response else logging.INFO, ms=ms,
                   rpc=message.get("method") if isinstance(message, dict) else None,
                   rpc_error=response.get("error"),
                   tool_error=bool(response.get("result", {}).get("isError")))
    if log.isEnabledFor(logging.DEBUG):
        logsetup.event(log, "mcp.response_body", logging.DEBUG, body=logsetup.content(json.dumps(response)))
    return web.json_response(response, headers=headers)


async def mcp_get(request):
    bearer(request)
    raise web.HTTPMethodNotAllowed("GET", ["POST"], headers=NO_CACHE)


async def mcp_delete(request):
    principal = bearer(request)
    session = request.headers.get("MCP-Session-Id")
    if session is None:
        raise web.HTTPBadRequest(text="MCP-Session-Id required", headers=NO_CACHE)
    gw = rt(request).gateway
    if gw.session_active(session, principal):
        gw.close_session(session)
        logsetup.event(log, "mcp.session_closed", session=logsetup.short(session))
    return web.Response(status=204, headers=NO_CACHE)


def make_app(runtime: Runtime) -> web.Application:
    app = web.Application(client_max_size=MAX_BODY, middlewares=[observe])
    app[RT] = runtime
    v = oauth_views
    app.router.add_post(MCP_PATH, mcp_post)
    app.router.add_get(MCP_PATH, mcp_get)
    app.router.add_delete(MCP_PATH, mcp_delete)
    app.router.add_get(RESOURCE_METADATA_PATH, v.resource_metadata)
    app.router.add_get(SERVER_METADATA_PATH, v.server_metadata)
    app.router.add_get(OAUTH_PATH + "/.well-known/oauth-authorization-server", v.server_metadata)
    app.router.add_post(OAUTH_PATH + "/register", v.register)
    app.router.add_get(OAUTH_PATH + "/authorize", v.authorize_get)
    app.router.add_post(OAUTH_PATH + "/authorize", v.authorize_post)
    app.router.add_post(OAUTH_PATH + "/token", v.token)
    app.router.add_get("/health", v.health)

    async def close(app):
        await runtime.hermes.close()

    app.on_cleanup.append(close)
    return app
