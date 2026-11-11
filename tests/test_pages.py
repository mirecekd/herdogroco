# tests/test_pages.py
import base64
import hashlib
import re

from herdogroco import pages

from .conftest import PUBLIC, REDIRECT, get_tokens


def test_form_page_has_logo_and_form():
    page = pages.render(REDIRECT, "tx" * 20)
    assert "<svg" in page and 'aria-label="herdogroco"' in page
    assert 'name="pairing_secret"' in page and 'name="transaction"' in page
    assert "grok.com" in page


def test_pages_are_self_contained():
    for page in (pages.render(REDIRECT, "tx"), pages.render_error("T", "m")):
        assert "<script" not in page.lower()
        assert not re.search(r"(src|href)=[\"']https?:", page)
        assert "http://" not in page.replace("http://www.w3.org/2000/svg", "")


def test_style_hash_matches_inline_style():
    page = pages.render(REDIRECT, "tx")
    css = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(css.encode()).digest()).decode()
    assert pages.STYLE_SOURCE == f"'sha256-{digest}'"


def test_text_is_escaped():
    page = pages.render_error("<b>x</b>", "<script>alert(1)</script>")
    assert "<script>alert" not in page and "&lt;script&gt;" in page


async def test_wrong_code_returns_styled_page_with_csp(client):
    client.rt.pairing.create("0" * 64)
    r = await client.post("/oauth/register", json={"redirect_uris": [REDIRECT]})
    cid = (await r.json())["client_id"]
    from .conftest import pkce
    _, challenge = pkce()
    q = {"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "state": "s",
         "code_challenge": challenge, "code_challenge_method": "S256",
         "resource": PUBLIC + "/mcp", "scope": "hermes"}
    r = await client.get("/oauth/authorize", params=q)
    assert r.status == 200
    assert pages.STYLE_SOURCE in r.headers["Content-Security-Policy"]
    assert "<svg" in await r.text()
    cookie = {n: m.value for n, m in r.cookies.items()}
    tx = next(iter(cookie.values()))
    r = await client.post("/oauth/authorize", data={"transaction": tx, "pairing_secret": "wrong"},
                          cookies=cookie, allow_redirects=False)
    assert r.status == 403
    assert "Pairing code rejected" in await r.text()
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert "form-action" not in r.headers["Content-Security-Policy"]


async def test_bad_authorize_request_is_styled(client):
    r = await client.get("/oauth/authorize", params={"client_id": "nope"})
    assert r.status == 400 and "<svg" in await r.text()


async def test_full_flow_still_works(client):
    assert await get_tokens(client) is not None
