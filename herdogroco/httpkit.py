# herdogroco/httpkit.py
"""Shared HTTP helpers: runtime state, rate limit, origin check, body readers."""

import asyncio
import json
import logging
import time
from urllib.parse import parse_qsl

from aiohttp import web

from . import logsetup, store
from .gateway import Gateway
from .hermes import Hermes
from .oauth import OAuthAuthority

log = logging.getLogger("herdogroco.http")
RT = web.AppKey("rt", object)
NO_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
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
        logsetup.event(log, "oauth.state_saved", logging.DEBUG, grants=len(self.authority.grants))

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
        logsetup.event(log, "rate_limited", logging.WARNING, bucket=bucket.split(":")[0], limit=n, window=window)
        raise web.HTTPTooManyRequests(headers={**NO_CACHE, "Retry-After": str(window)})


def check_origin(request, *, mcp=False):
    allowed = {rt(request).authority.base_url, *(GROK_ORIGINS if mcp else ())}
    if (origin := request.headers.get("Origin")) and origin not in allowed:
        logsetup.event(log, "origin_denied", logging.WARNING, origin=origin[:100])
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
