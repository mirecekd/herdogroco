# herdogroco

Talk to your own Hermes Agent from Grok - on grok.com or in a Tesla - through a
custom connector (remote MCP with OAuth).

<div align="center">

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/mirecekd) [!["PayPal.me"](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/donate/?business=LJ5ZF7Q9KMTRW&no_recurring=0&currency_code=USD)

</div>

## What it is

herdogroco is a small aiohttp service that exposes a Hermes Agent as a Grok
connector. Grok (on grok.com or in a Tesla) calls it as a custom connector over
MCP, authenticates through OAuth, and herdogroco forwards the request to the
Hermes Agent API server profile `grokovo`. The answer is short and plain text,
because it is read aloud.

## Architecture

```
  Grok (grok.com / Tesla)
          |
          |  HTTPS, MCP + OAuth
          v
  Caddy (reverse proxy, TLS)
          |
          |  http://127.0.0.1:8130
          v
  herdogroco (MCP server + OAuth)
          |
          |  HTTP, API key
          v
  Hermes Agent API server, profile "grokovo"
  (127.0.0.1:8642, /p/grokovo/v1)
```

## Tools

| Tool | What it does |
| --- | --- |
| `ask_hermes` | Sends a task to Hermes. If the answer arrives within `HERMES_SYNC_TIMEOUT` seconds it is returned directly; otherwise the task keeps running and a task id is returned. |
| `hermes_task_status` | Returns the status and, when finished, the output of a task by its id. |
| `hermes_task_cancel` | Cancels a running task by its id. |

Tasks that stop and wait for a manual approval are cancelled automatically,
because nobody can answer an approval prompt by voice.

## Quick start

1. Prepare the configuration:

   ```
   git clone https://github.com/mirecekd/herdogroco.git
   cd herdogroco
   cp .env.example .env
   # edit .env: set HERMES_KEY and PUBLIC_URL
   mkdir -p data && sudo chown 1000:1000 data
   ```

2. Start the container:

   ```
   docker compose up -d
   ```

3. Add the Caddy site (see [Caddy reverse proxy](#caddy-reverse-proxy)) and
   reload Caddy.

4. Generate a pairing code:

   ```
   docker exec herdogroco python -m herdogroco pair
   ```

   The code is valid for 10 minutes and can be used once.

5. In Grok open `grok.com/connectors` -> **New Connector** -> **Custom**, set
   the URL to `https://herdogroco.dev.mirecek.org/mcp` (your `PUBLIC_URL` plus
   `/mcp`) and enter the pairing code when asked.

## Hermes side setup

herdogroco talks to a dedicated Hermes profile named `grokovo`. Enable the API
server for that profile by setting a key in `~/.hermes/profiles/grokovo/.env`:

```
API_SERVER_KEY=<a long random value>
```

Hermes then serves the profile at `http://127.0.0.1:8642/p/grokovo/v1`. Use that
URL as `HERMES_URL` and the same key as `HERMES_KEY` in the herdogroco `.env`.

## Configuration

All settings are environment variables, normally set in `.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `HERMES_URL` | required | Base URL of the Hermes API server profile, for example `http://127.0.0.1:8642/p/grokovo/v1`. |
| `HERMES_KEY` | required | `API_SERVER_KEY` of the Hermes profile. |
| `PUBLIC_URL` | required | Public HTTPS URL of this service, used for OAuth metadata and the connector URL. |
| `HOST` | `127.0.0.1` | Listen address. The Docker image defaults to `0.0.0.0`; `docker-compose.yml` sets `127.0.0.1`. |
| `PORT` | `8130` | Listen port. |
| `DATA_DIR` | `data` | Directory for OAuth state. `/app/data` in the container. |
| `HERMES_SESSION` | `herdogroco-grok` | Hermes session name for Grok requests. |
| `HERMES_SYNC_TIMEOUT` | `25` | Seconds to wait for an answer before the task continues in the background. |
| `TASK_PREFIX` | built-in | Optional text prepended to every task. The default asks for short spoken answers without markdown. |
| `LOG_LEVEL` | `INFO` | Python log level. |

## Caddy reverse proxy

The compose file uses host networking and binds to `127.0.0.1`, so a reverse
proxy on the same host is the only way in. A plain reverse proxy is enough, with
no extra authentication in front, because the app does OAuth itself:

```
herdogroco.dev.mirecek.org {
    reverse_proxy 127.0.0.1:8130
}
```

## Security

- OAuth with PKCE. Connecting a new client requires a pairing code that is
  generated on the server, is valid for 10 minutes and can be used only once.
- Access tokens and the pairing code are stored only as hashes.
- Requests with a foreign `Origin` header are rejected.
- Sensitive endpoints are rate limited.
- Tasks that require a manual approval are cancelled automatically.
- The Hermes key stays on the server and is never sent to Grok.
- Run herdogroco against a restricted Hermes profile (`grokovo`) with only the
  tools you are willing to hand to a voice assistant.

## Development

```
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
ruff check .
pytest
```

Run the server locally with `python -m herdogroco` and create a pairing code
with `python -m herdogroco pair`.

## License

MIT - (c) 2026 Miroslav Dvorak. See [LICENSE](LICENSE).

## Acknowledgements

- [GrokConnectorForHomeAssistant](https://github.com/Jenik5/GrokConnectorForHomeAssistant) by Jenik5 (MIT) -
  the OAuth code in `herdogroco/oauth.py` and `herdogroco/tokens.py` is derived
  from it.
- [teskitty](https://github.com/mirecekd/teskitty) - the sibling project whose
  Hermes link settings and packaging this one follows.

## Support

<div align="center">

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/mirecekd) [!["PayPal.me"](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/donate/?business=LJ5ZF7Q9KMTRW&no_recurring=0&currency_code=USD)

</div>
