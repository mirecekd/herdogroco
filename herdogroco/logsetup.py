# herdogroco/logsetup.py
"""Structured logging: text or JSON, per-request id, secrets scrubbed by construction."""

import contextvars
import hashlib
import json
import logging
import sys
import time
from types import SimpleNamespace

request_id = contextvars.ContextVar("request_id", default="-")
# Whether task text and Hermes answers may appear in logs (LOG_CONTENT).
settings = SimpleNamespace(content=False, max_len=500)
SECRET_KEYS = {
    "authorization", "cookie", "set-cookie", "access_token", "refresh_token", "code", "code_verifier",
    "code_challenge", "pairing_secret", "pairing_code", "client_secret", "token", "hermes_key",
    "api_key", "transaction", "state",
}
RESERVED = {"ts", "level", "logger", "event", "request_id", "exc"}


def short(value) -> str:
    """Stable 8-char fingerprint to correlate log lines without exposing the value."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:8]


def clip(text, limit=None) -> str:
    text, limit = str(text), limit or settings.max_len
    return text if len(text) <= limit else f"{text[:limit]}...[+{len(text) - limit} chars]"


def content(text) -> str:
    """Task text / answers: only when LOG_CONTENT is on, otherwise just the length."""
    return clip(text) if settings.content else f"<hidden {len(str(text))} chars>"


def scrub(fields: dict) -> dict:
    return {("f_" + k if k in RESERVED else k): ("<redacted>" if k.lower() in SECRET_KEYS else v)
            for k, v in fields.items()}


def event(log: logging.Logger, name: str, level: int = logging.INFO, **fields) -> None:
    if log.isEnabledFor(level):
        log.log(level, name, extra={"fields": scrub(fields)})


class TextFormatter(logging.Formatter):
    def format(self, record):
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        parts = [f"{k}={json.dumps(v, ensure_ascii=False, default=str)}"
                 for k, v in getattr(record, "fields", {}).items()]
        line = f"{ts} {record.levelname:<7} {record.name} [{request_id.get()}] {record.getMessage()}"
        line += (" " + " ".join(parts)) if parts else ""
        return line + ("\n" + self.formatException(record.exc_info) if record.exc_info else "")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"), "level": record.levelname,
                "logger": record.name, "event": record.getMessage(), "request_id": request_id.get(),
                **getattr(record, "fields", {})}
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def setup(cfg) -> None:
    settings.content, settings.max_len = cfg.log_content, cfg.log_content_max
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if cfg.log_format == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(cfg.log_level)
    # aiohttp's own access log is replaced by ours; keep its errors.
    logging.getLogger("aiohttp.access").setLevel(logging.CRITICAL)
