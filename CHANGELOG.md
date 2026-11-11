# Changelog

All notable changes to this project are documented here.

Maintainer: Miroslav Dvorak

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
