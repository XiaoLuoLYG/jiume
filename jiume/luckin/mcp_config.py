"""Bootstrap the Luckin Coffee MCP server from local environment state."""

from __future__ import annotations

import os
from typing import Any, Callable

from jiuwenswarm.common.config import get_mcp_server_config, upsert_mcp_server_in_config

LUCKIN_MCP_NAME = "luckin-coffee"
LUCKIN_MCP_URL = "https://gwmcp.lkcoffee.com/order/user/mcp"
LUCKIN_TOKEN_ENV = "JIUME_LUCKIN_MCP_TOKEN"


def luckin_mcp_server_payload() -> dict[str, Any]:
    return {
        "name": LUCKIN_MCP_NAME,
        "enabled": True,
        "transport": "streamable_http",
        "url": LUCKIN_MCP_URL,
        "headers": {"Authorization": f"Bearer ${{{LUCKIN_TOKEN_ENV}}}"},
        "timeout_s": 30,
    }


def ensure_luckin_mcp_config(
    *,
    get_existing: Callable[[str], dict[str, Any] | None] = get_mcp_server_config,
    upsert: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]] = upsert_mcp_server_in_config,
) -> dict[str, Any]:
    if not os.getenv(LUCKIN_TOKEN_ENV):
        return {"configured": False, "reason": "missing_token"}

    desired = luckin_mcp_server_payload()
    if get_existing(LUCKIN_MCP_NAME) == desired:
        return {"configured": True, "created": False, "name": LUCKIN_MCP_NAME}

    _, created = upsert(desired)
    return {"configured": True, "created": bool(created), "name": LUCKIN_MCP_NAME}
