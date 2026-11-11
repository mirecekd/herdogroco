# herdogroco/pages.py
"""Authorization and error pages in the Copper document style. One inline stylesheet, no scripts."""

import base64
import hashlib
import html

from . import VERSION
from .logo import LOGO

STYLE = """
:root{color-scheme:dark;--paper:#202323;--ink:#eee9e1;--muted:#bdbcb5;--line:#545854;--accent:#e7ac80;
--surface:#303635;--soft:#f1d6b4;--bad:#e08a7a}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif;
line-height:1.7;-webkit-font-smoothing:antialiased}
.shell{max-width:30rem;margin:auto;padding:0 24px 56px}
.meta{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);display:flex;
flex-wrap:wrap;gap:8px 24px;padding:24px 0 18px;border-bottom:1px solid var(--line)}
.meta span:first-child::before{content:'';display:inline-block;width:8px;height:8px;
background:var(--accent);border-radius:50%;margin-right:10px}
.logo{display:block;width:176px;height:auto;margin:32px auto 0}
h1{font-size:clamp(30px,8vw,40px);line-height:1.1;letter-spacing:-.05em;font-weight:500;
margin:20px 0 10px;text-align:center}
.lead{color:var(--muted);font-size:16px;text-align:center;margin:0 0 8px}
strong{color:#fff;font-weight:600}
.callout{background:var(--surface);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;
padding:14px 18px;margin:22px 0}
.callout p{margin:0}
.label{display:block;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);
margin-bottom:4px}
.callout.bad{border-left-color:var(--bad)}
.callout.bad .label{color:var(--bad)}
label{display:block;font-size:13px;color:var(--muted);margin-top:18px}
input{width:100%;margin-top:6px;padding:12px 14px;background:var(--surface);color:var(--ink);
border:1px solid var(--line);border-radius:8px;font:inherit;letter-spacing:.04em}
button{width:100%;margin-top:16px;padding:13px 14px;background:var(--accent);color:#202323;border:0;
border-radius:8px;font:inherit;font-weight:600;cursor:pointer}
button:hover{background:var(--soft)}
input:focus-visible,button:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
code{background:var(--surface);border:1px solid var(--line);padding:1px 6px;border-radius:4px;
font-size:.88em;color:var(--soft);word-break:break-all}
.hint{color:var(--muted);font-size:13px;margin-top:22px}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);
font-size:12px;text-align:center}
"""
STYLE_SOURCE = "'sha256-" + base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode() + "'"
# For pages without a form (errors): nothing may load, nothing may submit.
STATIC_CSP = f"default-src 'none'; style-src {STYLE_SOURCE}; base-uri 'none'; frame-ancestors 'none'"


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="referrer" content="same-origin">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="color-scheme" content="dark"><title>{html.escape(title)}</title>'
        f'<style>{STYLE}</style></head><body><main class="shell">'
        '<div class="meta"><span>herdogroco</span><span>OAuth</span><span>Hermes profile grokovo</span></div>'
        f"{LOGO}<h1>herdogroco</h1>{body}"
        f"<footer>herdogroco {VERSION} - MIT licence</footer></main></body></html>"
    )


def render(redirect_uri: str, transaction: str) -> str:
    host = html.escape(redirect_uri.split("/")[2])
    return _page("herdogroco - authorize", (
        '<p class="lead">Connector for your Hermes Agent</p>'
        f'<div class="callout"><span class="label">Access request</span>'
        f"<p><strong>{host}</strong> asks to talk to your Hermes Agent: send it tasks, read the answers "
        "and cancel running tasks.</p></div>"
        '<form method="post">'
        f'<input type="hidden" name="transaction" value="{html.escape(transaction)}">'
        '<label>Pairing code<input name="pairing_secret" autocomplete="off" autocapitalize="off" '
        'spellcheck="false" required autofocus></label>'
        "<button>Allow access</button></form>"
        '<p class="hint">No code yet? Create one on the server (valid 10 minutes, single use):<br>'
        "<code>docker exec herdogroco python -m herdogroco pair</code></p>"))


def render_error(title: str, message: str) -> str:
    return _page(f"herdogroco - {title}", (
        f'<div class="callout bad"><span class="label">{html.escape(title)}</span>'
        f"<p>{html.escape(message)}</p></div>"
        '<p class="hint">Go back to Grok and start the connection again.</p>'))
