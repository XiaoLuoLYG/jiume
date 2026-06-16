"""Live runtime health probes for JiuMe's JiuwenSwarm gateway."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any

import websockets


class RuntimeHealthCode(str, Enum):
    NOT_RUNNING = "not_running"
    CONNECT_FAILED = "connect_failed"
    ACK_TIMEOUT = "ack_timeout"
    INVALID_ACK = "invalid_ack"
    READY = "ready"


@dataclass(frozen=True)
class RuntimeHealth:
    code: RuntimeHealthCode
    detail: str
    checked_url: str

    @property
    def ready(self) -> bool:
        return self.code == RuntimeHealthCode.READY

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "checkedUrl": self.checked_url,
            "ready": self.ready,
        }


async def _read_gateway_ack(gateway_url: str) -> Any:
    async with websockets.connect(gateway_url) as websocket:
        return await websocket.recv()


def _classify_first_frame(first_frame: Any, checked_url: str) -> RuntimeHealth:
    try:
        payload = json.loads(first_frame) if isinstance(first_frame, str) else first_frame
    except json.JSONDecodeError as exc:
        return RuntimeHealth(
            code=RuntimeHealthCode.INVALID_ACK,
            detail=f"Gateway first frame was not JSON: {exc.msg}.",
            checked_url=checked_url,
        )

    if not (
        isinstance(payload, dict)
        and payload.get("type") == "event"
        and payload.get("event") == "connection.ack"
    ):
        return RuntimeHealth(
            code=RuntimeHealthCode.INVALID_ACK,
            detail=f"Gateway first frame was not connection.ack: {payload!r}.",
            checked_url=checked_url,
        )

    return RuntimeHealth(
        code=RuntimeHealthCode.READY,
        detail="Gateway acknowledged connection.",
        checked_url=checked_url,
    )


async def check_gateway_health_async(gateway_url: str, timeout_seconds: float = 1.5) -> RuntimeHealth:
    checked_url = str(gateway_url or "").strip()
    if not checked_url:
        return RuntimeHealth(
            code=RuntimeHealthCode.NOT_RUNNING,
            detail="Gateway URL is empty.",
            checked_url="",
        )

    try:
        first_frame = await asyncio.wait_for(_read_gateway_ack(checked_url), timeout=timeout_seconds)
    except TimeoutError:
        return RuntimeHealth(
            code=RuntimeHealthCode.ACK_TIMEOUT,
            detail=f"Gateway did not send connection.ack within {timeout_seconds:.1f}s.",
            checked_url=checked_url,
        )
    except Exception as exc:
        return RuntimeHealth(
            code=RuntimeHealthCode.CONNECT_FAILED,
            detail=str(exc) or exc.__class__.__name__,
            checked_url=checked_url,
        )

    return _classify_first_frame(first_frame, checked_url)


def _check_gateway_health_in_new_loop(gateway_url: str, timeout_seconds: float) -> RuntimeHealth:
    return asyncio.run(check_gateway_health_async(gateway_url, timeout_seconds))


def check_gateway_health(gateway_url: str, timeout_seconds: float = 1.5) -> RuntimeHealth:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _check_gateway_health_in_new_loop(gateway_url, timeout_seconds)

    result: list[RuntimeHealth] = []
    error: list[BaseException] = []

    def run_probe() -> None:
        try:
            result.append(_check_gateway_health_in_new_loop(gateway_url, timeout_seconds))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=run_probe, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]
