"""Shared MCP transport normalization."""

from __future__ import annotations

from typing import Any


MCP_TRANSPORT_ALIASES = {
    "stdio": "stdio",
    "sse": "sse",
    "streamablehttp": "streamable_http",
    "streamable-http": "streamable_http",
    "streamable_http": "streamable_http",
}

MCP_TRANSPORTS = frozenset(MCP_TRANSPORT_ALIASES.values())


def normalize_mcp_transport(value: Any) -> str:
    return MCP_TRANSPORT_ALIASES.get(str(value).strip().lower(), "")
