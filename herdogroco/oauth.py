# herdogroco/oauth.py
"""Independent OAuth authority (derived from grok_connector, MIT, (c) 2026 Jenik5).

Dynamic client registration, PKCE S256, single-use pairing code, 30-day grants,
10-minute access tokens with rotating refresh tokens. Only SHA-256 digests of
tokens are stored. Only HTTPS callbacks on grok.com or x.ai may register.
"""

import copy
import hashlib
import re
import secrets
import time
from urllib.parse import urlsplit

from . import MCP_PATH, OAUTH_PATH, SCOPE

LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST_RE = re.compile(LABEL + r"(?:\." + LABEL + r")+")
CALLBACK_DOMAINS = ("grok.com", "x.ai")


class OAuthError(ValueError):
    def __init__(self, error="invalid_request"):
        super().__init__(error)
        self.error = error


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def public_base(value):
    """Canonical HTTPS origin chosen by the operator; never fetched."""
    bad = (not isinstance(value, str) or len(value) > 2048 or "?" in value or "#" in value
           or any(ord(c) < 33 or ord(c) == 127 for c in value))
    parsed = urlsplit("" if bad else value)
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = -1
    if (bad or parsed.scheme != "https" or not HOST_RE.fullmatch(host) or len(host) > 253
            or re.fullmatch(r"[0-9]+|0x[0-9a-f]*", host.rsplit(".", 1)[-1])
            or parsed.username or parsed.password or parsed.netloc.endswith(":")
            or parsed.path not in ("", "/") or port == -1 or port == 0):
        raise ValueError("PUBLIC_URL must be an HTTPS origin with a DNS hostname")
    return "https://" + host + (f":{port}" if port not in (None, 443) else "")


def allowed_callback(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        p = urlsplit(value)
        host = p.hostname or ""
        return (p.scheme == "https" and p.port in (None, 443) and not p.username
                and not p.password and not p.fragment and len(host) <= 253
                and re.fullmatch(LABEL + r"(?:\." + LABEL + r")*", host) is not None
                and not any(ord(c) < 33 or ord(c) == 127 for c in value)
                and any(host == d or host.endswith("." + d) for d in CALLBACK_DOMAINS))
    except ValueError:
        return False


class OAuthAuthority:
    def __init__(self, base_url, saved=None, pairing=None, clock=time.time):
        self.base_url = public_base(base_url)
        self.resource, self.issuer = self.base_url + MCP_PATH, self.base_url + OAUTH_PATH
        self.clock, self.pairing = clock, pairing
        self.clients = copy.deepcopy((saved or {}).get("clients", {}))
        self.grants = copy.deepcopy((saved or {}).get("grants", {}))
        self.pending, self.codes, self.failures = {}, {}, []
        self.prune()

    def prune(self):
        now = self.clock()
        for coll, key in ((self.clients, "expires"), (self.pending, "expires"),
                          (self.codes, "expires"), (self.grants, "refresh_expires")):
            for k in [k for k, v in coll.items() if v[key] <= now]:
                del coll[k]
        self.failures = [t for t in self.failures if t > now - 60]

    def snapshot(self):
        self.prune()
        return {"grants": copy.deepcopy(self.grants), "clients": copy.deepcopy(
            {k: v for k, v in self.clients.items() if v.get("approved")})}

    def revoke(self):
        for coll in (self.grants, self.codes, self.pending, self.clients):
            coll.clear()

    def register(self, data):
        self.prune()
        redirects = data.get("redirect_uris")
        grants = data.get("grant_types", ["authorization_code", "refresh_token"])
        if (not isinstance(redirects, list) or not 1 <= len(redirects) <= 4
                or not all(allowed_callback(u) for u in redirects)
                or data.get("token_endpoint_auth_method", "none") != "none"
                or not isinstance(grants, list) or not all(isinstance(x, str) for x in grants)
                or "authorization_code" not in grants
                or set(grants) - {"authorization_code", "refresh_token"}
                or data.get("response_types", ["code"]) != ["code"]):
            raise OAuthError("invalid_client_metadata")
        if len(self.clients) >= 64:
            raise OAuthError("temporarily_unavailable")
        cid = secrets.token_urlsafe(24)
        self.clients[cid] = {"redirects": redirects, "expires": self.clock() + 3600}
        return {"client_id": cid, "redirect_uris": redirects, "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}

    def begin(self, params):
        self.prune()
        client = self.clients.get(params.get("client_id"))
        if not client or params.get("redirect_uri") not in client["redirects"]:
            raise OAuthError("invalid_client")
        if (params.get("response_type") != "code" or params.get("code_challenge_method") != "S256"
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.get("code_challenge", ""))
                or not isinstance(params.get("state"), str) or not 1 <= len(params["state"]) <= 1024
                or params.get("resource") != self.resource
                or params.get("scope", SCOPE) != SCOPE):
            raise OAuthError()
        if len(self.pending) >= 64:
            raise OAuthError("temporarily_unavailable")
        tx = secrets.token_urlsafe(32)
        self.pending[tx] = {k: params[k] for k in ("client_id", "redirect_uri", "code_challenge", "state")}
        self.pending[tx]["expires"] = self.clock() + 600
        return tx

    def approve(self, tx, pairing_secret):
        self.prune()
        pending = self.pending.get(tx)
        if not pending or len(self.failures) >= 10:
            raise OAuthError("access_denied")
        expected = self.pairing.pending() if self.pairing else None
        try:
            ok = bool(expected) and secrets.compare_digest(digest(pairing_secret), expected)
        except (UnicodeError, AttributeError, TypeError):
            ok = False
        if not ok:
            self.failures.append(self.clock())
            raise OAuthError("access_denied")
        self.pairing.clear()
        del self.pending[tx]
        code = secrets.token_urlsafe(32)
        self.codes[digest(code)] = {**pending, "expires": self.clock() + 120}
        return pending["redirect_uri"], code, pending["state"]
