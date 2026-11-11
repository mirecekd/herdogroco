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

    @classmethod
    def from_env(cls, env=os.environ):
        def need(name):
            if not (value := env.get(name, "").strip()):
                raise SystemExit(f"Missing required environment variable {name}")
            return value

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
            log_level=env.get("LOG_LEVEL", "INFO"),
        )
