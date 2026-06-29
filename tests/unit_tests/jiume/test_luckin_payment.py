from __future__ import annotations

import json
from typing import Any

import jiume.launcher as jiume_launcher
from jiume.launcher import LaunchPlan
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


def test_luckin_launcher_bootstrap_is_non_fatal_for_managed_agent(monkeypatch, capsys) -> None:
    calls = 0

    def raise_config_error() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise RuntimeError("local-test-token should not leak")

    monkeypatch.setattr(jiume_launcher, "ensure_luckin_mcp_config", raise_config_error)
    plan = LaunchPlan(
        setup_command=None,
        agent_command=["/python", "-m", "jiuwenswarm.app"],
        web_command=None,
        wait_for_gateway=True,
        runtime_config_url="http://localhost:5173/?panel=config",
    )

    jiume_launcher._bootstrap_luckin_mcp_for_launch(plan)

    out = capsys.readouterr().out
    assert calls == 1
    assert "Luckin MCP bootstrap skipped (RuntimeError)" in out
    assert "local-test-token" not in out
    assert "Authorization" not in out


def test_luckin_launcher_bootstrap_skips_without_managed_agent(monkeypatch) -> None:
    def fail_config() -> dict[str, Any]:
        raise AssertionError("should not bootstrap Luckin MCP without managed agent")

    monkeypatch.setattr(jiume_launcher, "ensure_luckin_mcp_config", fail_config)
    plan = LaunchPlan(
        setup_command=None,
        agent_command=None,
        web_command=None,
        wait_for_gateway=False,
        runtime_config_url="http://localhost:5173/?panel=config",
    )

    jiume_launcher._bootstrap_luckin_mcp_for_launch(plan)
