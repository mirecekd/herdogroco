# herdogroco/gateway.py
"""MCP JSON-RPC gateway (Streamable HTTP, JSON responses). No HTTP knowledge here."""

import json
import logging
import re
import secrets
import time

from . import VERSION, logsetup
from .hermes import Hermes, HermesError

log = logging.getLogger("herdogroco.gateway")

PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
INSTRUCTIONS = (
    "Hermes is the user's personal agent with memory, notes, messages, files and a "
    "terminal. Use ask_hermes for anything you cannot do yourself. If it answers "
    "that the task is still running, tell the user and later call hermes_task_status.")

TEXT = {"type": "string", "minLength": 1, "maxLength": 2000}
TOOLS = [
    {"name": "ask_hermes", "title": "Ask Hermes",
     "description": ("Hand a task to the Hermes agent and wait briefly for the answer. "
                     "Pass the whole task in one or two sentences. If it takes longer it "
                     "returns a task_id; poll with hermes_task_status."),
     "inputSchema": {"type": "object", "properties": {"request": TEXT}, "required": ["request"],
                     "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
                     "openWorldHint": True}},
    {"name": "hermes_task_status", "title": "Hermes task status",
     "description": "Check a task started by ask_hermes that was still running.",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string", "pattern": "^run_[a-f0-9]{8,64}$"}},
                     "required": ["task_id"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                     "openWorldHint": False}},
    {"name": "hermes_task_cancel", "title": "Cancel Hermes task",
     "description": "Stop a running Hermes task.",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string", "pattern": "^run_[a-f0-9]{8,64}$"}},
                     "required": ["task_id"], "additionalProperties": False},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                     "openWorldHint": False}},
]


def content(data, error=False):
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "isError": error}


def _rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class Gateway:
    def __init__(self, hermes: Hermes, clock=time.monotonic):
        self.hermes, self.clock = hermes, clock
        self.sessions = {}  # session id -> (principal, last_used)
        self.replies = {}  # (principal, session, id) -> (expires, tool, result)

    def open_session(self, principal):
        self.sessions = {k: v for k, v in self.sessions.items() if v[1] > self.clock() - 1800}
        if len(self.sessions) >= 128:
            self.sessions.pop(next(iter(self.sessions)))
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = (principal, self.clock())
        return sid

    def session_active(self, sid, principal):
        entry = self.sessions.get(sid)
        if not entry or entry[0] != principal or entry[1] <= self.clock() - 1800:
            self.sessions.pop(sid, None)
            return False
        self.sessions[sid] = (principal, self.clock())
        return True

    def close_session(self, sid):
        self.sessions.pop(sid, None)
        self.replies = {k: v for k, v in self.replies.items() if k[1] != sid}

    async def _call_tool(self, name, args, idem):
        try:
            if name == "ask_hermes":
                return content(await self.hermes.ask(args["request"], idem))
            if name == "hermes_task_status":
                return content(await self.hermes.status(args["task_id"]))
            return content(await self.hermes.cancel(args["task_id"]))
        except HermesError as err:
            logsetup.event(log, "tool.failed", logging.ERROR, tool=name, error=str(err))
            return content({"error": str(err)}, True)

    async def rpc(self, message, principal, session=None):
        if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
                or not isinstance(message.get("method"), str)
                or ("id" in message and type(message["id"]) not in (str, int))):
            return _rpc_error(None, -32600, "Invalid JSON-RPC request")
        if "id" not in message:
            return None
        rid, method, params = message["id"], message["method"], message.get("params", {})
        if not isinstance(params, dict):
            return _rpc_error(rid, -32602, "Invalid parameters")
        if session is not None and not self.session_active(session, principal):
            return _rpc_error(rid, -32000, "MCP session expired")
        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[-1],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "Herdogroco", "version": VERSION},
                      "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = await self._tools_call(rid, params, principal, session)
            if isinstance(result, dict) and "jsonrpc" in result:
                return result
        else:
            return _rpc_error(rid, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    async def _tools_call(self, rid, params, principal, session):
        name, args = params.get("name"), params.get("arguments", {})
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None or not isinstance(args, dict):
            logsetup.event(log, "tool.rejected", logging.WARNING, reason="unknown_tool_or_bad_args",
                           tool=str(name)[:60], args_type=type(args).__name__)
            return _rpc_error(rid, -32602, "Unknown tool or invalid arguments")
        schema = tool["inputSchema"]["properties"]
        if set(args) != set(schema) or not all(isinstance(v, str) and v for v in args.values()):
            logsetup.event(log, "tool.rejected", logging.WARNING, reason="schema_mismatch", tool=name,
                           expected=sorted(schema), got=sorted(args))
            return _rpc_error(rid, -32602, "Invalid tool arguments")
        if "request" in args and len(args["request"]) > 2000:
            return _rpc_error(rid, -32602, "Request too long")
        if "task_id" in args and not re.fullmatch(r"run_[a-f0-9]{8,64}", args["task_id"]):
            return _rpc_error(rid, -32602, "Invalid task_id")
        # A retried JSON-RPC id inside one session replays the first answer.
        key = (principal, session, type(rid), rid)
        now = self.clock()
        self.replies = {k: v for k, v in self.replies.items() if v[0] > now}
        if session is not None and key in self.replies:
            if self.replies[key][1] != name:
                logsetup.event(log, "tool.id_collision", logging.WARNING, tool=name, rpc_id=rid)
                return _rpc_error(rid, -32602, "Request ID already used for another tool")
            logsetup.event(log, "tool.replayed", tool=name, rpc_id=rid)
            return self.replies[key][2]
        idem = f"{principal}:{session}:{rid}" if session is not None and name == "ask_hermes" else None
        result = await self._call_tool(name, args, idem)
        if session is not None and session in self.sessions:
            if len(self.replies) >= 256:
                self.replies.pop(next(iter(self.replies)))
            self.replies[key] = (now + 120, name, result)
        return result
