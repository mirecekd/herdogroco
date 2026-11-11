# herdogroco/__init__.py
"""Herdogroco - Grok connector (remote MCP + OAuth) for a local Hermes Agent profile."""

VERSION = "0.1.0"
MCP_PATH = "/mcp"
OAUTH_PATH = "/oauth"
RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource" + MCP_PATH
SERVER_METADATA_PATH = "/.well-known/oauth-authorization-server" + OAUTH_PATH
SCOPE = "hermes"
