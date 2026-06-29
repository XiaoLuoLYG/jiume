"""Small WebSocket bridge from the JiuMe desktop avatar to JiuwenSwarm Gateway."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse

import jiume.paths

DEFAULT_GATEWAY_URL = "ws://127.0.0.1:19000/ws"
DEFAULT_AGENT_MODE = "agent.plan"
GATEWAY_SESSION_STATE_FILE = "gateway_session.json"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".sql", ".sh"}
TABLE_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".log", ".rst"}
TRUSTED_PAYMENT_DEEPLINK_PREFIXES = ("weixin://wxpay/",)
PAYMENT_DEEPLINK_KEYS = {"payOrderUrl", "pay_order_url", "paymentUrl", "payment_url"}


@dataclass(frozen=True)
class GatewayEvent:
    kind: Literal["response", "event", "error"]
    event: str = ""
    payload: dict[str, Any] | None = None
    request_id: str = ""
    ok: bool | None = None
    error: str = ""


def get_gateway_session_state_path() -> Path:
    return jiume.paths.get_jiume_root() / GATEWAY_SESSION_STATE_FILE


def _clean_gateway_session_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text.startswith("jiume_"):
        return ""
    if any(char in text for char in "/\\: \t\r\n"):
        return ""
    return text[:80]


def _read_gateway_session_id() -> str:
    path = get_gateway_session_state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return _clean_gateway_session_id(payload.get("session_id"))


def _write_gateway_session_id(session_id: str) -> None:
    clean = _clean_gateway_session_id(session_id)
    if not clean:
        return
    path = get_gateway_session_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": clean}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _default_gateway_session_id() -> str:
    existing = _read_gateway_session_id()
    if existing:
        return existing
    session_id = f"jiume_{secrets.token_hex(5)}"
    _write_gateway_session_id(session_id)
    return session_id


def normalize_gateway_frame(raw: str | bytes | dict[str, Any]) -> GatewayEvent | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        frame = raw
    if not isinstance(frame, dict):
        return None

    frame_type = frame.get("type")
    if frame_type == "res":
        payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
        error = str(frame.get("error") or payload.get("error") or "")
        return GatewayEvent(
            kind="response",
            request_id=str(frame.get("id") or ""),
            ok=bool(frame.get("ok")),
            payload=payload,
            error=error,
        )

    if frame_type == "event":
        payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
        return GatewayEvent(kind="event", event=str(frame.get("event") or ""), payload=payload)

    return None


def desktop_state_for_gateway_event(event: GatewayEvent) -> str | None:
    if event.kind == "error":
        return "error"
    if event.kind != "event":
        return None
    payload = event.payload or {}
    if event.event == "chat.processing_status":
        return "thinking" if payload.get("is_processing") else "idle"
    if event.event == "chat.delta":
        return "speaking"
    if event.event == "chat.final":
        return "success"
    if event.event == "chat.subtask_update":
        status = str(payload.get("status") or "").lower()
        if status in {"completed", "done", "success", "succeeded"}:
            return "success"
        if status in {"error", "failed", "failure"}:
            return "error"
        return "working"
    if event.event in {"chat.tool_call", "chat.tool_result"}:
        return "working"
    if event.event == "chat.ask_user_question":
        return "waiting_approval"
    if event.event == "chat.interrupt_result":
        return "success" if payload.get("success", True) else "error"
    if event.event == "chat.error":
        return "error"
    return None


def gateway_event_text(event: GatewayEvent) -> str:
    payload = event.payload or {}
    if event.kind == "error":
        return event.error
    if event.kind == "response" and event.ok is False:
        return event.error or "Gateway rejected the request."
    if event.event in {"chat.delta", "chat.final", "chat.error", "chat.file", "chat.media", "chat.session_result", "session_result"}:
        return str(payload.get("content") or payload.get("error") or "")
    if event.event == "chat.interrupt_result":
        return str(payload.get("message") or payload.get("content") or "")
    if event.event == "chat.processing_status":
        return "我正在处理。" if payload.get("is_processing") else ""
    if event.event == "chat.subtask_update":
        description = payload.get("description") or payload.get("message") or payload.get("result") or "子任务更新"
        status = str(payload.get("status") or "").strip()
        index = payload.get("index")
        total = payload.get("total")
        prefix = ""
        if isinstance(index, int) and isinstance(total, int) and total > 0:
            prefix = f"{index}/{total} "
        return f"{prefix}{description}" + (f" · {status}" if status else "")
    if event.event == "chat.tool_call":
        name = payload.get("name") or payload.get("tool_name") or payload.get("toolName") or "tool"
        return f"正在调用 {name}..."
    if event.event == "chat.tool_result":
        name = payload.get("toolName") or payload.get("tool_name") or payload.get("name") or "tool"
        return f"{name} 已返回结果。"
    if event.event == "chat.ask_user_question":
        question = payload.get("question") or payload.get("prompt") or payload.get("message")
        if not question:
            questions = payload.get("questions")
            if isinstance(questions, list) and questions and isinstance(questions[0], dict):
                question = questions[0].get("question") or questions[0].get("header")
        return str(question or "需要你确认下一步。")
    return ""


def _artifact_suffix(target: str, label: str) -> str:
    value = target or label
    if target.startswith(("http://", "https://", "file://")):
        value = urlparse(target).path
    return Path(value).suffix.lower()


def trusted_payment_deeplink(value: Any) -> bool:
    text = str(value or "").strip()
    return any(text.startswith(prefix) for prefix in TRUSTED_PAYMENT_DEEPLINK_PREFIXES)


def _iter_payment_deeplink_values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        values: list[Any] = []
        for key, item in value.items():
            if key in PAYMENT_DEEPLINK_KEYS:
                values.append(item)
            values.extend(_iter_payment_deeplink_values(item))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_iter_payment_deeplink_values(item))
        return values
    return []


def gateway_event_payment_deeplink(event: GatewayEvent) -> str:
    for value in _iter_payment_deeplink_values(event.payload or {}):
        target = str(value or "").strip()
        if trusted_payment_deeplink(target):
            return target
    return ""


def _artifact_category(*, label: str, target: str, preview: str, explicit_type: str = "") -> str:
    type_hint = explicit_type.lower()
    suffix = _artifact_suffix(target, label)
    if trusted_payment_deeplink(target):
        return "payment"
    if "image" in type_hint or suffix in IMAGE_SUFFIXES:
        return "image"
    if "spreadsheet" in type_hint or "csv" in type_hint or suffix in TABLE_SUFFIXES:
        return "table"
    if "code" in type_hint or suffix in CODE_SUFFIXES:
        return "code"
    if "text" in type_hint or "markdown" in type_hint or suffix in TEXT_SUFFIXES or preview:
        return "text"
    if target.startswith(("http://", "https://")):
        return "link"
    return "file"


def gateway_event_artifacts(event: GatewayEvent) -> list[dict[str, str]]:
    payload = event.payload or {}
    raw_items: list[Any] = []
    for key in ("artifacts", "files", "attachments", "outputs"):
        raw = payload.get(key)
        if isinstance(raw, list):
            raw_items.extend(raw)
        elif isinstance(raw, dict):
            raw_items.append(raw)
        elif isinstance(raw, str) and raw.strip():
            raw_items.append(raw)
    if any(key in payload for key in ("path", "file_path", "filePath", "target", "url", "uri", "href")):
        raw_items.append(payload)

    artifacts: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_items:
        label = ""
        target = ""
        preview = ""
        explicit_type = ""
        if isinstance(item, str):
            target = item.strip()
            label = Path(target).name or target
        elif isinstance(item, dict):
            preview = str(item.get("preview") or item.get("content") or item.get("text") or "").strip()
            explicit_type = str(
                item.get("mime")
                or item.get("mimeType")
                or item.get("content_type")
                or item.get("contentType")
                or item.get("type")
                or ""
            )
            target = str(
                item.get("path")
                or item.get("file_path")
                or item.get("filePath")
                or item.get("url")
                or item.get("uri")
                or item.get("href")
                or item.get("target")
                or ""
            ).strip()
            label = str(
                item.get("title")
                or item.get("name")
                or item.get("filename")
                or item.get("fileName")
                or Path(target).name
                or target
            ).strip()
        if not target and preview:
            target = f"inline:{len(artifacts)}"
        if not target or target in seen:
            continue
        seen.add(target)
        kind = (
            "inline"
            if target.startswith("inline:")
            else "url"
            if trusted_payment_deeplink(target) or target.startswith(("http://", "https://", "file://"))
            else "file"
        )
        label = label or target
        artifact = {
            "label": label,
            "target": target,
            "kind": kind,
            "category": _artifact_category(label=label, target=target, preview=preview, explicit_type=explicit_type),
        }
        if explicit_type:
            artifact["mime"] = explicit_type
        if preview:
            artifact["preview"] = preview
        artifacts.append(artifact)
    return artifacts


def answers_for_decision(
    payload: dict[str, Any],
    decision: Literal["accept", "reject"],
    feedback: str = "",
) -> list[dict[str, Any]]:
    feedback = str(feedback or "").strip()
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        answer = {"selected_options": ["同意" if decision == "accept" else "拒绝"]}
        if feedback:
            answer["custom_input"] = feedback
        return [answer]

    answers: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, dict):
            answers.append({"selected_options": []})
            continue
        question_text = str(question.get("question") or question.get("header") or "").strip()
        options = question.get("options")
        labels = [
            str(option.get("label") or "").strip()
            for option in options
            if isinstance(option, dict) and str(option.get("label") or "").strip()
        ] if isinstance(options, list) else []
        label = _pick_decision_label(labels, decision)
        answer = {"selected_options": [label] if label else []}
        if question_text:
            answer["question"] = question_text
        if feedback:
            answer["custom_input"] = feedback
        answers.append(answer)
    return answers


def _pick_decision_label(labels: list[str], decision: Literal["accept", "reject"]) -> str:
    if not labels:
        return "同意" if decision == "accept" else "拒绝"
    positive = ("同意", "允许", "确认", "继续", "是", "批准", "accept", "approve", "allow", "yes", "ok")
    negative = ("拒绝", "取消", "否", "不", "停止", "reject", "deny", "cancel", "no", "stop")
    tokens = positive if decision == "accept" else negative
    for label in labels:
        low = label.lower()
        if any(token in low for token in tokens):
            return label
    return labels[0] if decision == "accept" else labels[-1]


def build_user_answer_request(
    *,
    session_id: str,
    request_id: str,
    source: str,
    answers: list[dict[str, Any]],
    mode: str = DEFAULT_AGENT_MODE,
    feedback: str = "",
) -> tuple[str, dict[str, Any]]:
    source = str(source or "").strip()
    feedback = str(feedback or "").strip()
    if source in {"permission_interrupt", "ask_user_interrupt"}:
        if feedback:
            answers = [
                {**answer, "custom_input": str(answer.get("custom_input") or feedback)}
                if isinstance(answer, dict)
                else answer
                for answer in answers
            ] or [{"selected_options": [], "custom_input": feedback}]
        return (
            "chat.send",
            {
                "session_id": session_id,
                "query": "",
                "request_id": request_id,
                "answers": answers,
                "source": source,
                "mode": mode,
            },
        )
    if source == "activate_confirm":
        selected = answers[0].get("selected_options", []) if answers else []
        first = str(selected[0] if selected else "").strip()
        action = "reject" if first in {"拒绝", "reject", "Reject", "deny", "Deny"} else "accept"
        return (
            "chat.send",
            {
                "session_id": session_id,
                "content": "",
                "mode": mode,
                "activate_response": {
                    "interaction_id": request_id,
                    "action": action,
                    "feedback": feedback,
                },
            },
        )
    return (
        "chat.user_answer",
        {
            "session_id": session_id,
            "request_id": request_id,
            "answers": answers,
        },
    )


def build_interrupt_request(
    *,
    session_id: str,
    intent: str = "cancel",
    mode: str = DEFAULT_AGENT_MODE,
) -> tuple[str, dict[str, Any]]:
    action = str(intent or "cancel").strip() or "cancel"
    return (
        "chat.interrupt",
        {
            "session_id": session_id,
            "intent": action,
            "mode": mode,
        },
    )


class JiuMeGatewayChatClient:
    def __init__(
        self,
        *,
        gateway_url: str = DEFAULT_GATEWAY_URL,
        session_id: str | None = None,
        mode: str = DEFAULT_AGENT_MODE,
        idle_timeout_seconds: float = 120.0,
    ) -> None:
        self.gateway_url = gateway_url
        self.session_id = session_id or _default_gateway_session_id()
        self.mode = mode or DEFAULT_AGENT_MODE
        self.idle_timeout_seconds = idle_timeout_seconds

    def send_chat(
        self,
        content: str,
        *,
        twin_id: str | None,
        on_event: Callable[[GatewayEvent], None],
    ) -> str:
        request_id = f"jiume-{secrets.token_hex(8)}"
        thread = threading.Thread(
            target=lambda: asyncio.run(
                self._send_chat_once(request_id, content, twin_id=twin_id, on_event=on_event)
            ),
            name=f"jiume_gateway_chat_{request_id[-6:]}",
            daemon=True,
        )
        thread.start()
        return request_id

    def send_user_answer(
        self,
        *,
        request_id: str,
        source: str,
        answers: list[dict[str, Any]],
        on_event: Callable[[GatewayEvent], None],
        feedback: str = "",
    ) -> str:
        outgoing_id = f"jiume-answer-{secrets.token_hex(8)}"
        method, params = build_user_answer_request(
            session_id=self.session_id,
            request_id=request_id,
            source=source,
            answers=answers,
            mode=self.mode,
            feedback=feedback,
        )
        thread = threading.Thread(
            target=lambda: asyncio.run(self._send_request_once(outgoing_id, method, params, on_event=on_event)),
            name=f"jiume_gateway_answer_{outgoing_id[-6:]}",
            daemon=True,
        )
        thread.start()
        return outgoing_id

    def send_interrupt(
        self,
        *,
        intent: str = "cancel",
        on_event: Callable[[GatewayEvent], None],
    ) -> str:
        outgoing_id = f"jiume-interrupt-{secrets.token_hex(8)}"
        method, params = build_interrupt_request(
            session_id=self.session_id,
            intent=intent,
            mode=self.mode,
        )
        thread = threading.Thread(
            target=lambda: asyncio.run(self._send_request_once(outgoing_id, method, params, on_event=on_event)),
            name=f"jiume_gateway_interrupt_{outgoing_id[-6:]}",
            daemon=True,
        )
        thread.start()
        return outgoing_id

    async def _send_chat_once(
        self,
        request_id: str,
        content: str,
        *,
        twin_id: str | None,
        on_event: Callable[[GatewayEvent], None],
    ) -> None:
        try:
            import websockets

            async with websockets.connect(self.gateway_url) as ws:
                params: dict[str, Any] = {
                    "session_id": self.session_id,
                    "content": content,
                    "mode": self.mode,
                }
                if twin_id:
                    params["twin_id"] = twin_id
                await ws.send(
                    json.dumps(
                        {
                            "type": "req",
                            "id": request_id,
                            "method": "chat.send",
                            "params": params,
                        },
                        ensure_ascii=False,
                    )
                )
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=self.idle_timeout_seconds)
                    event = normalize_gateway_frame(raw)
                    if event is None:
                        continue
                    on_event(event)
                    if event.kind == "response" and event.ok is False:
                        return
                    if event.kind != "event":
                        continue
                    if event.event == "chat.error":
                        return
                    if event.event == "chat.final":
                        return
                    if event.event == "chat.processing_status" and not (event.payload or {}).get("is_processing"):
                        return
        except Exception as exc:  # noqa: BLE001
            on_event(GatewayEvent(kind="error", error=str(exc)))

    async def _send_request_once(
        self,
        request_id: str,
        method: str,
        params: dict[str, Any],
        *,
        on_event: Callable[[GatewayEvent], None],
    ) -> None:
        try:
            import websockets

            async with websockets.connect(self.gateway_url) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "req",
                            "id": request_id,
                            "method": method,
                            "params": params,
                        },
                        ensure_ascii=False,
                    )
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=self.idle_timeout_seconds)
                event = normalize_gateway_frame(raw)
                if event is not None:
                    on_event(event)
        except Exception as exc:  # noqa: BLE001
            on_event(GatewayEvent(kind="error", error=str(exc)))
