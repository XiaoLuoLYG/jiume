"""Idle companionship moments for the JiuMe desktop person."""

from __future__ import annotations

from typing import Any

IDLE_COMPANION_SECONDS = 45.0

IDLE_COMPANION_MOMENTS: tuple[dict[str, str], ...] = (
    {
        "id": "check_in",
        "title": "轻声陪伴",
        "state": "speaking",
        "effect": "nod",
        "line": "我还在桌面上。你需要我时，直接叫我就好。",
    },
    {
        "id": "stretch",
        "title": "待机伸展",
        "state": "idle",
        "effect": "stretch",
        "line": "我伸展一下，继续在这里陪你守着。",
    },
    {
        "id": "focus_nudge",
        "title": "轻推一下",
        "state": "speaking",
        "effect": "peek",
        "line": "如果你卡住了，可以把第一件小事丢给我。",
    },
    {
        "id": "tiny_lot",
        "title": "递个小签",
        "state": "success",
        "effect": "cheer",
        "line": "我递你一个小签：先向前一步，不用一次想完整。",
    },
    {
        "id": "quiet",
        "title": "安静守候",
        "state": "idle",
        "effect": "breathe",
        "line": "我先安静一点，但不会走开。",
    },
)


def idle_companion_moments() -> list[dict[str, Any]]:
    """Return detached idle companion moment records for UI callbacks and tests."""

    return [dict(item) for item in IDLE_COMPANION_MOMENTS]


def idle_companion_moment(index: int) -> dict[str, Any]:
    moments = idle_companion_moments()
    if not moments:
        return {}
    return moments[index % len(moments)]


def should_run_idle_companion(
    *,
    state: str,
    idle_seconds: float,
    has_visible_surface: bool,
    enabled: bool = False,
) -> bool:
    if not enabled:
        return False
    if state != "idle":
        return False
    if has_visible_surface:
        return False
    return idle_seconds >= IDLE_COMPANION_SECONDS
