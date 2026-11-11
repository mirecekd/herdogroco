# herdogroco/__main__.py
"""Entry point: `python -m herdogroco` (server) or `python -m herdogroco pair`."""

import logging
import secrets
import sys

from aiohttp import web

from . import VERSION, logsetup
from .config import Config
from .oauth import digest
from .store import Pairing
from .web import Runtime, make_app

log = logging.getLogger("herdogroco")


def pair(cfg: Config) -> None:
    code = secrets.token_urlsafe(24)
    Pairing(cfg.data_dir / "pairing.json").create(digest(code))
    log.info("pairing code created")
    print(f"Pairing code (valid 10 minutes, single use):\n\n  {code}\n")
    print(f"Add the connector in Grok with URL: {cfg.public_url.rstrip('/')}/mcp")


def main() -> None:
    cfg = Config.from_env()
    if sys.argv[1:] == ["pair"]:
        return pair(cfg)
    if sys.argv[1:]:
        raise SystemExit("usage: python -m herdogroco [pair]")
    logsetup.setup(cfg)
    host_hint = "loopback only" if cfg.host in ("127.0.0.1", "::1") else "all interfaces"
    logsetup.event(log, "startup", version=VERSION, listen=f"{cfg.host}:{cfg.port} ({host_hint})",
                   public_url=cfg.public_url, hermes_url=cfg.hermes_url, hermes_key_set=bool(cfg.hermes_key),
                   session=cfg.session, sync_timeout=cfg.sync_timeout, log_level=cfg.log_level,
                   log_format=cfg.log_format, log_content=cfg.log_content, data_dir=str(cfg.data_dir))
    if cfg.log_content:
        logsetup.event(log, "log_content_enabled", logging.WARNING,
                       note="task text and Hermes answers are written to the log")
    runtime = Runtime(cfg)
    logsetup.event(log, "oauth.loaded", grants=len(runtime.authority.grants),
                   clients=len(runtime.authority.clients))
    web.run_app(make_app(runtime), host=cfg.host, port=cfg.port, access_log=None, print=None)


if __name__ == "__main__":
    main()
