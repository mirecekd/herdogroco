# herdogroco/__main__.py
"""Entry point: `python -m herdogroco` (server) or `python -m herdogroco pair`."""

import logging
import secrets
import sys

from aiohttp import web

from .config import Config
from .oauth import digest
from .store import Pairing
from .web import Runtime, make_app


def pair(cfg: Config) -> None:
    code = secrets.token_urlsafe(24)
    Pairing(cfg.data_dir / "pairing.json").create(digest(code))
    print(f"Pairing code (valid 10 minutes, single use):\n\n  {code}\n")
    print(f"Add the connector in Grok with URL: {cfg.public_url.rstrip('/')}/mcp")


def main() -> None:
    cfg = Config.from_env()
    if sys.argv[1:] == ["pair"]:
        return pair(cfg)
    if sys.argv[1:]:
        raise SystemExit("usage: python -m herdogroco [pair]")
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    web.run_app(make_app(Runtime(cfg)), host=cfg.host, port=cfg.port, access_log=None)


if __name__ == "__main__":
    main()
