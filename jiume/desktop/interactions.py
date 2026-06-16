"""Playful local interactions for the JiuMe desktop person."""

from __future__ import annotations

from typing import Any

INTERACTION_ACTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "wave",
        "label": "挥手",
        "title": "挥手回应",
        "state": "success",
        "effect": "wave",
        "line": "我在这里。你一叫我，我就会看向你。",
    },
    {
        "id": "pat",
        "label": "拍拍",
        "title": "轻拍回应",
        "state": "speaking",
        "effect": "pat",
        "line": "收到，这一下我接到了。我在这儿，下一步你交给我就好。",
    },
    {
        "id": "cheer",
        "label": "打气",
        "title": "给你打气",
        "state": "success",
        "effect": "cheer",
        "line": "可以的。我们先把下一步做小一点，然后动起来。",
    },
    {
        "id": "nod",
        "label": "点头",
        "title": "点头回应",
        "state": "speaking",
        "effect": "nod",
        "line": "嗯，我点头了。你说下一步，我跟上。",
    },
    {
        "id": "stretch",
        "label": "伸展",
        "title": "伸个懒腰",
        "state": "idle",
        "effect": "stretch",
        "line": "我伸展一下，继续陪你守着桌面。",
    },
    {
        "id": "breathe",
        "label": "呼吸",
        "title": "一起呼吸",
        "state": "idle",
        "effect": "breathe",
        "line": "吸气，放慢一点。呼气。好了，我们回来。",
    },
    {
        "id": "peek",
        "label": "探头",
        "title": "探头看看",
        "state": "speaking",
        "effect": "peek",
        "line": "我探个头看看。需要我接手什么，就叫我。",
    },
    {
        "id": "dance",
        "label": "小跳",
        "title": "开心小跳",
        "state": "success",
        "effect": "dance",
        "line": "好，开心一下。事情动起来了。",
    },
    {
        "id": "heart",
        "label": "比心",
        "title": "比心回应",
        "state": "success",
        "effect": "heart",
        "line": "给你比个心。先把这一小步交给我，我们慢慢来。",
    },
    {
        "id": "companion",
        "label": "陪伴",
        "title": "陪伴一下",
        "state": "speaking",
        "effect": "companion",
        "line": "我在桌面上陪着你。你先做一点点，我替你守住下一步。",
    },
)


def interaction_actions() -> list[dict[str, Any]]:
    """Return detached interaction records for UI callbacks and tests."""

    return [dict(item) for item in INTERACTION_ACTIONS]


def interaction_by_id(action_id: str) -> dict[str, Any] | None:
    needle = str(action_id or "").strip()
    if not needle:
        return None
    for action in INTERACTION_ACTIONS:
        if action["id"] == needle:
            return dict(action)
    return None
