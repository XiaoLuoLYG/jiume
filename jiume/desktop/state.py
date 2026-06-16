"""Shared desktop avatar state helpers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jiume.paths import get_jiume_root

VALID_STATES = {
    "idle",
    "thinking",
    "speaking",
    "working",
    "waiting_approval",
    "success",
    "error",
    "sleep",
}


def get_desktop_state_path() -> Path:
    return get_jiume_root() / "desktop_state.json"


def get_service_status_path() -> Path:
    return get_jiume_root() / "services_status.json"


def get_companion_state_path() -> Path:
    return get_jiume_root() / "companion_state.json"


def get_window_state_path() -> Path:
    return get_jiume_root() / "window_state.json"


def get_conversation_state_path() -> Path:
    return get_jiume_root() / "conversation_state.json"


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _non_negative_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _opacity_value(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0.35 or number > 1.0:
        return None
    return round(number, 2)


def _enabled_bool(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "quiet"}
    return bool(value)


def _clean_text(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _normalize_companion_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    state = {
        "interaction_count": _non_negative_int(payload.get("interaction_count")),
        "idle_companion_index": _non_negative_int(payload.get("idle_companion_index")),
        "idle_companion_enabled": _enabled_bool(payload.get("idle_companion_enabled"), default=False),
    }
    for key in ("twin_id", "updated_at"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            state[key] = value.strip()
    return state


def _normalize_artifacts(items: Any, *, limit: int = 3) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    artifacts: list[dict[str, str]] = []
    for item in items:
        if len(artifacts) >= limit:
            break
        if not isinstance(item, dict):
            continue
        target = _clean_text(item.get("target"), limit=360)
        label = _clean_text(item.get("label") or target or "产物", limit=80)
        if not target and not label:
            continue
        artifact: dict[str, str] = {
            "label": label or "产物",
            "target": target,
            "kind": _clean_text(item.get("kind") or "file", limit=32),
            "category": _clean_text(item.get("category") or "file", limit=32),
        }
        for key in ("mime", "preview"):
            value = _clean_text(item.get(key), limit=360 if key == "preview" else 80)
            if value:
                artifact[key] = value
        artifacts.append(artifact)
    return artifacts


def _normalize_chat_items(items: Any, *, limit: int = 80) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in items[-limit:]:
        if not isinstance(item, dict):
            continue
        text = _clean_text(item.get("text"), limit=180)
        if not text:
            continue
        role = "user" if str(item.get("role") or "") == "user" else "assistant"
        normalized.append({"role": role, "text": text})
    return normalized


def _normalize_activity_items(items: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title") or "最近任务", limit=80)
        detail = _clean_text(item.get("detail"), limit=120)
        if not title and not detail:
            continue
        normalized.append(
            {
                "kind": _clean_text(item.get("kind"), limit=32),
                "title": title or "最近任务",
                "detail": detail,
                "artifacts": _normalize_artifacts(item.get("artifacts")),
                "time": _clean_text(item.get("time"), limit=24),
            }
        )
    return normalized


def _normalize_active_skill(payload: Any) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    skill_id = _clean_text(payload.get("id"), limit=80)
    display_name = _clean_text(payload.get("displayName") or payload.get("name") or skill_id, limit=80)
    if not skill_id or not display_name:
        return None
    state = {
        "id": skill_id,
        "displayName": display_name,
        "summary": _clean_text(payload.get("summary"), limit=220),
        "category": _clean_text(payload.get("category"), limit=80),
        "risk": _clean_text(payload.get("risk") or "unknown", limit=32) or "unknown",
        "whyJiume": _clean_text(payload.get("whyJiume"), limit=220),
    }
    return {key: value for key, value in state.items() if value}


def _normalize_window_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    state: dict[str, Any] = {}
    x = _int_value(payload.get("x"))
    y = _int_value(payload.get("y"))
    if x is not None and y is not None:
        state["x"] = x
        state["y"] = y
    for key in ("size", "screen_width", "screen_height"):
        value = _non_negative_int(payload.get(key))
        if value > 0:
            state[key] = value
    opacity = _opacity_value(payload.get("opacity"))
    if opacity is not None:
        state["opacity"] = opacity
    for key in ("twin_id", "updated_at"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            state[key] = value.strip()
    return state


def _normalize_conversation_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    state: dict[str, Any] = {
        "chat": _normalize_chat_items(payload.get("chat")),
        "activity": _normalize_activity_items(payload.get("activity")),
    }
    active_skill = _normalize_active_skill(payload.get("activeSkill"))
    if active_skill:
        state["activeSkill"] = active_skill
    for key in ("twin_id", "updated_at"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            state[key] = value.strip()
    return state


def set_desktop_state(state: str, **payload: Any) -> dict[str, Any]:
    state = (state or "idle").strip().lower()
    if state not in VALID_STATES:
        raise ValueError(f"invalid desktop avatar state: {state}")
    event = {
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **{key: value for key, value in payload.items() if value is not None},
    }
    path = get_desktop_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    return event


def set_service_status(**payload: Any) -> dict[str, Any]:
    event = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **{key: value for key, value in payload.items() if value is not None},
    }
    path = get_service_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    return event


def read_service_status() -> dict[str, Any]:
    path = get_service_status_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_companion_state() -> dict[str, Any]:
    path = get_companion_state_path()
    if not path.exists():
        return _normalize_companion_state({})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _normalize_companion_state({})
    return _normalize_companion_state(payload if isinstance(payload, dict) else {})


def read_window_state() -> dict[str, Any]:
    path = get_window_state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _normalize_window_state(payload if isinstance(payload, dict) else {})


def read_conversation_state() -> dict[str, Any]:
    path = get_conversation_state_path()
    if not path.exists():
        return _normalize_conversation_state({})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _normalize_conversation_state({})
    return _normalize_conversation_state(payload if isinstance(payload, dict) else {})


def write_companion_state(
    *,
    interaction_count: int,
    idle_companion_index: int,
    idle_companion_enabled: bool,
    twin_id: str | None = None,
) -> dict[str, Any]:
    event = _normalize_companion_state(
        {
            "interaction_count": interaction_count,
            "idle_companion_index": idle_companion_index,
            "idle_companion_enabled": idle_companion_enabled,
            "twin_id": twin_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    path = get_companion_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    return event


def write_conversation_state(
    *,
    chat_items: list[dict[str, Any]],
    activity_items: list[dict[str, Any]],
    active_skill: dict[str, Any] | None = None,
    twin_id: str | None = None,
) -> dict[str, Any]:
    event = _normalize_conversation_state(
        {
            "chat": chat_items,
            "activity": activity_items,
            "activeSkill": active_skill,
            "twin_id": twin_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    path = get_conversation_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    return event


def write_window_state(
    *,
    x: int,
    y: int,
    size: int,
    screen_width: int,
    screen_height: int,
    opacity: float | None = None,
    twin_id: str | None = None,
) -> dict[str, Any]:
    event = _normalize_window_state(
        {
            "x": x,
            "y": y,
            "size": size,
            "screen_width": screen_width,
            "screen_height": screen_height,
            "opacity": opacity,
            "twin_id": twin_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    path = get_window_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description="Set the JiuMe desktop avatar state.")
    parser.add_argument("state", choices=sorted(VALID_STATES))
    parser.add_argument("--message", default="")
    args = parser.parse_args()
    event = set_desktop_state(args.state, message=args.message or None)
    print(json.dumps(event, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
