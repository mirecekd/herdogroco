# herdogroco/store.py
"""Tiny JSON files in DATA_DIR: OAuth state (hashes only) and the pairing code."""

import json
import os
import time
from pathlib import Path


def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save(path: Path, data) -> None:
    """Atomic write with 0600 permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)


class Pairing:
    """Single-use pairing code created by `python -m herdogroco pair`.

    Kept in a file so the CLI (a second process) can hand it to the server.
    Only the SHA-256 digest is stored.
    """

    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = path, clock

    def create(self, digest_hex: str, ttl: int = 600) -> None:
        save(self.path, {"hash": digest_hex, "expires": self.clock() + ttl})

    def pending(self):
        data = load(self.path, {})
        if data.get("expires", 0) <= self.clock():
            return None
        return data.get("hash")

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
