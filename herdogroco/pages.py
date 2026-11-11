# herdogroco/pages.py
"""Authorization page: one inline stylesheet, no scripts, strict CSP."""

import base64
import hashlib
import html

STYLE = ("body{font:16px system-ui,sans-serif;max-width:26rem;margin:12vh auto;padding:0 1rem;"
         "background:#fff;color:#1a1a1a}@media(prefers-color-scheme:dark){body{background:#161616;"
         "color:#eee}}input,button{font:inherit;padding:.6rem;width:100%;box-sizing:border-box;"
         "margin:.4rem 0}small{color:#888}")
STYLE_SOURCE = "'sha256-" + base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode() + "'"


def render(redirect_uri: str, transaction: str) -> str:
    host = html.escape(redirect_uri.split("/")[2])
    return (f"<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>Herdogroco</title>"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<style>{STYLE}</style><h1>Herdogroco</h1>"
            f"<p><b>{host}</b> asks for access to your Hermes agent (profile grokovo).</p>"
            f"<form method=\"post\"><input type=\"hidden\" name=\"transaction\" "
            f"value=\"{html.escape(transaction)}\">"
            f"<label>Pairing code<input name=\"pairing_secret\" autocomplete=\"off\" required></label>"
            f"<button>Allow</button></form>"
            f"<small>Create a code with: docker exec herdogroco python -m herdogroco pair</small></html>")
