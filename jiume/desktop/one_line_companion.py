"""Daily one-line companion contract for the desktop avatar."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from jiume.desktop.gateway_client import GatewayEvent, gateway_event_artifacts, gateway_event_text

CompanionMode = Literal["resting", "listening", "working", "need_user", "done"]

ONE_LINE_INPUT_HINT = "想让我做什么？"
WORKING_STATUSES = ("在想", "在看", "在整理", "等你确认", "快好了")
DAILY_FORBIDDEN_LABELS = (
    "猜拳",
    "掷骰子",
    "抽签",
    "看屏幕",
    "交屏幕",
    "贴材料",
    "交材料",
    "选文件",
    "选 skill",
    "当前 skill",
    "取消当前 skill",
    "打开技能货架",
    "看进度",
    "看任务进度",
    "看产物",
    "看结果",
    "看问题",
    "打开产物列表",
    "停止当前任务",
    "后台状态",
    "陪伴等级",
)
INFRASTRUCTURE_WORDS = (
    "gateway",
    "agentserver",
    "model config",
    "offline mode",
    "websocket",
    "request_id",
)

_DEFAULT_WORKING_STATUS = "在想"
_QUESTION_LIMIT = 22
_SUMMARY_LIMIT = 28
_DONE_GENERIC = "任务已结束。"
_DONE_ARTIFACT = "整理好了。"
_DONE_PREFIXES = (
    "整理好了",
    "已整理好",
    "已经整理好",
    "收好了",
    "已经收好",
    "收到产物",
    "完成了",
    "已完成",
    "搞定",
)
_FAILED_WITH_DETAIL = "我卡住了，可以换个说法再试一次。"
_FAILED_GENERIC = "这件事现在还不能继续。"
FAILED_SUBTASK_STATUSES = frozenset({"error", "failed", "failure"})
COMPLETED_SUBTASK_STATUSES = frozenset({"completed", "done", "success", "succeeded"})
SENSITIVE_DETAIL_WORDS = (
    "token",
    "secret",
    "private",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "密码",
    "密钥",
    "私钥",
)


@dataclass(frozen=True)
class CompanionAction:
    id: str
    label: str


@dataclass(frozen=True)
class TaskCapsule:
    mode: CompanionMode
    short_status: str = ""
    question: str = ""
    summary: str = ""
    actions: tuple[CompanionAction, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", tuple(self.actions))

    @property
    def primary_text(self) -> str:
        return self.question or self.summary or self.short_status


def daily_label_is_allowed(label: str) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    return not any(forbidden in text for forbidden in DAILY_FORBIDDEN_LABELS)


def working_capsule(status: str = _DEFAULT_WORKING_STATUS) -> TaskCapsule:
    safe_status = status if status in WORKING_STATUSES else _DEFAULT_WORKING_STATUS
    return TaskCapsule(mode="working", short_status=safe_status)


def need_user_capsule(question: str, allow_cancel: bool = True) -> TaskCapsule:
    actions: list[CompanionAction] = [CompanionAction(id="confirm", label="好的")]
    if allow_cancel:
        actions.append(CompanionAction(id="cancel", label="取消"))
    return TaskCapsule(
        mode="need_user",
        question=_clip_text(question, _QUESTION_LIMIT, "需要你确认下一步。"),
        actions=actions,
    )


def done_capsule(summary: str, has_artifact: bool = False) -> TaskCapsule:
    actions = (CompanionAction(id="view", label="查看"),) if has_artifact else ()
    return TaskCapsule(mode="done", summary=_done_summary(summary, has_artifact=has_artifact), actions=actions)


def failed_capsule(detail: str = "") -> TaskCapsule:
    if _contains_infrastructure_word(detail):
        summary = _FAILED_GENERIC
    elif str(detail or "").strip():
        summary = _FAILED_WITH_DETAIL
    else:
        summary = _FAILED_GENERIC
    return TaskCapsule(mode="done", summary=summary)


def capsule_for_gateway_event(event: GatewayEvent, current_reply: str = "") -> TaskCapsule | None:
    if event.kind == "response":
        return (
            working_capsule(_DEFAULT_WORKING_STATUS)
            if event.ok
            else failed_capsule(gateway_event_text(event) or event.error)
        )
    if event.kind == "error":
        return failed_capsule(gateway_event_text(event) or event.error)
    if event.kind != "event":
        return None

    event_name = event.event
    text = gateway_event_text(event)

    if event_name == "chat.error":
        return failed_capsule(text)
    if event_name == "chat.processing_status":
        payload = event.payload or {}
        if payload.get("is_processing"):
            return working_capsule("在整理")
        return done_capsule(current_reply or text or "任务已结束。")
    if event_name == "chat.delta":
        return working_capsule("快好了")
    if event_name == "chat.final":
        return done_capsule(
            text or current_reply or "任务已结束。",
            has_artifact=bool(gateway_event_artifacts(event)),
        )
    if event_name == "chat.ask_user_question":
        return need_user_capsule(text)
    if event_name in {"chat.file", "chat.media", "chat.session_result", "session_result"}:
        return done_capsule(text or current_reply or "收到产物。", has_artifact=True)
    if event_name == "chat.subtask_update":
        status = str((event.payload or {}).get("status") or "").strip().lower()
        if gateway_subtask_status_is_failed(status):
            return failed_capsule(text)
        if gateway_subtask_status_is_completed(status):
            return working_capsule("快好了")
        return working_capsule("在整理")
    if event_name in {"chat.tool_call", "chat.tool_result"}:
        return working_capsule("在整理")
    return None


def _clip_text(value: str, limit: int, fallback: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _done_summary(value: str, *, has_artifact: bool = False) -> str:
    text = _strip_infrastructure_words(value)
    fallback = _DONE_ARTIFACT if has_artifact else _DONE_GENERIC
    if _contains_sensitive_detail(text):
        return fallback
    normalized = _clip_text(text, _SUMMARY_LIMIT, "").strip()
    if not normalized:
        return fallback
    for prefix in _DONE_PREFIXES:
        if normalized.startswith(prefix):
            return _DONE_ARTIFACT if prefix != "收到产物" else "收到产物。"
    if normalized in {_DONE_GENERIC, _DONE_ARTIFACT}:
        return normalized
    return fallback


def _contains_infrastructure_word(value: str) -> bool:
    lowered = str(value or "").lower()
    return any(word in lowered for word in INFRASTRUCTURE_WORDS)


def _contains_sensitive_detail(value: str) -> bool:
    text = str(value or "")
    lowered = text.lower()
    if any(word in lowered for word in SENSITIVE_DETAIL_WORDS):
        return True
    if re.search(r"(^|\s)(/Users/|/var/|/tmp/|~/|[A-Za-z]:[\\/])", text):
        return True
    if re.search(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", text):
        return True
    return bool(re.search(r"\b(sk|pk)-[A-Za-z0-9_-]{12,}\b", text))


def _strip_infrastructure_words(value: str) -> str:
    text = str(value or "")
    for word in INFRASTRUCTURE_WORDS:
        text = re.sub(re.escape(word), "", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip()


def gateway_subtask_status_is_failed(status: str) -> bool:
    return str(status or "").strip().lower() in FAILED_SUBTASK_STATUSES


def gateway_subtask_status_is_completed(status: str) -> bool:
    return str(status or "").strip().lower() in COMPLETED_SUBTASK_STATUSES
