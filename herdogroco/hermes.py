# herdogroco/hermes.py
"""Client for the Hermes API server (Runs API) of one profile, e.g. /p/grokovo/v1."""

import asyncio
import hashlib
import logging

import aiohttp

log = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class HermesError(Exception):
    pass


class Hermes:
    def __init__(self, cfg):
        self.cfg = cfg
        self._http = None

    async def _client(self):
        if self._http is None:
            self._http = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.cfg.hermes_key}"},
                timeout=aiohttp.ClientTimeout(total=15))
        return self._http

    async def close(self):
        if self._http:
            await self._http.close()

    async def _call(self, method, path, **kw):
        try:
            http = await self._client()
            async with http.request(method, self.cfg.hermes_url + path, **kw) as r:
                body = await r.json(content_type=None)
                if r.status >= 400:
                    raise HermesError(f"Hermes HTTP {r.status}")
                return body
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            log.warning("hermes call failed: %s %s: %s", method, path, type(err).__name__)
            raise HermesError("Hermes is unreachable") from None

    async def start(self, text: str, idem: str | None = None) -> str:
        """Create a run; the idempotency key makes an MCP retry reuse the same run."""
        headers = {"Idempotency-Key": hashlib.sha256(idem.encode()).hexdigest()} if idem else {}
        body = await self._call("POST", "/runs", headers=headers, json={
            "input": self.cfg.prefix + text, "session_id": self.cfg.session})
        return body["run_id"]

    async def status(self, run_id: str) -> dict:
        data = await self._call("GET", f"/runs/{run_id}")
        return {"task_id": run_id, "status": data.get("status", "unknown"),
                "output": data.get("output")}

    async def cancel(self, run_id: str) -> dict:
        await self._call("POST", f"/runs/{run_id}/stop")
        return {"task_id": run_id, "status": "stopping"}

    async def ask(self, text: str, idem: str | None = None) -> dict:
        """Wait up to sync_timeout for the answer; otherwise return the running task id.

        A run that asks for approval is stopped: nobody can answer by voice.
        """
        run_id = await self.start(text, idem)
        deadline = asyncio.get_running_loop().time() + self.cfg.sync_timeout
        while True:
            st = await self.status(run_id)
            if st["status"] in TERMINAL:
                return st
            if st["status"] == "waiting_for_approval":
                await self.cancel(run_id)
                return {**st, "status": "cancelled", "output":
                        "The task needs a manual approval, so it was stopped."}
            if asyncio.get_running_loop().time() >= deadline:
                return st
            await asyncio.sleep(1)
