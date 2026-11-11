# herdogroco/web.py
"""aiohttp app: MCP endpoint, OAuth endpoints and discovery documents."""

import asyncio
import json
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiohttp import web

from . import MCP_PATH, OAUTH_PATH, RESOURCE_METADATA_PATH, SCOPE, SERVER_METADATA_PATH, pages, store, tokens
from .gateway import PROTOCOLS, Gateway
from .hermes import Hermes
from .oauth import OAuthAuthority, OAuthError, allowed_callback

log = logging.getLogger("herdogroco")
RT = web.AppKey("rt", object)
NO_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
FORM_CSP = ("default-src 'none'; style-src {style}; form-action 'self' {origin}; "
            "base-uri 'none'; frame-ancestors 'none'")
GROK_ORIGINS = ("https://grok.com", "https://www.grok.com")
MAX_BODY = 16384


class Runtime:
    def __init__(self, cfg, hermes=None, clock=time.time):
        self.cfg = cfg
        self.state_path = cfg.data_dir / "oauth.json"
        self.pairing = store.Pairing(cfg.data_dir / "pairing.json", clock)
        self.authority = OAuthAuthority(cfg.public_url, store.load(self.state_path, {}), self.pairing, clock)
        self.hermes = hermes or Hermes(cfg)
        self.gateway = Gateway(self.hermes)
        self.token_lock = asyncio.Lock()
        self.rates = {}
        self.clock = clock

    def save(self):
        store.save(self.state_path, self.authority.snapshot())

    def rate_ok(self, bucket, limit, window=60):
        now = self.clock()
        hits = [t for t in self.rates.get(bucket, []) if t > now - window]
        if len(hits) >= limit:
            self.rates[bucket] = hits
            return False
        self.rates[bucket] = [*hits, now]
        if len(self.rates) > 512:
            self.rates = {k: v for k, v in self.rates.items() if v and v[-1] > now - window}
        return True


def rt(request) -> Runtime:
    return request.app[RT]


def limit(request, bucket, n, window=60):
    if not rt(request).rate_ok(bucket, n, window):
        raise web.HTTPTooManyRequests(headers={**NO_CACHE, "Retry-After": str(window)})


def check_origin(request, *, mcp=False):
    allowed = {rt(request).authority.base_url, *(GROK_ORIGINS if mcp else ())}
    if (origin := request.headers.get("Origin")) and origin not in allowed:
        raise web.HTTPForbidden(text="Origin denied")


async def read_body(request):
    body = bytearray()
    async for chunk in request.content.iter_chunked(4096):
        body.extend(chunk)
        if len(body) > MAX_BODY:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=len(body))
    try:
        return body.decode("utf-8")
    except UnicodeError:
        raise web.HTTPBadRequest(text="UTF-8 required") from None


def unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate key")
        out[k] = v
    return out


async def read_json(request):
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType()
    try:
        return json.loads(await read_body(request), object_pairs_hook=unique)
    except (ValueError, RecursionError):
        raise web.HTTPBadRequest(text="Invalid JSON") from None


async def read_form(request):
    if request.content_type != "application/x-www-form-urlencoded":
        raise web.HTTPUnsupportedMediaType()
    try:
        return unique(parse_qsl(await read_body(request), keep_blank_values=True, max_num_fields=20))
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid form") from None


def tx_cookie(tx):
    return "herdogroco_tx_" + re.sub(r"[^A-Za-z0-9]", "", tx)[:16]


def bearer(request):
    check_origin(request, mcp=True)
    principal = tokens.authenticate(rt(request).authority, request.headers.get("Authorization"))
    if principal is None:
        raise web.HTTPUnauthorized(headers={**NO_CACHE, "WWW-Authenticate":
            f'Bearer resource_metadata="{rt(request).authority.base_url}{RESOURCE_METADATA_PATH}"'})
    if any(k in request.query for k in ("access_token", "token", "authSig")):
        raise web.HTTPBadRequest(text="Credentials must be in the Authorization header")
    limit(request, "mcp:" + principal, 60)
    return principal


async def mcp_post(request):
    principal = bearer(request)
    gw = rt(request).gateway
    session = request.headers.get("MCP-Session-Id")
    if session is not None and not gw.session_active(session, principal):
        raise web.HTTPNotFound(text="MCP session expired", headers=NO_CACHE)
    if "application/json" not in request.headers.get("Accept", ""):
        raise web.HTTPNotAcceptable(text="Client must accept application/json")
    version = request.headers.get("MCP-Protocol-Version")
    if version is not None and version not in PROTOCOLS:
        raise web.HTTPBadRequest(text="Unsupported MCP protocol version")
    message = await read_json(request)
    # Shield: a client disconnect must not cancel a task Hermes already accepted.
    response = await asyncio.shield(asyncio.ensure_future(gw.rpc(message, principal, session)))
    if response is None:
        return web.Response(status=202, headers=NO_CACHE)
    headers = dict(NO_CACHE)
    if isinstance(message, dict) and message.get("method") == "initialize" and "result" in response:
        headers["MCP-Session-Id"] = gw.open_session(principal)
    return web.json_response(response, headers=headers)


async def mcp_get(request):
    bearer(request)
    raise web.HTTPMethodNotAllowed("GET", ["POST"], headers=NO_CACHE)


async def mcp_delete(request):
    principal = bearer(request)
    session = request.headers.get("MCP-Session-Id")
    if session is None:
        raise web.HTTPBadRequest(text="MCP-Session-Id required", headers=NO_CACHE)
    if rt(request).gateway.session_active(session, principal):
        rt(request).gateway.close_session(session)
    return web.Response(status=204, headers=NO_CACHE)


async def resource_metadata(request):
    a = rt(request).authority
    return web.json_response({"resource": a.resource, "resource_name": "Hermes agent (profile grokovo)",
                              "authorization_servers": [a.issuer], "scopes_supported": [SCOPE],
                              "bearer_methods_supported": ["header"]}, headers=NO_CACHE)


async def server_metadata(request):
    issuer = rt(request).authority.issuer
    return web.json_response({
        "issuer": issuer, "authorization_endpoint": issuer + "/authorize",
        "token_endpoint": issuer + "/token", "registration_endpoint": issuer + "/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"], "scopes_supported": [SCOPE]}, headers=NO_CACHE)


async def register(request):
    check_origin(request, mcp=True)
    limit(request, "register", 32, 3600)
    data = await read_json(request)
    if not isinstance(data, dict):
        raise web.HTTPBadRequest()
    try:
        return web.json_response(rt(request).authority.register(data), status=201, headers=NO_CACHE)
    except OAuthError as err:
        return web.json_response({"error": err.error}, status=400, headers=NO_CACHE)


def form_headers(callback):
    if not allowed_callback(callback):
        raise OAuthError("invalid_client")
    p = urlsplit(callback)
    origin = "https://" + p.hostname + (":443" if p.port == 443 else "")
    return {**NO_CACHE, "Referrer-Policy": "same-origin",
            "Content-Security-Policy": FORM_CSP.format(style=pages.STYLE_SOURCE, origin=origin)}


async def authorize_get(request):
    limit(request, "authorize", 60)
    a = rt(request).authority
    try:
        params = unique(request.query.items())
        headers = form_headers(params.get("redirect_uri", ""))
        tx = a.begin(params)
    except (OAuthError, ValueError):
        return web.Response(text="Invalid authorization request", status=400, headers=NO_CACHE)
    resp = web.Response(text=pages.render(params["redirect_uri"], tx), content_type="text/html", headers=headers)
    resp.set_cookie(tx_cookie(tx), tx, max_age=600, path=OAUTH_PATH, secure=True, httponly=True, samesite="Lax")
    return resp


async def authorize_post(request):
    check_origin(request)
    limit(request, "authorize", 60)
    data = await read_form(request)
    tx = data.get("transaction", "")
    if not tx or tx != request.cookies.get(tx_cookie(tx)):
        raise web.HTTPForbidden(text="Invalid transaction")
    try:
        redirect, code, state = rt(request).authority.approve(tx, data.get("pairing_secret", ""))
    except OAuthError:
        return web.Response(text="Invalid or expired pairing code", status=403, headers=NO_CACHE)
    p = urlsplit(redirect)
    query = urlencode([*parse_qsl(p.query), ("code", code), ("state", state)])
    resp = web.HTTPSeeOther(location=urlunsplit((p.scheme, p.netloc, p.path, query, "")),
                            headers={**NO_CACHE, "Referrer-Policy": "no-referrer"})
    resp.del_cookie(tx_cookie(tx), path=OAUTH_PATH)
    return resp


async def token(request):
    check_origin(request, mcp=True)
    limit(request, "token", 120)
    data = await read_form(request)
    r = rt(request)
    async with r.token_lock:
        try:
            result = tokens.issue(r.authority, data)
        except OAuthError as err:
            r.save()  # a refresh replay revokes a family; persist it
            return web.json_response({"error": err.error}, status=400, headers=NO_CACHE)
        r.save()
    return web.json_response(result, headers=NO_CACHE)


async def health(request):
    return web.json_response({"status": "ok"})


def make_app(runtime: Runtime) -> web.Application:
    app = web.Application(client_max_size=MAX_BODY)
    app[RT] = runtime
    app.router.add_post(MCP_PATH, mcp_post)
    app.router.add_get(MCP_PATH, mcp_get)
    app.router.add_delete(MCP_PATH, mcp_delete)
    app.router.add_get(RESOURCE_METADATA_PATH, resource_metadata)
    app.router.add_get(SERVER_METADATA_PATH, server_metadata)
    app.router.add_get(OAUTH_PATH + "/.well-known/oauth-authorization-server", server_metadata)
    app.router.add_post(OAUTH_PATH + "/register", register)
    app.router.add_get(OAUTH_PATH + "/authorize", authorize_get)
    app.router.add_post(OAUTH_PATH + "/authorize", authorize_post)
    app.router.add_post(OAUTH_PATH + "/token", token)
    app.router.add_get("/health", health)

    async def close(app):
        await runtime.hermes.close()

    app.on_cleanup.append(close)
    return app
