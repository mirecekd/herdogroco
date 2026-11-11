# tests/test_logging.py
import json
import logging

import pytest

from herdogroco import logsetup
from herdogroco.config import Config

from .conftest import PUBLIC, auth, get_tokens, rpc

ENV = {"HERMES_URL": "http://x", "HERMES_KEY": "k", "PUBLIC_URL": PUBLIC}


@pytest.fixture(autouse=True)
def debug_logs(caplog):
    caplog.set_level(logging.DEBUG, logger="herdogroco")
    logsetup.settings.content, logsetup.settings.max_len = False, 500
    yield
    logsetup.settings.content = False


def events(caplog):
    return {r.getMessage() for r in caplog.records}


def text_of(caplog):
    """Everything a handler would print, in both formats."""
    out = []
    for r in caplog.records:
        out += [logsetup.TextFormatter().format(r), logsetup.JsonFormatter().format(r)]
    return "\n".join(out)


async def test_oauth_and_mcp_events_are_logged(client, caplog):
    tok = await get_tokens(client)
    await client.post("/mcp", json=rpc("initialize", {"protocolVersion": "2025-06-18"}), headers=auth(tok))
    seen = events(caplog)
    assert {"register.ok", "authorize.form_shown", "authorize.approved", "token.issued", "http",
            "mcp.request", "mcp.response", "mcp.session_opened"} <= seen


async def test_no_secret_ever_reaches_the_log(client, caplog, hermes):
    tok = await get_tokens(client)
    r = await client.post("/mcp", json=rpc("initialize", {"protocolVersion": "2025-06-18"}), headers=auth(tok))
    sid = r.headers["MCP-Session-Id"]
    h = {**auth(tok), "MCP-Session-Id": sid, "Cookie": "herdogroco_tx_x=secretcookie"}
    call = rpc("tools/call", {"name": "ask_hermes", "arguments": {"request": "tajne zadani"}}, id=2)
    await client.post("/mcp", json=call, headers=h)
    await client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": "BADREFRESH" * 4,
                                            "client_id": tok["client_id"], "resource": PUBLIC + "/mcp"})
    blob = text_of(caplog)
    for secret in (tok["access_token"], tok["refresh_token"], "pairing-code-123", "secretcookie", sid,
                   tok["client_id"], "BADREFRESH"):
        assert secret not in blob, secret[:6]
    assert "tajne zadani" not in blob  # content is off by default
    assert "<hidden" in blob


async def test_log_content_on_shows_task_but_never_tokens(client, caplog):
    logsetup.settings.content = True
    tok = await get_tokens(client)
    call = rpc("tools/call", {"name": "ask_hermes", "arguments": {"request": "tajne zadani"}})
    await client.post("/mcp", json=call, headers=auth(tok))
    blob = text_of(caplog)
    assert "tajne zadani" in blob and "done" in blob
    assert tok["access_token"] not in blob and tok["refresh_token"] not in blob


async def test_rejections_carry_a_reason(client, caplog):
    await client.post("/oauth/register", json={"redirect_uris": ["https://evil.com/cb"]})
    r = await client.post("/mcp", json=rpc("ping"), headers={"Accept": "application/json"})
    assert r.status == 401
    reasons = {getattr(rec, "fields", {}).get("reason") for rec in caplog.records}
    assert "no_authorization_header" in reasons
    rejected = next(r for r in caplog.records if r.getMessage() == "register.rejected")
    assert "evil.com" in rejected.fields["reason"]


async def test_pkce_mismatch_reason(client, caplog):
    tok = await get_tokens(client)
    await client.post("/oauth/token", data={"grant_type": "authorization_code", "code": "x" * 43,
                                            "client_id": tok["client_id"], "code_verifier": "v" * 50,
                                            "redirect_uri": "https://grok.com/api/oauth/callback",
                                            "resource": PUBLIC + "/mcp"})
    reasons = {getattr(rec, "fields", {}).get("reason") for rec in caplog.records}
    assert "unknown_or_used_or_expired_code" in reasons


async def test_request_id_is_echoed_and_in_lines(client, caplog):
    r = await client.get("/oauth/.well-known/oauth-authorization-server", headers={"X-Request-Id": "abc123"})
    assert r.headers["X-Request-Id"] == "abc123"
    r = await client.get("/health")
    assert len(r.headers["X-Request-Id"]) == 8


def test_health_is_debug_only(caplog):
    caplog.set_level(logging.INFO, logger="herdogroco")
    assert logsetup.scrub({"authorization": "Bearer x", "ok": 1}) == {"authorization": "<redacted>", "ok": 1}
    assert logsetup.scrub({"event": 1}) == {"f_event": 1}


def test_formats():
    rec = logging.LogRecord("herdogroco.x", logging.INFO, "", 0, "tok", None, None)
    rec.fields = {"a": 1, "text": "p\u0159\u00edli\u0161"}
    data = json.loads(logsetup.JsonFormatter().format(rec))
    assert data["event"] == "tok" and data["a"] == 1 and data["level"] == "INFO"
    assert 'a=1' in logsetup.TextFormatter().format(rec)


def test_clip_and_config_validation():
    logsetup.settings.max_len = 10
    assert logsetup.clip("x" * 25) == "x" * 10 + "...[+15 chars]"
    cfg = Config.from_env({**ENV, "LOG_LEVEL": "debug", "LOG_FORMAT": "JSON", "LOG_CONTENT": "yes"})
    assert (cfg.log_level, cfg.log_format, cfg.log_content) == ("DEBUG", "json", True)
    for bad in ({"LOG_LEVEL": "TRACE"}, {"LOG_FORMAT": "xml"}):
        with pytest.raises(SystemExit):
            Config.from_env({**ENV, **bad})
