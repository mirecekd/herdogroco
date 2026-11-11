# Changelog

All notable changes to this project are documented here.

Maintainer: Miroslav Dvorak

## Unreleased

### New

- Extensive, configurable logging: `LOG_LEVEL`, `LOG_FORMAT` (text or json) and
  `LOG_CONTENT`. One access line per request, a request id on every line and
  in the `X-Request-Id` header, OAuth, MCP and Hermes run events, and a
  rejection `reason` for every failed OAuth step.

### Changed

- `web.py` split into `httpkit.py`, `oauth_views.py` and `web.py`.
- Licence notice completed: `LICENSE`, README and the source headers now list every
  file derived from grok_connector (Jenik5, MIT), not only the two OAuth modules.

### Security

- Tokens, codes, cookies, the pairing code and the Hermes key are never
  logged; clients and sessions are logged as fingerprints only.

## 0.1.0

### New

- Remote MCP server that lets Grok (grok.com or a Tesla) use a Hermes Agent
  through a custom connector.
- OAuth with PKCE and a single-use pairing code created with
  `python -m herdogroco pair`.
- Tools `ask_hermes`, `hermes_task_status` and `hermes_task_cancel`.
- Forwarding to the Hermes Agent API server profile `grokovo`, with a
  synchronous wait (`HERMES_SYNC_TIMEOUT`) and background continuation.
- `/health` endpoint and a container healthcheck.
- Dockerfile, `docker-compose.yml` (host networking, loopback bind) and
  `.env.example`.
- GitHub Actions workflow that runs `ruff` and `pytest`, then builds and
  publishes a multi-arch (amd64, arm64) image to GHCR.
- Dependabot configuration for pip, docker and github-actions.

### Changed

- None.

### Fixed

- None.

### Security

- Tokens and the pairing code are stored as hashes.
- `Origin` checks and rate limits on sensitive endpoints.
- Tasks that require a manual approval are cancelled automatically.
- The Hermes key never leaves the server.

### Breaking

- None. First release.
