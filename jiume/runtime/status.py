"""Runtime diagnostics shared by JiuMe setup, launcher, and settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from jiume.runtime.health import RuntimeHealth

RuntimeStatusCode = Literal[
    "not_running",
    "config_missing",
    "validation_failed",
    "chat_unavailable",
    "ready",
]


@dataclass(frozen=True)
class RuntimeDiagnostic:
    code: RuntimeStatusCode
    label: str
    detail: str
    primary_action: str = "打开 JiuwenSwarm 配置"
    secondary_action: str = "重新检测"

    @property
    def ready(self) -> bool:
        return self.code == "ready"

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "code": self.code,
            "label": self.label,
            "detail": self.detail,
            "primaryAction": self.primary_action,
            "secondaryAction": self.secondary_action,
            "ready": self.ready,
        }


def runtime_config_url(*, host: str = "localhost", port: int = 5173) -> str:
    safe_host = str(host or "localhost").strip() or "localhost"
    safe_port = int(port or 5173)
    return f"http://{safe_host}:{safe_port}/?panel=config"


def runtime_diagnostic_from_health(
    health: "RuntimeHealth",
    service_payload: dict[str, Any] | None = None,
) -> RuntimeDiagnostic:
    from jiume.runtime.health import RuntimeHealthCode

    if health.ready:
        return RuntimeDiagnostic(
            code="ready",
            label="Agent runtime 已连接",
            detail=health.detail or "Gateway 已返回 connection.ack。",
        )
    if health.code == RuntimeHealthCode.NOT_RUNNING:
        return RuntimeDiagnostic(
            code="not_running",
            label="Gateway 未启动",
            detail=health.detail or "还没有可检测的 Gateway URL。",
        )
    if health.code in {
        RuntimeHealthCode.CONNECT_FAILED,
        RuntimeHealthCode.ACK_TIMEOUT,
        RuntimeHealthCode.INVALID_ACK,
    }:
        detail = health.detail or "Gateway 没有返回可用连接确认。"
        return RuntimeDiagnostic(
            code="not_running",
            label="Gateway 未连接",
            detail=f"Live health: {detail}",
        )
    return RuntimeDiagnostic(
        code="not_running",
        label="Gateway 未连接",
        detail=health.detail or "Gateway live health 未通过。",
    )


def runtime_diagnostic_from_service(payload: dict[str, Any] | None) -> RuntimeDiagnostic:
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, dict):
        return RuntimeDiagnostic(
            code="not_running",
            label="JiuwenSwarm 未启动",
            detail="还没有检测到 JiuMe launcher 写入的 runtime 状态。",
        )

    agent = services.get("agent")
    if not isinstance(agent, dict):
        return RuntimeDiagnostic(
            code="not_running",
            label="Gateway 未启动",
            detail="没有检测到 JiuwenSwarm Agent/Gateway 服务。",
        )

    status = str(agent.get("status") or "").strip().lower()
    mode = str(agent.get("mode") or "").strip()
    exit_code = agent.get("exit_code")
    gateway_ready = agent.get("gateway_ready")
    if status in {"running", "reused"}:
        if gateway_ready is False:
            return RuntimeDiagnostic(
                code="validation_failed",
                label="Gateway 还未通过检测",
                detail="JiuwenSwarm 进程存在，但 Gateway 端口还不可达。请稍后重新检测，或打开配置页检查模型。",
            )
        return RuntimeDiagnostic(
            code="ready",
            label="Agent runtime 已连接",
            detail="Gateway 可达。模型配置仍以 JiuwenSwarm 配置页为准，需要时可以重新打开验证。",
        )
    if status == "disabled":
        return RuntimeDiagnostic(
            code="config_missing",
            label="Agent runtime 未启用",
            detail="JiuMe 没有启动 runtime。请在 JiuwenSwarm 配置页补齐模型并重新检测。",
        )
    if status == "exited":
        extra = f"退出码 {exit_code}" if exit_code is not None else "服务已退出"
        return RuntimeDiagnostic(
            code="chat_unavailable",
            label="Agent runtime 已退出",
            detail=f"{extra}。请重新检测，或打开 JiuwenSwarm 配置修复模型/Gateway。",
        )
    if mode == "managed":
        return RuntimeDiagnostic(
            code="validation_failed",
            label="Agent runtime 正在启动",
            detail="服务已由 JiuMe 管理，但还没有通过连接检测。",
        )
    return RuntimeDiagnostic(
        code="not_running",
        label="Agent runtime 状态未知",
        detail="请打开 JiuwenSwarm 配置页确认模型和 Gateway。",
    )
