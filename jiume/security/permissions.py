"""Twin permission helpers."""

from __future__ import annotations

from typing import Any

DEFAULT_DENIED_TOOL_CATEGORIES = ["payment", "irreversible_delete"]
DEFAULT_SKILLS = ["personal-briefing", "meeting-minutes", "knowledge-research"]
PERMISSION_MODES = {
    "chat_only",
    "read_only",
    "draft",
    "confirm_before_act",
    "autonomous",
}


def normalize_permission_mode(value: Any) -> str:
    raw = str(value or "").strip()
    if raw in PERMISSION_MODES:
        return raw
    return "confirm_before_act"


def normalize_skill_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        skill_id = str(item or "").strip()
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        out.append(skill_id)
    return out
