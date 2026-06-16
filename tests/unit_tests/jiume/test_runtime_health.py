from __future__ import annotations

import asyncio
import importlib
import json
import sys

import pytest

from jiume.runtime.health import RuntimeHealth, RuntimeHealthCode
import jiume.runtime.health as runtime_health
from jiume.runtime.status import runtime_diagnostic_from_health


def test_runtime_health_as_dict_shape() -> None:
    health = RuntimeHealth(
        code=RuntimeHealthCode.READY,
        detail="Gateway acknowledged connection.",
        checked_url="ws://127.0.0.1:19092/ws",
    )

    assert health.ready is True
    assert health.as_dict() == {
        "code": "ready",
        "detail": "Gateway acknowledged connection.",
        "checkedUrl": "ws://127.0.0.1:19092/ws",
        "ready": True,
    }


def test_live_ready_overrides_stale_service_status() -> None:
    diagnostic = runtime_diagnostic_from_health(
        RuntimeHealth(
            code=RuntimeHealthCode.READY,
            detail="Gateway acknowledged connection.",
            checked_url="ws://127.0.0.1:19092/ws",
        ),
        service_payload={"services": {"agent": {"status": "exited", "exit_code": 1}}},
    )

    assert diagnostic.ready is True
    assert diagnostic.code == "ready"
    assert diagnostic.label == "Agent runtime 已连接"
    assert "Gateway acknowledged connection." in diagnostic.detail


def test_live_failure_returns_gateway_disconnected_detail() -> None:
    diagnostic = runtime_diagnostic_from_health(
        RuntimeHealth(
            code=RuntimeHealthCode.CONNECT_FAILED,
            detail="connection refused",
            checked_url="ws://127.0.0.1:19092/ws",
        ),
        service_payload={"services": {"agent": {"status": "running", "gateway_ready": True}}},
    )

    assert diagnostic.ready is False
    assert diagnostic.code == "not_running"
    assert diagnostic.label == "Gateway 未连接"
    assert "connection refused" in diagnostic.detail


def test_live_unknown_failure_does_not_fall_back_to_stale_ready_service() -> None:
    class UnknownHealth:
        ready = False
        code = "unexpected"
        detail = "probe failed"

    diagnostic = runtime_diagnostic_from_health(
        UnknownHealth(),  # type: ignore[arg-type]
        service_payload={"services": {"agent": {"status": "running", "gateway_ready": True}}},
    )

    assert not diagnostic.ready
    assert diagnostic.code == "not_running"
    assert diagnostic.label == "Gateway 未连接"


def test_check_gateway_health_classifies_first_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeWebSocket:
        async def __aenter__(self) -> "FakeWebSocket":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def recv(self) -> str:
            return json.dumps({"type": "event", "event": "connection.ack"})

    def fake_connect(_url: str):
        return FakeWebSocket()

    monkeypatch.setattr(runtime_health.websockets, "connect", fake_connect)

    ready = runtime_health.check_gateway_health("ws://127.0.0.1:19092/ws", timeout_seconds=0.01)
    empty = runtime_health.check_gateway_health("", timeout_seconds=0.01)

    assert ready.code == RuntimeHealthCode.READY
    assert ready.ready
    assert ready.checked_url == "ws://127.0.0.1:19092/ws"
    assert empty.code == RuntimeHealthCode.NOT_RUNNING


def test_check_gateway_health_rejects_invalid_first_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeWebSocket:
        async def __aenter__(self) -> "FakeWebSocket":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def recv(self) -> str:
            return json.dumps({"type": "event", "event": "something.else"})

    def fake_connect(_url: str):
        return FakeWebSocket()

    monkeypatch.setattr(runtime_health.websockets, "connect", fake_connect)

    health = runtime_health.check_gateway_health("ws://127.0.0.1:19092/ws", timeout_seconds=0.01)

    assert health.code == RuntimeHealthCode.INVALID_ACK
    assert "connection.ack" in health.detail


def test_check_gateway_health_is_safe_inside_running_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeWebSocket:
        async def __aenter__(self) -> "FakeWebSocket":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def recv(self) -> str:
            return json.dumps({"type": "event", "event": "connection.ack"})

    def fake_connect(_url: str):
        return FakeWebSocket()

    monkeypatch.setattr(runtime_health.websockets, "connect", fake_connect)

    async def run_inside_loop() -> tuple[RuntimeHealth, RuntimeHealth]:
        health = await asyncio.to_thread(
            runtime_health.check_gateway_health,
            "ws://127.0.0.1:19092/ws",
            0.01,
        )
        inline_health = runtime_health.check_gateway_health(
            "ws://127.0.0.1:19092/ws",
            timeout_seconds=0.01,
        )
        return health, inline_health

    health, inline_health = asyncio.run(run_inside_loop())

    assert health.code == RuntimeHealthCode.READY
    assert inline_health.code == RuntimeHealthCode.READY


def test_runtime_status_import_does_not_eagerly_import_runtime_health() -> None:
    sys.modules.pop("jiume.runtime.status", None)
    sys.modules.pop("jiume.runtime.health", None)

    importlib.import_module("jiume.runtime.status")

    assert "jiume.runtime.health" not in sys.modules
