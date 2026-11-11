# tests/conftest.py
import base64
import hashlib
import secrets

import pytest

from herdogroco.config import Config
from herdogroco.oauth import digest
from herdogroco.web import Runtime, make_app

PUBLIC = "https://herdogroco.example.org"
REDIRECT = "https://grok.com/api/oauth/callback"


class FakeHermes:
    """Stands in for the Hermes Runs API; statuses are scripted per test."""

    def __init__(self):
        self.started, self.cancelled = [], []
        self.statuses = ["completed"]
        self.output = "done"
        self.fail = False

    async def start(self, text, idem=None):
        self.started.append((text, idem))
        return "run_" + "a" * 32

    async def status(self, run_id):
        return {"task_id": run_id, "status": self.statuses[0], "output": self.output}

    async def cancel(self, run_id):
        self.cancelled.append(run_id)
        return {"task_id": run_id, "status": "stopping"}

    async def ask(self, text, idem=None):
        from herdogroco.hermes import Hermes, HermesError
        if self.fail:
            raise HermesError("Hermes is unreachable")
        return await Hermes.ask(self, text, idem)

    cfg = type("C", (), {"sync_timeout": 0.05})()

    async def close(self):
        pass


@pytest.fixture
def hermes():
    return FakeHermes()


@pytest.fixture
def cfg(tmp_path):
    return Config(hermes_url="http://x", hermes_key="k", public_url=PUBLIC, data_dir=tmp_path)


@pytest.fixture
async def client(aiohttp_client, cfg, hermes):
    rt = Runtime(cfg, hermes=hermes)
    c = await aiohttp_client(make_app(rt))
    c.rt = rt
    return c


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


async def get_tokens(client, pair=True):
    """Run the full OAuth dance as Grok would; return the token response."""
    r = await client.post("/oauth/register", json={"redirect_uris": [REDIRECT]})
    cid = (await r.json())["client_id"]
    verifier, challenge = pkce()
    q = {"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "state": "s1",
         "code_challenge": challenge, "code_challenge_method": "S256",
         "resource": PUBLIC + "/mcp", "scope": "hermes"}
    r = await client.get("/oauth/authorize", params=q)
    assert r.status == 200
    tx = next(iter(r.cookies.values())).value
    cookie = {name: m.value for name, m in r.cookies.items()}
    code = "pairing-code-123"
    if pair:
        client.rt.pairing.create(digest(code))
    r = await client.post("/oauth/authorize", data={"transaction": tx, "pairing_secret": code},
                          cookies=cookie, allow_redirects=False)
    if r.status != 303:
        return None
    auth_code = r.headers["Location"].split("code=")[1].split("&")[0]
    r = await client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": auth_code, "client_id": cid,
        "redirect_uri": REDIRECT, "code_verifier": verifier, "resource": PUBLIC + "/mcp"})
    assert r.status == 200
    return {**await r.json(), "client_id": cid}


def rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, **({"params": params} if params else {})}


HEADERS = {"Accept": "application/json, text/event-stream"}


def auth(tok):
    return {**HEADERS, "Authorization": "Bearer " + tok["access_token"]}
