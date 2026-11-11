# tests/test_flow.py
import pytest

from herdogroco.oauth import allowed_callback, public_base

from .conftest import PUBLIC, REDIRECT, auth, get_tokens, rpc


def test_public_base():
    assert public_base("https://a.example.org/") == "https://a.example.org"
    assert public_base("https://a.example.org:8443") == "https://a.example.org:8443"
    for bad in ("http://a.example.org", "https://localhost", "https://1.2.3.4",
                "https://a.example.org/x", "https://u:p@a.example.org", "https://a.example.org:0"):
        with pytest.raises(ValueError):
            public_base(bad)


def test_callbacks():
    assert allowed_callback(REDIRECT)
    assert allowed_callback("https://x.ai/cb")
    for bad in ("http://grok.com/cb", "https://evil.com/cb", "https://grok.com.evil.com/cb",
                "https://grok.com:8443/cb", "https://grok.com/cb#f"):
        assert not allowed_callback(bad)


async def test_discovery(client):
    r = await client.get("/.well-known/oauth-protected-resource/mcp")
    body = await r.json()
    assert body["resource"] == PUBLIC + "/mcp"
    assert body["authorization_servers"] == [PUBLIC + "/oauth"]
    r = await client.get("/.well-known/oauth-authorization-server/oauth")
    assert (await r.json())["code_challenge_methods_supported"] == ["S256"]


async def test_mcp_needs_bearer(client):
    r = await client.post("/mcp", json=rpc("ping"), headers={"Accept": "application/json"})
    assert r.status == 401
    assert "resource_metadata" in r.headers["WWW-Authenticate"]


async def test_register_rejects_foreign_redirect(client):
    r = await client.post("/oauth/register", json={"redirect_uris": ["https://evil.com/cb"]})
    assert r.status == 400


async def test_wrong_pairing_code(client):
    client.rt.pairing.create("0" * 64)
    assert await get_tokens(client, pair=False) is None


async def test_pairing_is_single_use(client):
    assert await get_tokens(client) is not None
    assert client.rt.pairing.pending() is None


async def test_full_flow_ask(client, hermes):
    tok = await get_tokens(client)
    r = await client.post("/mcp", json=rpc("initialize", {"protocolVersion": "2025-06-18"}), headers=auth(tok))
    assert r.status == 200
    sid = r.headers["MCP-Session-Id"]
    h = {**auth(tok), "MCP-Session-Id": sid}
    r = await client.post("/mcp", json=rpc("tools/list", id=2), headers=h)
    assert {t["name"] for t in (await r.json())["result"]["tools"]} == {
        "ask_hermes", "hermes_task_status", "hermes_task_cancel"}
    call = rpc("tools/call", {"name": "ask_hermes", "arguments": {"request": "Kolik je hodin?"}}, id=3)
    r = await client.post("/mcp", json=call, headers=h)
    res = (await r.json())["result"]
    assert not res["isError"] and "done" in res["content"][0]["text"]
    assert len(hermes.started) == 1
    # Retried JSON-RPC id replays the answer instead of starting a second run.
    r = await client.post("/mcp", json=call, headers=h)
    assert (await r.json())["result"] == res
    assert len(hermes.started) == 1


async def test_running_task_returns_id(client, hermes):
    hermes.statuses = ["running"]
    tok = await get_tokens(client)
    call = rpc("tools/call", {"name": "ask_hermes", "arguments": {"request": "dlouhy ukol"}})
    r = await client.post("/mcp", json=call, headers=auth(tok))
    text = (await r.json())["result"]["content"][0]["text"]
    assert '"status": "running"' in text and "task_id" in text


async def test_approval_is_cancelled(client, hermes):
    hermes.statuses = ["waiting_for_approval"]
    tok = await get_tokens(client)
    call = rpc("tools/call", {"name": "ask_hermes", "arguments": {"request": "smaz vsechno"}})
    r = await client.post("/mcp", json=call, headers=auth(tok))
    assert "cancelled" in (await r.json())["result"]["content"][0]["text"]
    assert hermes.cancelled


async def test_hermes_down_is_tool_error(client, hermes):
    hermes.fail = True
    tok = await get_tokens(client)
    call = rpc("tools/call", {"name": "ask_hermes", "arguments": {"request": "ahoj"}})
    r = await client.post("/mcp", json=call, headers=auth(tok))
    assert (await r.json())["result"]["isError"] is True


@pytest.mark.parametrize("args", [{}, {"request": ""}, {"request": "x", "extra": "y"}, {"request": 5},
                                  {"request": "x" * 2001}])
async def test_bad_arguments(client, args):
    tok = await get_tokens(client)
    r = await client.post("/mcp", json=rpc("tools/call", {"name": "ask_hermes", "arguments": args}),
                          headers=auth(tok))
    assert "error" in await r.json()


async def test_task_id_validated(client):
    tok = await get_tokens(client)
    call = rpc("tools/call", {"name": "hermes_task_status", "arguments": {"task_id": "../../x"}})
    r = await client.post("/mcp", json=call, headers=auth(tok))
    assert (await r.json())["error"]["code"] == -32602


async def test_foreign_origin_and_url_token(client):
    tok = await get_tokens(client)
    r = await client.post("/mcp", json=rpc("ping"), headers={**auth(tok), "Origin": "https://evil.com"})
    assert r.status == 403
    r = await client.post("/mcp?access_token=x", json=rpc("ping"), headers=auth(tok))
    assert r.status == 400


async def test_unknown_session_is_404(client):
    tok = await get_tokens(client)
    r = await client.post("/mcp", json=rpc("ping"), headers={**auth(tok), "MCP-Session-Id": "nope"})
    assert r.status == 404


async def test_refresh_rotation_and_replay(client):
    tok = await get_tokens(client)
    data = {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
            "client_id": tok["client_id"], "resource": PUBLIC + "/mcp"}
    r = await client.post("/oauth/token", data=data)
    assert r.status == 200
    new = await r.json()
    r = await client.post("/oauth/token", data=data)  # replay kills the family
    assert r.status == 400
    r = await client.post("/mcp", json=rpc("ping"), headers=auth(new))
    assert r.status == 401


async def test_state_persists_hashes_only(client, cfg):
    tok = await get_tokens(client)
    raw = (cfg.data_dir / "oauth.json").read_text()
    assert tok["access_token"] not in raw and tok["refresh_token"] not in raw
    assert (cfg.data_dir / "oauth.json").stat().st_mode & 0o777 == 0o600
