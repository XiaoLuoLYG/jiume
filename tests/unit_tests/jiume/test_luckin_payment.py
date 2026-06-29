from __future__ import annotations

import json
from typing import Any

from jiume.luckin.mcp_config import (
    LUCKIN_MCP_NAME,
    LUCKIN_MCP_URL,
    LUCKIN_TOKEN_ENV,
    ensure_luckin_mcp_config,
    luckin_mcp_server_payload,
)


def test_luckin_mcp_payload_uses_token_placeholder(monkeypatch) -> None:
    monkeypatch.setenv(LUCKIN_TOKEN_ENV, "local-test-token")

    payload = luckin_mcp_server_payload()

    assert payload == {
        "name": LUCKIN_MCP_NAME,
        "enabled": True,
        "transport": "streamable_http",
        "url": LUCKIN_MCP_URL,
        "headers": {"Authorization": f"Bearer ${{{LUCKIN_TOKEN_ENV}}}"},
        "timeout_s": 30,
    }
    assert "local-test-token" not in json.dumps(payload)


def test_luckin_mcp_config_skips_without_token(monkeypatch) -> None:
    monkeypatch.delenv(LUCKIN_TOKEN_ENV, raising=False)

    def fail_get_existing(_name: str) -> dict[str, Any] | None:
        raise AssertionError("should not read real MCP config without token")

    def fail_upsert(_payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        raise AssertionError("should not write real MCP config without token")

    assert ensure_luckin_mcp_config(get_existing=fail_get_existing, upsert=fail_upsert) == {
        "configured": False,
        "reason": "missing_token",
    }


def test_luckin_mcp_config_upserts_placeholder_payload(monkeypatch) -> None:
    monkeypatch.setenv(LUCKIN_TOKEN_ENV, "local-test-token")
    captured: dict[str, Any] = {}

    def get_existing(_name: str) -> dict[str, Any] | None:
        return None

    def upsert(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        captured.update(payload)
        return payload, True

    assert ensure_luckin_mcp_config(get_existing=get_existing, upsert=upsert) == {
        "configured": True,
        "created": True,
        "name": LUCKIN_MCP_NAME,
    }
    assert captured["headers"]["Authorization"] == f"Bearer ${{{LUCKIN_TOKEN_ENV}}}"
    assert "local-test-token" not in json.dumps(captured)


def test_luckin_mcp_config_skips_upsert_when_existing_matches(monkeypatch) -> None:
    monkeypatch.setenv(LUCKIN_TOKEN_ENV, "local-test-token")

    def get_existing(_name: str) -> dict[str, Any]:
        return luckin_mcp_server_payload()

    def fail_upsert(_payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        raise AssertionError("should not upsert matching MCP config")

    assert ensure_luckin_mcp_config(get_existing=get_existing, upsert=fail_upsert) == {
        "configured": True,
        "created": False,
        "name": LUCKIN_MCP_NAME,
    }
