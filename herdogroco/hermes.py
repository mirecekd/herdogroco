# herdogroco/hermes.py
"""Client for the Hermes API server (Runs API) of one profile, e.g. /p/grokovo/v1."""

import asyncio
import hashlib
import logging
import time

import aiohttp

from . import logsetup

log = logging.getLogger("herdogroco.hermes")
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
        started = time.monotonic()
        try:
            http = await self._client()
            async with http.request(method, self.cfg.hermes_url + path, **kw) as r:
                body = await r.json(content_type=None)
                logsetup.event(log, "hermes.call", logging.DEBUG if r.status < 400 else logging.WARNING,
                               method=method, path=path.split("/run_")[0] + ("/{run}" if "/run_" in path else ""),
                               status=r.status, ms=round((time.monotonic() - started) * 1000))
                if r.status >= 400:
                    logsetup.event(log, "hermes.error_body", logging.DEBUG, body=logsetup.content(body))
                    raise HermesError(f"Hermes HTTP {r.status}")
                return body
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            logsetup.event(log, "hermes.unreachable", logging.ERROR, method=method, path=path,
                           error=type(err).__name__, detail=str(err)[:200],
                           ms=round((time.monotonic() - started) * 1000))
            raise HermesError("Hermes is unreachable") from None

    async def start(self, text: str, idem: str | None = None) -> str:
        """Create a run; the idempotency key makes an MCP retry reuse the same run."""
        headers = {"Idempotency-Key": hashlib.sha256(idem.encode()).hexdigest()} if idem else {}
        body = await self._call("POST", "/runs", headers=headers, json={
            "input": self.cfg.prefix + text, "session_id": self.cfg.session})
        logsetup.event(log, "hermes.run_started", run=body["run_id"], session=self.cfg.session,
                       idempotent=bool(idem), replayed=body.get("replayed"), task=logsetup.content(text))
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
        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline, last = started + self.cfg.sync_timeout, None
        while True:
            st = await self.status(run_id)
            if st["status"] != last:
                logsetup.event(log, "hermes.run_status", run=run_id, status=st["status"],
                               waited_s=round(loop.time() - started, 1))
                last = st["status"]
            if st["status"] in TERMINAL:
                logsetup.event(log, "hermes.run_finished", logging.INFO if st["status"] == "completed"
                               else logging.WARNING, run=run_id, status=st["status"],
                               waited_s=round(loop.time() - started, 1), answer=logsetup.content(st["output"] or ""))
                return st
            if st["status"] == "waiting_for_approval":
                logsetup.event(log, "hermes.approval_cancelled", logging.WARNING, run=run_id)
                await self.cancel(run_id)
                return {**st, "status": "cancelled", "output":
                        "The task needs a manual approval, so it was stopped."}
            if loop.time() >= deadline:
                logsetup.event(log, "hermes.sync_timeout", logging.WARNING, run=run_id, status=st["status"],
                               waited_s=round(loop.time() - started, 1))
                return st
            await asyncio.sleep(1)
