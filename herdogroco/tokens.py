# herdogroco/tokens.py
"""Token endpoint logic and bearer authentication for OAuthAuthority."""

import base64
import hashlib
import re
import secrets

from . import SCOPE
from .oauth import OAuthAuthority, OAuthError, digest


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def _from_code(auth: OAuthAuthority, params):
    try:
        code = auth.codes.pop(digest(params.get("code", "")), None)
    except UnicodeError:
        code = None
    verifier = params.get("code_verifier", "")
    if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        raise OAuthError("invalid_grant", "bad_code_verifier_format")
    if not code:
        raise OAuthError("invalid_grant", "unknown_or_used_or_expired_code")
    if params.get("client_id") != code["client_id"]:
        raise OAuthError("invalid_grant", "client_id_mismatch")
    if params.get("redirect_uri") != code["redirect_uri"]:
        raise OAuthError("invalid_grant", "redirect_uri_mismatch")
    if not secrets.compare_digest(_challenge(verifier), code["code_challenge"]):
        raise OAuthError("invalid_grant", "pkce_mismatch")
    if len(auth.grants) >= 8:
        raise OAuthError("temporarily_unavailable", "grant_limit_reached")
    grant = {"client_id": code["client_id"], "refresh_expires": auth.clock() + 30 * 86400,
             "used_refresh": []}
    auth.grants[secrets.token_urlsafe(24)] = grant
    client = auth.clients.setdefault(code["client_id"], {"redirects": [code["redirect_uri"]]})
    client.update(approved=True, expires=auth.clock() + 10 * 365 * 86400)
    return grant


def _from_refresh(auth: OAuthAuthority, params):
    try:
        refresh_hash = digest(params.get("refresh_token", ""))
    except UnicodeError:
        raise OAuthError("invalid_grant", "bad_refresh_token_format") from None
    for principal, grant in list(auth.grants.items()):
        if refresh_hash in grant["used_refresh"]:  # replay: kill the whole family
            del auth.grants[principal]
            raise OAuthError("invalid_grant", "refresh_token_replay_family_revoked")
        if secrets.compare_digest(refresh_hash, grant.get("refresh_hash", "")):
            break
    else:
        raise OAuthError("invalid_grant", "unknown_refresh_token")
    if params.get("client_id") != grant["client_id"]:
        raise OAuthError("invalid_grant", "client_id_mismatch")
    grant["used_refresh"] = [*grant["used_refresh"][-31:], refresh_hash]
    return grant


def issue(auth: OAuthAuthority, params):
    auth.prune()
    if params.get("resource") != auth.resource:
        raise OAuthError("invalid_target", "resource_mismatch")
    kind = params.get("grant_type")
    if kind == "authorization_code":
        grant = _from_code(auth, params)
    elif kind == "refresh_token":
        grant = _from_refresh(auth, params)
    else:
        raise OAuthError("unsupported_grant_type", "grant_type=" + str(kind)[:40])
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    grant.update(access_hash=digest(access), access_expires=auth.clock() + 600,
                 refresh_hash=digest(refresh), resource=auth.resource)
    return {"access_token": access, "token_type": "Bearer", "expires_in": 600,
            "refresh_token": refresh, "scope": SCOPE}


def authenticate(auth: OAuthAuthority, authorization):
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    if len(token) != 43:
        return None
    try:
        value = digest(token)
    except UnicodeError:
        return None
    now = auth.clock()
    for principal, g in auth.grants.items():
        if (g.get("access_expires", 0) > now and g["refresh_expires"] > now
                and g.get("resource") == auth.resource
                and secrets.compare_digest(value, g["access_hash"])):
            return principal
    return None
