# herdogroco/oauth_views.py
"""OAuth + discovery HTTP handlers. Every outcome is logged with the reason, never with secrets.

The endpoint flow (register, authorize, token) follows grok_connector (http.py),
MIT, (c) 2026 Jenik5. See LICENSE.
"""

import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiohttp import web

from . import OAUTH_PATH, RESOURCE_METADATA_PATH, SCOPE, logsetup, pages, tokens
from .httpkit import NO_CACHE, check_origin, limit, read_form, read_json, rt, unique
from .oauth import OAuthError, allowed_callback

log = logging.getLogger("herdogroco.oauth")
FORM_CSP = ("default-src 'none'; style-src {style}; form-action 'self' {origin}; "
            "base-uri 'none'; frame-ancestors 'none'")


def error_page(status, title, message):
    return web.Response(text=pages.render_error(title, message), status=status, content_type="text/html",
                        headers={**NO_CACHE, "Content-Security-Policy": pages.STATIC_CSP})


def tx_cookie(tx):
    return "herdogroco_tx_" + re.sub(r"[^A-Za-z0-9]", "", tx)[:16]


def form_headers(callback):
    if not allowed_callback(callback):
        raise OAuthError("invalid_client", "callback_not_allowed:" + str(callback)[:80])
    p = urlsplit(callback)
    origin = "https://" + p.hostname + (":443" if p.port == 443 else "")
    return {**NO_CACHE, "Referrer-Policy": "same-origin",
            "Content-Security-Policy": FORM_CSP.format(style=pages.STYLE_SOURCE, origin=origin)}


async def resource_metadata(request):
    a = rt(request).authority
    logsetup.event(log, "discovery.resource_metadata", logging.DEBUG, ua=request.headers.get("User-Agent", "")[:80])
    return web.json_response({"resource": a.resource, "resource_name": "Hermes agent (profile grokovo)",
                              "authorization_servers": [a.issuer], "scopes_supported": [SCOPE],
                              "bearer_methods_supported": ["header"]}, headers=NO_CACHE)


async def server_metadata(request):
    issuer = rt(request).authority.issuer
    logsetup.event(log, "discovery.server_metadata", logging.DEBUG, ua=request.headers.get("User-Agent", "")[:80])
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
    logsetup.event(log, "register.request", logging.DEBUG, redirect_uris=data.get("redirect_uris"),
                   client_name=str(data.get("client_name", ""))[:60], keys=sorted(data))
    try:
        result = rt(request).authority.register(data)
    except OAuthError as err:
        logsetup.event(log, "register.rejected", logging.WARNING, error=err.error, reason=err.reason)
        return web.json_response({"error": err.error}, status=400, headers=NO_CACHE)
    logsetup.event(log, "register.ok", client=logsetup.short(result["client_id"]),
                   clients=len(rt(request).authority.clients))
    return web.json_response(result, status=201, headers=NO_CACHE)


async def authorize_get(request):
    limit(request, "authorize", 60)
    a = rt(request).authority
    try:
        params = unique(request.query.items())
        headers = form_headers(params.get("redirect_uri", ""))
        tx = a.begin(params)
    except (OAuthError, ValueError) as err:
        logsetup.event(log, "authorize.rejected", logging.WARNING,
                       reason=getattr(err, "reason", str(err)), params=sorted(request.query))
        return error_page(400, "Invalid request", "This authorization request is not valid or has expired.")
    logsetup.event(log, "authorize.form_shown", client=logsetup.short(params["client_id"]),
                   redirect_host=urlsplit(params["redirect_uri"]).hostname, pending=len(a.pending))
    resp = web.Response(text=pages.render(params["redirect_uri"], tx), content_type="text/html", headers=headers)
    resp.set_cookie(tx_cookie(tx), tx, max_age=600, path=OAUTH_PATH, secure=True, httponly=True, samesite="Lax")
    return resp


async def authorize_post(request):
    check_origin(request)
    limit(request, "authorize", 60)
    data = await read_form(request)
    tx = data.get("transaction", "")
    if not tx or tx != request.cookies.get(tx_cookie(tx)):
        logsetup.event(log, "authorize.denied", logging.WARNING,
                       reason="transaction_missing" if not tx else "cookie_missing_or_mismatch",
                       cookie_header=bool(request.headers.get("Cookie")))
        return error_page(403, "Session expired", "This sign-in step has expired or was opened in another browser.")
    try:
        redirect, code, state = rt(request).authority.approve(tx, data.get("pairing_secret", ""))
    except OAuthError as err:
        logsetup.event(log, "authorize.denied", logging.WARNING, reason=err.reason,
                       failures=len(rt(request).authority.failures))
        return error_page(403, "Pairing code rejected", "The code is wrong, already used or expired.")
    logsetup.event(log, "authorize.approved", redirect_host=urlsplit(redirect).hostname)
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
    kind = str(data.get("grant_type"))[:30]
    async with r.token_lock:
        try:
            result = tokens.issue(r.authority, data)
        except OAuthError as err:
            logsetup.event(log, "token.rejected", logging.WARNING, grant_type=kind, error=err.error,
                           reason=err.reason, client=logsetup.short(data.get("client_id", "")),
                           has_resource="resource" in data, fields=sorted(data))
            r.save()  # a refresh replay revokes a family; persist it
            return web.json_response({"error": err.error}, status=400, headers=NO_CACHE)
        r.save()
    logsetup.event(log, "token.issued", grant_type=kind, client=logsetup.short(data.get("client_id", "")),
                   grants=len(r.authority.grants), expires_in=result["expires_in"])
    return web.json_response(result, headers=NO_CACHE)


async def health(request):
    return web.json_response({"status": "ok"})


__all__ = ["RESOURCE_METADATA_PATH", "authorize_get", "authorize_post", "health", "register",
           "resource_metadata", "server_metadata", "token"]
