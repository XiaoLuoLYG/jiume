from __future__ import annotations

import json
from typing import Any

import jiume.desktop.app as desktop_app
import jiume.launcher as jiume_launcher
from jiume.desktop.app import JiuMeDesktopAvatar
from jiume.desktop.gateway_client import (
    GatewayEvent,
    gateway_event_artifacts,
    gateway_event_payment_deeplink,
    trusted_payment_deeplink,
)
from jiume.launcher import LaunchPlan
from jiume.luckin.mcp_config import (
    LUCKIN_MCP_NAME,
    LUCKIN_MCP_URL,
    LUCKIN_TOKEN_ENV,
    ensure_luckin_mcp_config,
    luckin_mcp_server_payload,
)
from jiume.runtime.context import _context_block
from jiume.skills.catalog import LUCKIN_ORDER_SKILL_ID, recommended_skill_by_id


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


def test_luckin_order_skill_is_recommended() -> None:
    skill = recommended_skill_by_id(LUCKIN_ORDER_SKILL_ID)

    assert skill is not None
    assert skill["category"] == "食"
    assert skill["risk"] == "high"
    assert "瑞幸" in skill["displayName"]


def test_luckin_order_skill_adds_prompt_boundary() -> None:
    profile = {
        "id": "local-test-twin",
        "displayName": "Local Test",
        "purpose": "Test",
        "tone": "plain",
        "permissions": {"defaultMode": "ask", "allowedSkillIds": [LUCKIN_ORDER_SKILL_ID]},
    }

    block = _context_block(profile, query="帮我点一杯常喝的瑞幸")

    assert "Luckin official MCP" in block
    assert "cancelOrder" in block
    assert "WeChat Pay confirmation is the payment approval" in block
    assert "Do not use QR code payment as the default path" in block
    assert "Ask before external actions, irreversible changes, calendar changes, payment" in block


def test_luckin_order_boundary_requires_mounted_skill() -> None:
    profile = {
        "id": "local-test-twin",
        "displayName": "Local Test",
        "purpose": "Test",
        "tone": "plain",
        "permissions": {"defaultMode": "ask", "allowedSkillIds": []},
    }

    block = _context_block(profile, query="帮我点一杯常喝的瑞幸")

    assert "Luckin official MCP" not in block
    assert "WeChat Pay confirmation is the payment approval" not in block
    assert "Do not use QR code payment as the default path" not in block
    assert "Ask before external actions, irreversible changes, calendar changes, payment" in block


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


def test_luckin_gateway_event_payment_deeplink_prefers_trusted_pay_url() -> None:
    event = GatewayEvent(
        kind="event",
        event="chat.tool_result",
        payload={
            "name": "createOrder",
            "result": {
                "orderIdStr": "local-test-order",
                "payOrderUrl": "weixin://wxpay/bizpayurl?pr=abc",
                "payOrderQrCodeUrl": "https://opentest03.lkcoffee.com/transfer/qrcode?token=qr",
            },
        },
    )

    assert gateway_event_payment_deeplink(event) == "weixin://wxpay/bizpayurl?pr=abc"


def test_luckin_gateway_event_payment_deeplink_rejects_qr_and_http() -> None:
    qr_only = GatewayEvent(
        kind="event",
        event="chat.tool_result",
        payload={"result": {"payOrderQrCodeUrl": "https://opentest03.lkcoffee.com/transfer/qrcode?token=qr"}},
    )
    http_pay = GatewayEvent(
        kind="event",
        event="chat.tool_result",
        payload={"result": {"payOrderUrl": "https://opentest03.lkcoffee.com/pay"}},
    )

    assert gateway_event_payment_deeplink(qr_only) == ""
    assert gateway_event_payment_deeplink(http_pay) == ""


def test_luckin_trusted_payment_deeplink_allows_only_wechat_pay() -> None:
    assert trusted_payment_deeplink("weixin://wxpay/bizpayurl?pr=abc")
    assert not trusted_payment_deeplink("weixin://not-pay")


def test_luckin_payment_artifact_is_payment_url() -> None:
    event = GatewayEvent(
        kind="event",
        event="chat.final",
        payload={"artifacts": [{"target": "weixin://wxpay/bizpayurl?pr=abc", "name": "微信支付"}]},
    )

    artifacts = gateway_event_artifacts(event)

    assert artifacts[0]["category"] == "payment"
    assert artifacts[0]["kind"] == "url"


def test_luckin_desktop_opens_trusted_wechat_pay_target(monkeypatch) -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    opened: list[str] = []
    avatar.show_bubble = lambda *_args, **_kwargs: None
    monkeypatch.setattr(desktop_app.webbrowser, "open", opened.append)

    JiuMeDesktopAvatar._open_activity_target(avatar, "weixin://wxpay/bizpayurl?pr=abc")

    assert opened == ["weixin://wxpay/bizpayurl?pr=abc"]


def test_luckin_payment_deeplink_open_is_deduped_and_redacted(monkeypatch) -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar._opened_payment_deeplinks = set()
    avatar._active_twin_id = "local-test-twin"
    bubbles: list[str] = []
    activities: list[tuple[str, str, str]] = []
    audits: list[tuple[str, str, dict[str, Any]]] = []
    opened: list[str] = []
    avatar.show_bubble = lambda text, **_kwargs: bubbles.append(str(text))
    avatar._record_activity = lambda kind, title, detail="": activities.append((kind, title, detail))
    monkeypatch.setattr(desktop_app.webbrowser, "open", lambda target: opened.append(target) or True)
    monkeypatch.setattr(
        desktop_app,
        "append_audit_event",
        lambda twin_id, event_type, payload: audits.append((twin_id, event_type, payload)),
    )
    event = GatewayEvent(
        kind="event",
        event="chat.tool_result",
        payload={"result": {"payOrderUrl": "weixin://wxpay/bizpayurl?pr=abc"}},
    )

    JiuMeDesktopAvatar._maybe_open_payment_deeplink(avatar, event)
    JiuMeDesktopAvatar._maybe_open_payment_deeplink(avatar, event)

    assert opened == ["weixin://wxpay/bizpayurl?pr=abc"]
    assert bubbles == []
    assert activities == [("payment", "打开微信支付", "我已打开微信支付，请在微信里确认。")]
    assert audits == [
        (
            "local-test-twin",
            "luckin.payment_deeplink_opened",
            {"scheme": "weixin", "target": "weixin://wxpay/[redacted]"},
        )
    ]
