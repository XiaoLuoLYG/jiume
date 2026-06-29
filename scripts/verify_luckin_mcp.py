#!/usr/bin/env python3
"""Verify Luckin's official Streamable HTTP MCP exposes the expected tools."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Iterable

LUCKIN_MCP_NAME = "luckin-coffee"
LUCKIN_MCP_URL = "https://gwmcp.lkcoffee.com/order/user/mcp"
LUCKIN_TOKEN_ENV = "JIUME_LUCKIN_MCP_TOKEN"
EXPECTED_TOOLS = {
    "queryShopList",
    "searchProductForMcp",
    "switchProduct",
    "queryProductDetailInfo",
    "previewOrder",
    "createOrder",
    "queryOrderDetailInfo",
    "cancelOrder",
}


def _base_summary(*, ok: bool, tools: Iterable[str]) -> dict[str, Any]:
    names = sorted(set(tools))
    return {
        "ok": ok,
        "server": LUCKIN_MCP_NAME,
        "url": LUCKIN_MCP_URL,
        "tool_count": len(names),
        "tools": names,
    }


def _missing_summary(tools: Iterable[str]) -> tuple[int, dict[str, Any]]:
    summary = _base_summary(ok=True, tools=tools)
    missing = sorted(EXPECTED_TOOLS - set(summary["tools"]))
    if missing:
        summary["ok"] = False
        summary["missing_tools"] = missing
        return 1, summary
    return 0, summary


def _safe_message(exc: BaseException, token: str) -> str:
    message = str(exc) or exc.__class__.__name__
    if token:
        message = message.replace(token, "<redacted>")
    return re.sub(r"Bearer\s+\S+", "Bearer <redacted>", message)


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name", "")).strip()
    return str(getattr(tool, "name", "")).strip()


def _make_client(token: str) -> Any:
    from openjiuwen.core.foundation.tool import McpServerConfig
    from openjiuwen.core.runner.resources_manager.tool_manager import ToolMgr

    cfg = McpServerConfig(
        server_name=LUCKIN_MCP_NAME,
        server_path=LUCKIN_MCP_URL,
        client_type="streamable_http",
        auth_headers={"Authorization": f"Bearer {token}"},
        params={"timeout_s": 30},
    )
    return ToolMgr._create_client(cfg)


async def verify(token: str, *, make_client=_make_client) -> tuple[int, dict[str, Any]]:
    client = None
    try:
        client = make_client(token)
        connected = await client.connect(timeout=30.0)
        if not connected:
            raise ConnectionError("connection failed")
        tools = [_tool_name(tool) for tool in await client.list_tools(timeout=30.0)]
        return _missing_summary(name for name in tools if name)
    except Exception as exc:
        summary = _base_summary(ok=False, tools=[])
        summary["error_type"] = exc.__class__.__name__
        summary["message"] = _safe_message(exc, token)
        return 1, summary
    finally:
        if client is not None:
            try:
                await client.disconnect(timeout=5.0)
            except Exception:
                pass


def main() -> int:
    token = os.getenv(LUCKIN_TOKEN_ENV, "")
    if not token:
        print(LUCKIN_TOKEN_ENV)
        return 1

    logging.disable(logging.CRITICAL)
    code, summary = asyncio.run(verify(token))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
