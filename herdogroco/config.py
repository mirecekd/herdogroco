# herdogroco/config.py
"""Environment configuration. Names for the Hermes link match teskitty (.env)."""

import os
from dataclasses import dataclass
from pathlib import Path

# Prepended to every task: the text comes from a voice assistant (Grok in a car).
DEFAULT_PREFIX = (
    "[Request relayed by the Grok voice assistant, possibly from a car; speech "
    "recognition may contain errors. Answer in the user's language in at most "
    "two short sentences, without markdown, bullet points or URLs - the answer "
    "is read aloud. Ask before any irreversible or ambiguous action.]\n"
)


@dataclass(frozen=True)
class Config:
    hermes_url: str
    hermes_key: str
    public_url: str
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8130
    session: str = "herdogroco-grok"
    sync_timeout: float = 25.0
    prefix: str = DEFAULT_PREFIX
    log_level: str = "INFO"
    log_format: str = "text"
    log_content: bool = False
    log_content_max: int = 500

    @classmethod
    def from_env(cls, env=os.environ):
        def need(name):
            if not (value := env.get(name, "").strip()):
                raise SystemExit(f"Missing required environment variable {name}")
            return value

        level = env.get("LOG_LEVEL", "INFO").strip().upper()
        fmt = env.get("LOG_FORMAT", "text").strip().lower()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise SystemExit("LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
        if fmt not in ("text", "json"):
            raise SystemExit("LOG_FORMAT must be text or json")

        return cls(
            hermes_url=need("HERMES_URL").rstrip("/"),
            hermes_key=need("HERMES_KEY"),
            public_url=need("PUBLIC_URL"),
            data_dir=Path(env.get("DATA_DIR", "data")),
            host=env.get("HOST", "127.0.0.1"),
            port=int(env.get("PORT", "8130")),
            session=env.get("HERMES_SESSION", "herdogroco-grok"),
            sync_timeout=float(env.get("HERMES_SYNC_TIMEOUT", "25")),
            prefix=env.get("TASK_PREFIX", DEFAULT_PREFIX),
            log_level=level,
            log_format=fmt,
            log_content=env.get("LOG_CONTENT", "false").strip().lower() in ("1", "true", "yes", "on"),
            log_content_max=int(env.get("LOG_CONTENT_MAX", "500")),
        )
