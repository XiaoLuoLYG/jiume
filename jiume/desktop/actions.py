"""Desktop-native quick actions for the JiuMe human assistant."""

from __future__ import annotations

from typing import Any

QUICK_ACTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "focus",
        "label": "专注",
        "title": "陪我专注",
        "kind": "agent",
        "state": "thinking",
        "prompt": (
            "Start a JiuMe desktop focus session with me. Ask me for one concrete goal, "
            "help me choose the first next action, and keep the exchange concise. "
            "Do not claim a timer is running unless I explicitly ask you to start one."
        ),
        "fallback": "可以。告诉我这轮专注目标，我会帮你压成一个可以立刻开始的第一步。",
    },
    {
        "id": "today",
        "label": "今日",
        "title": "整理今天",
        "kind": "agent",
        "state": "thinking",
        "prompt": (
            "Help me triage today from the JiuMe desktop assistant. Ask what is currently on my mind, "
            "then turn it into a short priority list with one first action."
        ),
        "fallback": "把今天脑子里最吵的三件事告诉我，我会先帮你排出第一件该处理的事。",
    },
    {
        "id": "skill_picker",
        "label": "选 skill",
        "title": "帮我选 skill",
        "kind": "agent",
        "state": "thinking",
        "prompt": (
            "Recommend the best JiuMe skill for my next task. Consider mounted skills first, "
            "then available desktop shelf skills. Ask for the missing task context if needed."
        ),
        "fallback": "你说一下要处理的任务，我会在会议纪要、数据分析、PRD、研发和内容类 skill 里帮你选一个。",
    },
    {
        "id": "rest",
        "label": "休息",
        "title": "安静待机",
        "kind": "local",
        "state": "sleep",
        "prompt": "",
        "fallback": "我先安静待机。需要我的时候，单击我就回来。",
    },
)


def quick_actions() -> list[dict[str, Any]]:
    """Return detached action records for Tk callbacks and tests."""

    return [dict(item) for item in QUICK_ACTIONS]


def quick_action_by_id(action_id: str) -> dict[str, Any] | None:
    needle = str(action_id or "").strip()
    if not needle:
        return None
    for action in QUICK_ACTIONS:
        if action["id"] == needle:
            return dict(action)
    return None


def quick_action_prompt(action_id: str) -> str:
    action = quick_action_by_id(action_id)
    return str(action.get("prompt") or "") if action else ""
