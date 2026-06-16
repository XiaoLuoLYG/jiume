"""Menu labels for JiuMe's desktop-native application surface."""

from __future__ import annotations

APP_MENU_LABELS: tuple[str, ...] = (
    "设置",
    "退出 JiuMe",
)

MATERIAL_MENU_LABELS: tuple[str, ...] = (
    "看屏幕",
    "贴材料",
    "选文件",
)

SKILL_MENU_LABELS: tuple[str, ...] = (
    "查看当前 skill",
    "取消当前 skill",
    "打开技能货架",
)

TASK_MENU_LABELS: tuple[str, ...] = (
    "看任务进度",
    "打开产物列表",
    "停止当前任务",
)

COMPANION_MENU_LABELS: tuple[str, ...] = (
    "恢复陪伴",
    "安静守着",
    "陪我一下",
)

PLAY_MENU_LABELS: tuple[str, ...] = (
    "猜拳",
    "掷骰子",
    "抽签",
)

STATE_MENU_LABELS: tuple[str, ...] = (
    "待命",
    "思考",
    "执行中",
    "休息",
)


def app_menu_labels() -> list[str]:
    return list(APP_MENU_LABELS)


def material_menu_labels() -> list[str]:
    return []


def skill_menu_labels() -> list[str]:
    return []


def task_menu_labels() -> list[str]:
    return []


def companion_menu_labels() -> list[str]:
    return []


def play_menu_labels() -> list[str]:
    return []


def state_menu_labels() -> list[str]:
    return []
