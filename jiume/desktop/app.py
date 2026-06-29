"""A standalone human desktop avatar window for the active JiuMe twin."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, SimpleQueue
from tkinter import filedialog
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from PIL import Image, ImageDraw, ImageFont, ImageTk

from jiume.avatar.service import (
    AVATAR_VIEW_NAMES,
    CODEX_CELL,
    CODEX_GRID,
    CODEX_PET_FRAME_COUNTS,
    CODEX_PET_STATE_ALIASES,
    DESKTOP_STATES,
    AvatarService,
)
from jiume.desktop.actions import quick_action_by_id, quick_actions
from jiume.desktop.overlay import (
    AVATAR_DRAG_THRESHOLD_PX,
    AvatarLayer,
    BubbleLayer,
    DesktopOverlayHost,
    FloatingCardLayer,
)
from jiume.desktop.companion import (
    IDLE_COMPANION_SECONDS,
    idle_companion_moment,
    should_run_idle_companion,
)
from jiume.desktop.gateway_client import (
    DEFAULT_AGENT_MODE,
    DEFAULT_GATEWAY_URL,
    GatewayEvent,
    JiuMeGatewayChatClient,
    answers_for_decision,
    desktop_state_for_gateway_event,
    gateway_event_artifacts,
    gateway_event_text,
)
from jiume.desktop.interactions import interaction_actions, interaction_by_id
from jiume.desktop.menus import (
    APP_MENU_LABELS,
    COMPANION_MENU_LABELS,
    MATERIAL_MENU_LABELS,
    PLAY_MENU_LABELS,
    SKILL_MENU_LABELS,
    STATE_MENU_LABELS,
    TASK_MENU_LABELS,
)
from jiume.desktop.one_line_companion import (
    ONE_LINE_INPUT_HINT,
    TaskCapsule,
    capsule_for_gateway_event,
    daily_label_is_allowed,
    done_capsule,
    failed_capsule,
    gateway_subtask_status_is_completed,
    gateway_subtask_status_is_failed,
    need_user_capsule,
    working_capsule,
)
from jiume.desktop.state import (
    get_desktop_state_path,
    read_companion_state,
    read_conversation_state,
    read_service_status,
    read_window_state,
    write_companion_state,
    write_conversation_state,
    write_window_state,
)
from jiume.paths import get_jiume_root
from jiume.skills.catalog import (
    RECOMMENDED_SKILLS,
    SKILL_FILTER_ALL,
    filter_recommended_skills,
    skill_categories,
    skill_risks,
)
from jiume.skills.local_install import install_local_skill
from jiume.security.permissions import normalize_permission_mode
from jiume.twins.appearance import (
    appearance_preset_by_id,
    appearance_presets,
    normalize_twin_appearance,
    twin_appearance_label,
)
from jiume.twins.store import MAX_TWIN_MEMORIES, TWIN_MEMORY_CHAR_LIMIT, TwinStore, normalize_twin_memories

DEFAULT_AVATAR_SIZE = 128
AVATAR_SIZE_MIN = 80
AVATAR_SIZE_MAX = 220
AVATAR_FRAME_MS = 150
AVATAR_OPACITY_MIN = 0.35
AVATAR_OPACITY_MAX = 1.0
AVATAR_OPACITY_STEP = 0.15

PANEL_BG = "#F6F4EE"
DIRECT_TK_FONT = "PingFang SC"
DIRECT_GLASS_BG = "#EAF5F3"
DIRECT_GLASS_SURFACE = "#F9FFFC"
DIRECT_GLASS_BORDER = "#8FCFC7"
DIRECT_GLASS_SHADOW = "#030405"
DIRECT_GLASS_HIGHLIGHT = "#F7FFFD"
DIRECT_GLASS_FROST = "#EDF8F6"
DIRECT_GLASS_FROST_ALPHA = 214
DIRECT_GLASS_EDGE_ALPHA = 104
DIRECT_GLASS_SHEEN_ALPHA = 118
DIRECT_TK_SHADOW = "#D5DEE0"
DIRECT_ASSISTANT_BUBBLE = "#F9FFFC"
DIRECT_USER_BUBBLE = "#10181C"
DIRECT_USER_BUBBLE_EDGE = "#26363B"
DIRECT_CHAMPAGNE = "#71CFC5"
DIRECT_CHAMPAGNE_SOFT = "#CDEFEA"
DIRECT_INPUT_BG = "#FBFFFC"
DIRECT_ACTION_BG = "#071215"
DIRECT_ACTION_STOP_EDGE = "#5A2424"
DIRECT_SURFACE_BG = DIRECT_GLASS_SURFACE
DIRECT_SURFACE_EDGE = DIRECT_GLASS_BORDER
DIRECT_SURFACE_SHADOW = DIRECT_GLASS_SHADOW
DIRECT_SHADOW_ALPHA = 18
DIRECT_MESSAGE_SHADOW_ALPHA = 10
DIRECT_LAYER_BG = DIRECT_GLASS_BG
DIRECT_LAYER_SOFT = "#EDF2F4"
INK = "#111A1D"
MUTED = "#64797D"
LINE = "#C9DDE0"
ACCENT = DIRECT_ACTION_BG
INVERSE_TEXT = "#ECFFFA"
SUCCESS = "#157F3B"
AVATAR_STATUS_BADGES: dict[str, dict[str, Any]] = {
    "idle": {"label": "在", "color": (101, 96, 87), "pulse": (0, 0, 1, 0, 0, 1)},
    "thinking": {"label": "想", "color": (99, 102, 241), "pulse": (0, 1, 2, 1, 0, 1)},
    "speaking": {"label": "说", "color": (37, 99, 235), "pulse": (0, 1, 1, 0, 1, 0)},
    "working": {"label": "做", "color": (234, 88, 12), "pulse": (0, 1, 2, 3, 2, 1)},
    "waiting_approval": {"label": "等", "color": (202, 138, 4), "pulse": (1, 2, 4, 2, 1, 3)},
    "success": {"label": "好", "color": (21, 127, 59), "pulse": (0, 2, 1, 0, 1, 0)},
    "error": {"label": "错", "color": (180, 35, 24), "pulse": (2, 0, 2, 0, 1, 0)},
    "sleep": {"label": "眠", "color": (100, 116, 139), "pulse": (0, 0, 0, 1, 0, 0)},
}
INTERACTION_LINES = (
    "我在。你直接说，我会接住。",
    "嗯？我听着。",
    "要我接手什么，就丢给我。",
    "我还在桌面上，随时可以开工。",
)
WAKE_LINES = (
    "我醒啦。你说，我回到这里了。",
    "嗯，我回来了。要继续哪件事？",
    "收到，我从安静待机回来了。",
)
WORK_HUD_ACTIVE_KINDS = {"user", "quick", "accepted", "processing", "subtask", "tool", "approval"}
WORK_HUD_TERMINAL_KINDS = {"artifact", "final", "error"}
ARTIFACT_TRAY_LIMIT = 8
DIRECT_CHAT_PREVIEW_LIMIT = 3
DIRECT_CHAT_HISTORY_LIMIT = 80
DIRECT_SKILL_SHORTCUT_LIMIT = 3
DIRECT_QUICK_ACTION_LIMIT = 3
HOVER_MENU_WIDTH = 280
HOVER_MENU_HEIGHT = 188
BUBBLE_WIDTH = 286
BUBBLE_MIN_HEIGHT = 78
BUBBLE_MAX_HEIGHT = 220
CLIPBOARD_MATERIAL_CHAR_LIMIT = 6000
CLIPBOARD_MATERIAL_FILE_LIMIT = 6
FILE_MATERIAL_LIMIT = 8
SCREEN_CAPTURE_TIMEOUT_SECONDS = 8
ARTIFACT_PREVIEW_CHAR_LIMIT = 12000
DIRECT_CHAT_WIDTH = 432
ONE_LINE_DIRECT_HEIGHT = 84
ONE_LINE_DIRECT_WIDTH = DIRECT_CHAT_WIDTH
DIRECT_CHAT_MIN_HEIGHT = 138
DIRECT_CHAT_SCREEN_MARGIN = 80
DIRECT_CHAT_CHROME_HEIGHT = 76
DIRECT_CHAT_COMPOSER_WIDTH = 372
DIRECT_CHAT_COMPOSER_HEIGHT = 60
DIRECT_MESSAGE_MIN_WIDTH = 84
DIRECT_MESSAGE_MAX_WIDTH = 286
DIRECT_COMPANION_ACTION_IDS = ("nod", "pat", "heart", "stretch", "breathe", "companion")
NATIVE_DIRECT_SURFACES = {"chat", "settings", "skills", "progress"}
DESKTOP_STATE_EVENT_TTL_SECONDS = 45
TRANSIENT_EXTERNAL_DESKTOP_STATES = {"speaking", "thinking", "working", "waiting_approval", "success", "error"}
AGENT_UNAVAILABLE_TITLE = "后端无回复"
AGENT_UNAVAILABLE_DETAIL = "没有收到后端回复，未生成本地兜底。"
DIRECT_PLAY_ACTIONS = (
    {"id": "rps", "label": "猜拳"},
    {"id": "dice", "label": "骰子"},
    {"id": "coin", "label": "抽签"},
)


def _desktop_layer_background(platform: str = sys.platform) -> str:
    return DIRECT_LAYER_BG if platform == "darwin" else "#ff00ff"


def _uses_native_desktop_layers(platform: str = sys.platform) -> bool:
    return platform == "darwin"


def _uses_native_direct_chat(platform: str = sys.platform) -> bool:
    return _uses_native_desktop_layers(platform)


def _normalize_native_direct_surface(value: Any) -> str:
    key = str(value or "").strip()
    return key if key in NATIVE_DIRECT_SURFACES else "chat"


def _desktop_state_event_is_ignored(payload: Any, *, active_twin_id: str = "") -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("source") or "").strip().lower() == "setup":
        return True
    expected_twin_id = str(active_twin_id or "").strip()
    payload_twin_id = str(payload.get("twin_id") or payload.get("twinId") or "").strip()
    return bool(expected_twin_id and payload_twin_id and payload_twin_id != expected_twin_id)


def _direct_chat_suppresses_speech(is_visible: bool, state: str = "") -> bool:
    return bool(is_visible)


def _legacy_dialogue_layers_disabled() -> bool:
    return True


def _desktop_state_event_is_stale(payload: Any, *, now: datetime | None = None) -> bool:
    if not isinstance(payload, dict):
        return False
    state = str(payload.get("state") or "").strip().lower()
    if state not in TRANSIENT_EXTERNAL_DESKTOP_STATES:
        return False
    raw_updated_at = str(payload.get("updated_at") or "").strip()
    if not raw_updated_at:
        return False
    try:
        updated_at = datetime.fromisoformat(raw_updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = (current.astimezone(timezone.utc) - updated_at.astimezone(timezone.utc)).total_seconds()
    return age > DESKTOP_STATE_EVENT_TTL_SECONDS


def _hex_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    color = str(value or "#0A0D10").lstrip("#")
    if len(color) != 6:
        return (0, 0, 0, max(0, min(255, int(alpha))))
    return (
        int(color[0:2], 16),
        int(color[2:4], 16),
        int(color[4:6], 16),
        max(0, min(255, int(alpha))),
    )


def _native_render_scale(value: Any = 1.0) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError):
        scale = 1.0
    return max(1.0, min(3.0, scale))


def _scaled_int(value: float | int, scale: float) -> int:
    return int(round(float(value) * scale))


def _scaled_box(values: tuple[float | int, float | int, float | int, float | int], scale: float) -> tuple[int, int, int, int]:
    return tuple(_scaled_int(value, scale) for value in values)  # type: ignore[return-value]


def _draw_smooth_round_rect(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    radius: int,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 1,
) -> None:
    x1, y1, x2, y2 = [int(value) for value in box]
    if x2 <= x1 or y2 <= y1:
        return
    rect_width = x2 - x1
    rect_height = y2 - y1
    supersample = 3
    layer = Image.new("RGBA", (rect_width * supersample, rect_height * supersample), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    layer_draw.rounded_rectangle(
        (0, 0, rect_width * supersample - 1, rect_height * supersample - 1),
        radius=max(1, int(radius) * supersample),
        fill=fill,
        outline=outline,
        width=max(1, int(width) * supersample),
    )
    layer = layer.resize((rect_width, rect_height), Image.Resampling.LANCZOS)
    image.alpha_composite(layer, (x1, y1))


def _tk_ui_font(size: int, *, bold: bool = False) -> tuple[str, int] | tuple[str, int, str]:
    return (DIRECT_TK_FONT, int(size), "bold") if bold else (DIRECT_TK_FONT, int(size))


def _desktop_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, int(size))
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    image = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    box = draw.textbbox((0, 0), str(text or ""), font=font)
    return max(0, int(box[2] - box[0]))


def _wrap_desktop_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    *,
    max_lines: int | None = None,
) -> list[str]:
    raw = " ".join(str(text or "").split())
    if not raw:
        return [""]
    lines: list[str] = []
    current = ""
    for char in raw:
        candidate = current + char
        if current and _text_width(candidate, font) > max_width:
            lines.append(current)
            current = char.lstrip()
        else:
            current = candidate
    if current:
        lines.append(current)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[: max(1, max_lines)]
        last = lines[-1].rstrip()
        while last and _text_width(last + "...", font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = (last or lines[-1][:1]) + "..."
    return lines or [""]


def _draw_pil_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    max_width: int,
    max_lines: int | None = None,
    line_gap: int = 4,
) -> int:
    lines = _wrap_desktop_text(text, font, max_width, max_lines=max_lines)
    x, y = xy
    line_height = max(14, int(getattr(font, "size", 12)) + line_gap)
    for index, line in enumerate(lines):
        draw.text((x, y + index * line_height), line, font=font, fill=_hex_rgba(fill))
    return y + len(lines) * line_height


def _native_speech_bubble_image(text: str, layout: dict[str, Any]) -> Image.Image:
    width = int(layout["width"])
    height = int(layout["height"])
    tail = str(layout["tail"])
    tail_x = int(layout["tail_x"])
    top_pad = 12 if tail == "top" else 4
    bottom_pad = 12 if tail == "bottom" else 4
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    rect = (3, top_pad, width - 3, height - bottom_pad)
    shadow = (5, top_pad + 3, width - 1, height - bottom_pad + 3)
    draw.rounded_rectangle(shadow, radius=24, fill=_hex_rgba(DIRECT_SURFACE_SHADOW, DIRECT_SHADOW_ALPHA))
    if tail == "top":
        draw.polygon(
            [(tail_x - 12, top_pad + 3), (tail_x, 1), (tail_x + 12, top_pad + 3)],
            fill=_hex_rgba(DIRECT_ASSISTANT_BUBBLE, 238),
            outline=_hex_rgba(DIRECT_SURFACE_EDGE, 210),
        )
    elif tail == "bottom":
        draw.polygon(
            [
                (tail_x - 12, height - bottom_pad - 3),
                (tail_x, height - 1),
                (tail_x + 12, height - bottom_pad - 3),
            ],
            fill=_hex_rgba(DIRECT_ASSISTANT_BUBBLE, 238),
            outline=_hex_rgba(DIRECT_SURFACE_EDGE, 210),
        )
    draw.rounded_rectangle(
        rect,
        radius=24,
        fill=_hex_rgba(DIRECT_ASSISTANT_BUBBLE, 238),
        outline=_hex_rgba(DIRECT_SURFACE_EDGE, 210),
    )
    draw.line((rect[0] + 20, rect[1] + 2, rect[2] - 22, rect[1] + 2), fill=_hex_rgba(DIRECT_GLASS_HIGHLIGHT, 150), width=1)
    draw.line((rect[0] + 22, rect[3] - 2, rect[0] + 76, rect[3] - 2), fill=_hex_rgba(DIRECT_CHAMPAGNE, 90), width=1)
    font = _desktop_font(14)
    available_height = max(26, height - top_pad - bottom_pad - 24)
    max_lines = max(1, available_height // 20)
    _draw_pil_text(
        draw,
        (18, top_pad + 12),
        str(text or ""),
        font=font,
        fill=INK,
        max_width=width - 36,
        max_lines=max_lines,
    )
    return image
RPS_MOVES = ("rock", "scissors", "paper")
FOCUS_DEFAULT_MINUTES = 25
FOCUS_MIN_MINUTES = 5
FOCUS_MAX_MINUTES = 90
DIRECT_TONE_PRESETS = (
    ("清晰", "clear, helpful, and work-focused"),
    ("温和", "warm and concise"),
    ("直接", "direct and action-oriented"),
)
DIRECT_PERMISSION_PRESETS = (
    ("只聊天", "chat_only"),
    ("只读", "read_only"),
    ("先起草", "draft"),
    ("确认", "confirm_before_act"),
    ("自主", "autonomous"),
)
DIRECT_SIZE_PRESETS = (
    ("小", 96),
    ("标准", DEFAULT_AVATAR_SIZE),
    ("大", 168),
)
DIRECT_SETTINGS_SECTIONS = (
    {"id": "identity", "label": "身份", "detail": "先确认我是谁、主要陪你做什么。"},
    {"id": "tone", "label": "语气", "detail": "选择我和你说话时的节奏。"},
    {"id": "permission", "label": "权限", "detail": "决定我行动前要不要先问你。"},
    {"id": "appearance", "label": "外观", "detail": "记录外观偏好；形象资产来自 Codex pet 包。"},
    {"id": "size", "label": "大小", "detail": "调整我在桌面上的存在感。"},
)
DIRECT_SKILL_SECTIONS = (
    {"id": "recommended", "label": "推荐", "detail": "先给你几个最常用 skill。"},
    {"id": "current", "label": "当前", "detail": "看我现在正拿着哪个 skill。"},
    {"id": "materials", "label": "材料", "detail": "把屏幕、剪贴板或文件交给当前 skill。"},
    {"id": "more", "label": "更多", "detail": "在这一层继续展开可用 skill。"},
)
DIRECT_HELP_SECTIONS = (
    {"id": "talk", "label": "聊天", "detail": "直接说任务、补一句，或把当前屏幕交给我看。"},
    {"id": "settings", "label": "设置", "detail": "右键打开设置中心，调整身份、语气、权限、外观和桌面表现。"},
    {"id": "skills", "label": "技能", "detail": "选择、查看或取消当前挂载的 skill，也可以把材料交给它。"},
    {"id": "progress", "label": "进度", "detail": "看正在执行的任务、确认动作，并打开已生成的结果。"},
)
APPEARANCE_COMMAND_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("blue", ("清爽蓝", "蓝色", "蓝衣服", "blue")),
    ("mint", ("薄荷绿", "绿色", "绿衣服", "mint", "green")),
    ("pink", ("草莓粉", "粉色", "粉衣服", "pink")),
    ("purple", ("葡萄紫", "紫色", "紫衣服", "purple")),
    ("sun", ("暖阳黄", "黄色", "黄衣服", "yellow", "sunny")),
    ("ink", ("极简黑", "黑色", "黑衣服", "black", "ink")),
)


def _state_file(manifest: dict[str, Any], state: str, frame_index: int = 0) -> Path | None:
    states = manifest.get("states")
    if not isinstance(states, dict):
        return None
    state_key = CODEX_PET_STATE_ALIASES.get(str(state or "").strip(), str(state or "").strip())
    item = states.get(state_key) or states.get("idle")
    if not isinstance(item, dict):
        return None
    frames = item.get("frames")
    if isinstance(frames, list) and frames:
        frame = frames[frame_index % len(frames)]
        if isinstance(frame, dict):
            file_path = frame.get("file")
            if isinstance(file_path, str) and file_path:
                return Path(file_path)
    file_path = item.get("file")
    return Path(file_path) if isinstance(file_path, str) and file_path else None


def _sprite_frame(manifest: dict[str, Any], state: str, frame_index: int = 0) -> tuple[Path, tuple[int, int, int, int]] | None:
    pack = manifest.get("spritePack")
    if not isinstance(pack, dict):
        return None
    spritesheet = str(pack.get("spritesheet") or "").strip()
    if not spritesheet:
        return None
    sheet_path = Path(spritesheet)
    if not sheet_path.is_absolute():
        manifest_path = Path(str(pack.get("manifest") or ""))
        if manifest_path.is_absolute():
            sheet_path = manifest_path.parent / sheet_path
    states = manifest.get("states")
    if not isinstance(states, dict):
        return None
    state_key = CODEX_PET_STATE_ALIASES.get(str(state or "").strip(), str(state or "").strip()) or "idle"
    item = states.get(state_key) or states.get("idle")
    if not isinstance(item, dict):
        return None
    try:
        row = int(item.get("row") if item.get("row") is not None else DESKTOP_STATES.index(state_key))
    except (ValueError, TypeError):
        row = 0
    frame_count = int(item.get("frames") or CODEX_PET_FRAME_COUNTS.get(state_key) or CODEX_PET_FRAME_COUNTS["idle"])
    frame_count = max(1, min(frame_count, CODEX_GRID[0]))
    column = frame_index % frame_count
    width, height = CODEX_CELL
    return sheet_path, (column * width, row * height, (column + 1) * width, (row + 1) * height)


def _avatar_manifest_signature(manifest: dict[str, Any] | None) -> str:
    if not isinstance(manifest, dict):
        return ""
    states = manifest.get("states") if isinstance(manifest.get("states"), dict) else {}
    views = manifest.get("views") if isinstance(manifest.get("views"), dict) else {}
    source = manifest.get("sourceImage") if isinstance(manifest.get("sourceImage"), dict) else {}
    pack = manifest.get("spritePack") if isinstance(manifest.get("spritePack"), dict) else {}
    parts: list[str] = [
        str(manifest.get("generated_at") or ""),
        str(manifest.get("provider") or ""),
        str(source.get("file") or source.get("src") or ""),
        str(pack.get("spritesheet") or ""),
    ]
    for state in DESKTOP_STATES:
        item = states.get(state) if isinstance(states, dict) else None
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("file") or item.get("src") or ""))
        frames = item.get("frames")
        if isinstance(frames, list):
            for frame in frames:
                if isinstance(frame, dict):
                    parts.append(str(frame.get("file") or frame.get("src") or ""))
    for view in AVATAR_VIEW_NAMES:
        item = views.get(view) if isinstance(views, dict) else None
        if isinstance(item, dict):
            parts.append(str(item.get("file") or item.get("src") or ""))
    return "\n".join(part for part in parts if part)


def _hover_menu_action_specs() -> list[dict[str, str]]:
    return []


def _hover_prompt_chip_specs() -> list[dict[str, str]]:
    return [dict(item) for item in _hover_menu_action_specs()]


def _floating_card_action_specs(
    *,
    state: str,
    has_pending_approval: bool = False,
    active_skill: dict[str, Any] | None = None,
    latest_activity: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    return [dict(item) for item in _avatar_context_action_specs()]


def _avatar_context_action_specs() -> list[dict[str, str]]:
    # Right-click is reserved for application shell actions.
    return [
        {"id": "settings", "label": "设置"},
        {"id": "quit", "label": "退出 JiuMe"},
    ]


def _direct_settings_section_specs() -> list[dict[str, str]]:
    return [dict(item) for item in DIRECT_SETTINGS_SECTIONS]


def _normalize_direct_settings_section(value: Any) -> str:
    section = str(value or "").strip()
    ids = {str(item["id"]) for item in DIRECT_SETTINGS_SECTIONS}
    return section if section in ids else "identity"


def _direct_skill_section_specs(*, has_active_skill: bool = False) -> list[dict[str, str]]:
    specs = [dict(item) for item in DIRECT_SKILL_SECTIONS]
    if not has_active_skill:
        return [item for item in specs if item["id"] != "materials"]
    return specs


def _direct_help_section_specs() -> list[dict[str, str]]:
    return []


def _normalize_direct_help_section(value: Any) -> str:
    return "overview"


def _direct_chat_composer_action_specs() -> list[dict[str, str]]:
    return [{"id": "send", "label": "发送"}]


def _normalize_direct_skill_section(value: Any, *, has_active_skill: bool = False) -> str:
    section = str(value or "").strip()
    ids = {str(item["id"]) for item in _direct_skill_section_specs(has_active_skill=has_active_skill)}
    return section if section in ids else "recommended"


def _hover_menu_geometry(
    *,
    icon_x: int,
    icon_y: int,
    size: int,
    screen_width: int,
    screen_height: int,
    width: int = HOVER_MENU_WIDTH,
    height: int = HOVER_MENU_HEIGHT,
) -> str:
    x = icon_x + size // 2 - width // 2
    x = max(8, min(screen_width - width - 8, x))
    y = icon_y - height - 12
    if y < 8:
        y = icon_y + size + 10
    y = max(8, min(screen_height - height - 8, y))
    return f"{width}x{height}+{x}+{y}"


def _hover_menu_item_positions(
    width: int = HOVER_MENU_WIDTH,
    height: int = HOVER_MENU_HEIGHT,
) -> list[tuple[int, int]]:
    center = width // 2
    lower_y = height - 54
    upper_y = max(42, height - 130)
    return [
        (center - 96, lower_y),
        (center - 34, upper_y),
        (center + 34, upper_y),
        (center + 96, lower_y),
    ]


def _speech_bubble_height(text: str) -> int:
    length = len(str(text or ""))
    lines = max(1, (length + 9) // 10)
    return max(BUBBLE_MIN_HEIGHT, min(BUBBLE_MAX_HEIGHT, 42 + lines * 18))


def _speech_bubble_layout(
    *,
    text: str,
    icon_x: int,
    icon_y: int,
    size: int,
    screen_width: int,
    screen_height: int,
    width: int = BUBBLE_WIDTH,
) -> dict[str, Any]:
    height = _speech_bubble_height(text)
    x = icon_x + size // 2 - width // 2
    x = max(8, min(screen_width - width - 8, x))
    y = icon_y - height - 10
    tail = "bottom"
    if y < 8:
        y = icon_y + size + 8
        tail = "top"
    y = max(8, min(screen_height - height - 8, y))
    tail_x = max(32, min(width - 32, icon_x + size // 2 - x))
    return {"width": width, "height": height, "x": x, "y": y, "tail": tail, "tail_x": tail_x}


def _direct_chat_surface_rect(width: int, height: int) -> dict[str, int]:
    if int(height or 0) <= ONE_LINE_DIRECT_HEIGHT:
        return {
            "x": 6,
            "y": 4,
            "width": max(214, width - 12),
            "height": max(52, min(66, height - 8)),
            "radius": 28,
            "draw": True,
        }
    surface_width = max(214, width - 42)
    surface_height = max(132, height - 82)
    return {
        "x": 6,
        "y": 4,
        "width": surface_width,
        "height": surface_height,
        "radius": 34,
        "draw": True,
    }


def _direct_chat_composer_rect(width: int, height: int) -> dict[str, int]:
    composer_width = min(DIRECT_CHAT_COMPOSER_WIDTH, max(214, width - 86))
    if int(height or 0) <= ONE_LINE_DIRECT_HEIGHT:
        composer_height = min(DIRECT_CHAT_COMPOSER_HEIGHT, max(34, height - 20))
        return {
            "x": max(18, width - composer_width - 24),
            "y": max(6, min(height - composer_height - 6, (height - composer_height) // 2)),
            "width": composer_width,
            "height": composer_height,
            "radius": 24,
            "draw": True,
        }
    composer_height = 48
    return {
        "x": max(18, width - composer_width - 24),
        "y": max(112, height - composer_height - 10),
        "width": composer_width,
        "height": composer_height,
        "radius": 24,
        "draw": True,
    }


def _direct_chat_surface_bubbles(width: int, height: int) -> list[dict[str, int]]:
    return [_direct_chat_surface_rect(width, height), _direct_chat_composer_rect(width, height)]


def _direct_chat_geometry_for_avatar(
    *,
    icon_x: int,
    icon_y: int,
    size: int,
    width: int,
    height: int,
    screen_width: int,
    screen_height: int,
) -> dict[str, int | str]:
    margin = 20
    gap = 14
    avatar_center_x = int(icon_x) + int(size) // 2
    preferred_side = "right" if avatar_center_x < int(screen_width) // 2 else "left"

    if preferred_side == "right":
        x = int(icon_x) + int(size) + gap
        if x + int(width) > int(screen_width) - margin:
            preferred_side = "left"
            x = int(icon_x) - int(width) - gap
    else:
        x = int(icon_x) - int(width) - gap
        if x < margin:
            preferred_side = "right"
            x = int(icon_x) + int(size) + gap

    x = max(margin, min(int(screen_width) - int(width) - margin, x))
    y = int(icon_y) + int(size) // 2 - int(height) // 2
    y = max(margin, min(int(screen_height) - int(height) - margin, y))
    return {"x": x, "y": y, "side": preferred_side}


def _direct_chat_content_rect(width: int, height: int) -> dict[str, int]:
    if int(height or 0) <= ONE_LINE_DIRECT_HEIGHT:
        surface = _direct_chat_surface_rect(width, height)
        return {
            "x": surface["x"] + 18,
            "y": 3,
            "width": max(198, surface["width"] - 32),
            "height": max(DIRECT_CHAT_COMPOSER_HEIGHT + 14, height - 6),
        }
    surface = _direct_chat_surface_rect(width, height)
    return {
        "x": surface["x"] + 18,
        "y": surface["y"] + 13,
        "width": max(198, surface["width"] - 32),
        "height": max(42, height - 28),
    }


def _direct_message_max_width(container_width: int = DIRECT_CHAT_WIDTH) -> int:
    return max(128, min(DIRECT_MESSAGE_MAX_WIDTH, int(container_width or DIRECT_CHAT_WIDTH) - 86))


def _direct_message_bubble_metrics(
    text: str,
    container_width: int = DIRECT_CHAT_WIDTH,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None,
) -> dict[str, Any]:
    message_text = str(text or "")
    body_font = font or _desktop_font(13)
    max_width = _direct_message_max_width(container_width)
    text_horizontal_inset = 46
    max_text_width = max(64, max_width - text_horizontal_inset)
    lines = _wrap_desktop_text(message_text, body_font, max_text_width)
    text_width = max((_text_width(line, body_font) for line in lines), default=0)
    width = max(DIRECT_MESSAGE_MIN_WIDTH, min(max_width, text_width + text_horizontal_inset))
    line_height = max(18, int(getattr(body_font, "size", 13)) + 5)
    height = max(52, min(176, 28 + len(lines) * line_height))
    return {
        "width": width,
        "height": height,
        "lines": lines,
        "text_width": text_width,
        "text_width_limit": max(32, width - text_horizontal_inset),
    }


def _direct_message_bubble_height(
    text: str,
    container_width: int = DIRECT_CHAT_WIDTH,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None,
) -> int:
    return int(_direct_message_bubble_metrics(text, container_width, font=font)["height"])


def _direct_message_bubble_width(
    text: str,
    container_width: int = DIRECT_CHAT_WIDTH,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None,
) -> int:
    return int(_direct_message_bubble_metrics(text, container_width, font=font)["width"])


def _direct_speech_bubble_width(title: str, detail: str, *, max_width: int = 292) -> int:
    text_len = max(len(str(title or "")), min(len(str(detail or "")), 46))
    return max(196, min(int(max_width or 292), 86 + text_len * 7))


def _direct_value_bubble_width(label: str, value: str, *, max_width: int = 270) -> int:
    text_len = max(len(str(label or "")) + 2, min(len(str(value or "")), 36))
    return max(178, min(int(max_width or 270), 82 + text_len * 7))


def _direct_text_preview_bubble_width(title: str, text: str, *, max_width: int = 292) -> int:
    text_len = max(len(str(title or "")) + 3, min(len(str(text or "")), 42))
    return max(206, min(int(max_width or 292), 82 + text_len * 6))


def _clip(value: str, limit: int = 72) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _animation_transform(state: str, frame: int) -> dict[str, float]:
    _ = (state, frame)
    return {"scale": 1.0, "dx": 0.0, "dy": 0.0, "rotation": 0.0, "alpha": 1.0}


def _interaction_effect_transform(effect: str, frame: int) -> dict[str, float] | None:
    key = str(effect or "").strip()
    local_frame = int(frame or 0)
    if local_frame < 0 or local_frame >= 18:
        return None
    transform = {"scale": 1.0, "dx": 0.0, "dy": 0.0, "rotation": 0.0, "alpha": 1.0}
    if key == "wave":
        transform["rotation"] = float([0, -5, 6, -6, 5, -4, 3, 0][local_frame % 8])
        transform["dx"] = float([0, -2, 2, -2, 2, -1, 1, 0][local_frame % 8])
    elif key == "cheer":
        transform["scale"] = float([1.0, 1.08, 1.04, 1.0, 1.055, 1.02][local_frame % 6])
        transform["dy"] = float([0, -7, -3, 0, -4, -1][local_frame % 6])
    elif key == "nod":
        transform["dy"] = float([0, 3, 6, 3, -1, 0, 2, 0][local_frame % 8])
        transform["scale"] = float([1.0, 0.995, 0.99, 0.997, 1.01, 1.0][local_frame % 6])
    elif key == "pat":
        transform["scale"] = float([1.0, 1.035, 0.997, 1.02, 1.0, 1.012][local_frame % 6])
        transform["dy"] = float([0, -3, 1, -2, 0, 0][local_frame % 6])
        transform["rotation"] = float([0, -1, 1, 0.5, 0, 0][local_frame % 6])
    elif key == "stretch":
        transform["scale"] = float([1.0, 1.025, 1.055, 1.04, 1.015, 1.0][local_frame % 6])
        transform["dy"] = float([0, 1, 2, 1, 0, -1][local_frame % 6])
    elif key == "breathe":
        transform["scale"] = float([1.0, 1.012, 1.026, 1.038, 1.026, 1.012][local_frame % 6])
        transform["dy"] = float([0, -1, -2, -2, -1, 0][local_frame % 6])
    elif key == "companion":
        transform["scale"] = float([1.0, 1.022, 1.035, 1.022, 1.0, 1.012][local_frame % 6])
        transform["rotation"] = float([0, -1, 0, 1, 0, 0][local_frame % 6])
    elif key == "peek":
        transform["dx"] = float([8, 6, 3, 0, -1, 0, 2, 5][local_frame % 8])
        transform["dy"] = float([1, 0, -1, -2, -1, 0, 1, 1][local_frame % 8])
        transform["rotation"] = float([2, 1, 0, -1, 0, 1, 1, 2][local_frame % 8])
    elif key == "glance":
        transform["dx"] = float([0, 2, 4, 3, 1, 0][local_frame % 6])
        transform["dy"] = float([0, -1, -1, 0, 1, 0][local_frame % 6])
        transform["rotation"] = float([0, 0.8, 1.2, 0.6, 0, 0][local_frame % 6])
    elif key == "dance":
        transform["scale"] = float([1.0, 1.06, 1.02, 1.065, 1.0, 1.035][local_frame % 6])
        transform["dx"] = float([-3, 3, -2, 2, -1, 1][local_frame % 6])
        transform["dy"] = float([0, -6, -2, -7, -1, 0][local_frame % 6])
        transform["rotation"] = float([-3, 3, -2, 2, -1, 1][local_frame % 6])
    elif key == "heart":
        transform["scale"] = float([1.0, 1.075, 1.035, 1.08, 1.02, 1.0][local_frame % 6])
        transform["dy"] = float([0, -5, -2, -4, -1, 0][local_frame % 6])
        transform["rotation"] = float([0, -2, 1.5, -1, 0.8, 0][local_frame % 6])
    elif key == "poke":
        transform["scale"] = float([1.0, 1.06, 0.985, 1.025, 1.0, 1.0][local_frame % 6])
        transform["dy"] = float([0, -5, 2, -2, 0, 0][local_frame % 6])
    else:
        return None
    return transform


def _merge_avatar_transforms(base: dict[str, float], overlay: dict[str, float]) -> dict[str, float]:
    return {
        "scale": float(base.get("scale", 1.0)) * float(overlay.get("scale", 1.0)),
        "dx": float(base.get("dx", 0.0)) + float(overlay.get("dx", 0.0)),
        "dy": float(base.get("dy", 0.0)) + float(overlay.get("dy", 0.0)),
        "rotation": float(base.get("rotation", 0.0)) + float(overlay.get("rotation", 0.0)),
        "alpha": float(base.get("alpha", 1.0)) * float(overlay.get("alpha", 1.0)),
    }


def _wake_line(index: int) -> str:
    return WAKE_LINES[index % len(WAKE_LINES)]


def _should_wake_on_click(state: str, *, drag_moved: bool) -> bool:
    return not drag_moved and str(state or "").strip() == "sleep"


def _hover_effect_for_state(state: str) -> str:
    key = str(state or "").strip()
    if key in {"idle", "thinking", "working", "waiting_approval", "sleep"}:
        return ""
    return "glance"


def _avatar_hover_hint(
    state: str,
    *,
    active_skill: dict[str, Any] | None = None,
    latest_activity: dict[str, Any] | None = None,
    has_pending_approval: bool = False,
) -> dict[str, str]:
    key = str(state or "").strip()
    activity = latest_activity if isinstance(latest_activity, dict) else {}
    kind = str(activity.get("kind") or "").strip()
    title = _clip(str(activity.get("title") or "当前任务"), 28)
    detail = _clip(str(activity.get("detail") or ""), 44)
    if key == "sleep":
        return {"line": "我在安静待机。单击我就回来。", "state": "sleep", "effect": ""}
    if has_pending_approval or kind == "approval" or key == "waiting_approval":
        focus = detail or title
        return {"line": f"我在等你确认：{focus}", "state": "waiting_approval", "effect": "peek"}
    if kind in {"user", "quick", "accepted", "processing", "subtask", "tool"}:
        focus = f"：{detail}" if detail else ""
        return {
            "line": f"我还在处理「{title}」{focus}",
            "state": _work_hud_state_for_activity(kind) or "working",
            "effect": _activity_effect_for_kind(kind) or "peek",
        }
    if kind in {"artifact", "final"} or key == "success":
        focus = f"「{title}」" if title else "刚才那件事"
        return {"line": f"我刚完成 {focus}。点我可以继续查看。", "state": "success", "effect": "cheer"}
    if kind == "error" or key == "error":
        focus = detail or title
        return {"line": f"刚才有点问题：{focus}。点我看详情。", "state": "error", "effect": ""}
    skill = _active_skill_snapshot(active_skill)
    if skill:
        name = _clip(skill["displayName"], 18)
        return {
            "line": f"我拿着「{name}」。直接把要求说给我。",
            "state": "speaking",
            "effect": "" if key == "idle" else "peek",
        }
    if key == "thinking":
        return {"line": "我正在想这件事。点我可以看进展。", "state": "thinking", "effect": "peek"}
    return {"line": "我在。单击就直接说话。", "state": "idle", "effect": ""}


def _avatar_status_badge_style(state: str, frame: int) -> dict[str, Any]:
    style = AVATAR_STATUS_BADGES.get(str(state or "").strip(), AVATAR_STATUS_BADGES["idle"])
    pulses = style.get("pulse")
    pulse_values = tuple(int(value) for value in pulses) if isinstance(pulses, tuple) else (0,)
    return {
        "label": str(style.get("label") or "在"),
        "color": tuple(style.get("color") or AVATAR_STATUS_BADGES["idle"]["color"]),
        "pulse": pulse_values[int(frame or 0) % len(pulse_values)],
    }


def _draw_avatar_aura(canvas: Image.Image, state: str, frame: int) -> None:
    _ = (canvas, state, frame)


def _draw_avatar_status_badge(canvas: Image.Image, state: str, frame: int) -> None:
    style = _avatar_status_badge_style(state, frame)
    color = tuple(int(value) for value in style["color"])
    pulse = int(style["pulse"])
    side = max(1, min(canvas.size))
    radius = max(5, side // 16)
    margin = max(4, side // 18)
    center_x = canvas.width - margin - radius
    center_y = margin + radius
    halo_radius = radius + 4 + pulse
    draw = ImageDraw.Draw(canvas, "RGBA")
    halo = (color[0], color[1], color[2], 44)
    outline = (color[0], color[1], color[2], 145)
    fill = (color[0], color[1], color[2], 230)
    draw.ellipse(
        (
            center_x - halo_radius,
            center_y - halo_radius,
            center_x + halo_radius,
            center_y + halo_radius,
        ),
        fill=halo,
        outline=outline,
        width=max(1, side // 80),
    )
    draw.ellipse(
        (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        ),
        fill=fill,
        outline=(255, 255, 255, 235),
        width=max(2, side // 52),
    )
    glint_radius = max(2, radius // 3)
    draw.ellipse(
        (
            center_x - radius // 2,
            center_y - radius // 2,
            center_x - radius // 2 + glint_radius,
            center_y - radius // 2 + glint_radius,
        ),
        fill=(255, 255, 255, 210),
    )


def _reaction_chip_for_effect(effect: str) -> dict[str, Any]:
    key = str(effect or "").strip()
    chips: dict[str, dict[str, Any]] = {
        "wave": {"label": "HI", "color": (37, 99, 235)},
        "pat": {"label": "OK", "color": (15, 118, 110)},
        "cheer": {"label": "YES", "color": (22, 163, 74)},
        "nod": {"label": "OK", "color": (37, 99, 235)},
        "peek": {"label": "?", "color": (124, 58, 237)},
        "stretch": {"label": "...", "color": (217, 119, 6)},
        "breathe": {"label": "...", "color": (15, 118, 110)},
        "companion": {"label": "ON", "color": (37, 99, 235)},
        "dance": {"label": "YES", "color": (22, 163, 74)},
        "heart": {"label": "LOVE", "color": (219, 39, 119)},
        "poke": {"label": "!", "color": (217, 119, 6)},
    }
    return dict(chips.get(key, {}))


def _draw_reaction_chip(canvas: Image.Image, effect: str | None, frame: int = 0) -> None:
    chip = _reaction_chip_for_effect(str(effect or ""))
    label = str(chip.get("label") or "")
    if not label:
        return
    side = max(1, min(canvas.size))
    height = max(17, side // 7)
    margin = max(5, side // 18)
    width = min(canvas.width - margin * 2, max(height + 8, height + len(label) * max(7, side // 18)))
    pulse = int(frame or 0) % 6
    x0 = margin
    y0 = margin + (1 if pulse in {2, 3} else 0)
    x1 = x0 + width
    y1 = y0 + height
    color = tuple(int(value) for value in chip.get("color") or (37, 99, 235))
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        (x0 - 2, y0 - 2, x1 + 2, y1 + 2),
        radius=height // 2 + 2,
        fill=(255, 255, 255, 178),
    )
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=height // 2,
        fill=(color[0], color[1], color[2], 224),
        outline=(255, 255, 255, 230),
        width=max(1, side // 92),
    )
    font = _skill_badge_font(max(9, height // 2))
    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = x0 + (width - text_width) // 2
    text_y = y0 + (height - text_height) // 2 - 1
    draw.text((text_x, text_y), label, font=font, fill=(255, 255, 255, 246))


def _format_service_status(payload: dict[str, Any]) -> str:
    if not payload:
        return "后台状态还没有写入。用 jiume-launch 启动后，我会在这里显示配置窗口和 Agent/Gateway。"
    services = payload.get("services")
    if not isinstance(services, dict):
        return "后台状态格式不完整。"
    names = {"setup": "配置窗口", "agent": "Agent/Gateway", "web": "JiuwenSwarm 配置页"}
    status_names = {
        "running": "运行中",
        "reused": "复用外部服务",
        "idle": "未打开",
        "disabled": "未启用",
        "exited": "已退出",
    }
    lines: list[str] = []
    for key in ("setup", "agent", "web"):
        service = services.get(key)
        if not isinstance(service, dict):
            lines.append(f"{names[key]}：未知")
            continue
        status = status_names.get(str(service.get("status") or ""), str(service.get("status") or "未知"))
        mode = str(service.get("mode") or "")
        suffixes: list[str] = []
        if mode == "managed" and service.get("pid"):
            suffixes.append(f"pid {service['pid']}")
        restart_count = service.get("restart_count")
        if isinstance(restart_count, int) and restart_count > 0:
            suffixes.append(f"已恢复 {restart_count} 次")
        if mode == "reused":
            suffixes.append("外部管理")
        if mode == "disabled":
            suffixes.append("已关闭")
        if key == "agent" and service.get("gateway_ready") is False:
            suffixes.append("Gateway 未通过检测")
        if key == "web" and service.get("url"):
            suffixes.append(str(service.get("url")))
        tail = f"（{'，'.join(suffixes)}）" if suffixes else ""
        lines.append(f"{names[key]}：{status}{tail}")
    note = str(payload.get("note") or "").strip()
    if note:
        lines.append(_clip(note, 54))
    return "\n".join(lines)


def _direct_service_status_summary(payload: dict[str, Any]) -> dict[str, str]:
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, dict):
        return {
            "state": "unknown",
            "label": "后台状态未知",
            "detail": "用 jiume-launch 启动后，我会在这里显示 Agent 是否在线。",
        }
    agent = services.get("agent")
    setup = services.get("setup")
    agent_status = str(agent.get("status") or "") if isinstance(agent, dict) else ""
    gateway_ready = agent.get("gateway_ready") if isinstance(agent, dict) else None
    setup_status = str(setup.get("status") or "") if isinstance(setup, dict) else ""
    active_statuses = {"running", "reused"}
    if agent_status in active_statuses and gateway_ready is False:
        label = "Gateway 检测中"
        state = "unknown"
    elif agent_status in active_statuses:
        label = "Agent 在线"
        state = "online"
    elif agent_status == "disabled":
        label = "Agent 未启用"
        state = "offline"
    elif agent_status == "exited":
        label = "Agent 已退出"
        state = "offline"
    else:
        label = "Agent 状态未知"
        state = "unknown"
    detail_parts: list[str] = []
    if setup_status:
        detail_parts.append("配置窗口 " + ("在线" if setup_status in active_statuses else setup_status))
    if isinstance(agent, dict):
        mode = str(agent.get("mode") or "")
        if mode == "reused":
            detail_parts.append("复用外部服务")
        if gateway_ready is False:
            detail_parts.append("Gateway 端口还不可达")
        restart_count = agent.get("restart_count")
        if isinstance(restart_count, int) and restart_count > 0:
            detail_parts.append(f"已恢复 {restart_count} 次")
    detail = " · ".join(detail_parts) or "后台状态已写入。"
    return {"state": state, "label": label, "detail": _clip(detail, 72)}


def _recommended_skill_by_name(name: str) -> dict[str, Any] | None:
    for skill in RECOMMENDED_SKILLS:
        if name in str(skill.get("displayName") or ""):
            return skill
    return None


def _recommended_skill_by_id(skill_id: str) -> dict[str, Any] | None:
    target = str(skill_id or "").strip()
    for skill in RECOMMENDED_SKILLS:
        if str(skill.get("id") or "").strip() == target:
            return skill
    return None


def _skill_text_key(value: str) -> str:
    return str(value or "").lower().replace(" ", "").replace("-", "").replace("_", "")


def _skill_aliases(skill: dict[str, Any]) -> tuple[str, ...]:
    display_name = str(skill.get("displayName") or skill.get("name") or "")
    category = str(skill.get("category") or "")
    summary = str(skill.get("summary") or "")
    aliases = {str(skill.get("id") or ""), display_name, category}
    haystack = f"{display_name} {category} {summary}".lower()
    alias_map: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
        (("会议", "纪要", "meeting"), ("会议", "纪要", "会议纪要", "meeting", "minutes")),
        (("数据", "分析", "data", "csv"), ("数据", "数据分析", "表格", "data", "analytics", "csv")),
        (("email", "邮件", "mail"), ("邮件", "email", "mail", "email optimizer")),
        (("prd", "产品", "需求"), ("prd", "产品", "需求", "prd评审")),
        (("代码", "review", "研发", "pr "), ("代码", "代码评审", "code", "review", "pr review")),
        (("调试", "bug", "debug"), ("调试", "bug", "debug", "debugging")),
        (("文档", "doc"), ("文档", "doc", "docs", "documentation")),
        (("截图", "screenshot"), ("截图", "screen", "screenshot")),
        (("社媒", "内容", "social"), ("社媒", "内容", "social", "content")),
        (("安全", "审计", "security"), ("安全", "审计", "security", "audit")),
    )
    for triggers, values in alias_map:
        if any(trigger in haystack for trigger in triggers):
            aliases.update(values)
    return tuple(alias for alias in aliases if alias)


def _skill_match_score(skill: dict[str, Any], message: str) -> int:
    text_key = _skill_text_key(message)
    if not text_key:
        return 0
    score = 0
    for alias in _skill_aliases(skill):
        alias_key = _skill_text_key(alias)
        if not alias_key or alias_key not in text_key:
            continue
        score = max(score, len(alias_key))
    return score


def _skill_candidates(enabled_skill_ids: list[str] | None = None) -> list[dict[str, Any]]:
    rows = [dict(skill) for skill in RECOMMENDED_SKILLS]
    known_ids = {str(skill.get("id") or "") for skill in rows}
    for skill_id in enabled_skill_ids or []:
        target = str(skill_id or "").strip()
        if target and target not in known_ids:
            rows.append(
                {
                    "id": target,
                    "displayName": target,
                    "category": "个人",
                    "risk": "unknown",
                    "summary": "本地导入并挂载到 JiuMe 的个人 skill。",
                    "whyJiume": "这是用户给当前分身安装的本地能力。",
                    "isLocal": True,
                }
            )
    return rows


def _native_skill_command(message: str, enabled_skill_ids: list[str] | None = None) -> dict[str, Any] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    ignored = (
        "打开技能",
        "技能货架",
        "技能面板",
        "取消当前skill",
        "取消当前 skill",
        "不用这个skill",
        "不用这个 skill",
        "show skills",
        "skill shelf",
        "clear skill",
    )
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in ignored):
        return None
    has_skill_word = "skill" in lower or "技能" in text
    strong_command_tokens = (
        "使用",
        "装",
        "装载",
        "启用",
        "启动",
        "切到",
        "切换到",
        "换到",
        "固定",
        "mount ",
        "activate ",
        "switch to ",
    )
    triggers = (
        "用",
        "使用",
        "装",
        "装载",
        "启用",
        "启动",
        "切到",
        "切换到",
        "换到",
        "固定",
        "skill",
        "技能",
        "use ",
        "mount ",
        "activate ",
        "switch to ",
    )
    if not any(token in lower or token in text or token.replace(" ", "") in compact_text for token in triggers):
        return None
    informational_skill_tokens = (
        "有哪些skill",
        "有哪些 skill",
        "有什么skill",
        "有什么 skill",
        "哪些skill",
        "哪些 skill",
        "有哪些技能",
        "有什么技能",
        "哪些技能",
        "你会哪些技能",
        "你会哪些skill",
        "你现在有哪些skill",
        "你现在有哪些 skill",
        "what skills",
        "which skills",
        "available skills",
        "list skills",
        "skills do you have",
    )
    if any(
        token in lower
        or token in text
        or token.replace(" ", "") in compact_lower
        or token.replace(" ", "") in compact_text
        for token in informational_skill_tokens
    ):
        return None

    ranked: list[tuple[int, dict[str, Any]]] = []
    for skill in _skill_candidates(enabled_skill_ids):
        score = _skill_match_score(skill, text)
        if score > 0:
            ranked.append((score, skill))
    if not ranked:
        if has_skill_word or any(token in lower or token in text for token in strong_command_tokens):
            return {"action": "choose"}
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return {"action": "use", "skill": dict(ranked[0][1])}


def _native_skill_import_command(
    message: str,
    *,
    path_exists: Callable[[Path], bool] | None = None,
) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    has_skill_word = "skill" in lower or "技能" in text
    has_import_word = any(token in lower or token in text for token in ("导入", "安装", "添加", "import", "install"))
    if not (has_skill_word and has_import_word):
        return None

    candidates: list[str] = []
    candidates.extend(match.group(1).strip() for match in re.finditer(r"[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]", text))
    for line in _clipboard_candidate_lines(text):
        cleaned = re.sub(
            r"^(请)?(帮我)?(导入|安装|添加|import|install)\s*(本地|local)?\s*(skill|技能)?\s*[:：-]?\s*",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned and cleaned != line:
            candidates.append(cleaned)
        for match in re.finditer(r"(file://\S+|~[^\s，,。;；]+|/[^\n]+)", line):
            candidates.append(match.group(1).strip(" ，,。.;；"))

    exists = path_exists or (lambda path: path.exists())
    for candidate in candidates:
        path = _clipboard_path_candidate(candidate)
        if path is None:
            continue
        try:
            if exists(path):
                return str(path.resolve())
        except OSError:
            continue
    return None


def _active_skill_snapshot(skill: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(skill, dict):
        return None
    skill_id = str(skill.get("id") or "").strip()
    display_name = str(skill.get("displayName") or skill.get("name") or skill_id).strip()
    if not skill_id or not display_name:
        return None
    return {
        "id": skill_id,
        "displayName": display_name,
        "summary": str(skill.get("summary") or "").strip(),
        "category": str(skill.get("category") or "").strip(),
        "risk": str(skill.get("risk") or "unknown").strip() or "unknown",
        "whyJiume": str(skill.get("whyJiume") or "").strip(),
    }


def _active_skill_badge_label(skill: dict[str, Any] | None) -> str:
    snapshot = _active_skill_snapshot(skill)
    if not snapshot:
        return ""
    name = re.sub(
        r"(精炼团队|专业组|委员会|团队|小组|skill)$",
        "",
        snapshot["displayName"].strip(),
        flags=re.IGNORECASE,
    ).strip(" -_/")
    parts = re.findall(r"[A-Za-z0-9]+", name)
    if len(parts) > 1 and re.search(r"[-_/ ]", name):
        return "".join(part[0] for part in parts).upper()[:3]
    leading_ascii = re.match(r"[A-Za-z0-9]{2,4}", name)
    if leading_ascii:
        return leading_ascii.group(0).upper()[:3]
    cjk = re.findall(r"[\u4e00-\u9fff]", name)
    if cjk:
        return "".join(cjk[:2])
    if parts:
        if len(parts) == 1:
            return parts[0].upper()[:3]
        return "".join(part[0] for part in parts).upper()[:3]
    return name[:2]


def _skill_badge_font(size: int) -> ImageFont.ImageFont:
    for name in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_active_skill_badge(canvas: Image.Image, skill: dict[str, Any] | None, frame: int = 0) -> None:
    label = _active_skill_badge_label(skill)
    if not label:
        return
    side = max(1, min(canvas.size))
    badge_height = max(18, side // 6)
    badge_width = min(canvas.width - max(8, side // 9), max(badge_height * 2, badge_height + len(label) * 9))
    margin = max(5, side // 18)
    x0 = margin
    y0 = canvas.height - margin - badge_height
    x1 = x0 + badge_width
    y1 = y0 + badge_height
    pulse = int(frame or 0) % 6
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        (x0 - 2, y0 - 2, x1 + 2, y1 + 2),
        radius=badge_height // 2 + 2,
        fill=(255, 255, 255, 180),
    )
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=badge_height // 2,
        fill=(17, 17, 17, 224),
        outline=(139, 92, 246, 155 + pulse * 10),
        width=max(1, side // 96),
    )
    draw.ellipse(
        (x0 + 4, y0 + 5, x0 + badge_height - 5, y1 - 5),
        fill=(139, 92, 246, 235),
    )
    font = _skill_badge_font(max(9, badge_height // 2))
    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = x0 + badge_height + max(2, (badge_width - badge_height - text_width) // 2)
    text_y = y0 + (badge_height - text_height) // 2 - 1
    draw.text((text_x, text_y), label, font=font, fill=(255, 255, 255, 245))


def _active_skill_followup_message(message: str, skill: dict[str, Any] | None) -> str:
    body = str(message or "").strip()
    snapshot = _active_skill_snapshot(skill)
    if not body or not snapshot:
        return body
    details = [
        f"Continue with the active mounted JiuMe skill \"{snapshot['displayName']}\".",
        f"Skill id: {snapshot['id']}. Category: {snapshot['category'] or 'unknown'}. Risk: {snapshot['risk']}.",
    ]
    if snapshot["summary"]:
        details.append(f"Skill summary: {snapshot['summary']}")
    if snapshot["whyJiume"]:
        details.append(f"Why this skill fits JiuMe: {snapshot['whyJiume']}")
    details.extend(
        [
            "User request/material:",
            body,
            "",
            "Use this active skill for the task. If anything required is missing, ask only for the missing item.",
        ]
    )
    return "\n".join(details)


def _jiume_agent_conversation_message(message: str, twin: dict[str, Any] | None = None) -> str:
    body = str(message or "").strip()
    if not body:
        return body
    source = twin if isinstance(twin, dict) else {}
    name = str(source.get("displayName") or source.get("name") or "JiuMe").strip() or "JiuMe"
    purpose = str(source.get("purpose") or "desktop personal twin").strip() or "desktop personal twin"
    tone = str(source.get("tone") or "warm and concise").strip() or "warm and concise"
    return "\n".join(
        [
            "JiuMe desktop personal twin context:",
            "You are answering inside the JiuMe desktop avatar chat.",
            "Treat the assistant identity as the user's active JiuMe desktop personal twin, not a generic backend, website, model, or system assistant.",
            f"Active twin name: {name}",
            f"Twin purpose: {purpose}",
            f"Twin tone: {tone}",
            "",
            "User original message:",
            body,
            "",
            "Response rules:",
            "- Answer the user's actual message directly.",
            "- Do not introduce yourself as JiuwenSwarm or as a private agent created by JiuwenSwarm.",
            "- Do not mention the current time, date, timezone, platform time sync, or efficiency claims.",
            "- Do not mention model names, qwen-plus, backend runtime, system prompts, tools, or service wiring.",
            "- Do not fabricate previous conversation history.",
            "- If the user asks who you are, say you are the active JiuMe desktop personal twin/avatar in a concise, natural way.",
            "- Reply in the user's language.",
        ]
    )


def _active_skill_summary(skill: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = _active_skill_snapshot(skill)
    if not snapshot:
        return {
            "hasSkill": False,
            "label": "现在没有固定 skill",
            "detail": "你可以直接说“用数据分析 skill”，也可以让我打开技能货架来挑一个。",
        }
    name = _clip(snapshot["displayName"], 22)
    summary = _clip(snapshot["summary"] or "这个 skill 已固定给后续材料和任务。", 72)
    parts = [f"我现在拿着「{name}」。{summary}"]
    if snapshot["category"] or snapshot["risk"]:
        parts.append(f"分类：{snapshot['category'] or '个人'}；风险：{snapshot['risk']}。")
    if snapshot["whyJiume"]:
        parts.append(_clip(snapshot["whyJiume"], 58))
    parts.append("你可以直接交屏幕、剪贴板或文件，我会按这个 skill 交给 Agent。")
    return {
        "hasSkill": True,
        "label": f"当前 skill：{name}",
        "detail": _clip(" ".join(parts), 190),
        "id": snapshot["id"],
        "displayName": snapshot["displayName"],
        "risk": snapshot["risk"],
    }


def _native_active_skill_query_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    excluded = (
        "打开技能",
        "技能货架",
        "技能面板",
        "取消当前skill",
        "取消当前 skill",
        "不用这个skill",
        "不用这个 skill",
        "帮我选skill",
        "帮我选 skill",
        "该用哪个skill",
        "该用哪个 skill",
        "推荐skill",
        "推荐 skill",
        "show skills",
        "skill shelf",
        "clear skill",
        "pick a skill",
        "recommend skill",
    )
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in excluded):
        return False
    task_tokens = (
        "帮我",
        "写",
        "设计",
        "实现",
        "整理",
        "总结",
        "分析",
        "review",
        "write",
        "draft",
        "design",
        "build",
        "create",
        "summarize",
        "analyze",
    )
    if any(token in lower or token in text for token in task_tokens):
        return False
    exact = compact_lower.strip("?.!。！？,，")
    if exact in {"当前skill", "当前技能", "当前能力", "activeskill", "currentskill"}:
        return True
    tokens = (
        "当前 skill",
        "当前skill",
        "当前技能",
        "当前能力",
        "你现在拿着哪个 skill",
        "你现在拿着哪个skill",
        "你现在拿着什么 skill",
        "你现在拿着什么skill",
        "你拿着哪个 skill",
        "你拿着哪个skill",
        "你固定了哪个 skill",
        "你固定了哪个skill",
        "现在用的 skill",
        "现在用的skill",
        "active skill",
        "current skill",
        "what skill are you holding",
        "which skill is active",
    )
    for token in tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return True
    return False


def _idle_companion_moment_for_context(
    index: int,
    active_skill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = _active_skill_snapshot(active_skill)
    if not snapshot:
        return idle_companion_moment(index)
    name = _clip(snapshot["displayName"], 18)
    moments = (
        {
            "id": "skill_ready",
            "title": f"{name} 已接手",
            "state": "speaking",
            "effect": "peek",
            "line": f"我还拿着「{name}」。把屏幕、剪贴板或文件交给我，我会按这个 skill 处理。",
        },
        {
            "id": "skill_waiting_material",
            "title": f"{name} 等材料",
            "state": "speaking",
            "effect": "nod",
            "line": f"「{name}」还在我手上。你直接丢材料或补一句要求就行。",
        },
    )
    return dict(moments[int(index or 0) % len(moments)])


def _native_material_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    screen_tokens = ("看屏幕", "看一下屏幕", "看看屏幕", "看下屏幕", "当前屏幕", "屏幕截图", "截屏", "截图", "screen", "screenshot")
    clipboard_tokens = ("剪贴板", "粘贴板", "贴材料", "贴一下", "粘贴一下", "paste", "clipboard")
    file_tokens = ("选文件", "选择文件", "发文件", "交文件", "上传文件", "打开文件", "file picker", "choose file", "select file")
    if any(token in lower or token in text for token in screen_tokens):
        return "screen"
    if any(token in lower or token in text for token in clipboard_tokens):
        return "clipboard"
    if any(token in lower or token in text for token in file_tokens):
        return "file"
    return None


def _native_artifact_command(message: str) -> dict[str, str] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    excluded = ("看进度", "任务进度", "当前任务", "最近任务", "show progress")
    if any(token in lower or token in text for token in excluded):
        return None
    category = "image" if any(token in lower or token in text for token in ("图", "图片", "image", "photo", "screenshot")) else ""
    list_tokens = (
        "产物列表",
        "结果列表",
        "所有产物",
        "全部产物",
        "所有结果",
        "全部结果",
        "最近产物列表",
        "show artifacts",
        "list artifacts",
        "show results",
        "list results",
        "artifact tray",
    )
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    for token in list_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"action": "list", "category": category}
    copy_tokens = (
        "复制结果",
        "复制产物",
        "复制最近结果",
        "复制最近产物",
        "复制刚才的结果",
        "复制刚才的产物",
        "copy result",
        "copy artifact",
        "copy latest",
    )
    for token in copy_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"action": "copy", "category": category}
    tokens = (
        "看结果",
        "查看结果",
        "打开结果",
        "看产物",
        "查看产物",
        "打开产物",
        "看最近产物",
        "打开最近产物",
        "看刚才的结果",
        "打开刚才的结果",
        "看刚才那张图",
        "打开刚才那张图",
        "看刚才的图片",
        "打开刚才的文件",
        "show result",
        "open result",
        "show artifact",
        "open artifact",
        "open latest",
    )
    if not any((token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")) in (compact_lower if token.isascii() else compact_text) for token in tokens):
        return None
    action = "open" if any(token in lower or token in text for token in ("打开", "open")) else "preview"
    return {"action": action, "category": category}


def _native_placement_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    excluded = (
        "右键",
        "左键",
        "左右",
        "靠右一点说",
        "靠左一点说",
        "right click",
        "left click",
    )
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in excluded):
        return None
    summon_tokens = (
        "过来",
        "过来一下",
        "到我这边",
        "到我这边来",
        "靠近我",
        "靠近一点",
        "离我近点",
        "来我这里",
        "come here",
        "come closer",
        "stay near me",
    )
    task_context_tokens = (
        "帮我",
        "看看",
        "看下",
        "看一下",
        "处理",
        "整理",
        "分析",
        "写",
        "生成",
        "方案",
        "文档",
        "屏幕",
        "review",
        "analyze",
        "summarize",
        "write",
    )
    has_task_context = any(token in lower or token in text for token in task_context_tokens)
    is_short_summon = len(compact_text) <= 12 or len(compact_lower) <= 24
    if is_short_summon and not has_task_context:
        for token in summon_tokens:
            compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact_lower if token.isascii() else compact_text
            if token in lower or token in text or compact_token in haystack:
                return "summon"
    placement_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "avoid",
            (
                "别挡我",
                "不要挡我",
                "别遮住",
                "挪开",
                "躲一下",
                "靠边",
                "让一下",
                "step aside",
                "move aside",
                "don't block",
                "dont block",
            ),
        ),
        ("bottom_right", ("右下角", "回到右下", "回右下", "右下", "bottom right", "lower right")),
        ("bottom_left", ("左下角", "左下", "bottom left", "lower left")),
        ("top_right", ("右上角", "右上", "top right", "upper right")),
        ("top_left", ("左上角", "左上", "top left", "upper left")),
        ("center", ("居中", "中间", "到中间", "屏幕中央", "center", "middle")),
        ("right", ("靠右", "去右边", "移到右边", "到右边", "右侧", "move right", "right side")),
        ("left", ("靠左", "去左边", "移到左边", "到左边", "左侧", "move left", "left side")),
    )
    for placement, tokens in placement_tokens:
        for token in tokens:
            compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact_lower if token.isascii() else compact_text
            if token in lower or token in text or compact_token in haystack:
                return placement
    return None


def _normalize_avatar_opacity(value: Any, *, default: float = AVATAR_OPACITY_MAX) -> float:
    try:
        opacity = float(value)
    except (TypeError, ValueError):
        opacity = float(default)
    opacity = min(max(opacity, AVATAR_OPACITY_MIN), AVATAR_OPACITY_MAX)
    return round(opacity, 2)


def _avatar_opacity_from_state(saved: dict[str, Any] | None = None) -> float:
    saved = saved if isinstance(saved, dict) else {}
    return _normalize_avatar_opacity(saved.get("opacity"), default=AVATAR_OPACITY_MAX)


def _avatar_opacity_label(value: float) -> str:
    opacity = _normalize_avatar_opacity(value)
    if opacity <= 0.5:
        return "很低调"
    if opacity <= 0.75:
        return "半透明"
    if opacity < 0.98:
        return "轻微透明"
    return "清晰"


def _native_opacity_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    excluded = ("透明背景", "透明png", "透明 png", "transparent background", "transparent png")
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in excluded):
        return None
    command_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "softer",
            (
                "透明一点",
                "淡一点",
                "低调一点",
                "别那么显眼",
                "不那么显眼",
                "少显眼",
                "降低透明度",
                "transparent",
                "more transparent",
                "less visible",
                "fade a bit",
            ),
        ),
        ("full", ("恢复不透明", "恢复默认透明度", "完全显示", "full opacity", "reset opacity")),
        (
            "clearer",
            (
                "清楚一点",
                "明显一点",
                "亮一点",
                "看清楚",
                "恢复清楚",
                "不透明",
                "fully visible",
                "more visible",
                "clearer",
                "opaque",
            ),
        ),
        ("low", ("半透明", "很低调", "最小透明", "hide a bit", "low opacity")),
    )
    for command, tokens in command_tokens:
        for token in tokens:
            compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact_lower if token.isascii() else compact_text
            if token in lower or token in text or compact_token in haystack:
                return command
    return None


def _latest_activity_artifact(
    items: list[dict[str, Any]],
    *,
    category: str = "",
) -> dict[str, Any] | None:
    target_category = str(category or "").strip()
    for item in items:
        if not isinstance(item, dict):
            continue
        artifacts = item.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if target_category and str(artifact.get("category") or "") != target_category:
                continue
            if str(artifact.get("label") or artifact.get("target") or artifact.get("preview") or "").strip():
                return dict(artifact)
    return None


def _native_interaction_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    interaction_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("wave", ("挥手", "挥挥手", "招手", "打招呼", "hello", "wave")),
        ("pat", ("拍拍", "拍拍肩", "拍肩", "轻拍一下", "摸摸头", "摸头", "pat", "head pat")),
        ("cheer", ("打气", "鼓励我", "给我加油", "加油", "cheer")),
        ("nod", ("点头", "点点头", "点一下头", "nod")),
        ("stretch", ("伸懒腰", "伸个懒腰", "伸展", "拉伸", "stretch")),
        ("breathe", ("呼吸", "深呼吸", "喘口气", "breathe")),
        ("peek", ("探头", "冒个泡", "露个脸", "peek")),
        ("dance", ("小跳", "跳一下", "转一圈", "开心一下", "庆祝一下", "dance", "celebrate")),
        ("heart", ("比心", "比个心", "给我比心", "给我比个心", "heart", "send love", "show love")),
        ("companion", ("陪我", "陪伴", "陪一下", "陪我一下", "守着我", "companion")),
        ("rest", ("休息", "睡吧", "安静", "别吵", "待机", "rest", "sleep")),
    )
    for action_id, tokens in interaction_tokens:
        if any(token in lower or token in text for token in tokens):
            return action_id
    return None


def _native_wake_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    question_tokens = ("醒着吗", "在吗", "are you awake", "are you there")
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in question_tokens):
        return False
    task_tokens = (
        "帮我",
        "处理",
        "整理",
        "总结",
        "分析",
        "写",
        "做",
        "打开",
        "看一下",
        "看下",
        "review",
        "write",
        "summarize",
        "analyze",
        "open",
        "build",
        "create",
    )
    if any(token in lower or token in text for token in task_tokens):
        return False
    exact = compact_lower.strip("?.!。！？,，")
    if exact in {"wakeup", "comeback", "wake", "back"}:
        return True
    tokens = (
        "醒醒",
        "醒来",
        "醒一下",
        "起来",
        "回来",
        "回来吧",
        "回到这里",
        "别睡了",
        "wake up",
        "come back",
        "wake back up",
    )
    for token in tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if compact_token in haystack and len(haystack) <= 18:
            return True
    return False


def _attention_name_aliases(names: Any = None) -> tuple[str, ...]:
    aliases: list[str] = []
    for raw_name in names or []:
        name = str(raw_name or "").strip()
        if not name:
            continue
        aliases.append(name)
        compact_name = name.replace(" ", "")
        if compact_name and compact_name != name:
            aliases.append(compact_name)
        ascii_words = re.findall(r"[A-Za-z0-9]+", name)
        if ascii_words:
            aliases.append(ascii_words[0])
        cjk_name = "".join(re.findall(r"[\u4e00-\u9fff]", name))
        if 1 < len(cjk_name) <= 6:
            aliases.append(cjk_name)

    normalized: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        lowered = str(alias or "").strip().lower()
        compact = lowered.replace(" ", "")
        if not compact or compact in seen:
            continue
        seen.add(compact)
        normalized.append(compact)
    return tuple(normalized)


def _native_attention_command(message: str, *, names: Any = None) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    compact_signal = "".join(ch for ch in compact_lower if ch not in "?.!。！？,，:：~～、")
    task_tokens = (
        "帮我",
        "处理",
        "整理",
        "总结",
        "分析",
        "设计",
        "实现",
        "写",
        "做",
        "打开",
        "看一下",
        "看下",
        "review",
        "write",
        "summarize",
        "analyze",
        "design",
        "build",
        "create",
        "open",
    )
    if any(token in lower or token in text for token in task_tokens):
        return False
    query_tokens = (
        "什么",
        "是谁",
        "状态",
        "设置",
        "技能",
        "进度",
        "后台",
        "怎么",
        "如何",
        "what",
        "status",
        "settings",
        "skill",
        "progress",
        "help",
    )
    if any(token in lower or token in text for token in query_tokens):
        return False
    exact_calls = {
        "jiume",
        "heyjiume",
        "hijiume",
        "hellojiume",
        "xiaojiu",
        "heyxiaojiu",
        "hixiaojiu",
        "helloxiaojiu",
        "jiume在吗",
        "小九",
        "九妹",
        "玖妹",
        "嘿小九",
        "嗨小九",
        "你好小九",
        "小九在吗",
        "九妹在吗",
        "醒醒",
        "回来吧",
        "comeback",
    }
    if compact_signal in exact_calls:
        return True
    name_tokens = ("jiume", "xiaojiu", "小九", "九妹", "玖妹", *_attention_name_aliases(names))
    greeting_tokens = ("hey", "hi", "hello", "嘿", "嗨", "你好", "在吗", "醒醒", "回来")
    if compact_signal in name_tokens:
        return True
    return (
        len(compact_signal) <= 18
        and any(token in compact_signal or token in compact_text for token in name_tokens)
        and any(token in compact_signal or token in compact_text for token in greeting_tokens)
    )


def _native_rps_command(message: str) -> dict[str, str] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_text = text.replace(" ", "")
    compact_lower = lower.replace(" ", "")
    if any(token in compact_text for token in ("布置", "发布", "分布", "布局")):
        return None
    start_tokens = ("猜拳", "石头剪刀布", "剪刀石头布", "rock paper scissors", "rps")
    explicit_move_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("rock", ("我出石头", "出石头", "选石头", "石头", "rock")),
        ("scissors", ("我出剪刀", "出剪刀", "选剪刀", "剪刀", "scissors", "scissor")),
        ("paper", ("我出布", "出布", "选布", "布", "paper")),
    )
    if compact_text in {"石头剪刀布", "剪刀石头布"} or compact_lower in {"rockpaperscissors", "rps"}:
        return {"action": "start", "move": ""}
    for move, tokens in explicit_move_tokens:
        for token in tokens:
            compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact_lower if token.isascii() else compact_text
            if token in lower or token in text or compact_token == haystack or compact_token in haystack:
                return {"action": "play", "move": move}
    for token in start_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"action": "start", "move": ""}
    return None


def _normalize_dice_sides(value: Any, *, default: int = 6) -> int:
    try:
        sides = int(value)
    except (TypeError, ValueError):
        sides = default
    return min(max(sides, 2), 100)


def _native_dice_command(message: str) -> dict[str, int] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    task_tokens = (
        "帮我",
        "写",
        "设计",
        "实现",
        "开发",
        "功能",
        "算法",
        "代码",
        "review",
        "write",
        "design",
        "build",
        "implement",
        "feature",
        "code",
    )
    if any(token in lower or token in text for token in task_tokens):
        return None
    tokens = ("掷骰子", "摇骰子", "骰子", "面骰", "骰", "roll dice", "roll a die", "roll d", "dice")
    if not any(
        token in lower
        or token in text
        or (token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")) in (compact_lower if token.isascii() else compact_text)
        for token in tokens
    ):
        return None
    sides = 6
    match = re.search(r"\bd(\d{1,3})\b", lower)
    if match:
        sides = _normalize_dice_sides(match.group(1))
    else:
        chinese_match = re.search(r"(\d{1,3})\s*面", text)
        if chinese_match:
            sides = _normalize_dice_sides(chinese_match.group(1))
    return {"sides": sides}


def _native_coin_command(message: str) -> dict[str, str] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    task_tokens = (
        "写",
        "设计",
        "实现",
        "开发",
        "功能",
        "算法",
        "代码",
        "review",
        "write",
        "design",
        "build",
        "implement",
        "feature",
        "code",
    )
    if any(token in lower or token in text for token in task_tokens):
        return None
    draw_tokens = ("抽签", "抽一签", "抽个签", "今日签", "draw lots", "draw a lot")
    coin_tokens = ("抛硬币", "扔硬币", "投硬币", "硬币", "flip a coin", "coin toss", "toss a coin")
    for token in draw_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"mode": "draw"}
    for token in coin_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"mode": "coin"}
    return None


def _rps_move_label(move: str) -> str:
    labels = {"rock": "石头", "scissors": "剪刀", "paper": "布"}
    return labels.get(str(move or ""), "石头")


def _rps_round(user_move: str, jiume_move: str) -> dict[str, str]:
    user = str(user_move or "").strip()
    jiume = str(jiume_move or "").strip()
    if user not in RPS_MOVES:
        user = "rock"
    if jiume not in RPS_MOVES:
        jiume = "rock"
    wins = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
    if user == jiume:
        result = "draw"
        state = "speaking"
        effect = "nod"
        line = f"平手！你出{_rps_move_label(user)}，我也出{_rps_move_label(jiume)}。再来一轮？"
    elif (user, jiume) in wins:
        result = "user_win"
        state = "success"
        effect = "cheer"
        line = f"你赢了！你出{_rps_move_label(user)}，我出{_rps_move_label(jiume)}。这一下漂亮。"
    else:
        result = "jiume_win"
        state = "success"
        effect = "dance"
        line = f"这轮我赢啦。我出{_rps_move_label(jiume)}，你出{_rps_move_label(user)}。要不要再来？"
    return {
        "userMove": user,
        "jiumeMove": jiume,
        "result": result,
        "line": line,
        "state": state,
        "effect": effect,
    }


def _dice_roll(sides: int = 6, *, seed: int = 0) -> dict[str, Any]:
    normalized_sides = _normalize_dice_sides(sides)
    result = (max(0, int(seed or 0)) % normalized_sides) + 1
    if result == normalized_sides:
        state = "success"
        effect = "dance"
        line = f"我掷出 D{normalized_sides} 的 {result}。顶格！这一下很有精神。"
    elif result == 1:
        state = "speaking"
        effect = "nod"
        line = f"我掷出 D{normalized_sides} 的 1。先把它当成小提醒：慢一点也没关系。"
    else:
        state = "success"
        effect = "cheer"
        line = f"我掷出 D{normalized_sides} 的 {result}。要不要拿这个数做决定？"
    return {
        "sides": normalized_sides,
        "result": result,
        "line": line,
        "state": state,
        "effect": effect,
    }


def _coin_flip(mode: str = "coin", *, seed: int = 0) -> dict[str, str]:
    normalized = "draw" if str(mode or "").strip() == "draw" else "coin"
    index = max(0, int(seed or 0)) % 2
    if normalized == "draw":
        choices = (
            ("向前一步", "我抽到「向前一步」。先挑一件最小的事推进。", "cheer"),
            ("先收住", "我抽到「先收住」。先停一下，把下一步说清楚。", "nod"),
        )
        label, line, effect = choices[index]
        return {"mode": "draw", "result": label, "line": line, "state": "success", "effect": effect}
    if index == 0:
        return {"mode": "coin", "result": "正面", "line": "硬币是正面。我们就按第一个选项来？", "state": "success", "effect": "cheer"}
    return {"mode": "coin", "result": "反面", "line": "硬币是反面。换个角度也可以。", "state": "speaking", "effect": "nod"}


def _native_companion_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    task_tokens = (
        "安静跑",
        "后台跑",
        "静默跑",
        "你先跑着",
        "先跑着",
        "run quietly",
        "quiet run",
        "background",
    )
    rest_tokens = ("休息", "睡吧", "睡觉", "待机", "rest", "sleep")
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in task_tokens):
        return None
    if any(token in lower or token in text for token in rest_tokens):
        return None
    command_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "quiet",
            (
                "安静守着",
                "安静陪着",
                "安静一点",
                "安静点",
                "你先安静",
                "先安静",
                "别主动说话",
                "不要主动说话",
                "别自己说话",
                "不要自己说话",
                "少打扰",
                "不要打扰",
                "别打扰",
                "quiet companionship",
                "stay quiet",
                "be quiet for now",
                "less proactive",
                "stop check-ins",
            ),
        ),
        (
            "resume",
            (
                "恢复陪伴",
                "恢复主动",
                "继续陪我",
                "主动一点",
                "主动点",
                "可以主动",
                "可以提醒我",
                "别太安静",
                "resume companionship",
                "be more present",
                "check in again",
                "be proactive",
            ),
        ),
    )
    for command, tokens in command_tokens:
        for token in tokens:
            compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact_lower if token.isascii() else compact_text
            if token in lower or token in text or compact_token in haystack:
                return command
    return None


def _native_tuck_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    rest_tokens = ("休息", "睡吧", "睡觉", "待机", "rest", "sleep")
    if any(token in lower or token in text for token in rest_tokens):
        return False
    task_tokens = (
        "写",
        "做",
        "实现",
        "开发",
        "设计",
        "整理",
        "总结",
        "分析",
        "检查",
        "修复",
        "新增",
        "加一个",
        "功能",
        "方案",
        "文档",
        "代码",
        "review",
        "write",
        "draft",
        "build",
        "create",
        "implement",
        "design",
        "summarize",
        "analyze",
        "fix",
        "feature",
        "code",
    )
    if any(
        token in lower or token in text or token.replace(" ", "") in compact_lower or token.replace(" ", "") in compact_text
        for token in task_tokens
    ):
        return False
    exact_lower = compact_lower.strip("?.!。！？,，")
    exact_text = compact_text.strip("?.!。！？,，")
    if exact_lower in {
        "hideui",
        "hidepanel",
        "hidepanels",
        "closeui",
        "closepanels",
        "tuckaway",
        "justavatar",
        "justtheavatar",
        "onlyavatar",
    }:
        return True
    if exact_text in {"收起", "收起来", "先收起", "收起面板", "收起窗口", "收起气泡", "只留头像", "只留你", "回到头像"}:
        return True
    command_tokens = (
        "把旁边收起来",
        "旁边收起来",
        "把面板收起来",
        "先把面板收起来",
        "把气泡收起来",
        "藏起面板",
        "头像旁边收起来",
        "帮我把面板收起来",
        "帮我把旁边收起来",
        "hide ui",
        "hide panels",
        "hide panel",
        "close panels",
        "close ui",
        "dismiss panels",
        "tuck away",
        "just the avatar",
        "only avatar",
    )
    for token in command_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return True
    return False


def _native_control_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    if _native_tuck_command(text):
        return "tuck"
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    task_context_tokens = (
        "帮我",
        "写",
        "做",
        "实现",
        "开发",
        "设计",
        "整理",
        "总结",
        "分析",
        "功能",
        "方案",
        "文档",
        "代码",
        "review",
        "write",
        "build",
        "create",
        "implement",
        "design",
        "summarize",
        "analyze",
        "feature",
        "code",
    )
    has_task_context = any(
        token in lower or token in text or token.replace(" ", "") in compact_lower or token.replace(" ", "") in compact_text
        for token in task_context_tokens
    )
    front_tokens = (
        "到前面来",
        "来到前面",
        "别被挡住",
        "别被盖住",
        "不要被挡住",
        "不要被盖住",
        "保持最前",
        "保持在前面",
        "浮到前面",
        "bring to front",
        "come to front",
        "stay on top",
        "keep on top",
        "frontmost",
    )
    if not has_task_context:
        for token in front_tokens:
            compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact_lower if token.isascii() else compact_text
            if token in lower or token in text or compact_token in haystack:
                return "front"
    chat_task_tokens = (
        "写",
        "做",
        "实现",
        "开发",
        "设计",
        "整理",
        "总结",
        "分析",
        "功能",
        "系统",
        "网页",
        "app",
        "ui",
        "review",
        "write",
        "build",
        "create",
        "design",
        "summarize",
        "analyze",
        "feature",
        "system",
    )
    chat_tokens = (
        "打开对话",
        "打开聊天",
        "打开说话",
        "直接说话",
        "和你聊聊",
        "跟你聊聊",
        "想和你说话",
        "想跟你说话",
        "聊聊",
        "聊一会",
        "说句话",
        "chat with you",
        "talk to you",
        "talk to jiume",
        "open chat",
        "direct chat",
        "let's chat",
        "lets chat",
    )
    has_chat_task_context = any(
        token in lower or token in text or token.replace(" ", "") in compact_lower or token.replace(" ", "") in compact_text
        for token in chat_task_tokens
    )
    if not has_chat_task_context:
        for token in chat_tokens:
            compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact_lower if token.isascii() else compact_text
            if token in lower or token in text or compact_token in haystack:
                return "direct_chat"
    control_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("settings", ("打开设置", "轻量设置", "权限设置", "语气设置", "大小设置", "调一下设置", "配置jiume", "settings", "preferences")),
        ("skills", ("打开技能", "技能货架", "技能面板", "skill shelf", "skills panel", "show skills")),
        ("progress", ("看进度", "任务进度", "当前任务", "最近任务", "你在做什么", "现在在做什么", "show progress")),
        ("status", ("后台状态", "服务状态", "agent状态", "gateway状态", "连接状态", "健康状态", "service status")),
        ("clear_skill", ("取消当前skill", "取消当前 skill", "取消固定skill", "取消固定 skill", "不用这个skill", "不用这个 skill", "普通对话", "clear skill")),
    )
    for command, tokens in control_tokens:
        for token in tokens:
            compact_token = token.replace(" ", "")
            if token in lower or token in text or compact_token in compact_lower or compact_token in compact_text:
                return command
    login_command = _native_login_item_command(text)
    if login_command:
        return f"login_{login_command}"
    return None


def _native_login_item_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact = lower.replace(" ", "")
    status_tokens = (
        "登录启动状态",
        "登录项状态",
        "开机自启状态",
        "自启状态",
        "login item status",
        "startup status",
    )
    uninstall_tokens = (
        "关闭开机自启",
        "取消开机自启",
        "关闭登录启动",
        "取消登录启动",
        "不要登录启动",
        "不要开机启动",
        "uninstall login item",
        "disable login item",
        "disable startup",
    )
    install_tokens = (
        "登录后自动出现",
        "登录后自动打开",
        "开机自启",
        "开机启动",
        "登录启动",
        "装成登录项",
        "install login item",
        "enable login item",
        "start at login",
    )
    for command, tokens in (("status", status_tokens), ("uninstall", uninstall_tokens), ("install", install_tokens)):
        for token in tokens:
            needle = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact if token.isascii() else text.replace(" ", "")
            if token in lower or token in text or needle in haystack:
                return command
    return None


def _login_item_command_args(
    command: str,
    *,
    size: int,
    gateway_url: str = DEFAULT_GATEWAY_URL,
    agent_mode: str = DEFAULT_AGENT_MODE,
) -> list[str]:
    action = str(command or "").strip()
    flag_by_action = {
        "install": "--install-login-item",
        "uninstall": "--uninstall-login-item",
        "status": "--login-item-status",
    }
    flag = flag_by_action.get(action)
    if not flag:
        return []
    args = [sys.executable, "-m", "jiume.launcher", flag]
    if action != "install":
        return args
    args.extend(
        [
            "--size",
            str(max(1, int(size or DEFAULT_AVATAR_SIZE))),
            "--gateway-url",
            str(gateway_url or ""),
            "--agent-mode",
            str(agent_mode or DEFAULT_AGENT_MODE),
        ]
    )
    return args


def _native_help_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    excluded = (
        "后台状态",
        "服务状态",
        "agent状态",
        "gateway状态",
        "连接状态",
        "健康状态",
        "help me write",
        "help me draft",
        "help me summarize",
        "help me analyze",
        "help me review",
    )
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in excluded):
        return False
    exact_lower = compact_lower.strip("?.!。！？")
    if exact_lower in {"help", "whatcanyoudo", "howdoiuseyou", "howtouseyou"}:
        return True
    tokens = (
        "你会什么",
        "你能做什么",
        "你可以做什么",
        "你能帮我什么",
        "能帮我做什么",
        "怎么用你",
        "如何使用你",
        "使用说明",
        "新手引导",
        "能力说明",
        "功能说明",
        "what can you do",
        "how do i use you",
        "how to use you",
    )
    for token in tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return True
    return False


def _native_identity_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    context_tokens = ("状态", "心情", "进度", "后台", "service", "status", "mood", "progress")
    if any(token in lower or token in text for token in context_tokens):
        return False
    task_tokens = (
        "帮我",
        "写",
        "设计",
        "实现",
        "整理",
        "总结",
        "分析",
        "review",
        "write",
        "draft",
        "design",
        "build",
        "create",
        "summarize",
        "analyze",
    )
    if any(token in lower or token in text for token in task_tokens):
        return False
    exact = compact_lower.strip("?.!。！？,，")
    if exact in {
        "whoareyou",
        "whatareyou",
        "areyouapet",
        "areyouapet?",
        "jiume是什么",
        "你是谁",
        "你是什么",
        "你是宠物吗",
        "你是不是宠物",
        "你是pet吗",
        "你是codexpet吗",
    }:
        return True
    tokens = (
        "你是谁",
        "你是什么",
        "你是宠物吗",
        "你是不是宠物",
        "你不是宠物吧",
        "你是 pet 吗",
        "你是 codex pet 吗",
        "jiume 是什么",
        "jiume是什么",
        "who are you",
        "what are you",
        "are you a pet",
    )
    for token in tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return True
    return False


def _identity_summary(display_name: str = "") -> dict[str, Any]:
    name = _clip(str(display_name or "").strip() or "JiuMe", 18)
    detail = (
        f"我不是宠物，也不是网页面板；我是一直在桌面上的人形分身「{name}」，"
        "作为你的个人分身和背后 Agent 的主入口。你可以直接和我说话、调设置、装 skill、丢材料，"
        "需要执行时我会把任务交给 Agent。JiuMe 是这套桌面分身能力的名字。"
    )
    return {
        "label": f"我是{name}，你的桌面个人分身",
        "detail": detail,
        "badges": ["人形分身", "Agent 主入口", "常驻桌面"],
    }


def _help_summary() -> dict[str, Any]:
    entries = [str(item["label"]) for item in DIRECT_HELP_SECTIONS]
    return {
        "label": "直接跟我说就行",
        "detail": "我可以接任务、看材料、回答进度，也能按你的话切换 skill；设置从右键菜单打开。",
        "entries": entries,
        "examples": [
            "看一下屏幕，帮我总结",
            "用数据分析 skill",
            "把自己靠右一点",
            "陪我专注 25 分钟",
        ],
    }


def _attention_summary(active_skill: dict[str, Any] | None = None) -> dict[str, Any]:
    skill = _active_skill_snapshot(active_skill)
    if skill:
        detail = (
            f"我在，手里拿着「{_clip(skill['displayName'], 18)}」。"
            "点头像后直接补一句，我会接着处理。"
        )
        actions = ["补一句", "继续处理"]
    else:
        detail = "我在，就在桌面上。点头像后直接说一句，我会把它交给 Agent。"
        actions = ["说一句", "交给 Agent"]
    return {
        "label": "我在",
        "detail": detail,
        "actions": actions,
        "effect": "wave",
    }


def _direct_help_action_specs(section: str = "overview") -> list[dict[str, str]]:
    return [
        {"id": "talk", "label": "说一句"},
        {"id": "settings", "label": "设置"},
    ]


def _direct_play_action_specs(excluded_ids: set[str] | None = None) -> list[dict[str, str]]:
    excluded = {str(item or "").strip() for item in (excluded_ids or set()) if str(item or "").strip()}
    return [dict(item) for item in DIRECT_PLAY_ACTIONS if str(item.get("id") or "") not in excluded]


def _direct_unhandled_action_reply(surface: str = "") -> dict[str, str]:
    labels = {
        "help": "未知能力入口",
        "companion": "未知下一步",
        "activity": "未知任务入口",
        "skill_material": "未知材料入口",
    }
    label = labels.get(str(surface or "").strip(), "未知入口")
    return {
        "label": label,
        "line": "这个按钮我还没认出来。我先把对话放到你旁边，你直接说下一步，我会接住。",
        "state": "speaking",
    }


def _native_presence_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    excluded = ("后台状态", "服务状态", "agent状态", "gateway状态", "连接状态", "健康状态", "service status")
    if any(token in lower or token in text for token in excluded):
        return False
    tokens = (
        "你现在怎么样",
        "现在怎么样",
        "你状态怎么样",
        "状态怎么样",
        "心情怎么样",
        "你还好吗",
        "还好吗",
        "你醒着吗",
        "醒着吗",
        "你在吗",
        "在不在",
        "how are you",
        "are you there",
        "are you awake",
    )
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    for token in tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if compact_token in haystack:
            return True
    return False


def _native_memory_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    tokens = (
        "你记得什么",
        "还记得什么",
        "记得刚才",
        "刚才我们",
        "刚刚我们",
        "最近我们",
        "回忆一下",
        "总结刚才",
        "刚才做了什么",
        "最近做了什么",
        "what do you remember",
        "what did we do",
        "recap",
    )
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    for token in tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if compact_token in haystack:
            return True
    return False


def _native_clear_chat_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    excluded = (
        "长期记忆",
        "个人记忆",
        "记忆",
        "skill",
        "技能",
        "artifact",
        "产物",
        "result",
        "结果",
        "task",
        "任务",
        "feature",
        "功能",
        "ui",
        "界面",
        "系统",
        "设计",
        "实现",
        "开发",
        "写一个",
        "做一个",
        "build",
        "create",
    )
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in excluded):
        return False
    exact_compact = compact_lower.strip("?.!。！？")
    if exact_compact in {
        "newchat",
        "freshchat",
        "clearchat",
        "clearchathistory",
        "resetchat",
        "clearconversation",
        "resetconversation",
    }:
        return True
    chinese_patterns = (
        r"(?:清空|清除|清掉|删除|重置).{0,8}(?:对话|聊天|会话)",
        r"(?:重新开始|从头).{0,6}(?:聊|对话|聊天|会话)",
        r"(?:新|新的).{0,3}(?:对话|聊天|会话)",
    )
    for pattern in chinese_patterns:
        if re.search(pattern, compact_text):
            return True
    english_patterns = (
        r"\b(?:clear|reset|delete)\b.{0,20}\b(?:chat|conversation|thread)\b",
        r"\b(?:new|fresh)\b.{0,10}\b(?:chat|conversation|thread)\b",
        r"\bstart\b.{0,12}\b(?:new|fresh)\b.{0,10}\b(?:chat|conversation|thread)\b",
    )
    return any(re.search(pattern, lower) for pattern in english_patterns)


def _setting_memory_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip(" ：:，,。.;；")[:TWIN_MEMORY_CHAR_LIMIT]


def _native_profile_memory_command(message: str) -> dict[str, str] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    list_tokens = (
        "你长期记得什么",
        "你记住了什么",
        "长期记忆",
        "个人记忆",
        "long-term memory",
        "what do you remember about me",
    )
    for token in list_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"action": "list", "text": ""}

    forget_patterns = (
        r"^(?:忘记|别记|删除记忆|删掉记忆|移除记忆)\s*[:：]?\s*(.+)$",
        r"^(?:forget|remove memory|delete memory)\s+(.+)$",
    )
    for pattern in forget_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        item = _setting_memory_text(match.group(1))
        if item in {"全部", "所有", "所有长期记忆", "全部长期记忆"} or item.lower() in {"all", "everything", "all memories"}:
            return {"action": "clear", "text": ""}
        if item:
            return {"action": "forget", "text": item}

    add_patterns = (
        r"^(?:记住|记一下|帮我记住|请记住|以后记得)\s*[:：]?\s*(.+)$",
        r"^(?:remember that|remember|keep in mind that|keep in mind)\s+(.+)$",
    )
    for pattern in add_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        item = _setting_memory_text(match.group(1))
        if item:
            return {"action": "add", "text": item}
    return None


def _profile_memory_summary(memories: list[str]) -> dict[str, Any]:
    items = normalize_twin_memories(memories)
    if not items:
        return {
            "label": "还没有长期记忆",
            "detail": "你可以直接说“记住：我喜欢中文简洁回复”。",
            "hasMemory": False,
        }
    shown = "；".join(items[:3])
    if len(items) > 3:
        shown += f"；还有 {len(items) - 3} 条"
    return {"label": f"{len(items)} 条长期记忆", "detail": shown, "hasMemory": True}


def _apply_profile_memory_command(memories: list[str], command: dict[str, str]) -> tuple[list[str], str, bool]:
    items = normalize_twin_memories(memories)
    action = str(command.get("action") or "").strip()
    text = _setting_memory_text(str(command.get("text") or ""))
    if action == "add" and text:
        next_items = [item for item in items if item.casefold() != text.casefold()]
        next_items.insert(0, text)
        next_items = normalize_twin_memories(next_items[:MAX_TWIN_MEMORIES])
        return next_items, f"我记住了：{text}", True
    if action == "forget" and text:
        next_items = [item for item in items if text.casefold() not in item.casefold()]
        if len(next_items) == len(items):
            return items, f"我没有找到包含「{_clip(text, 36)}」的长期记忆。", False
        return next_items, f"好，我忘掉了和「{_clip(text, 36)}」相关的长期记忆。", True
    if action == "clear":
        if not items:
            return items, "现在还没有长期记忆。", False
        return [], "好，我清空了长期记忆。", True
    summary = _profile_memory_summary(items)
    return items, f"我长期记得：{summary['detail']}", False


def _focus_minutes_from_text(message: str, *, default: int = FOCUS_DEFAULT_MINUTES) -> int:
    text = str(message or "").strip()
    lower = text.lower()
    minutes = default
    if "半小时" in text or "half hour" in lower:
        minutes = 30
    elif "一小时" in text or "1小时" in text or "one hour" in lower or "1 hour" in lower:
        minutes = 60
    else:
        match = re.search(r"(\d{1,3})\s*(?:分钟|分|min|mins|minute|minutes|m\b)", lower)
        if match:
            minutes = int(match.group(1))
    return min(max(int(minutes or default), FOCUS_MIN_MINUTES), FOCUS_MAX_MINUTES)


def _native_focus_command(message: str) -> dict[str, int | str] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    stop_tokens = (
        "结束专注",
        "停止专注",
        "取消专注",
        "退出专注",
        "专注结束",
        "stop focus",
        "end focus",
        "cancel focus",
    )
    status_tokens = (
        "专注进度",
        "专注还剩",
        "还剩多久",
        "专注多久",
        "focus status",
        "focus progress",
        "time left",
    )
    start_tokens = (
        "陪我专注",
        "开始专注",
        "专注一下",
        "专注模式",
        "帮我进入专注",
        "开始番茄钟",
        "番茄钟",
        "focus session",
        "focus with me",
        "start focus",
        "pomodoro",
    )
    for token in stop_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"action": "stop", "minutes": 0}
    for token in status_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"action": "status", "minutes": 0}
    for token in start_tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return {"action": "start", "minutes": _focus_minutes_from_text(text)}
    return None


def _native_quick_action_command(message: str) -> dict[str, Any] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    excluded = (
        "打开技能",
        "技能货架",
        "技能面板",
        "取消当前 skill",
        "取消当前skill",
        "show skills",
        "skill shelf",
        "clear skill",
    )
    if any(token in lower or token in text for token in excluded):
        return None
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    action_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "focus",
            (
                "陪我专注",
                "开始专注",
                "专注一下",
                "专注模式",
                "帮我进入专注",
                "focus session",
                "focus with me",
            ),
        ),
        (
            "today",
            (
                "整理今天",
                "安排今天",
                "今天安排",
                "今日计划",
                "今天优先级",
                "帮我排今天",
                "triage today",
                "plan today",
            ),
        ),
        (
            "skill_picker",
            (
                "帮我选skill",
                "帮我选 skill",
                "选一个skill",
                "选一个 skill",
                "该用哪个skill",
                "该用哪个 skill",
                "推荐skill",
                "推荐 skill",
                "recommend skill",
                "pick a skill",
            ),
        ),
    )
    for action_id, tokens in action_tokens:
        for token in tokens:
            compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
            haystack = compact_lower if token.isascii() else compact_text
            if compact_token in haystack:
                return quick_action_by_id(action_id)
    return None


def _contains_setting_token(text: str, lower: str, tokens: tuple[str, ...]) -> bool:
    compact_text = text.replace(" ", "").replace("-", "").replace("_", "")
    compact_lower = lower.replace(" ", "").replace("-", "").replace("_", "")
    for token in tokens:
        haystack = compact_lower if token.isascii() else compact_text
        if token.isascii():
            needle = token.lower().replace(" ", "").replace("-", "").replace("_", "")
        else:
            needle = token.replace(" ", "")
        if needle in haystack:
            return True
    return False


def _setting_value_from_patterns(text: str, patterns: tuple[str, ...], *, limit: int = 32) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip()
        value = value.strip(" 「」『』“”\"'`：:,，。.;；、")
        value = re.split(r"[\n,，。.;；]", value, maxsplit=1)[0].strip()
        if 0 < len(value) <= limit:
            return value
    return ""


def _appearance_update_from_text(text: str, lower: str) -> dict[str, str] | None:
    context_tokens = (
        "外观",
        "衣服",
        "服装",
        "换衣服",
        "形象",
        "avatar",
        "appearance",
        "outfit",
        "clothes",
    )
    has_context = _contains_setting_token(text, lower, context_tokens)
    compact_text = text.replace(" ", "").replace("-", "").replace("_", "").lower()
    for preset_id, tokens in APPEARANCE_COMMAND_TOKENS:
        token_matched = _contains_setting_token(text, lower, tokens)
        token_compacts = {
            token.lower().replace(" ", "").replace("-", "").replace("_", "")
            for token in tokens
        }
        simple_color = compact_text in token_compacts
        if not token_matched or not (has_context or simple_color):
            continue
        preset = appearance_preset_by_id(preset_id)
        if preset:
            return preset
    return None


def _next_appearance_preset(current: Any) -> dict[str, str]:
    presets = appearance_presets()
    if not presets:
        return normalize_twin_appearance(current)
    current_id = normalize_twin_appearance(current)["id"]
    for index, preset in enumerate(presets):
        if preset["id"] == current_id:
            return dict(presets[(index + 1) % len(presets)])
    return dict(presets[0])


def _native_avatar_makeover_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    compact_lower = lower.replace(" ", "").replace("-", "").replace("_", "")
    compact_text = text.replace(" ", "").replace("-", "").replace("_", "")
    task_tokens = (
        "帮我画",
        "帮我生成",
        "帮我设计",
        "画一张",
        "生成一张",
        "设计一个",
        "draw an",
        "generate an image",
        "design an avatar",
    )
    if any(token in lower or token in text for token in task_tokens):
        return None
    next_tokens = (
        "换个样子",
        "换个造型",
        "换身衣服",
        "换套衣服",
        "换一套衣服",
        "衣服换一套",
        "换个衣服",
        "换个颜色",
        "换个外观",
        "change your outfit",
        "new outfit",
        "different look",
        "change your look",
    )
    for token in next_tokens:
        needle = token.lower().replace(" ", "").replace("-", "").replace("_", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if needle in haystack:
            return "next_appearance"
    return None


def _native_settings_update(message: str) -> dict[str, Any] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    explicit_tokens = (
        "设置",
        "权限",
        "模式",
        "默认",
        "语气",
        "口吻",
        "说话风格",
        "风格",
        "大小",
        "桌面大小",
        "外观",
        "衣服",
        "服装",
        "颜色",
        "换衣服",
        "头像",
        "分身",
        "名字",
        "名称",
        "改名",
        "叫你",
        "喊你",
        "用途",
        "定位",
        "职责",
        "permission",
        "mode",
        "default",
        "tone",
        "voice",
        "style",
        "size",
        "appearance",
        "outfit",
        "color",
        "avatar",
        "make yourself bigger",
        "make yourself smaller",
        "rename",
        "name you",
        "purpose",
        "role",
    )
    simple_commands = (
        "只聊天",
        "只读",
        "先起草",
        "行动前确认",
        "先确认",
        "自主执行",
        "自主",
        "温和点",
        "温柔点",
        "直接点",
        "清晰点",
        "变大一点",
        "大一点",
        "放大一点",
        "变小一点",
        "小一点",
        "缩小一点",
        "标准大小",
        "正常大小",
        "清爽蓝",
        "薄荷绿",
        "草莓粉",
        "葡萄紫",
        "暖阳黄",
        "极简黑",
        "chat only",
        "read only",
        "draft",
        "ask before acting",
        "autonomous",
        "warmer",
        "more direct",
        "clearer",
        "larger",
        "smaller",
        "blue",
        "green",
        "pink",
        "purple",
        "yellow",
        "black",
    )
    compact = text.replace(" ", "").replace("-", "").replace("_", "").lower()
    simple_set = {item.replace(" ", "").replace("-", "").replace("_", "").lower() for item in simple_commands}
    if not _contains_setting_token(text, lower, explicit_tokens) and compact not in simple_set:
        return None

    update: dict[str, Any] = {}
    permission_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("chat_only", ("只聊天", "只聊", "只陪聊", "chat_only", "chat only")),
        ("read_only", ("只读", "只读模式", "不要改文件", "别改文件", "不改文件", "read_only", "read only")),
        ("draft", ("先起草", "先写草稿", "草稿", "draft")),
        (
            "confirm_before_act",
            ("行动前确认", "执行前确认", "先确认", "需要确认", "改前确认", "confirm_before_act", "ask before acting", "confirm before"),
        ),
        ("autonomous", ("自主执行", "自动执行", "自主", "自动", "autonomous")),
    )
    for mode, tokens in permission_tokens:
        if _contains_setting_token(text, lower, tokens):
            update["defaultMode"] = mode
            break

    tone_patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("warm and concise", ("语气温和", "口吻温和", "温和点", "温柔点", "暖一点", "warmer", "warm tone")),
        ("direct and action-oriented", ("语气直接", "口吻直接", "直接点", "干脆点", "more direct", "direct tone")),
        ("clear, helpful, and work-focused", ("语气清晰", "口吻清晰", "清晰点", "工作化", "专业点", "clearer", "clear tone")),
    )
    for tone, tokens in tone_patterns:
        if _contains_setting_token(text, lower, tokens):
            update["tone"] = tone
            break

    size_patterns: tuple[tuple[int, tuple[str, ...]], ...] = (
        (96, ("变小", "小一点", "小号", "缩小", "smaller", "small size", "make yourself smaller")),
        (168, ("变大", "大一点", "大号", "放大", "larger", "large size", "make yourself bigger")),
        (DEFAULT_AVATAR_SIZE, ("标准大小", "正常大小", "中等大小", "标准", "normal size", "default size")),
    )
    for size, tokens in size_patterns:
        if _contains_setting_token(text, lower, tokens):
            update["size"] = size
            break

    appearance = _appearance_update_from_text(text, lower)
    if appearance:
        update["appearance"] = appearance

    display_name = _setting_value_from_patterns(
        text,
        (
            r"(?:名字|名称)\s*(?:改成|改为|设为|叫)\s*([^\n,，。.;；]+)",
            r"(?:改名为|改名叫|改名)\s*([^\n,，。.;；]+)",
            r"(?:以后|之后)?\s*(?:叫你|喊你)\s*([^\n,，。.;；]+)",
            r"(?:rename(?:\s+you)?\s+to|name\s+you|call\s+you)\s+([^\n,，。.;；]+)",
        ),
        limit=24,
    )
    if display_name:
        update["displayName"] = display_name

    purpose = _setting_value_from_patterns(
        text,
        (
            r"(?:用途|定位|职责)\s*(?:改成|改为|设为|是|变成)\s*([^\n,，。.;；]+)",
            r"(?:purpose|role)\s*(?:to|is|=)\s*([^\n,，。.;；]+)",
        ),
        limit=80,
    )
    if purpose:
        update["purpose"] = purpose

    return update or None


def _approval_reply_from_text(message: str) -> tuple[str, str] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    decision_tokens: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("reject", ("不同意", "不可以", "不行", "拒绝", "取消", "停止", "别继续", "不要继续", "否", "no", "reject", "deny", "cancel", "stop")),
        ("accept", ("可以继续", "同意继续", "同意", "可以", "继续", "确认", "允许", "批准", "好的", "好", "行", "yes", "ok", "okay", "accept", "approve", "allow", "continue", "go ahead")),
    )
    for decision, tokens in decision_tokens:
        for token in tokens:
            haystack = lower if token.isascii() else text
            needle = token.lower() if token.isascii() else token
            index = haystack.find(needle)
            if index < 0 or index > 4:
                continue
            feedback = text[index + len(token) :].strip()
            feedback = feedback.lstrip(" ，,。.;；:：、")
            for prefix in ("但是", "但", "不过", "并且", "而且", "因为", "原因是", "with ", "but ", "because "):
                if feedback.lower().startswith(prefix.lower()):
                    feedback = feedback[len(prefix) :].strip(" ，,。.;；:：、")
            return decision, feedback
    return None


def _task_runtime_command(message: str) -> tuple[str, str] | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    quiet_tokens = ("安静跑", "后台跑", "静默跑", "你先跑着", "先跑着", "quiet", "run quietly", "background")
    progress_tokens = ("看进度", "任务进度", "当前任务", "最近任务", "进度", "show progress")
    nudge_tokens = (
        "戳一下",
        "戳戳",
        "轻轻戳一下",
        "轻轻催一下",
        "催一下",
        "加把劲",
        "还在跑吗",
        "还在处理吗",
        "poke task",
        "tap task",
        "nudge task",
    )
    cancel_tokens = (
        "停止任务",
        "停下任务",
        "停一下",
        "停下来",
        "取消任务",
        "取消当前任务",
        "别继续了",
        "不要继续了",
        "先停",
        "stop task",
        "stop current task",
        "cancel task",
        "cancel current task",
        "abort task",
        "interrupt task",
    )
    note_prefixes = ("补一句", "补充一句", "补充", "追加一句", "追加", "提醒一下", "顺便", "note", "add note")
    if any(token in lower or token in text for token in cancel_tokens):
        return "cancel", ""
    if any(token in lower or token in text for token in nudge_tokens):
        return "nudge", ""
    if any(token in lower or token in text for token in quiet_tokens):
        return "quiet", ""
    if any(token in lower or token in text for token in progress_tokens):
        return "progress", ""
    for prefix in note_prefixes:
        haystack = lower if prefix.isascii() else text
        needle = prefix.lower() if prefix.isascii() else prefix
        if not haystack.startswith(needle):
            continue
        note = text[len(prefix) :].strip(" ：:，,。.;；")
        return "note", note
    return None


def _task_followup_message(note: str) -> str:
    detail = str(note or "").strip()
    if not detail:
        return ""
    return (
        "Additional instruction for the current running JiuMe task:\n"
        f"{detail}\n\n"
        "Apply this to the in-progress task if possible. If it conflicts with earlier instructions, ask me before acting."
    )


def _task_continuation_command(message: str) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    lower = text.lower()
    if lower in {"继续聊", "继续聊天", "聊聊", "continue chatting"}:
        return None
    prefixes = (
        "继续",
        "接着",
        "按刚才",
        "基于刚才",
        "用刚才",
        "就这个",
        "那就",
        "再来一版",
        "再短一点",
        "再长一点",
        "改成",
        "换成",
        "优化",
        "扩写",
        "缩短",
        "润色",
        "重试",
        "再试一次",
        "重新试",
        "重新来",
        "continue",
        "revise",
        "refine",
        "iterate",
        "make it",
        "retry",
        "try again",
        "rerun",
    )
    for prefix in prefixes:
        haystack = lower if prefix.isascii() else text
        needle = prefix.lower() if prefix.isascii() else prefix
        if not haystack.startswith(needle):
            continue
        note = text[len(prefix) :].strip(" ：:，,。.;；")
        return note or text
    return None


def _task_continuation_summary(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    summary = _direct_activity_summary(items)
    if not summary:
        return None
    kind = str(summary.get("kind") or "").strip()
    if kind not in WORK_HUD_TERMINAL_KINDS:
        return None
    return summary


def _task_continuation_message(note: str, summary: dict[str, Any]) -> str:
    detail = str(note or "").strip()
    if not detail:
        return ""
    title = str(summary.get("title") or "recent JiuMe task").strip()
    task_detail = str(summary.get("detail") or "").strip()
    stage = str(summary.get("stage") or "").strip()
    artifacts = summary.get("artifacts")
    artifact_lines: list[str] = []
    if isinstance(artifacts, list):
        for artifact in artifacts[:3]:
            if not isinstance(artifact, dict):
                continue
            label = str(artifact.get("label") or artifact.get("target") or "artifact").strip()
            target = str(artifact.get("target") or "").strip()
            if target:
                artifact_lines.append(f"- {label}: {target}")
            else:
                artifact_lines.append(f"- {label}")
    artifact_block = "\n".join(artifact_lines) if artifact_lines else "- None"
    task_line = f"Recent task: {title}"
    if stage:
        task_line = f"{task_line} ({stage})"
    return (
        "Continue from the latest JiuMe task instead of treating this as unrelated chat.\n"
        f"{task_line}\n"
        f"Recent task detail: {task_detail or 'None'}\n"
        f"Recent artifacts:\n{artifact_block}\n\n"
        f"User continuation: {detail}"
    )


def _message_with_material_instruction(message: str, instruction: str) -> str:
    body = str(message or "").strip()
    extra = str(instruction or "").strip()
    if not body or not extra:
        return body
    return f"{body}\n\n用户补充：{extra}"


def _chat_role_label(role: str, *, assistant_name: str = "") -> str:
    if role == "user":
        return "你"
    name = str(assistant_name or "").strip() or "JiuMe"
    return _clip(name, 18)


def _conversation_reaction(text: str, *, role: str = "assistant", state: str = "") -> dict[str, str]:
    if str(role or "") != "assistant":
        return {"label": "", "effect": ""}
    body = str(text or "").strip()
    if not body:
        return {"label": "", "effect": ""}
    lower = body.lower()
    compact = lower.replace(" ", "")
    key = str(state or "").strip()
    if key == "sleep":
        return {"label": "安静休息", "effect": ""}
    if key == "error" or any(token in lower or token in body for token in ("失败", "错误", "出错", "找不到", "打不开", "failed", "error")):
        return {"label": "皱眉检查", "effect": "peek"}
    if key == "waiting_approval" or any(token in lower or token in body for token in ("确认", "同意", "拒绝", "approve", "confirm")):
        return {"label": "等你点头", "effect": "nod"}
    if key == "success" or any(token in lower or token in body for token in ("完成", "好了", "已", "done", "finished", "success")):
        return {"label": "开心收尾", "effect": "cheer"}
    if any(token in lower or token in body for token in ("屏幕", "剪贴板", "文件", "材料", "skill", "技能", "clipboard", "file", "screen")):
        return {"label": "接住材料", "effect": "peek"}
    if any(token in lower or token in body for token in ("我想", "正在", "处理", "分析", "整理", "thinking", "processing")):
        return {"label": "认真思考", "effect": "peek"}
    if "?" in compact or "？" in body or any(token in lower or token in body for token in ("吗", "怎么", "如何", "what", "how", "why")):
        return {"label": "认真听着", "effect": "nod"}
    return {"label": "轻轻点头", "effect": "nod"}


def _chat_heading(role: str, text: str, *, assistant_name: str = "") -> str:
    label = _chat_role_label(role, assistant_name=assistant_name)
    reaction = _conversation_reaction(text, role=role)
    reaction_label = str(reaction.get("label") or "")
    if reaction_label:
        return f"{label} · {reaction_label}"
    return label


def _conversation_normalized_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in items:
        role = "user" if str(item.get("role") or "") == "user" else "assistant"
        text = _clip(str(item.get("text") or ""), 96)
        if text:
            normalized.append({"role": role, "text": text})
    return normalized


def _conversation_max_scroll_offset(items: list[dict[str, str]], limit: int = DIRECT_CHAT_PREVIEW_LIMIT) -> int:
    window_size = max(1, int(limit or DIRECT_CHAT_PREVIEW_LIMIT))
    return max(0, len(_conversation_normalized_items(items)) - window_size)


def _conversation_preview_items(
    items: list[dict[str, str]],
    limit: int = DIRECT_CHAT_PREVIEW_LIMIT,
    *,
    offset: int = 0,
) -> list[dict[str, str]]:
    normalized = _conversation_normalized_items(items)
    window_size = max(1, int(limit or DIRECT_CHAT_PREVIEW_LIMIT))
    try:
        scroll_offset = int(offset or 0)
    except (TypeError, ValueError):
        scroll_offset = 0
    scroll_offset = max(0, min(scroll_offset, max(0, len(normalized) - window_size)))
    end = max(0, len(normalized) - scroll_offset)
    start = max(0, end - window_size)
    return normalized[start:end]


def _direct_skill_shortcuts(
    skills: list[dict[str, Any]],
    *,
    limit: int = DIRECT_SKILL_SHORTCUT_LIMIT,
) -> list[dict[str, Any]]:
    shortcuts: list[dict[str, Any]] = []
    for skill in skills:
        if len(shortcuts) >= max(1, limit):
            break
        skill_id = str(skill.get("id") or "").strip()
        if not skill_id:
            continue
        name = str(skill.get("displayName") or skill_id).strip()
        shortcuts.append(
            {
                "id": skill_id,
                "displayName": _clip(name, 18),
                "isEnabled": bool(skill.get("isEnabled")),
                "risk": str(skill.get("risk") or "unknown"),
            }
        )
    return shortcuts


def _skill_picker_suggestions(
    skills: list[dict[str, Any]],
    *,
    limit: int = DIRECT_SKILL_SHORTCUT_LIMIT,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for skill in skills:
        if len(suggestions) >= max(1, limit):
            break
        skill_id = str(skill.get("id") or "").strip()
        if not skill_id:
            continue
        name = str(skill.get("displayName") or skill.get("name") or skill_id).strip()
        summary = str(skill.get("summary") or "适合交给 JiuMe 处理这类任务。").strip()
        suggestions.append(
            {
                "id": skill_id,
                "displayName": _clip(name, 18),
                "summary": _clip(summary, 62),
                "risk": str(skill.get("risk") or "unknown"),
                "isEnabled": bool(skill.get("isEnabled")),
            }
        )
    return suggestions


def _skill_picker_reply(suggestions: list[dict[str, Any]]) -> dict[str, str]:
    if not suggestions:
        return {
            "label": "我先问清任务",
            "detail": "你告诉我要处理什么，我会在头像旁帮你挑合适的 skill，再把材料接过去。",
        }
    names = "、".join(str(item.get("displayName") or item.get("id") or "skill") for item in suggestions[:3])
    enabled_count = sum(1 for item in suggestions if bool(item.get("isEnabled")))
    prefix = "已装好的我会优先递给你。" if enabled_count else "这些还没固定，点一下我会先装载。"
    return {
        "label": "skill 入口已打开",
        "detail": (
            f"我先把 skill 入口放在头像旁；推荐里会有：{names}。{prefix}"
            "点「展开 skill」再看推荐、当前和更多；也可以直接说任务。"
        ),
    }


def _direct_skill_overflow_count(
    skills: list[dict[str, Any]],
    *,
    limit: int = DIRECT_SKILL_SHORTCUT_LIMIT,
) -> int:
    available = sum(1 for skill in skills if str(skill.get("id") or "").strip())
    return max(0, available - max(1, limit))


def _active_skill_material_action_specs() -> list[dict[str, str]]:
    return [
        {"id": "screen", "label": "看屏幕"},
        {"id": "clipboard", "label": "贴材料"},
        {"id": "file", "label": "选文件"},
    ]


def _direct_quick_action_shortcuts(
    actions: list[dict[str, Any]],
    *,
    limit: int = DIRECT_QUICK_ACTION_LIMIT,
) -> list[dict[str, Any]]:
    shortcuts: list[dict[str, Any]] = []
    for action in actions:
        if len(shortcuts) >= limit:
            break
        if str(action.get("kind") or "") != "agent":
            continue
        action_id = str(action.get("id") or "").strip()
        label = str(action.get("label") or action.get("title") or action_id).strip()
        if not action_id or not label:
            continue
        shortcuts.append(
            {
                "id": action_id,
                "label": _clip(label, 10),
                "title": _clip(str(action.get("title") or label), 18),
                "state": str(action.get("state") or "thinking"),
            }
        )
    return shortcuts


def _clipboard_candidate_lines(raw: str) -> list[str]:
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return [line.strip() for line in text.split("\n") if line.strip()]


def _clipboard_path_candidate(line: str) -> Path | None:
    text = str(line or "").strip().strip("\"'")
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1].strip()
    if not text:
        return None

    parsed = urlparse(text)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).expanduser()
    if parsed.scheme:
        return None
    if not (text.startswith("/") or text.startswith("~")):
        return None
    return Path(unquote(text)).expanduser()


def _clipboard_file_targets(
    raw: str,
    *,
    path_exists: Callable[[Path], bool] | None = None,
    limit: int = CLIPBOARD_MATERIAL_FILE_LIMIT,
) -> list[str]:
    lines = _clipboard_candidate_lines(raw)
    if not lines:
        return []

    exists = path_exists or (lambda path: path.exists())
    targets: list[str] = []
    for line in lines:
        path = _clipboard_path_candidate(line)
        if path is None:
            return []
        try:
            if not exists(path):
                return []
            resolved = path.resolve()
        except OSError:
            return []
        if len(targets) < limit:
            targets.append(str(resolved))
    return targets


def _clipboard_text_preview(text: str, *, limit: int = CLIPBOARD_MATERIAL_CHAR_LIMIT) -> tuple[str, bool]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) <= limit:
        return normalized, False
    return f"{normalized[: max(0, limit - 1)].rstrip()}…", True


def _clipboard_material_payload(
    raw: str,
    *,
    path_exists: Callable[[Path], bool] | None = None,
) -> dict[str, str] | None:
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None

    lines = _clipboard_candidate_lines(text)
    file_targets = _clipboard_file_targets(text, path_exists=path_exists)
    if file_targets:
        hidden_count = max(0, len(lines) - len(file_targets))
        names = [_clip(Path(target).name or target, 22) for target in file_targets[:3]]
        detail = ", ".join(names) if names else "剪贴板文件"
        if len(file_targets) > 3:
            detail = f"{detail} 等 {len(file_targets)} 个"
        if hidden_count:
            detail = f"{detail}，另有 {hidden_count} 个路径"
        listed = "\n".join(f"- {target}" for target in file_targets)
        if hidden_count:
            listed = f"{listed}\n- ... 还有 {hidden_count} 个剪贴板路径"
        return {
            "kind": "files",
            "title": f"剪贴板材料：{len(file_targets)} 个文件/路径",
            "detail": _clip(detail, 86),
            "message": f"请处理我从剪贴板交给你的文件或路径：\n{listed}",
        }

    preview, truncated = _clipboard_text_preview(text)
    first_line = next((line for line in preview.split("\n") if line.strip()), "剪贴板文本")
    suffix = f"\n\n[剪贴板原文较长，JiuMe 先发送前 {CLIPBOARD_MATERIAL_CHAR_LIMIT} 字。]" if truncated else ""
    return {
        "kind": "text",
        "title": "剪贴板材料（已截取）" if truncated else "剪贴板材料",
        "detail": _clip(first_line, 86),
        "message": f"请处理我从剪贴板交给你的材料：\n\n{preview}{suffix}",
    }


def _file_artifact_category(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}:
        return "image"
    if suffix in {".csv", ".tsv", ".xlsx", ".xls", ".numbers"}:
        return "table"
    if suffix in {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".swift",
        ".kt",
        ".rb",
        ".sh",
        ".sql",
        ".css",
        ".html",
    }:
        return "code"
    if suffix in {".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".toml", ".xml", ".rtf", ".log"}:
        return "text"
    return "file"


def _file_material_payload(
    paths: list[str | Path] | tuple[str | Path, ...],
    *,
    path_exists: Callable[[Path], bool] | None = None,
    limit: int = FILE_MATERIAL_LIMIT,
) -> dict[str, Any] | None:
    exists = path_exists or (lambda path: path.exists())
    targets: list[Path] = []
    for raw_path in paths:
        if len(targets) >= max(1, limit):
            break
        path = Path(str(raw_path or "").strip()).expanduser()
        if not str(path):
            continue
        try:
            if not exists(path):
                continue
            targets.append(path.resolve())
        except OSError:
            continue
    if not targets:
        return None

    names = [_clip(path.name or str(path), 22) for path in targets[:3]]
    detail = ", ".join(names)
    if len(targets) > 3:
        detail = f"{detail} 等 {len(targets)} 个"
    listed = "\n".join(f"- {path}" for path in targets)
    artifacts = [
        {
            "label": path.name or "文件",
            "target": str(path),
            "kind": "file",
            "category": _file_artifact_category(path),
        }
        for path in targets
    ]
    return {
        "kind": "files",
        "title": f"文件材料：{len(targets)} 个文件",
        "detail": _clip(detail or "本地文件", 86),
        "message": f"请处理我刚从桌面交给你的本地文件：\n{listed}",
        "artifacts": artifacts,
    }


def _direct_path_material_payload(
    raw: str,
    *,
    path_exists: Callable[[Path], bool] | None = None,
) -> dict[str, Any] | None:
    file_targets = _clipboard_file_targets(raw, path_exists=path_exists, limit=FILE_MATERIAL_LIMIT)
    if not file_targets:
        return None

    payload = _file_material_payload(file_targets, path_exists=path_exists, limit=FILE_MATERIAL_LIMIT)
    if not payload:
        return None

    payload = dict(payload)
    artifacts = [item for item in payload.get("artifacts", []) if isinstance(item, dict)]
    count = len(artifacts) or len(file_targets)
    listed = "\n".join(f"- {target}" for target in file_targets[:count])
    payload["title"] = f"路径材料：{count} 个文件"
    payload["message"] = f"请处理我直接在对话里交给你的本地文件路径：\n{listed}"
    return payload


def _screen_capture_path(root: Path, *, timestamp: str | None = None) -> Path:
    stamp = str(timestamp or time.strftime("%Y%m%d-%H%M%S")).strip() or "screen"
    safe_stamp = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in stamp)
    return Path(root) / "screen_context" / f"screen-{safe_stamp}.png"


def _screen_material_payload(path: Path) -> dict[str, Any]:
    target = str(Path(path).expanduser())
    name = Path(target).name or "screen.png"
    return {
        "kind": "screen",
        "title": "屏幕材料",
        "detail": name,
        "message": f"请根据这张当前桌面截图协助我。截图路径：\n- {target}",
        "artifact": {
            "label": "当前屏幕截图",
            "target": target,
            "kind": "file",
            "category": "image",
            "mime": "image/png",
        },
    }


def _permission_mode_label(value: str) -> str:
    mode = normalize_permission_mode(value)
    labels = {
        "chat_only": "只聊天",
        "read_only": "只读",
        "draft": "先起草",
        "confirm_before_act": "行动前确认",
        "autonomous": "自主执行",
    }
    return labels.get(mode, "行动前确认")


def _tone_label(value: str) -> str:
    tone = str(value or "").strip()
    for label, preset in DIRECT_TONE_PRESETS:
        if tone == preset:
            return label
    return _clip(tone or DIRECT_TONE_PRESETS[0][1], 18)


def _direct_settings_snapshot(twin: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(twin, dict):
        appearance = normalize_twin_appearance({})
        return {
            "displayName": "JiuMe",
            "purpose": "",
            "tone": DIRECT_TONE_PRESETS[0][1],
            "defaultMode": "confirm_before_act",
            "defaultModeLabel": "行动前确认",
            "appearanceId": appearance["id"],
            "appearanceLabel": appearance["label"],
            "appearanceColor": appearance["outfitColor"],
        }
    permissions = twin.get("permissions") if isinstance(twin.get("permissions"), dict) else {}
    mode = normalize_permission_mode(permissions.get("defaultMode"))
    tone = str(twin.get("tone") or DIRECT_TONE_PRESETS[0][1]).strip() or DIRECT_TONE_PRESETS[0][1]
    appearance = normalize_twin_appearance(twin.get("appearance"))
    return {
        "displayName": str(twin.get("displayName") or "JiuMe"),
        "purpose": str(twin.get("purpose") or ""),
        "tone": tone,
        "defaultMode": mode,
        "defaultModeLabel": _permission_mode_label(mode),
        "appearanceId": appearance["id"],
        "appearanceLabel": appearance["label"],
        "appearanceColor": appearance["outfitColor"],
    }


def _direct_settings_payload(
    tone: str,
    default_mode: str,
    *,
    display_name: str = "",
    purpose: str = "",
    appearance: Any = None,
) -> dict[str, Any]:
    name = str(display_name or "").strip() or "JiuMe"
    return {
        "displayName": name,
        "purpose": str(purpose or "").strip(),
        "tone": str(tone or DIRECT_TONE_PRESETS[0][1]).strip() or DIRECT_TONE_PRESETS[0][1],
        "appearance": normalize_twin_appearance(appearance),
        "permissions": {"defaultMode": normalize_permission_mode(default_mode)},
    }


def _settings_summary(twin: dict[str, Any] | None, *, size: int = DEFAULT_AVATAR_SIZE) -> dict[str, str]:
    snapshot = _direct_settings_snapshot(twin)
    name = _clip(snapshot["displayName"], 18)
    purpose = _clip(snapshot["purpose"] or "你的桌面个人分身助手", 34)
    tone = _tone_label(snapshot["tone"])
    detail = (
        f"我叫「{name}」，定位是「{purpose}」。"
        f"我会用「{snapshot['defaultModeLabel']}」权限、"
        f"「{tone}」语气和「{snapshot['appearanceLabel']}」外观配合你，"
        f"桌面大小是「{_avatar_size_label(size)}」。"
    )
    return {
        "label": f"{name}的配合方式",
        "detail": _clip(detail, 150),
        "mode": snapshot["defaultMode"],
        "appearance": snapshot["appearanceLabel"],
        "tone": tone,
    }


def _native_settings_query_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    task_tokens = (
        "帮我",
        "写",
        "设计",
        "实现",
        "整理",
        "总结",
        "分析",
        "review",
        "write",
        "draft",
        "design",
        "build",
        "create",
        "summarize",
        "analyze",
    )
    if any(token in lower or token in text for token in task_tokens):
        return False
    excluded = ("打开设置", "调一下设置", "配置jiume", "settings panel", "open settings")
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    if any(token in lower or token in text or token.replace(" ", "") in compact_lower for token in excluded):
        return False
    exact = compact_lower.strip("?.!。！？,，")
    if exact in {"当前设置", "你的设置", "分身设置", "currentsettings", "yoursettings", "whatsettings"}:
        return True
    tokens = (
        "当前设置",
        "你的设置",
        "你现在的设置",
        "分身设置是什么",
        "你怎么配合我",
        "你会怎么配合我",
        "怎么配合我",
        "你现在怎么配合我",
        "current settings",
        "your settings",
        "what are your current settings",
        "what are your settings",
        "how are you configured",
        "how will you work with me",
    )
    for token in tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return True
    return False


def _native_onboarding_prompt(twin: dict[str, Any] | None) -> dict[str, str]:
    snapshot = _direct_settings_snapshot(twin)
    name = _clip(snapshot["displayName"], 18)
    return {
        "label": "先完成原生配置窗口",
        "detail": (
            f"我先叫「{name}」。先导入 Codex pet 包，点“启用”后我才会常驻桌面。"
            "之后桌面只保留头像；单击和我说话，右键打开设置或退出。"
        ),
    }


def _direct_activity_summary(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    fallback: dict[str, Any] | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        title = _clip(str(item.get("title") or "最近任务"), 42)
        detail = _clip(str(item.get("detail") or ""), 86)
        artifacts = item.get("artifacts")
        artifact_items = (
            [dict(artifact) for artifact in artifacts[:2] if isinstance(artifact, dict)]
            if isinstance(artifacts, list)
            else []
        )
        summary = {
            "kind": kind,
            "stage": _activity_stage_label(kind),
            "title": title,
            "detail": detail,
            "time": str(item.get("time") or ""),
            "artifacts": artifact_items,
        }
        if kind == "interaction":
            fallback = fallback or summary
            continue
        return summary
    return fallback


def _direct_activity_action_specs(
    summary: dict[str, Any] | None,
    *,
    has_artifact_tray: bool = False,
    expanded: bool = False,
) -> list[dict[str, str]]:
    if not isinstance(summary, dict):
        return []
    kind = str(summary.get("kind") or "").strip()
    artifacts = summary.get("artifacts")
    has_artifacts = bool(
        has_artifact_tray or (isinstance(artifacts, list) and artifacts)
    )
    if kind == "approval":
        actions = [
            {"id": "approval_accept", "label": "同意", "style": "primary"},
            {"id": "approval_reject", "label": "拒绝", "style": "secondary"},
            {"id": "chat", "label": "补限制", "style": "secondary"},
        ]
        if expanded:
            actions.append({"id": "cheer", "label": "打气", "style": "secondary"})
            actions.append({"id": "less", "label": "收起", "style": "secondary"})
        else:
            actions.append({"id": "more", "label": "更多", "style": "secondary"})
        return actions
    if kind in {"user", "quick", "accepted", "processing", "subtask", "tool"}:
        if not expanded:
            return [
                {"id": "chat", "label": "补一句", "style": "primary"},
                {"id": "progress", "label": "进度", "style": "secondary"},
                {"id": "more", "label": "更多", "style": "secondary"},
            ]
        return [
            {"id": "chat", "label": "补一句", "style": "primary"},
            {"id": "progress", "label": "进度", "style": "secondary"},
            {"id": "nudge", "label": "戳戳", "style": "secondary"},
            {"id": "quiet", "label": "安静", "style": "secondary"},
            {"id": "cancel", "label": "停止", "style": "secondary"},
            {"id": "cheer", "label": "打气", "style": "secondary"},
            {"id": "less", "label": "收起", "style": "secondary"},
        ]
    if kind in {"artifact", "final"}:
        if has_artifacts:
            primary = {"id": "artifacts", "label": "产物列表", "style": "primary"}
        else:
            primary = {"id": "progress", "label": "查看", "style": "primary"}
        return [
            primary,
            {"id": "chat", "label": "继续聊", "style": "secondary"},
        ]
    if kind == "error":
        return [
            {"id": "progress", "label": "查看", "style": "primary"},
            {"id": "retry", "label": "重试", "style": "secondary"},
            {"id": "chat", "label": "补充", "style": "secondary"},
        ]
    return [
        {"id": "chat", "label": "继续聊", "style": "primary"},
        {"id": "progress", "label": "进度", "style": "secondary"},
    ]


def _task_progress_reply(
    summary: dict[str, Any] | None,
    *,
    has_artifact_tray: bool = False,
) -> dict[str, str]:
    if not isinstance(summary, dict):
        return {
            "title": "现在没有任务进度",
            "detail": "我现在没有正在接手的任务。你可以直接把任务、屏幕、剪贴板或文件交给我。",
            "state": "speaking",
            "effect": "nod",
        }

    kind = str(summary.get("kind") or "").strip()
    title = _clip(str(summary.get("title") or "最近任务"), 38)
    detail = _clip(str(summary.get("detail") or ""), 76)
    stage = str(summary.get("stage") or _activity_stage_label(kind) or "").strip()
    stage_label = stage or "处理"
    state = _work_hud_state_for_activity(kind) or "speaking"
    if kind == "approval":
        line = f"我停在「{stage_label}」：{title}。"
    elif kind in {"user", "quick", "accepted", "processing", "subtask", "tool"}:
        line = f"我正在「{stage_label}」：{title}。"
    elif kind in {"artifact", "final"}:
        line = f"我刚刚「{stage_label}」：{title}。"
    elif kind == "error":
        line = f"我在「{stage_label}」这里卡住了：{title}。"
    elif kind == "interrupt":
        line = f"我正在「{stage_label}」：{title}。"
    else:
        line = f"最近任务是「{title}」，阶段是「{stage_label}」。"

    if detail:
        line += f" 刚刚这一步是：{detail}。"

    artifacts = summary.get("artifacts")
    artifact_labels = [
        _clip(str(item.get("label") or item.get("target") or "产物"), 18)
        for item in artifacts
        if isinstance(item, dict)
    ] if isinstance(artifacts, list) else []
    if artifact_labels:
        line += f" 我手边已有产物：{'、'.join(artifact_labels[:2])}。"
    elif has_artifact_tray:
        line += " 最近产物托盘里有可查看的结果。"

    actions = _direct_activity_action_specs(summary, has_artifact_tray=has_artifact_tray)
    action_labels = [str(item.get("label") or "") for item in actions[:3] if item.get("label")]
    if action_labels:
        line += f" 你可以直接点：{'、'.join(action_labels)}。"

    return {
        "title": f"任务进度 · {stage_label}",
        "detail": _clip(line, 220),
        "state": state,
        "effect": _activity_effect_for_kind(kind) or ("nod" if state == "speaking" else "peek"),
    }


def _task_nudge_reply(summary: dict[str, Any] | None = None) -> dict[str, str]:
    item = summary if isinstance(summary, dict) else {}
    title = _clip(str(item.get("title") or "当前任务"), 34)
    detail = _clip(str(item.get("detail") or ""), 54)
    if detail:
        line = f"我在，正盯着「{title}」。刚刚这一步是：{detail}"
    else:
        line = f"我在，正盯着「{title}」。我会继续往前推，有需要确认时会叫你。"
    return {
        "title": "轻轻戳一下",
        "detail": _clip(line, 118),
        "state": "working",
        "effect": "peek",
    }


def _direct_companion_suggestion_specs(
    *,
    presence: dict[str, Any] | None = None,
    activity_summary: dict[str, Any] | None = None,
    active_skill: dict[str, Any] | None = None,
    has_artifact_tray: bool = False,
) -> list[dict[str, str]]:
    mood = str(presence.get("mood") or "") if isinstance(presence, dict) else ""
    kind = str(activity_summary.get("kind") or "") if isinstance(activity_summary, dict) else ""
    if kind == "approval" or mood == "waiting_approval":
        return [
            {"id": "approval_accept", "label": "同意继续", "style": "primary"},
            {"id": "approval_reject", "label": "拒绝说明", "style": "secondary"},
            {"id": "chat", "label": "补限制", "style": "secondary"},
        ]
    if kind in {"user", "quick", "accepted", "processing", "subtask", "tool"} or mood in {"thinking", "working"}:
        return [
            {"id": "chat", "label": "补一句", "style": "primary"},
            {"id": "quiet", "label": "安静跑", "style": "secondary"},
        ]
    if kind in {"artifact", "final"} or mood == "success":
        if has_artifact_tray:
            return [
                {"id": "artifacts", "label": "查看", "style": "primary"},
                {"id": "chat", "label": "继续说", "style": "secondary"},
            ]
        return [
            {"id": "chat", "label": "继续说", "style": "primary"},
        ]
    if kind == "error" or mood == "error":
        return [
            {"id": "chat", "label": "补一句", "style": "primary"},
            {"id": "retry", "label": "重试", "style": "secondary"},
        ]
    if _active_skill_snapshot(active_skill):
        return [
            {"id": "chat", "label": "补一句", "style": "primary"},
            {"id": "settings", "label": "设置", "style": "secondary"},
        ]
    if mood == "sleep":
        return [
            {"id": "wake", "label": "叫醒", "style": "primary"},
            {"id": "settings", "label": "设置", "style": "secondary"},
        ]
    return [
        {"id": "chat", "label": "说一句", "style": "primary"},
        {"id": "settings", "label": "设置", "style": "secondary"},
    ]


def _native_companion_plan_command(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    lower = text.lower()
    task_tokens = (
        "帮我",
        "整理",
        "安排",
        "写",
        "做",
        "生成",
        "分析",
        "总结",
        "review",
        "write",
        "draft",
        "build",
        "create",
        "summarize",
        "analyze",
        "plan today",
        "triage today",
    )
    if any(token in lower or token in text for token in task_tokens):
        return False
    compact_lower = lower.replace(" ", "")
    compact_text = text.replace(" ", "")
    exact = compact_lower.strip("?.!。！？,，")
    if exact in {"陪伴计划", "陪我计划", "companionplan"}:
        return True
    tokens = (
        "今天怎么陪我",
        "你今天怎么陪我",
        "接下来怎么陪我",
        "下一步怎么陪我",
        "你会怎么陪我",
        "你接下来怎么陪我",
        "陪伴计划",
        "陪我计划",
        "how will you stay with me",
        "how will you accompany me",
        "companion plan",
    )
    for token in tokens:
        compact_token = token.lower().replace(" ", "") if token.isascii() else token.replace(" ", "")
        haystack = compact_lower if token.isascii() else compact_text
        if token in lower or token in text or compact_token in haystack:
            return True
    return False


def _native_agent_conversation_query(message: str, *, names: Any = None) -> bool:
    return any(
        (
            _native_settings_query_command(message),
            _native_attention_command(message, names=names),
            _native_identity_command(message),
            _native_help_command(message),
            _native_presence_command(message),
            _native_memory_command(message),
            _native_companion_plan_command(message),
            _native_active_skill_query_command(message),
        )
    )


def _companion_plan_summary(
    *,
    presence: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    suggestions: list[dict[str, str]] | None = None,
    active_skill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = presence if isinstance(presence, dict) else {}
    remembered = memory if isinstance(memory, dict) else {}
    mood = str(current.get("mood") or "idle")
    presence_label = str(current.get("label") or "在桌面待命")
    memory_label = str(remembered.get("label") or "刚开始认识")
    action_labels = [
        str(item.get("label") or "").strip()
        for item in (suggestions or [])
        if isinstance(item, dict)
        and str(item.get("label") or "").strip()
        and daily_label_is_allowed(str(item.get("label") or ""))
    ][:3]
    if not action_labels:
        action_labels = ["直接说话", "补一句", "设置"]

    skill = _active_skill_snapshot(active_skill)
    if mood in {"thinking", "working"}:
        plan = "我先守住当前任务，你可以补一句，或让我安静跑完。"
    elif mood == "waiting_approval":
        plan = "我会先等你确认，不会擅自继续；你可以同意、拒绝，或补一句限制。"
    elif skill:
        plan = f"我会先按「{_clip(skill['displayName'], 18)}」理解你的下一句话；需要更多上下文时会问你。"
    elif mood == "success":
        plan = "我会先把刚完成的结果收好，你可以继续说要改哪里。"
    elif mood == "sleep":
        plan = "我先安静待机；你单击我或叫我回来，我就继续接住对话。"
    else:
        plan = "我会安静待命，先接住一件小事；点头像说一句就能开始。"

    detail = (
        f"现在我是「{presence_label}」，刚刚记得「{memory_label}」。"
        f"{plan} 现在最顺手的入口是：{' / '.join(action_labels)}。"
    )
    return {
        "label": "今天我这样陪你",
        "detail": _clip(detail, 180),
        "actions": action_labels,
        "mood": mood,
    }


def _activity_artifact_cards(
    items: list[dict[str, Any]],
    *,
    category: str = "",
    limit: int = ARTIFACT_TRAY_LIMIT,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    target_category = str(category or "").strip()
    max_items = max(1, int(limit or ARTIFACT_TRAY_LIMIT))
    for item in items:
        if not isinstance(item, dict):
            continue
        artifacts = item.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_category = str(artifact.get("category") or "file")
            if target_category and artifact_category != target_category:
                continue
            label = str(artifact.get("label") or artifact.get("target") or artifact.get("preview") or "").strip()
            if not label:
                continue
            cards.append(
                {
                    "label": _clip(label, 40),
                    "category": artifact_category,
                    "kind": str(artifact.get("kind") or ""),
                    "target": str(artifact.get("target") or ""),
                    "preview": str(artifact.get("preview") or ""),
                    "mime": str(artifact.get("mime") or ""),
                    "activityTitle": _clip(str(item.get("title") or "最近任务"), 36),
                    "activityTime": str(item.get("time") or ""),
                    "artifact": dict(artifact),
                }
            )
            if len(cards) >= max_items:
                return cards
    return cards


def _geometry_offset(value: int) -> str:
    return f"+{value}"


def _window_position_geometry(x: int, y: int) -> str:
    return f"{_geometry_offset(x)}{_geometry_offset(y)}"


def _normalize_avatar_size(value: Any, *, default: int = DEFAULT_AVATAR_SIZE) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = default
    return min(max(size, AVATAR_SIZE_MIN), AVATAR_SIZE_MAX)


def _avatar_size_from_state(default_size: int, saved: dict[str, Any] | None = None) -> int:
    saved = saved if isinstance(saved, dict) else {}
    if int(default_size or DEFAULT_AVATAR_SIZE) == DEFAULT_AVATAR_SIZE and isinstance(saved.get("size"), int):
        return _normalize_avatar_size(saved["size"])
    return _normalize_avatar_size(default_size)


def _avatar_size_label(size: int) -> str:
    normalized = _normalize_avatar_size(size)
    if normalized <= 104:
        return "小"
    if normalized >= 152:
        return "大"
    return "标准"


def _avatar_window_geometry(
    *,
    size: int,
    screen_width: int,
    screen_height: int,
    saved: dict[str, Any] | None = None,
) -> str:
    width = max(size + 48, int(screen_width or 0))
    height = max(size + 48, int(screen_height or 0))
    default_x = max(24, width - size - 36)
    default_y = max(24, height - size - 96)
    saved = saved if isinstance(saved, dict) else {}
    if isinstance(saved.get("x"), int) and isinstance(saved.get("y"), int):
        min_x = min(24, -width + 24)
        max_x = max(24, width * 2 - size - 24)
        min_y = min(24, -height + 24)
        max_y = max(24, height * 2 - size - 24)
        x = min(max(saved["x"], min_x), max_x)
        y = min(max(saved["y"], min_y), max_y)
    else:
        x = default_x
        y = default_y
    return f"{size}x{size}{_window_position_geometry(x, y)}"


def _avatar_placement_geometry(
    placement: str,
    *,
    size: int,
    screen_width: int,
    screen_height: int,
    current_x: int | None = None,
) -> str:
    normalized_size = _normalize_avatar_size(size)
    width = max(normalized_size + 48, int(screen_width or 0))
    height = max(normalized_size + 48, int(screen_height or 0))
    x_margin = 36
    top_margin = 36
    bottom_margin = 96
    left_x = x_margin
    right_x = max(x_margin, width - normalized_size - x_margin)
    center_x = max(x_margin, (width - normalized_size) // 2)
    top_y = top_margin
    middle_y = max(top_margin, (height - normalized_size) // 2)
    bottom_y = max(top_margin, height - normalized_size - bottom_margin)
    target = str(placement or "").strip() or "bottom_right"
    if target == "avoid":
        target = "bottom_left" if current_x is not None and current_x >= width // 2 else "bottom_right"
    elif target == "summon":
        target = "center"
    coordinates = {
        "bottom_right": (right_x, bottom_y),
        "right": (right_x, middle_y),
        "top_right": (right_x, top_y),
        "bottom_left": (left_x, bottom_y),
        "left": (left_x, middle_y),
        "top_left": (left_x, top_y),
        "center": (center_x, middle_y),
    }
    x, y = coordinates.get(target, coordinates["bottom_right"])
    return f"{normalized_size}x{normalized_size}{_window_position_geometry(x, y)}"


def _placement_label(placement: str) -> str:
    labels = {
        "avoid": "躲到旁边",
        "bottom_right": "右下角",
        "right": "右侧",
        "top_right": "右上角",
        "bottom_left": "左下角",
        "left": "左侧",
        "top_left": "左上角",
        "center": "中间",
        "summon": "身边",
    }
    return labels.get(str(placement or ""), "右下角")


def _companion_status(interactions: int, idle_moments: int, *, enabled: bool = True) -> dict[str, Any]:
    interaction_count = max(0, int(interactions or 0))
    idle_count = max(0, int(idle_moments or 0))
    points = interaction_count * 2 + idle_count
    level = min(5, 1 + points // 4)
    if not enabled:
        label = "安静守候"
    elif level >= 5:
        label = "默契很好"
    elif level >= 3:
        label = "陪伴升温"
    else:
        label = "刚刚在一起"
    return {
        "level": level,
        "points": points,
        "label": label,
        "detail": f"{interaction_count} 次互动 · {idle_count} 次待机陪伴",
        "enabled": enabled,
    }


def _presence_summary(
    *,
    state: str,
    has_pending_approval: bool = False,
    active_skill: dict[str, Any] | None = None,
    latest_activity: dict[str, Any] | None = None,
    companion: dict[str, Any] | None = None,
    service: dict[str, Any] | None = None,
) -> dict[str, str]:
    key = str(state or "idle").strip() or "idle"
    skill_name = ""
    if isinstance(active_skill, dict):
        skill_name = _clip(str(active_skill.get("displayName") or active_skill.get("name") or ""), 18)
    activity = latest_activity if isinstance(latest_activity, dict) else {}
    activity_title = _clip(str(activity.get("title") or ""), 32)
    activity_detail = _clip(str(activity.get("detail") or ""), 46)
    service_state = str(service.get("state") or "") if isinstance(service, dict) else ""
    companion_label = str(companion.get("label") or "") if isinstance(companion, dict) else ""

    if has_pending_approval or key == "waiting_approval":
        label = "等你确认"
        detail = "我先停住动作，等你说同意、拒绝，或补一句限制。"
        mood = "waiting_approval"
    elif key in {"thinking", "working"}:
        label = f"正用「{skill_name}」" if skill_name else "正在处理"
        target = activity_title or "你刚交给我的事"
        detail = f"我在跟进：{target}。{activity_detail}" if activity_detail else f"我在跟进：{target}。"
        mood = key
    elif key == "sleep":
        label = "安静待机"
        detail = "我在旁边安静守着。单击我，就会回到对话。"
        mood = "sleep"
    elif key == "error":
        label = "遇到问题"
        detail = activity_detail or "我卡在一个错误上了，你可以问我问题或让我继续补充。"
        mood = "error"
    elif key == "success":
        label = "刚完成一步"
        detail = activity_title or "我刚把上一件事收住了，可以继续接下一步。"
        mood = "success"
    elif key == "speaking":
        label = "正在听你说"
        detail = "我在对话状态，适合直接给任务、材料、设置或互动指令。"
        mood = "speaking"
    elif skill_name:
        label = f"拿着「{skill_name}」待命"
        detail = "你后续发来的话或材料，我会优先按这个 skill 处理。"
        mood = "ready"
    else:
        label = "在桌面待命"
        detail = "我醒着，也在这里。你可以直接说话、丢材料、装 skill 或让我互动一下。"
        mood = "idle"

    if companion_label and key == "idle":
        detail = f"{detail} 现在的陪伴状态是「{companion_label}」。"
    return {"label": label, "detail": _clip(detail, 132), "mood": mood}


def _memory_summary(
    chat_items: list[dict[str, Any]],
    activity_items: list[dict[str, Any]],
    *,
    interaction_count: int = 0,
    active_skill: dict[str, Any] | None = None,
    profile_memories: list[str] | None = None,
) -> dict[str, Any]:
    latest_user = ""
    for item in reversed(chat_items):
        if not isinstance(item, dict) or str(item.get("role") or "") != "user":
            continue
        latest_user = _clip(str(item.get("text") or ""), 40)
        if latest_user:
            break

    latest_activity = next((item for item in activity_items if isinstance(item, dict)), {})
    activity_title = _clip(str(latest_activity.get("title") or ""), 34) if latest_activity else ""
    activity_detail = _clip(str(latest_activity.get("detail") or ""), 52) if latest_activity else ""
    skill_name = ""
    if isinstance(active_skill, dict):
        skill_name = _clip(str(active_skill.get("displayName") or active_skill.get("name") or ""), 20)
    interactions = max(0, int(interaction_count or 0))
    long_term = normalize_twin_memories(profile_memories or [])

    has_memory = bool(latest_user or activity_title or skill_name or interactions or long_term)
    if activity_title:
        label = activity_title
    elif latest_user:
        label = "最近对话"
    elif skill_name:
        label = f"等「{skill_name}」的材料"
    elif long_term:
        label = f"{len(long_term)} 条长期记忆"
    elif interactions:
        label = "刚互动过"
    else:
        label = "刚开始认识"

    parts: list[str] = []
    if latest_user:
        parts.append(f"你刚说：{latest_user}")
    if activity_title:
        activity_line = activity_title
        if activity_detail:
            activity_line = f"{activity_line}：{activity_detail}"
        parts.append(f"最近一件事是 {activity_line}")
    if skill_name:
        parts.append(f"我会继续用「{skill_name}」接手")
    if long_term:
        parts.append(f"长期记得：{'；'.join(long_term[:2])}")
    if interactions:
        parts.append(f"我们已经有 {interactions} 次桌面互动")
    detail = "；".join(parts) if parts else "我还没有最近对话或任务。你说一句，我就会把这段上下文留在身边。"
    return {"label": label, "detail": _clip(detail, 150), "hasMemory": has_memory}


def _direct_chat_height(
    preview_count: int,
    *,
    has_approval: bool = False,
    has_skill_shortcuts: bool = False,
    has_settings: bool = False,
    has_activity: bool = False,
    has_artifacts: bool = False,
    has_companion: bool = False,
    has_service: bool = False,
    has_help: bool = False,
    has_quick_actions: bool = False,
) -> int:
    return ONE_LINE_DIRECT_HEIGHT


def _direct_chat_window_height(natural_height: int, screen_height: int) -> int:
    usable_height = max(ONE_LINE_DIRECT_HEIGHT, int(screen_height or 0) - DIRECT_CHAT_SCREEN_MARGIN)
    requested_height = max(ONE_LINE_DIRECT_HEIGHT, int(natural_height or 0))
    return min(requested_height, usable_height)


def _direct_chat_content_window_height(content_height: int, *, composer_height: int = DIRECT_CHAT_COMPOSER_HEIGHT) -> int:
    return max(DIRECT_CHAT_MIN_HEIGHT, int(content_height or 0) + int(composer_height or 0) + 30)


def _direct_chat_scroll_height(window_height: int) -> int:
    return max(160, int(window_height or 0) - DIRECT_CHAT_CHROME_HEIGHT)


def _work_hud_state_for_activity(kind: str) -> str | None:
    key = str(kind or "").strip()
    if key not in WORK_HUD_ACTIVE_KINDS and key not in WORK_HUD_TERMINAL_KINDS:
        return None
    if key in {"user", "quick", "accepted", "processing"}:
        return "thinking"
    if key in {"subtask", "tool"}:
        return "working"
    if key == "approval":
        return "waiting_approval"
    if key in {"artifact", "final"}:
        return "success"
    if key == "error":
        return "error"
    return None


def _activity_stage_label(kind: str) -> str:
    key = str(kind or "").strip()
    labels = {
        "user": "接住任务",
        "quick": "启动快捷动作",
        "accepted": "等 Agent 接手",
        "processing": "拆步骤",
        "reply": "组织回复",
        "subtask": "推进子任务",
        "tool": "使用工具",
        "approval": "等你确认",
        "artifact": "整理产物",
        "final": "收尾完成",
        "error": "遇到问题",
        "skill": "切换 skill",
        "interaction": "桌面互动",
        "interrupt": "请求停止",
    }
    return labels.get(key, "")


def _activity_effect_for_kind(kind: str) -> str:
    key = str(kind or "").strip()
    effects = {
        "user": "nod",
        "quick": "nod",
        "accepted": "nod",
        "processing": "peek",
        "reply": "nod",
        "subtask": "peek",
        "tool": "peek",
        "approval": "nod",
        "artifact": "cheer",
        "final": "cheer",
        "skill": "nod",
        "interrupt": "nod",
    }
    return effects.get(key, "")


def _work_hud_auto_hide_ms(kind: str) -> int | None:
    key = str(kind or "").strip()
    if key in {"artifact", "final"}:
        return 3200
    if key == "error":
        return 5200
    return None


def _work_hud_resume_activity(items: list[dict[str, Any]]) -> dict[str, str] | None:
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind in WORK_HUD_TERMINAL_KINDS:
            return None
        if kind not in WORK_HUD_ACTIVE_KINDS:
            continue
        state = _work_hud_state_for_activity(kind)
        if not state:
            continue
        title = _clip(str(item.get("title") or "上次任务仍在进行"), 44)
        detail = _clip(
            str(item.get("detail") or "这是上次退出前还在进行的任务。"),
            92,
        )
        return {"kind": kind, "title": title, "detail": detail, "state": state}
    return None


def _work_hud_phase_label(state: str, frame: int, kind: str = "") -> str:
    key = str(state or "").strip()
    if key == "focus":
        return "JiuMe 陪你专注" + "." * (frame % 4)
    phase_by_kind = {
        "user": "JiuMe 接住任务",
        "quick": "JiuMe 启动快捷动作",
        "accepted": "JiuMe 等 Agent 接手",
        "processing": "JiuMe 正在拆步骤",
        "reply": "JiuMe 正在组织回复",
        "subtask": "JiuMe 推进子任务",
        "tool": "JiuMe 正在用工具",
        "approval": "JiuMe 等你确认",
        "artifact": "JiuMe 整理产物",
        "final": "JiuMe 收尾完成",
        "error": "JiuMe 遇到问题",
        "skill": "JiuMe 切换 skill",
    }
    kind_key = str(kind or "").strip()
    if kind_key in phase_by_kind:
        base = phase_by_kind[kind_key]
        if key in {"waiting_approval", "success", "error"}:
            return base
        return base + "." * (frame % 4)
    if key == "waiting_approval":
        return "JiuMe 等你确认"
    if key == "success":
        return "JiuMe 完成了"
    if key == "error":
        return "JiuMe 遇到问题"
    base = "JiuMe 正在处理"
    return base + "." * (frame % 4)


def _work_hud_bubble_line(title: str, detail: str = "", *, state: str = "working", kind: str = "") -> str:
    phase = _work_hud_phase_label(state, 0, kind).rstrip(".")
    headline = _clip(str(title or "正在处理").strip(), 34)
    body = _clip(str(detail or "").strip(), 68)
    if body:
        return f"{phase}｜{headline}：{body}"
    return f"{phase}｜{headline}"


def _work_hud_action_specs(state: str) -> list[dict[str, str]]:
    key = str(state or "").strip()
    if key == "focus":
        return [
            {"id": "finish_focus", "label": "结束", "style": "primary"},
            {"id": "focus_status", "label": "还剩", "style": "secondary"},
            {"id": "cheer", "label": "打气", "style": "secondary"},
            {"id": "chat", "label": "说一句", "style": "secondary"},
        ]
    if key == "waiting_approval":
        return [
            {"id": "approval_accept", "label": "同意", "style": "primary"},
            {"id": "approval_reject", "label": "拒绝", "style": "secondary"},
            {"id": "chat", "label": "补限制", "style": "secondary"},
            {"id": "cheer", "label": "打气", "style": "secondary"},
        ]
    if key in {"thinking", "working"}:
        return [
            {"id": "chat", "label": "补一句", "style": "primary"},
            {"id": "progress", "label": "进度", "style": "secondary"},
            {"id": "nudge", "label": "戳戳", "style": "secondary"},
            {"id": "cheer", "label": "打气", "style": "secondary"},
            {"id": "quiet", "label": "安静", "style": "secondary"},
            {"id": "cancel", "label": "停止", "style": "secondary"},
        ]
    if key == "success":
        return [
            {"id": "progress", "label": "查看", "style": "primary"},
            {"id": "chat", "label": "继续聊", "style": "secondary"},
        ]
    if key == "error":
        return [
            {"id": "progress", "label": "查看", "style": "primary"},
            {"id": "retry", "label": "重试", "style": "secondary"},
            {"id": "chat", "label": "补充", "style": "secondary"},
        ]
    return [
        {"id": "chat", "label": "对话", "style": "primary"},
        {"id": "progress", "label": "进度", "style": "secondary"},
    ]


class JiuMeDesktopAvatar:
    def __init__(
        self,
        size: int = 128,
        gateway_url: str = DEFAULT_GATEWAY_URL,
        agent_mode: str = DEFAULT_AGENT_MODE,
    ) -> None:
        saved_window_state = read_window_state()
        self.size = _avatar_size_from_state(size, saved_window_state)
        self.opacity = _avatar_opacity_from_state(saved_window_state)
        self.gateway_url = gateway_url
        self.agent_mode = agent_mode
        self.store = TwinStore()
        self.avatars = AvatarService(self.store)
        self.gateway = (
            JiuMeGatewayChatClient(gateway_url=gateway_url, mode=agent_mode)
            if gateway_url.strip()
            else None
        )
        self.root = tk.Tk()
        self.root.title("JiuMe")
        if sys.platform != "darwin":
            self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self._transparent_bg = _desktop_layer_background(sys.platform)
        self.root.configure(bg=self._transparent_bg)
        self._ui_events: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._ui_event_polling = False
        self._ensure_ui_event_polling()
        if sys.platform != "darwin":
            try:
                self.root.wm_attributes("-transparentcolor", self._transparent_bg)
            except tk.TclError:
                self._transparent_bg = "#f6f8fb"
                self.root.configure(bg=self._transparent_bg)
        self._apply_window_opacity()
        self.overlay = DesktopOverlayHost(self.root, transparent_bg=self._transparent_bg)
        self.avatar_layer = AvatarLayer()
        self.bubble_layer = BubbleLayer()
        self.floating_card_layer = FloatingCardLayer()

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(
            _avatar_window_geometry(
                size=self.size,
                screen_width=screen_width,
                screen_height=screen_height,
                saved=saved_window_state,
            )
        )
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass
        self.overlay.apply_avatar_window(self.root, title="JiuMe")

        self.label = tk.Label(self.root, bg=self._transparent_bg, bd=0, highlightthickness=0, cursor="hand2")
        self.label.pack(fill="both", expand=True)
        self.label.bind("<ButtonPress-1>", self._start_drag)
        self.label.bind("<B1-Motion>", self._drag)
        self.label.bind("<ButtonRelease-1>", self._end_drag_or_click)
        self.label.bind("<Double-Button-1>", lambda _event: self.open_settings())
        self.label.bind("<Button-2>", lambda _event: self.root.destroy())
        self.label.bind("<Button-3>", self._open_menu)
        self.label.bind("<Control-Button-1>", self._open_menu)
        self.label.bind("<Enter>", self._on_avatar_enter)
        self.label.bind("<Leave>", lambda _event: self._schedule_hover_menu_hide(900))
        self.root.bind_all("<Escape>", lambda _event: self._close_current_overlay())
        if sys.platform == "darwin":
            self.overlay.set_avatar_callbacks(
                enter=lambda: self._on_avatar_enter(None),
                leave=lambda: self._schedule_hover_menu_hide(900),
                left_click=self._native_avatar_left_click,
                right_click=lambda: self._open_menu(None),  # type: ignore[arg-type]
                move=self._native_avatar_moved,
            )

        self._app_menu: tk.Menu | None = None
        self._install_app_menu()

        self._drag_origin: tuple[int, int, int, int] | None = None
        self._drag_moved = False
        self._photo: ImageTk.PhotoImage | None = None
        self._avatar_cache: dict[str, Image.Image] = {}
        self._animation_frame = 0
        self._animation_timer: str | None = None
        self._interaction_effect: str | None = None
        self._interaction_effect_started_at = 0
        self._last_hover_effect_at = 0.0
        self._poke_count = 0
        self._wake_count = 0
        self._interaction_count = 0
        self._idle_companion_index = 0
        self._idle_companion_enabled = False
        self._idle_companion_timer: str | None = None
        self._last_activity_at = time.monotonic()
        self._manifest: dict[str, Any] | None = None
        self._active_twin_id: str | None = None
        self._state = "idle"
        self._state_path = get_desktop_state_path()
        self._direct_chat: tk.Toplevel | None = None
        self._direct_entry: tk.Entry | None = None
        self._panel: tk.Toplevel | None = None
        self._artifact_panel: tk.Toplevel | None = None
        self._artifact_photo: ImageTk.PhotoImage | None = None
        self._name_label: tk.Label | None = None
        self._approval_frame: tk.Frame | None = None
        self._approval_anchor: tk.Widget | None = None
        self._approval_feedback_var: tk.StringVar | None = None
        self._direct_approval_feedback_visible = False
        self._chat_frame: tk.Frame | None = None
        self._direct_chat_frame: tk.Frame | None = None
        self._direct_companion_frame: tk.Frame | None = None
        self._direct_help_frame: tk.Frame | None = None
        self._direct_service_frame: tk.Frame | None = None
        self._direct_artifact_frame: tk.Frame | None = None
        self._direct_activity_frame: tk.Frame | None = None
        self._direct_approval_frame: tk.Frame | None = None
        self._direct_quick_frame: tk.Frame | None = None
        self._direct_skills_frame: tk.Frame | None = None
        self._direct_settings_frame: tk.Frame | None = None
        self._direct_composer_frame: tk.Canvas | None = None
        self._direct_scroll_canvas: tk.Canvas | None = None
        self._direct_scrollbar: tk.Scrollbar | None = None
        self._direct_content_frame: tk.Frame | None = None
        self._direct_settings_visible = False
        self._direct_settings_section = "identity"
        self._direct_settings_picker_visible = False
        self._direct_settings_detail_visible = False
        self._direct_activity_more_visible = False
        self._direct_activity_empty_visible = False
        self._direct_activity_detail_visible = False
        self._direct_skill_section = "recommended"
        self._direct_skills_picker_visible = False
        self._direct_skills_detail_visible = False
        self._direct_help_section = "overview"
        self._direct_artifact_category = ""
        self._direct_companion_visible = False
        self._direct_companion_more_visible = False
        self._direct_chat_scroll_offset = 0
        self._direct_name_var: tk.StringVar | None = None
        self._direct_purpose_var: tk.StringVar | None = None
        self._direct_tone_var: tk.StringVar | None = None
        self._direct_mode_var: tk.StringVar | None = None
        self._direct_appearance_var: tk.StringVar | None = None
        self._chat_items: list[dict[str, str]] = []
        self._stream_chat_index: int | None = None
        self._gateway_request_id: str | None = None
        self._gateway_request_message = ""
        self._quick_actions_frame: tk.Frame | None = None
        self._activity_frame: tk.Frame | None = None
        self._activity_items: list[dict[str, Any]] = []
        self._service_status_label: tk.Label | None = None
        self._skills_frame: tk.Frame | None = None
        self._skill_search_var: tk.StringVar | None = None
        self._skill_category_var: tk.StringVar | None = None
        self._skill_risk_var: tk.StringVar | None = None
        self._skill_filter_summary_var: tk.StringVar | None = None
        self._local_skill_path_var: tk.StringVar | None = None
        self._active_skill_context: dict[str, str] | None = None
        self._chat_entry: tk.Entry | None = None
        self._last_action: tk.StringVar | None = None
        self._settings_center: Any | None = None
        self._work_hud: tk.Toplevel | None = None
        self._work_hud_status_var: tk.StringVar | None = None
        self._work_hud_title_var: tk.StringVar | None = None
        self._work_hud_detail_var: tk.StringVar | None = None
        self._work_hud_status_label: tk.Label | None = None
        self._work_hud_actions_frame: tk.Frame | None = None
        self._work_hud_state = "thinking"
        self._work_hud_kind = ""
        self._work_hud_frame = 0
        self._work_hud_timer: str | None = None
        self._work_hud_hide_timer: str | None = None
        self._focus_session: dict[str, Any] | None = None
        self._focus_timer: str | None = None
        self._bubble: tk.Toplevel | None = None
        self._bubble_label: tk.Label | None = None
        self._bubble_canvas: tk.Canvas | None = None
        self._bubble_text = ""
        self._bubble_height = 92
        self._bubble_timer: str | None = None
        self._hover_menu: tk.Toplevel | None = None
        self._hover_canvas: tk.Canvas | None = None
        self._hover_mode = "prompt"
        self._hover_hide_timer: str | None = None
        self._direct_surface_canvas: tk.Canvas | None = None
        self._direct_surface_window: int | None = None
        self._native_direct_chat_visible = False
        self._native_direct_surface = "chat"
        self._restore_direct_chat_after_drag = False
        self._drag_suspended_direct_surface = "chat"
        self._one_line_capsule: TaskCapsule | None = None
        self._one_line_capsule_timer: str | None = None
        self._one_line_question_active = False
        self._typing_timer: str | None = None
        self._gateway_reply = ""
        self._pending_approval: dict[str, Any] | None = None
        self._native_onboarding_pending = False
        self._load_initial()
        self._load_companion_memory()
        self._load_desktop_history()
        self._watcher = threading.Thread(target=self._watch_state_file, daemon=True)
        self._watcher.start()
        self._keep_topmost()
        self._animate_avatar()
        self.root.after(120, self.overlay.refresh)
        if self._idle_companion_enabled:
            self._schedule_idle_companion()

    def _load_initial(self) -> None:
        active = self.store.get_active_twin_id()
        if not active:
            self._active_twin_id = None
            self._manifest = None
            self._avatar_cache.clear()
            self._native_onboarding_pending = True
            return
        self._active_twin_id = active
        try:
            self._manifest = self.avatars.get_manifest(active)
        except (FileNotFoundError, KeyError, OSError, ValueError):
            self._manifest = None
            self._avatar_cache.clear()
            self._native_onboarding_pending = True
            return
        self._avatar_cache.clear()
        self.set_state("idle")

    def _load_companion_memory(self) -> None:
        state = read_companion_state()
        self._interaction_count = int(state.get("interaction_count") or 0)
        self._idle_companion_index = int(state.get("idle_companion_index") or 0)
        self._idle_companion_enabled = False

    def _persist_companion_memory(self) -> None:
        try:
            write_companion_state(
                interaction_count=self._interaction_count,
                idle_companion_index=self._idle_companion_index,
                idle_companion_enabled=self._idle_companion_enabled,
                twin_id=self._active_twin_id,
            )
        except OSError:
            pass

    def _load_desktop_history(self) -> None:
        state = read_conversation_state()
        chat = state.get("chat")
        activity = state.get("activity")
        self._chat_items = (
            [dict(item) for item in chat if isinstance(item, dict)]
            if isinstance(chat, list)
            else []
        )
        self._activity_items = (
            [dict(item) for item in activity if isinstance(item, dict)]
            if isinstance(activity, list)
            else []
        )
        active_skill = state.get("activeSkill")
        self._active_skill_context = _active_skill_snapshot(active_skill if isinstance(active_skill, dict) else None)

    def _persist_desktop_history(self) -> None:
        try:
            write_conversation_state(
                chat_items=self._chat_items,
                activity_items=self._activity_items,
                active_skill=self._active_skill_context,
                twin_id=self._active_twin_id,
            )
        except OSError:
            pass

    def _persist_window_position(self) -> None:
        try:
            write_window_state(
                x=self.root.winfo_x(),
                y=self.root.winfo_y(),
                size=self.size,
                screen_width=self.root.winfo_screenwidth(),
                screen_height=self.root.winfo_screenheight(),
                opacity=self.opacity,
                twin_id=self._active_twin_id,
            )
        except (OSError, tk.TclError):
            pass

    def _apply_window_opacity(self) -> None:
        try:
            self.root.attributes("-alpha", self.opacity)
        except tk.TclError:
            pass

    def _set_avatar_size(self, size: int) -> None:
        new_size = _normalize_avatar_size(size, default=self.size)
        if new_size != self.size:
            self.size = new_size
            position = _window_position_geometry(self.root.winfo_x(), self.root.winfo_y())
            self.root.geometry(f"{self.size}x{self.size}{position}")
            self._render_avatar_frame()
            self._position_direct_chat()
            self._position_panel()
            self._position_work_hud()
            self._position_bubble()
            self._position_hover_menu()
        self._persist_window_position()
        if self._direct_settings_visible:
            self._rebuild_direct_settings_card()

    def _set_avatar_opacity(self, opacity: float) -> None:
        self.opacity = _normalize_avatar_opacity(opacity, default=self.opacity)
        self._apply_window_opacity()
        self._persist_window_position()

    def _run_native_opacity_command(self, command: str) -> None:
        current = _normalize_avatar_opacity(self.opacity)
        if command == "softer":
            next_opacity = current - AVATAR_OPACITY_STEP
        elif command == "clearer":
            next_opacity = current + AVATAR_OPACITY_STEP
        elif command == "low":
            next_opacity = 0.55
        else:
            next_opacity = AVATAR_OPACITY_MAX
        self._set_avatar_opacity(next_opacity)
        label = _avatar_opacity_label(self.opacity)
        reply = f"好，我现在是「{label}」显示。"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(f"显示透明度：{label}")
        self.show_bubble(reply, state="speaking", duration=2600)

    def _move_avatar_to_placement(self, placement: str) -> None:
        try:
            geometry = _avatar_placement_geometry(
                placement,
                size=self.size,
                screen_width=self.root.winfo_screenwidth(),
                screen_height=self.root.winfo_screenheight(),
                current_x=self.root.winfo_x(),
            )
            self.root.geometry(geometry)
            self.root.update_idletasks()
            self._position_direct_chat()
            self._position_panel()
            self._position_work_hud()
            self._position_bubble()
            self._persist_window_position()
        except tk.TclError:
            self.show_bubble("我现在挪不动窗口，稍后再试一下。", state="error", duration=3200)
            return

        label = _placement_label(placement)
        reply = f"好，我到{label}，不挡你。"
        if placement == "summon":
            reply = "我过来了，就在你顺手能叫到我的位置。"
        elif placement == "center":
            reply = "好，我到中间，方便你直接和我说话。"
        elif placement == "avoid":
            reply = "好，我躲到旁边，不挡你。"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(f"桌面位置：{label}")
        self.show_bubble(reply, state="speaking", duration=2600)

    def _refresh_twin_name(self) -> None:
        if not self._name_label or not self._name_label.winfo_exists():
            return
        twin = self._active_twin() or {}
        self._name_label.configure(text=str(twin.get("displayName") or "JiuMe"))

    def _active_twin(self) -> dict[str, Any] | None:
        active = self.store.get_active_twin_id()
        if not active:
            return None
        return self.store.get_twin(active)

    def _enabled_skill_ids(self) -> list[str]:
        twin = self._active_twin()
        if not twin:
            return []
        permissions = twin.get("permissions") if isinstance(twin.get("permissions"), dict) else {}
        skills = permissions.get("allowedSkillIds") if isinstance(permissions, dict) else []
        return [str(item) for item in skills] if isinstance(skills, list) else []

    def _reload_active_if_changed(self) -> None:
        active = self.store.get_active_twin_id()
        if not active or active == self._active_twin_id:
            return
        if self._sync_active_manifest(active):
            self.show_bubble("我已经换成你的桌面分身。单击就直接说话。", state="speaking", duration=3600)

    def _sync_active_manifest(self, twin_id: str = "") -> bool:
        active = self.store.get_active_twin_id()
        target = str(twin_id or active or "").strip()
        if not target or active != target:
            return False
        try:
            next_manifest = self.avatars.get_manifest(target)
        except (FileNotFoundError, KeyError, OSError, ValueError):
            self._active_twin_id = target
            self._manifest = None
            self._native_onboarding_pending = True
            self._avatar_cache.clear()
            self.set_state("idle")
            self._refresh_twin_name()
            return False
        current_signature = _avatar_manifest_signature(self._manifest)
        next_signature = _avatar_manifest_signature(next_manifest)
        changed = target != self._active_twin_id or bool(next_signature and next_signature != current_signature)
        if not changed:
            return False
        self._active_twin_id = target
        self._manifest = next_manifest
        self._native_onboarding_pending = False
        self._avatar_cache.clear()
        self.set_state(self._state)
        self._refresh_twin_name()
        self._rebuild_skill_rows()
        self._rebuild_direct_skill_shortcuts()
        if self._direct_settings_visible:
            self._direct_settings_picker_visible = False
            self._direct_settings_detail_visible = False
            self._rebuild_direct_settings_card()
        return True

    def _post_to_ui(self, callback: Callable[[], None]) -> None:
        self._ui_events.put(callback)

    def _ensure_ui_event_polling(self) -> None:
        if self._ui_event_polling:
            return
        self._ui_event_polling = True
        try:
            self.root.after(16, self._drain_ui_events)
        except tk.TclError:
            self._ui_event_polling = False

    def _drain_ui_events(self) -> None:
        while True:
            try:
                callback = self._ui_events.get_nowait()
            except Empty:
                break
            try:
                callback()
            except Exception:
                continue
        if not self._ui_event_polling:
            return
        try:
            self.root.after(16, self._drain_ui_events)
        except tk.TclError:
            self._ui_event_polling = False

    def _watch_state_file(self) -> None:
        last_seen = ""
        while True:
            try:
                self._post_to_ui(self._reload_active_if_changed)
                current = self._state_path.read_text(encoding="utf-8") if self._state_path.exists() else ""
                if current and current != last_seen:
                    last_seen = current
                    payload = json.loads(current)
                    if _desktop_state_event_is_ignored(payload, active_twin_id=self._active_twin_id or ""):
                        continue
                    if _desktop_state_event_is_stale(payload):
                        continue
                    state = str(payload.get("state") or "idle")
                    message = str(payload.get("message") or "")
                    twin_id = str(payload.get("twin_id") or payload.get("twinId") or "")
                    self._post_to_ui(lambda s=state, m=message, t=twin_id: self._apply_external_state(s, m, t))
            except Exception:
                pass
            time.sleep(0.4)

    def _apply_external_state(self, state: str, message: str = "", twin_id: str = "") -> None:
        if twin_id:
            self._sync_active_manifest(twin_id)
        self.set_state(state)
        if message:
            self._mark_activity()
            self.show_bubble(_clip(message, 88), state=state if state != "idle" else "speaking", duration=2800)

    def _keep_topmost(self) -> None:
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            if self._panel and self._panel.winfo_exists():
                self._panel.attributes("-topmost", True)
            if self._direct_chat and self._direct_chat.winfo_exists():
                self._direct_chat.attributes("-topmost", True)
            if self._artifact_panel and self._artifact_panel.winfo_exists():
                self._artifact_panel.attributes("-topmost", True)
            if self._work_hud and self._work_hud.winfo_exists():
                self._work_hud.attributes("-topmost", True)
            if self._bubble and self._bubble.winfo_exists():
                self._bubble.attributes("-topmost", True)
            if self._hover_menu and self._hover_menu.winfo_exists():
                self._hover_menu.attributes("-topmost", True)
            self.overlay.refresh()
        except tk.TclError:
            return
        self.root.after(1500, self._keep_topmost)

    def _populate_material_menu(self, menu: tk.Menu) -> None:
        menu.add_command(label=MATERIAL_MENU_LABELS[0], command=self._send_screen_context_from_direct)
        menu.add_command(label=MATERIAL_MENU_LABELS[1], command=self._send_clipboard_material_from_direct)
        menu.add_command(label=MATERIAL_MENU_LABELS[2], command=self._send_file_material_from_direct)

    def _populate_skill_menu(self, menu: tk.Menu) -> None:
        menu.add_command(label=SKILL_MENU_LABELS[0], command=self._reply_with_active_skill_summary)
        menu.add_command(label=SKILL_MENU_LABELS[1], command=lambda: self._run_native_control_command("clear_skill"))
        menu.add_command(label=SKILL_MENU_LABELS[2], command=lambda: self._run_native_control_command("skills"))

    def _populate_task_menu(self, menu: tk.Menu) -> None:
        menu.add_command(label=TASK_MENU_LABELS[0], command=lambda: self._run_native_control_command("progress"))
        menu.add_command(label=TASK_MENU_LABELS[1], command=self._show_artifact_tray)
        menu.add_command(label=TASK_MENU_LABELS[2], command=self._request_task_interrupt_from_menu)

    def _populate_companion_menu(self, menu: tk.Menu) -> None:
        menu.add_command(label=COMPANION_MENU_LABELS[0], command=lambda: self._set_idle_companion_enabled(True, record_chat=True))
        menu.add_command(label=COMPANION_MENU_LABELS[1], command=lambda: self._set_idle_companion_enabled(False, record_chat=True))
        menu.add_command(label=COMPANION_MENU_LABELS[2], command=self._play_companion_moment_from_menu)

    def _populate_interaction_menu(self, menu: tk.Menu) -> None:
        for action in interaction_actions():
            menu.add_command(
                label=str(action["title"]),
                command=lambda item=action: self._run_interaction_action(item),
            )
        menu.add_separator()
        menu.add_command(label=PLAY_MENU_LABELS[0], command=lambda: self._run_native_rps_command({"action": "start", "move": ""}))
        menu.add_command(label=PLAY_MENU_LABELS[1], command=lambda: self._run_native_dice_command({"sides": 6}))
        menu.add_command(label=PLAY_MENU_LABELS[2], command=lambda: self._run_native_coin_command({"mode": "draw"}))

    def _install_app_menu(self) -> None:
        app_menu = tk.Menu(self.root, tearoff=0)
        jiume_menu = tk.Menu(app_menu, tearoff=0)
        jiume_menu.add_command(label=APP_MENU_LABELS[0], command=self.open_settings)
        jiume_menu.add_separator()
        jiume_menu.add_command(label=APP_MENU_LABELS[1], command=self.root.destroy)
        app_menu.add_cascade(label="JiuMe", menu=jiume_menu)

        self._app_menu = app_menu
        self.root.configure(menu=app_menu)
        try:
            self.root.createcommand("tk::mac::ShowPreferences", self.open_settings)
            self.root.createcommand("tk::mac::Quit", self.root.destroy)
        except tk.TclError:
            pass

    def _mark_activity(self) -> None:
        self._last_activity_at = time.monotonic()

    def _window_is_visible(self, window: tk.Toplevel | None) -> bool:
        if not window:
            return False
        try:
            return bool(window.winfo_exists()) and window.state() != "withdrawn"
        except tk.TclError:
            return False

    def _direct_chat_is_visible(self) -> bool:
        if bool(getattr(self, "_native_direct_chat_visible", False)):
            return True
        return self._window_is_visible(getattr(self, "_direct_chat", None))

    def _suspend_direct_chat_for_avatar_drag(self) -> None:
        if bool(getattr(self, "_restore_direct_chat_after_drag", False)):
            return
        if not self._direct_chat_is_visible():
            return
        self._restore_direct_chat_after_drag = True
        self._drag_suspended_direct_surface = _normalize_native_direct_surface(
            getattr(self, "_native_direct_surface", "chat")
        )
        self._close_direct_chat()

    def _restore_direct_chat_after_avatar_drag(self) -> None:
        if not bool(getattr(self, "_restore_direct_chat_after_drag", False)):
            return
        surface = _normalize_native_direct_surface(getattr(self, "_drag_suspended_direct_surface", "chat"))
        self._restore_direct_chat_after_drag = False
        self._drag_suspended_direct_surface = "chat"
        if self._direct_chat_is_visible():
            return
        if _uses_native_direct_chat():
            self._open_native_direct_surface(surface)
        else:
            self.open_direct_chat()

    def _toggle_direct_chat_from_avatar(self) -> None:
        if self._direct_chat_is_visible():
            self._close_direct_chat()
            return
        self.open_direct_chat()

    def _has_visible_companion_surface(self) -> bool:
        if self._direct_chat_is_visible():
            return True
        if any(
            self.overlay.is_image_layer_visible(layer_id)
            for layer_id in ("hover", "speech", "direct_chat")
        ):
            return True
        return any(
            self._window_is_visible(window)
            for window in (
                self._direct_chat,
                self._panel,
                self._artifact_panel,
                self._work_hud,
                self._bubble,
                self._hover_menu,
            )
        )

    def _schedule_idle_companion(self, delay_ms: int = 10_000) -> None:
        if self._idle_companion_timer:
            try:
                self.root.after_cancel(self._idle_companion_timer)
            except tk.TclError:
                pass
            self._idle_companion_timer = None
        if not self._idle_companion_enabled:
            return
        self._idle_companion_timer = self.root.after(delay_ms, self._run_idle_companion_tick)

    def _run_idle_companion_tick(self) -> None:
        self._idle_companion_timer = None
        if not self._idle_companion_enabled:
            return
        idle_seconds = time.monotonic() - self._last_activity_at
        if should_run_idle_companion(
            state=self._state,
            idle_seconds=idle_seconds,
            has_visible_surface=self._has_visible_companion_surface(),
            enabled=self._idle_companion_enabled,
        ):
            self._play_idle_companion_moment()
        if self._idle_companion_enabled:
            self._schedule_idle_companion()

    def _play_conversation_reaction(self, text: str, *, state: str = "") -> None:
        reaction = _conversation_reaction(text, role="assistant", state=state)
        effect = str(reaction.get("effect") or "")
        if effect:
            self._start_interaction_effect(effect)

    def _play_idle_companion_moment(self) -> None:
        moment = _idle_companion_moment_for_context(
            self._idle_companion_index,
            self._active_skill_context,
        )
        self._idle_companion_index += 1
        self._mark_activity()
        self._persist_companion_memory()
        title = str(moment.get("title") or "待机陪伴")
        line = str(moment.get("line") or "我还在。")
        state = str(moment.get("state") or "speaking")
        effect = str(moment.get("effect") or "")
        if self._last_action:
            self._last_action.set(title)
        self._rebuild_direct_companion_card()
        self.show_bubble(line, state=state, duration=3600)
        self._start_interaction_effect(effect)

    def _play_companion_moment_from_menu(self) -> None:
        self._play_idle_companion_moment()
        self._record_activity("interaction", "陪我一下", "JiuMe 从头像菜单做了一次轻陪伴。")

    def _sync_work_hud_from_activity(self, kind: str, title: str, detail: str = "") -> None:
        state = _work_hud_state_for_activity(kind)
        if not state:
            return
        self._show_work_hud(title, detail, state=state, kind=kind)
        effect = _activity_effect_for_kind(kind)
        if effect:
            self._start_interaction_effect(effect)
        delay = _work_hud_auto_hide_ms(kind)
        if delay is not None:
            self._schedule_work_hud_hide(delay)

    def _restore_work_hud_from_history(self) -> None:
        summary = _work_hud_resume_activity(self._activity_items)
        if not summary:
            return
        self.set_state(str(summary["state"]))
        self._show_work_hud(
            str(summary["title"]),
            str(summary["detail"]),
            state=str(summary["state"]),
            kind=str(summary["kind"]),
        )

    def _show_work_hud(self, title: str, detail: str = "", *, state: str = "working", kind: str = "") -> None:
        if self._work_hud_hide_timer:
            try:
                self.root.after_cancel(self._work_hud_hide_timer)
            except tk.TclError:
                pass
            self._work_hud_hide_timer = None
        self._work_hud_state = state or "working"
        self._work_hud_kind = str(kind or "").strip()
        if self._work_hud and self._work_hud.winfo_exists():
            self._work_hud.withdraw()
        line = _work_hud_bubble_line(
            title or "正在处理",
            detail or "我正在把这件事往前推。",
            state=self._work_hud_state,
            kind=self._work_hud_kind,
        )
        if self._last_action:
            self._last_action.set(_clip(line, 54))
        bubble_state = self._work_hud_state
        if bubble_state == "focus":
            bubble_state = "working"
        if bubble_state not in AVATAR_STATUS_BADGES:
            bubble_state = "speaking"
        duration = None if self._work_hud_state in {"thinking", "working", "waiting_approval", "focus"} else _work_hud_auto_hide_ms(kind) or 3200
        self.show_bubble(line, state=bubble_state, duration=duration)
        if self._direct_chat and self._direct_chat.winfo_exists():
            self._rebuild_direct_activity_card()
            if self._work_hud_state == "waiting_approval":
                self._rebuild_direct_approval_card()

    def _build_work_hud(self) -> None:
        # Legacy boxed HUD is retired; task status now appears as avatar speech bubbles.
        self._work_hud = None
        self._work_hud_actions_frame = None

    def _work_hud_command(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        self._mark_activity()
        if action == "chat":
            self.open_direct_chat()
            self.show_bubble("你可以直接补一句，我会带着继续。", state="speaking", duration=2600)
        elif action == "progress":
            self._run_native_control_command("progress")
        elif action == "approval":
            self.open_direct_chat()
            self._rebuild_direct_approval_card()
            self.show_bubble("我把确认放到你旁边了。", state="waiting_approval", duration=None)
        elif action == "approval_accept":
            self._answer_pending_approval_from_avatar("accept")
        elif action == "approval_reject":
            self._answer_pending_approval_from_avatar("reject")
        elif action == "finish_focus":
            self._stop_focus_session(completed=False)
        elif action == "focus_status":
            self._reply_with_focus_status()
        elif action == "cheer":
            self._run_interaction_by_id("cheer")
        elif action == "nudge":
            self._nudge_current_task_from_direct()
        elif action == "quiet":
            self._hide_work_hud()
            self.show_bubble("好，我先安静跑着。需要补充时再点我。", state="working", duration=2600)
        elif action == "retry":
            self._retry_latest_task_from_direct()
        elif action == "cancel":
            self._request_task_interrupt()

    def _rebuild_work_hud_actions(self) -> None:
        if not self._work_hud_actions_frame:
            return
        for child in self._work_hud_actions_frame.winfo_children():
            child.destroy()
        specs = _work_hud_action_specs(self._work_hud_state)
        primary_id = next(
            (str(spec.get("id") or "") for spec in specs if str(spec.get("style") or "") == "primary"),
            "",
        )
        self._pack_direct_bubble_buttons(
            self._work_hud_actions_frame,
            [dict(spec) for spec in specs],
            lambda item: self._work_hud_command(str(item.get("id") or "")),
            primary_id=primary_id,
            columns=3,
            padx=0,
            pady=(0, 0),
        )

    def _apply_work_hud_style(self) -> None:
        if not self._work_hud_status_label:
            return
        colors = {
            "thinking": "#8A5A00",
            "working": "#155EEF",
            "focus": "#0F766E",
            "waiting_approval": "#9A3412",
            "success": SUCCESS,
            "error": "#B42318",
        }
        self._work_hud_status_label.configure(fg=colors.get(self._work_hud_state, SUCCESS))

    def _update_work_hud_phase(self) -> None:
        if self._work_hud_status_var:
            self._work_hud_status_var.set(
                _work_hud_phase_label(self._work_hud_state, self._work_hud_frame, self._work_hud_kind)
            )

    def _tick_work_hud(self) -> None:
        self._work_hud_timer = None
        if not self._work_hud or not self._work_hud.winfo_exists() or self._work_hud.state() == "withdrawn":
            return
        self._work_hud_frame += 1
        self._update_work_hud_phase()
        self._work_hud_timer = self.root.after(360, self._tick_work_hud)

    def _schedule_work_hud_hide(self, delay_ms: int) -> None:
        if self._work_hud_hide_timer:
            try:
                self.root.after_cancel(self._work_hud_hide_timer)
            except tk.TclError:
                pass
        self._work_hud_hide_timer = self.root.after(delay_ms, self._hide_work_hud)

    def _hide_work_hud(self) -> None:
        if self._work_hud_timer:
            try:
                self.root.after_cancel(self._work_hud_timer)
            except tk.TclError:
                pass
            self._work_hud_timer = None
        self._work_hud_hide_timer = None
        if self._work_hud and self._work_hud.winfo_exists():
            self._work_hud.withdraw()

    def _cancel_focus_timer(self) -> None:
        if not self._focus_timer:
            return
        try:
            self.root.after_cancel(self._focus_timer)
        except tk.TclError:
            pass
        self._focus_timer = None

    def _focus_remaining_seconds(self) -> int:
        if not self._focus_session:
            return 0
        try:
            started_at = float(self._focus_session.get("started_at") or time.monotonic())
            duration = float(self._focus_session.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            return 0
        return max(0, int(duration - (time.monotonic() - started_at)))

    def _focus_detail_text(self) -> str:
        if not self._focus_session:
            return "还没有正在进行的专注会话。"
        remaining = self._focus_remaining_seconds()
        minutes, seconds = divmod(remaining, 60)
        total = int(self._focus_session.get("minutes") or FOCUS_DEFAULT_MINUTES)
        return f"还剩 {minutes:02d}:{seconds:02d} · {total} 分钟专注 · 我在旁边守着这一小步。"

    def _schedule_focus_tick(self) -> None:
        self._cancel_focus_timer()
        self._focus_timer = self.root.after(1000, self._tick_focus_session)

    def _tick_focus_session(self) -> None:
        self._focus_timer = None
        if not self._focus_session:
            return
        if self._focus_remaining_seconds() <= 0:
            self._stop_focus_session(completed=True)
            return
        self.set_state("working")
        self._show_work_hud("专注陪伴中", self._focus_detail_text(), state="focus")
        self._schedule_focus_tick()

    def _start_focus_session(self, minutes: int, raw: str = "") -> None:
        duration_minutes = min(max(int(minutes or FOCUS_DEFAULT_MINUTES), FOCUS_MIN_MINUTES), FOCUS_MAX_MINUTES)
        self._cancel_focus_timer()
        self._focus_session = {
            "started_at": time.monotonic(),
            "duration_seconds": duration_minutes * 60,
            "minutes": duration_minutes,
            "prompt": str(raw or "").strip(),
        }
        reply = f"好，我陪你专注 {duration_minutes} 分钟。先只守住这一小步，结束时我会提醒你。"
        self._append_chat("assistant", reply)
        self._record_activity("interaction", "专注陪伴", f"{duration_minutes} 分钟桌面专注会话已开始。")
        if self._last_action:
            self._last_action.set(f"专注陪伴：{duration_minutes} 分钟")
        self.set_state("working")
        self._show_work_hud("专注陪伴中", self._focus_detail_text(), state="focus")
        self.show_bubble(reply, state="working", duration=3600)
        self._start_interaction_effect("nod")
        self._schedule_focus_tick()

    def _stop_focus_session(self, *, completed: bool = False) -> None:
        if not self._focus_session:
            reply = "现在没有正在进行的专注会话。"
            self._append_chat("assistant", reply)
            self.show_bubble(reply, state="speaking", duration=2800)
            return
        minutes = int(self._focus_session.get("minutes") or FOCUS_DEFAULT_MINUTES)
        self._focus_session = None
        self._cancel_focus_timer()
        if completed:
            title = "专注完成"
            reply = f"这轮 {minutes} 分钟专注完成了。先停一下，记一件刚刚推进的事。"
            kind = "final"
        else:
            title = "结束专注"
            reply = "好，这轮专注先收住。我还在旁边，下一步你再叫我。"
            kind = "interaction"
        self._append_chat("assistant", reply)
        self._record_activity(kind, title, reply)
        if self._last_action:
            self._last_action.set(reply)
        self.show_bubble(reply, state="success", duration=4200)
        self._show_work_hud(title, reply, state="success")
        self._schedule_work_hud_hide(3200)
        self.root.after(1400, lambda: self.set_state("idle"))

    def _reply_with_focus_status(self) -> None:
        if not self._focus_session:
            reply = "现在没有正在进行的专注会话。你可以说“陪我专注 25 分钟”。"
            self._append_chat("assistant", reply)
            self.show_bubble(reply, state="speaking", duration=3600)
            return
        reply = self._focus_detail_text()
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(reply)
        self._show_work_hud("专注陪伴中", reply, state="focus")
        self.show_bubble(reply, state="working", duration=3200)

    def _run_native_focus_command(self, command: dict[str, int | str], raw: str = "") -> None:
        action = str(command.get("action") or "").strip()
        if action == "start":
            self._start_focus_session(int(command.get("minutes") or FOCUS_DEFAULT_MINUTES), raw)
        elif action == "status":
            self._reply_with_focus_status()
        elif action == "stop":
            self._stop_focus_session(completed=False)

    def _position_work_hud(self) -> None:
        if not self._work_hud or not self._work_hud.winfo_exists():
            return
        width, height = 270, 138
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        icon_x = self.root.winfo_x()
        icon_y = self.root.winfo_y()
        x = icon_x - width - 12
        if x < 12:
            x = min(screen_width - width - 12, icon_x + self.size + 12)
        y = icon_y + self.size + 8
        if y + height > screen_height - 24:
            y = max(24, icon_y - height - 10)
        self._work_hud.geometry(f"{width}x{height}+{x}+{y}")

    def _show_shell_menu(self, event: tk.Event | None = None) -> None:
        self._hide_hover_menu()
        menu = tk.Menu(self.root, tearoff=0)
        for spec in _avatar_context_action_specs():
            action_id = str(spec.get("id") or "").strip()
            label = str(spec.get("label") or action_id)
            if action_id == "quit":
                menu.add_separator()
            menu.add_command(label=label, command=lambda value=action_id: self._run_avatar_context_action(value))
        try:
            if event is not None:
                x = int(event.x_root)
                y = int(event.y_root)
            else:
                x = self.root.winfo_x() + self.size
                y = self.root.winfo_y() + max(12, self.size // 2)
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except tk.TclError:
                pass

    def _open_menu(self, event: tk.Event | None) -> None:
        self._mark_activity()
        self._cancel_hover_menu_hide()
        self._show_shell_menu(event)

    def _redirect_first_run_to_setup(self) -> bool:
        if self._active_twin():
            return False
        if self._direct_chat and self._direct_chat.winfo_exists():
            self._close_direct_chat()
        self._hide_hover_menu()
        self.show_bubble("先完成原生配置窗口；照片生成并启用后，我才会留在桌面。", state="speaking", duration=4800)
        return True

    def _run_avatar_context_action(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        self._mark_activity()
        if action == "settings":
            self.open_settings()
            return
        if action == "quit":
            self.root.destroy()

    def _start_drag(self, event: tk.Event) -> None:
        self._mark_activity()
        self._drag_moved = False
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if not self._drag_origin:
            return
        start_x, start_y, win_x, win_y = self._drag_origin
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        if not self._drag_moved and abs(dx) <= AVATAR_DRAG_THRESHOLD_PX and abs(dy) <= AVATAR_DRAG_THRESHOLD_PX:
            return
        if abs(dx) > AVATAR_DRAG_THRESHOLD_PX or abs(dy) > AVATAR_DRAG_THRESHOLD_PX:
            self._drag_moved = True
            self._suspend_direct_chat_for_avatar_drag()
        self.root.geometry(_window_position_geometry(win_x + dx, win_y + dy))
        if not bool(getattr(self, "_restore_direct_chat_after_drag", False)):
            self._position_direct_chat()
        self._position_panel()
        self._position_work_hud()
        self._position_bubble()
        self._position_hover_menu()

    def _end_drag_or_click(self, _event: tk.Event) -> None:
        self._hide_hover_menu()
        if not self._drag_moved:
            if _should_wake_on_click(self._state, drag_moved=self._drag_moved):
                self._wake_from_sleep()
            self._toggle_direct_chat_from_avatar()
        else:
            self._persist_window_position()
            self._restore_direct_chat_after_avatar_drag()
        self._drag_origin = None
        self._drag_moved = False

    def _native_avatar_left_click(self, dragged: object = False) -> None:
        self._hide_hover_menu()
        if not bool(dragged):
            if _should_wake_on_click(self._state, drag_moved=False):
                self._wake_from_sleep()
            self._toggle_direct_chat_from_avatar()
        else:
            self._persist_window_position()
            self._restore_direct_chat_after_avatar_drag()

    def _native_avatar_moved(self, _x: object, _y: object) -> None:
        self._suspend_direct_chat_for_avatar_drag()
        if not bool(getattr(self, "_restore_direct_chat_after_drag", False)):
            self._position_direct_chat()
        self._position_panel()
        self._position_work_hud()
        if self._native_direct_chat_visible or bool(getattr(self, "_restore_direct_chat_after_drag", False)):
            self._hide_speech_surface()
            self._hide_hover_menu()
            return
        self._position_bubble()
        self._position_hover_menu()

    def _cancel_hover_menu_hide(self) -> None:
        if not self._hover_hide_timer:
            return
        try:
            self.root.after_cancel(self._hover_hide_timer)
        except tk.TclError:
            pass
        self._hover_hide_timer = None

    def _schedule_hover_menu_hide(self, delay_ms: int = 700) -> None:
        self._cancel_hover_menu_hide()
        try:
            self._hover_hide_timer = self.root.after(delay_ms, self._hide_hover_menu)
        except tk.TclError:
            self._hover_hide_timer = None

    def _draw_hover_menu(self) -> None:
        canvas = self._hover_canvas
        if not canvas:
            return
        canvas.delete("all")
        if self._hover_mode == "cards":
            self._draw_floating_cards(canvas)
            return
        specs = _hover_prompt_chip_specs()
        bubble_x1 = 14
        bubble_y1 = 18
        bubble_x2 = HOVER_MENU_WIDTH - 18
        bubble_y2 = 160
        self._draw_round_rect(
            canvas,
            bubble_x1 + 4,
            bubble_y1 + 6,
            bubble_x2 + 4,
            bubble_y2 + 6,
            26,
            fill=DIRECT_SURFACE_SHADOW,
            outline="",
            tags=("hover_prompt_bubble",),
        )
        self._draw_round_rect(
            canvas,
            bubble_x1,
            bubble_y1,
            bubble_x2,
            bubble_y2,
            26,
            fill=DIRECT_LAYER_BG,
            outline=DIRECT_SURFACE_EDGE,
            tags=("hover_prompt_bubble",),
        )
        canvas.create_polygon(
            HOVER_MENU_WIDTH // 2 - 12,
            bubble_y2 - 2,
            HOVER_MENU_WIDTH // 2,
            HOVER_MENU_HEIGHT - 14,
            HOVER_MENU_WIDTH // 2 + 12,
            bubble_y2 - 2,
            fill=DIRECT_LAYER_BG,
            outline=DIRECT_SURFACE_EDGE,
            tags=("hover_prompt_bubble",),
        )
        hint = _avatar_hover_hint(
            self._state,
            active_skill=self._active_skill_context,
            latest_activity=_direct_activity_summary(self._activity_items),
            has_pending_approval=bool(self._pending_approval),
        )
        canvas.create_text(
            bubble_x1 + 18,
            bubble_y1 + 18,
            text=_clip(str(hint.get("line") or "我在。要我做什么？"), 82),
            fill=INK,
            anchor="nw",
            justify="left",
            width=bubble_x2 - bubble_x1 - 36,
            font=_tk_ui_font(11, bold=True),
            tags=("hover_prompt_bubble",),
        )
    def _native_hover_menu_image(self) -> tuple[Image.Image, list[tuple[int, int, int, int, str]]]:
        image = Image.new("RGBA", (HOVER_MENU_WIDTH, HOVER_MENU_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        zones: list[tuple[int, int, int, int, str]] = []
        title_font = _desktop_font(14, bold=True)
        detail_font = _desktop_font(11)
        chip_font = _desktop_font(12, bold=True)

        if self._hover_mode == "cards":
            latest_activity = _direct_activity_summary(self._activity_items)
            specs = _floating_card_action_specs(
                state=self._state,
                has_pending_approval=bool(self._pending_approval),
                active_skill=self._active_skill_context,
                latest_activity=latest_activity,
            )
            card_width = 118
            card_height = 70
            gap = 10
            start_x = 13
            start_y = 16
            for index, spec in enumerate(specs[:4]):
                action_id = str(spec["id"])
                col = index % 2
                row = index // 2
                x1 = start_x + col * (card_width + gap)
                y1 = start_y + row * (card_height + gap)
                x2 = x1 + card_width
                y2 = y1 + card_height
                active = index == 0
                fill = ACCENT if active else DIRECT_LAYER_BG
                text_fill = INVERSE_TEXT if active else INK
                detail_fill = "#DCE9EA" if active else MUTED
                draw.rounded_rectangle(
                    (x1 + 4, y1 + 6, x2 + 4, y2 + 6),
                    radius=22,
                    fill=_hex_rgba(DIRECT_SURFACE_SHADOW, DIRECT_SHADOW_ALPHA),
                )
                draw.rounded_rectangle(
                    (x1, y1, x2, y2),
                    radius=22,
                    fill=_hex_rgba(fill, 245),
                    outline=_hex_rgba(DIRECT_SURFACE_EDGE, 220) if not active else None,
                )
                draw.text((x1 + 16, y1 + 13), str(spec.get("label") or action_id), font=title_font, fill=_hex_rgba(text_fill))
                _draw_pil_text(
                    draw,
                    (x1 + 16, y1 + 38),
                    str(spec.get("detail") or ""),
                    font=detail_font,
                    fill=detail_fill,
                    max_width=card_width - 30,
                    max_lines=2,
                    line_gap=2,
                )
                zones.append((x1, y1, card_width, card_height, action_id))
            return image, zones

        specs = _hover_prompt_chip_specs()
        bubble_x1 = 14
        bubble_y1 = 18
        bubble_x2 = HOVER_MENU_WIDTH - 18
        bubble_y2 = 160
        draw.rounded_rectangle(
            (bubble_x1 + 4, bubble_y1 + 6, bubble_x2 + 4, bubble_y2 + 6),
            radius=26,
            fill=_hex_rgba(DIRECT_SURFACE_SHADOW, DIRECT_SHADOW_ALPHA),
        )
        draw.rounded_rectangle(
            (bubble_x1, bubble_y1, bubble_x2, bubble_y2),
            radius=26,
            fill=_hex_rgba(DIRECT_LAYER_BG, 246),
            outline=_hex_rgba(DIRECT_SURFACE_EDGE, 230),
        )
        draw.polygon(
            [
                (HOVER_MENU_WIDTH // 2 - 12, bubble_y2 - 2),
                (HOVER_MENU_WIDTH // 2, HOVER_MENU_HEIGHT - 14),
                (HOVER_MENU_WIDTH // 2 + 12, bubble_y2 - 2),
            ],
            fill=_hex_rgba(DIRECT_LAYER_BG, 246),
            outline=_hex_rgba(DIRECT_SURFACE_EDGE, 230),
        )
        hint = _avatar_hover_hint(
            self._state,
            active_skill=self._active_skill_context,
            latest_activity=_direct_activity_summary(self._activity_items),
            has_pending_approval=bool(self._pending_approval),
        )
        _draw_pil_text(
            draw,
            (bubble_x1 + 18, bubble_y1 + 18),
            _clip(str(hint.get("line") or "我在。要我做什么？"), 82),
            font=title_font,
            fill=INK,
            max_width=bubble_x2 - bubble_x1 - 36,
            max_lines=4,
            line_gap=3,
        )
        return image, zones

    def _draw_floating_cards(self, canvas: tk.Canvas) -> None:
        latest_activity = _direct_activity_summary(self._activity_items)
        specs = _floating_card_action_specs(
            state=self._state,
            has_pending_approval=bool(self._pending_approval),
            active_skill=self._active_skill_context,
            latest_activity=latest_activity,
        )
        card_width = 118
        card_height = 70
        gap = 10
        start_x = 13
        start_y = 16
        for index, spec in enumerate(specs[:4]):
            action_id = str(spec["id"])
            tag = f"floating_card_{action_id}"
            col = index % 2
            row = index // 2
            x1 = start_x + col * (card_width + gap)
            y1 = start_y + row * (card_height + gap)
            x2 = x1 + card_width
            y2 = y1 + card_height
            active = index == 0
            fill = ACCENT if active else DIRECT_LAYER_BG
            text_fill = INVERSE_TEXT if active else INK
            detail_fill = "#DCE9EA" if active else MUTED
            self._draw_round_rect(
                canvas,
                x1 + 4,
                y1 + 6,
                x2 + 4,
                y2 + 6,
                22,
                fill=DIRECT_SURFACE_SHADOW,
                outline="",
                tags=(tag, "floating_card_shadow"),
            )
            self._draw_round_rect(
                canvas,
                x1,
                y1,
                x2,
                y2,
                22,
                fill=fill,
                outline=DIRECT_SURFACE_EDGE if not active else "",
                tags=(tag, "floating_card_shell"),
            )
            canvas.create_text(
                x1 + 16,
                y1 + 15,
                text=str(spec.get("label") or action_id),
                anchor="nw",
                fill=text_fill,
                font=_tk_ui_font(12, bold=True),
                tags=(tag,),
            )
            canvas.create_text(
                x1 + 16,
                y1 + 38,
                text=str(spec.get("detail") or ""),
                anchor="nw",
                fill=detail_fill,
                width=card_width - 30,
                font=_tk_ui_font(9),
                tags=(tag,),
            )
            canvas.tag_bind(tag, "<Button-1>", lambda _event, value=action_id: self._run_floating_card_action(value))

    @staticmethod
    def _draw_round_rect(
        canvas: tk.Canvas,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        *,
        fill: str,
        outline: str = "",
        width: int = 1,
        tags: tuple[str, ...] = (),
    ) -> None:
        radius = max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
        canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill, tags=tags)
        canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill, tags=tags)
        canvas.create_oval(x1, y1, x1 + radius * 2, y1 + radius * 2, fill=fill, outline=fill, tags=tags)
        canvas.create_oval(x2 - radius * 2, y1, x2, y1 + radius * 2, fill=fill, outline=fill, tags=tags)
        canvas.create_oval(x1, y2 - radius * 2, x1 + radius * 2, y2, fill=fill, outline=fill, tags=tags)
        canvas.create_oval(x2 - radius * 2, y2 - radius * 2, x2, y2, fill=fill, outline=fill, tags=tags)
        if outline:
            canvas.create_arc(x1, y1, x1 + radius * 2, y1 + radius * 2, start=90, extent=90, style="arc", outline=outline, width=width, tags=tags)
            canvas.create_arc(x2 - radius * 2, y1, x2, y1 + radius * 2, start=0, extent=90, style="arc", outline=outline, width=width, tags=tags)
            canvas.create_arc(x2 - radius * 2, y2 - radius * 2, x2, y2, start=270, extent=90, style="arc", outline=outline, width=width, tags=tags)
            canvas.create_arc(x1, y2 - radius * 2, x1 + radius * 2, y2, start=180, extent=90, style="arc", outline=outline, width=width, tags=tags)
            canvas.create_line(x1 + radius, y1, x2 - radius, y1, fill=outline, width=width, tags=tags)
            canvas.create_line(x2, y1 + radius, x2, y2 - radius, fill=outline, width=width, tags=tags)
            canvas.create_line(x1 + radius, y2, x2 - radius, y2, fill=outline, width=width, tags=tags)
            canvas.create_line(x1, y1 + radius, x1, y2 - radius, fill=outline, width=width, tags=tags)

    def _draw_speech_bubble(self, canvas: tk.Canvas, layout: dict[str, Any]) -> None:
        width = int(layout["width"])
        height = int(layout["height"])
        tail = str(layout["tail"])
        tail_x = int(layout["tail_x"])
        top_pad = 12 if tail == "top" else 4
        bottom_pad = 12 if tail == "bottom" else 4
        canvas.delete("all")
        if tail == "top":
            canvas.create_polygon(
                tail_x - 12,
                top_pad + 3,
                tail_x,
                1,
                tail_x + 12,
                top_pad + 3,
                fill=DIRECT_ASSISTANT_BUBBLE,
                outline=DIRECT_SURFACE_EDGE,
            )
        elif tail == "bottom":
            canvas.create_polygon(
                tail_x - 12,
                height - bottom_pad - 3,
                tail_x,
                height - 1,
                tail_x + 12,
                height - bottom_pad - 3,
                fill=DIRECT_ASSISTANT_BUBBLE,
                outline=DIRECT_SURFACE_EDGE,
            )
        self._draw_round_rect(
            canvas,
            3,
            top_pad,
            width - 3,
            height - bottom_pad,
            24,
            fill=DIRECT_ASSISTANT_BUBBLE,
            outline=DIRECT_SURFACE_EDGE,
            tags=("bubble",),
        )
        canvas.create_line(24, top_pad + 2, width - 28, top_pad + 2, fill=DIRECT_GLASS_HIGHLIGHT, tags=("bubble",))
        canvas.create_line(26, height - bottom_pad - 2, 78, height - bottom_pad - 2, fill=DIRECT_CHAMPAGNE, tags=("bubble",))
        canvas.create_text(
            18,
            top_pad + 13,
            text=self._bubble_text,
            anchor="nw",
            fill=INK,
            width=width - 36,
            font=_tk_ui_font(12),
            tags=("bubble_text",),
        )

    def _draw_direct_chat_surface(self, *, width: int, height: int) -> None:
        canvas = self._direct_surface_canvas
        if not canvas:
            return
        canvas.delete("surface")
        shadow_offset = 4
        for rect in _direct_chat_surface_bubbles(width, height):
            if not rect.get("draw", True):
                continue
            self._draw_round_rect(
                canvas,
                rect["x"] + shadow_offset,
                rect["y"] + shadow_offset,
                rect["x"] + rect["width"] + shadow_offset,
                rect["y"] + rect["height"] + shadow_offset,
                rect["radius"],
                fill=DIRECT_TK_SHADOW,
                outline="",
                tags=("surface",),
            )
        for rect in _direct_chat_surface_bubbles(width, height):
            if not rect.get("draw", True):
                continue
            self._draw_round_rect(
                canvas,
                rect["x"],
                rect["y"],
                rect["x"] + rect["width"],
                rect["y"] + rect["height"],
                rect["radius"],
                fill=DIRECT_GLASS_FROST,
                outline=DIRECT_GLASS_BORDER,
                tags=("surface",),
            )
            canvas.create_line(
                rect["x"] + rect["radius"],
                rect["y"] + 2,
                rect["x"] + rect["width"] - rect["radius"],
                rect["y"] + 2,
                fill=DIRECT_GLASS_HIGHLIGHT,
                tags=("surface",),
            )
            canvas.create_line(
                rect["x"] + rect["radius"],
                rect["y"] + rect["height"] - 2,
                rect["x"] + rect["radius"] + 54,
                rect["y"] + rect["height"] - 2,
                fill=DIRECT_CHAMPAGNE,
                tags=("surface",),
            )
        canvas.tag_lower("surface")

    def _show_hover_menu(self, *, mode: str = "prompt") -> None:
        self._cancel_hover_menu_hide()
        self._hover_mode = "cards" if mode == "cards" else "prompt"
        self._hide_speech_surface()
        if _legacy_dialogue_layers_disabled():
            self._hide_hover_menu()
            return
        if _uses_native_desktop_layers():
            self._position_hover_menu()
            return
        if not self._hover_menu or not self._hover_menu.winfo_exists():
            menu = tk.Toplevel(self.root)
            self._hover_menu = menu
            menu.overrideredirect(True)
            menu.attributes("-topmost", True)
            menu.configure(bg=self._transparent_bg)
            self.overlay.apply_transparent_layer(menu, kind="cards" if self._hover_mode == "cards" else "bubble")
            try:
                menu.wm_attributes("-transparentcolor", self._transparent_bg)
            except tk.TclError:
                pass
            try:
                menu.attributes("-alpha", 0.97)
            except tk.TclError:
                pass
            canvas = tk.Canvas(
                menu,
                width=HOVER_MENU_WIDTH,
                height=HOVER_MENU_HEIGHT,
                bg=self._transparent_bg,
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
            self._hover_canvas = canvas
            canvas.pack(fill="both", expand=True)
            canvas.bind("<Enter>", lambda _event: self._cancel_hover_menu_hide())
            canvas.bind("<Leave>", lambda _event: self._schedule_hover_menu_hide(700))
            menu.bind("<Enter>", lambda _event: self._cancel_hover_menu_hide())
            menu.bind("<Leave>", lambda _event: self._schedule_hover_menu_hide(700))
        self._draw_hover_menu()
        self._position_hover_menu()
        try:
            self._hover_menu.deiconify()
            self._hover_menu.lift()
        except tk.TclError:
            pass

    def _position_hover_menu(self) -> None:
        if _legacy_dialogue_layers_disabled():
            self._hide_hover_menu()
            return
        if _uses_native_desktop_layers():
            if self._native_direct_chat_visible:
                self._hide_hover_menu()
                return
            image, zones = self._native_hover_menu_image()
            geometry = _hover_menu_geometry(
                icon_x=self.root.winfo_x(),
                icon_y=self.root.winfo_y(),
                size=self.size,
                screen_width=self.root.winfo_screenwidth(),
                screen_height=self.root.winfo_screenheight(),
            )
            _, _, position = geometry.partition("+")
            x_raw, _, y_raw = position.partition("+")
            try:
                x = int(x_raw)
                y = int(y_raw)
            except ValueError:
                x = self.root.winfo_x()
                y = self.root.winfo_y() - HOVER_MENU_HEIGHT - 10
            callback = self._run_floating_card_action if self._hover_mode == "cards" else self._run_hover_menu_action
            self.overlay.show_image_layer("hover", image, x=x, y=y, click_zones=zones, on_click=callback)
            return
        if not self._hover_menu or not self._hover_menu.winfo_exists():
            return
        try:
            self._hover_menu.geometry(
                _hover_menu_geometry(
                    icon_x=self.root.winfo_x(),
                    icon_y=self.root.winfo_y(),
                    size=self.size,
                    screen_width=self.root.winfo_screenwidth(),
                    screen_height=self.root.winfo_screenheight(),
                )
            )
        except tk.TclError:
            pass

    def _hide_hover_menu(self) -> None:
        self._cancel_hover_menu_hide()
        self.overlay.hide_image_layer("hover")
        if self._hover_menu and self._hover_menu.winfo_exists():
            try:
                self._hover_menu.withdraw()
            except tk.TclError:
                pass

    def _close_current_overlay(self) -> None:
        self._hide_hover_menu()
        if self._native_direct_chat_visible:
            self._close_direct_chat()
            return
        if self._direct_chat and self._direct_chat.winfo_exists():
            self._close_direct_chat()
            return
        if self._bubble and self._bubble.winfo_exists():
            self._hide_bubble()

    def _run_floating_card_action(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        if action == "approval_accept":
            self._hide_hover_menu()
            self._answer_pending_approval_from_avatar("accept")
            return
        if action == "approval_reject":
            self._hide_hover_menu()
            self._answer_pending_approval_from_avatar("reject")
            return
        self._run_hover_menu_action("talk" if action == "chat" else action)

    def _run_hover_menu_action(self, action_id: str) -> None:
        self._mark_activity()
        self._hide_hover_menu()
        if action_id == "chat":
            action_id = "talk"
        if action_id in {"talk", "settings", "skills", "progress"} and self._redirect_first_run_to_setup():
            return
        if action_id == "settings":
            self.open_settings()
            return
        if _uses_native_direct_chat() and action_id in {"talk", "settings", "skills", "progress"}:
            if action_id == "talk":
                self._focus_direct_feature_layer()
                self._open_native_direct_surface("chat")
                return
            if action_id == "skills":
                self._focus_direct_feature_layer({"skills"})
                self._direct_skill_section = "recommended"
                self._direct_skills_picker_visible = False
                self._direct_skills_detail_visible = False
                self._open_native_direct_surface("skills")
                return
            self._focus_direct_feature_layer({"activity", "approval", "artifacts"})
            self._direct_activity_empty_visible = True
            self._direct_activity_detail_visible = False
            self._direct_activity_more_visible = False
            self._open_native_direct_surface("progress")
            return
        if action_id == "talk":
            self._focus_direct_feature_layer()
            self._run_native_control_command("direct_chat")
            return
        if action_id == "settings":
            self.open_settings()
            return
        if action_id == "skills":
            self._focus_direct_feature_layer({"skills"})
            self._reply_with_skill_picker()
            return
        if action_id == "progress":
            self._focus_direct_feature_layer({"activity", "approval", "artifacts"})
            self._run_native_control_command("progress")
            return
        self.open_direct_chat()

    def _on_avatar_enter(self, _event: tk.Event | None = None) -> None:
        now = time.monotonic()
        if now - self._last_hover_effect_at < 2.8:
            return
        latest_activity = _direct_activity_summary(self._activity_items)
        hint = _avatar_hover_hint(
            self._state,
            active_skill=self._active_skill_context,
            latest_activity=latest_activity,
            has_pending_approval=bool(self._pending_approval),
        )
        effect = str(hint.get("effect") or _hover_effect_for_state(self._state))
        if self._state == "idle":
            effect = ""
        line = str(hint.get("line") or "").strip()
        if not effect and not line:
            return
        self._last_hover_effect_at = now
        if effect:
            self._start_interaction_effect(effect)

    def set_state(self, state: str) -> None:
        if not self._manifest:
            return
        if state != self._state:
            self._animation_frame = 0
            self._interaction_effect = None
        self._state = state
        self._render_avatar_frame()
        self._rebuild_direct_companion_card()

    def _state_image(self, state: str) -> Image.Image | None:
        if not self._manifest:
            return None
        state_key = str(state or "").strip()
        frame_index = 0 if state_key == "idle" else self._animation_frame
        sprite = _sprite_frame(self._manifest, state_key, frame_index)
        if sprite is not None:
            sheet_path, box = sprite
            try:
                cache_key = f"atlas:{sheet_path.resolve()}:{sheet_path.stat().st_mtime_ns}"
            except OSError:
                cache_key = ""
            atlas = self._avatar_cache.get(cache_key) if cache_key else None
            if atlas is None and cache_key:
                try:
                    atlas = Image.open(sheet_path).convert("RGBA")
                    self._avatar_cache[cache_key] = atlas
                except Exception:
                    atlas = None
            if atlas is not None:
                return atlas.crop(box)
        path = _state_file(self._manifest, state_key, frame_index)
        if path is None or not path.exists():
            path = _state_file(self._manifest, "idle", 0)
        if path is None or not path.exists():
            return None
        try:
            cache_key = f"{path.resolve()}:{path.stat().st_mtime_ns}"
        except OSError:
            return None
        image = self._avatar_cache.get(cache_key)
        if image is None:
            image = Image.open(path).convert("RGBA")
            self._avatar_cache[cache_key] = image
        return image.copy()

    def _render_avatar_frame(self) -> None:
        image = self._state_image(self._state)
        if image is None:
            return
        render_scale = 1.0
        if sys.platform == "darwin":
            try:
                render_scale = _native_render_scale(self.overlay.native_backing_scale())
            except Exception:
                render_scale = 2.0
        pixel_size = max(1, _scaled_int(self.size, render_scale))
        transform = _animation_transform(self._state, self._animation_frame)
        if self._interaction_effect:
            effect_frame = self._animation_frame - self._interaction_effect_started_at
            effect_transform = _interaction_effect_transform(self._interaction_effect, effect_frame)
            if effect_transform is None:
                self._interaction_effect = None
            else:
                transform = _merge_avatar_transforms(transform, effect_transform)
        max_side = max(24, int(self.size * 0.88 * transform["scale"] * render_scale))
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if transform["rotation"]:
            image = image.rotate(
                transform["rotation"],
                resample=Image.Resampling.BICUBIC,
                expand=True,
            )
            if image.width > pixel_size or image.height > pixel_size:
                image.thumbnail((pixel_size, pixel_size), Image.Resampling.LANCZOS)
        if transform["alpha"] < 1.0:
            alpha = image.getchannel("A").point(lambda value: int(value * transform["alpha"]))
            image.putalpha(alpha)
        canvas = Image.new("RGBA", (pixel_size, pixel_size), (0, 0, 0, 0))
        x = (pixel_size - image.width) // 2 + _scaled_int(transform["dx"], render_scale)
        y = (pixel_size - image.height) // 2 + _scaled_int(transform["dy"], render_scale)
        x = max(0, min(pixel_size - image.width, x))
        y = max(0, min(pixel_size - image.height, y))
        _draw_avatar_aura(canvas, self._state, self._animation_frame)
        canvas.alpha_composite(image, (x, y))
        _draw_reaction_chip(canvas, self._interaction_effect, self._animation_frame)
        if sys.platform == "darwin":
            self.overlay.update_avatar_image(canvas, x=self.root.winfo_x(), y=self.root.winfo_y(), size=self.size)
            try:
                self.root.withdraw()
            except tk.TclError:
                pass
        else:
            self._photo = ImageTk.PhotoImage(canvas)
            self.label.configure(image=self._photo)

    def _start_interaction_effect(self, effect: str | None) -> None:
        if not effect:
            return
        if _interaction_effect_transform(effect, 0) is None:
            return
        self._interaction_effect = str(effect)
        self._interaction_effect_started_at = self._animation_frame
        self._render_avatar_frame()

    def _animate_avatar(self) -> None:
        try:
            self._animation_frame = (self._animation_frame + 1) % 10_000
            self._render_avatar_frame()
            self._animation_timer = self.root.after(AVATAR_FRAME_MS, self._animate_avatar)
        except tk.TclError:
            self._animation_timer = None

    @staticmethod
    def _interaction_line(index: int) -> str:
        return INTERACTION_LINES[index % len(INTERACTION_LINES)]

    def _poke_reaction(self) -> None:
        self._mark_activity()
        line = self._interaction_line(self._poke_count)
        self._poke_count += 1
        if self._last_action:
            self._last_action.set(line)
        self.show_bubble(line, state="success", duration=2600)
        self._start_interaction_effect("poke")

    def _wake_from_sleep(self) -> None:
        line = _wake_line(self._wake_count)
        self._wake_count += 1
        self._interaction_count += 1
        self._append_chat("assistant", line)
        self._record_activity("interaction", "唤醒", "JiuMe 从安静待机回来了。")
        self._persist_companion_memory()
        self._rebuild_direct_companion_card()
        if self._last_action:
            self._last_action.set(line)
        self.show_bubble(line, state="speaking", duration=2800)
        self._start_interaction_effect("poke")

    def _run_interaction_by_id(self, action_id: str) -> None:
        action = interaction_by_id(action_id)
        if action:
            self._run_interaction_action(action)

    def _run_interaction_action(self, action: dict[str, Any]) -> None:
        title = str(action.get("title") or action.get("label") or "互动")
        line = str(action.get("line") or title)
        state = str(action.get("state") or "speaking")
        effect = str(action.get("effect") or "")
        self._interaction_count += 1
        self._append_chat("assistant", line)
        self._record_activity("interaction", title, f"第 {self._interaction_count} 次桌面互动")
        self._persist_companion_memory()
        self._rebuild_direct_companion_card()
        if self._last_action:
            self._last_action.set(line)
        self.show_bubble(line, state=state, duration=3600)
        self._start_interaction_effect(effect)

    def _run_native_rps_command(self, command: dict[str, str]) -> None:
        action = str(command.get("action") or "").strip()
        self._interaction_count += 1
        if action == "start":
            line = "来，石头剪刀布。你可以直接说“我出石头 / 我出剪刀 / 我出布”。"
            self._append_chat("assistant", line)
            self._record_activity("interaction", "猜拳", "JiuMe 等你出拳。")
            self._persist_companion_memory()
            self._rebuild_direct_companion_card()
            if self._last_action:
                self._last_action.set("猜拳开始。")
            self.show_bubble(line, state="speaking", duration=4200)
            self._start_interaction_effect("peek")
            return

        move = str(command.get("move") or "rock")
        jiume_move = RPS_MOVES[(self._interaction_count + len(move)) % len(RPS_MOVES)]
        result = _rps_round(move, jiume_move)
        line = str(result["line"])
        self._append_chat("assistant", line)
        self._record_activity(
            "interaction",
            "猜拳",
            f"你出{_rps_move_label(str(result['userMove']))}，JiuMe 出{_rps_move_label(str(result['jiumeMove']))}。",
        )
        self._persist_companion_memory()
        self._rebuild_direct_companion_card()
        if self._last_action:
            self._last_action.set(line)
        self.show_bubble(line, state=str(result["state"]), duration=4200)
        self._start_interaction_effect(str(result["effect"]))

    def _run_native_dice_command(self, command: dict[str, int]) -> None:
        sides = _normalize_dice_sides(command.get("sides"))
        self._interaction_count += 1
        result = _dice_roll(sides, seed=self._interaction_count + sides)
        line = str(result["line"])
        self._append_chat("assistant", line)
        self._record_activity("interaction", "掷骰子", f"D{sides} -> {result['result']}")
        self._persist_companion_memory()
        self._rebuild_direct_companion_card()
        if self._last_action:
            self._last_action.set(line)
        self.show_bubble(line, state=str(result["state"]), duration=4200)
        self._start_interaction_effect(str(result["effect"]))

    def _run_native_coin_command(self, command: dict[str, str]) -> None:
        mode = str(command.get("mode") or "coin")
        self._interaction_count += 1
        result = _coin_flip(mode, seed=self._interaction_count)
        line = str(result["line"])
        self._append_chat("assistant", line)
        title = "抽签" if str(result["mode"]) == "draw" else "抛硬币"
        self._record_activity("interaction", title, str(result["result"]))
        self._persist_companion_memory()
        self._rebuild_direct_companion_card()
        if self._last_action:
            self._last_action.set(line)
        self.show_bubble(line, state=str(result["state"]), duration=4200)
        self._start_interaction_effect(str(result["effect"]))

    def toggle_panel(self) -> None:
        self._mark_activity()
        self._toggle_direct_chat_from_avatar()

    def open_direct_chat(self) -> None:
        self._mark_activity()
        if self._redirect_first_run_to_setup():
            return
        self._hide_speech_surface()
        if _uses_native_direct_chat():
            self._open_native_direct_surface("chat")
            return
        if self._direct_chat and self._direct_chat.winfo_exists():
            self._direct_chat.lift()
            if self._direct_entry:
                self._direct_entry.focus_set()
            return
        chat = tk.Toplevel(self.root)
        self._direct_chat = chat
        chat.configure(bg=self._transparent_bg)
        chat.overrideredirect(True)
        chat.attributes("-topmost", True)
        self.overlay.apply_transparent_layer(chat, kind="chat")
        try:
            chat.wm_attributes("-transparentcolor", self._transparent_bg)
        except tk.TclError:
            pass
        chat.bind("<Escape>", lambda _event: self._close_direct_chat())

        surface = tk.Canvas(
            chat,
            bg=self._transparent_bg,
            bd=0,
            highlightthickness=0,
            width=ONE_LINE_DIRECT_WIDTH,
            height=ONE_LINE_DIRECT_HEIGHT,
        )
        self._direct_surface_canvas = surface
        surface.pack(fill="both", expand=True)
        rect = _direct_chat_content_rect(ONE_LINE_DIRECT_WIDTH, ONE_LINE_DIRECT_HEIGHT)
        layer_bg = self._transparent_bg
        shell = tk.Frame(surface, bg=layer_bg, bd=0, highlightthickness=0)
        self._direct_surface_window = surface.create_window(
            rect["x"],
            rect["y"],
            window=shell,
            anchor="nw",
            width=rect["width"],
            height=rect["height"],
        )

        self._direct_scroll_canvas = None
        self._direct_scrollbar = None
        self._direct_content_frame = None

        content = shell

        composer_height = DIRECT_CHAT_COMPOSER_HEIGHT
        composer = tk.Canvas(
            shell,
            bg=layer_bg,
            bd=0,
            highlightthickness=0,
            width=DIRECT_CHAT_COMPOSER_WIDTH,
            height=composer_height,
        )
        self._direct_composer_frame = composer
        composer.pack(anchor="e", padx=(0, 14), pady=(8, 6))
        self._direct_entry = tk.Entry(
            composer,
            bg=DIRECT_INPUT_BG,
            fg=MUTED,
            relief="flat",
            insertbackground=INK,
            font=_tk_ui_font(12),
            bd=0,
            highlightthickness=0,
        )
        self._direct_entry.insert(0, ONE_LINE_INPUT_HINT)
        self._one_line_question_active = True

        def clear_one_line_hint(_event: tk.Event | None = None) -> None:
            if self._direct_entry and self._one_line_question_active:
                self._direct_entry.delete(0, "end")
                self._direct_entry.configure(fg=INK)
                self._one_line_question_active = False

        def restore_one_line_hint(_event: tk.Event | None = None) -> None:
            if self._direct_entry and not self._direct_entry.get().strip():
                self._direct_entry.delete(0, "end")
                self._direct_entry.insert(0, ONE_LINE_INPUT_HINT)
                self._direct_entry.configure(fg=MUTED)
                self._one_line_question_active = True

        self._direct_entry.bind("<KeyPress>", clear_one_line_hint)
        self._direct_entry.bind("<Button-1>", clear_one_line_hint)
        self._direct_entry.bind("<FocusOut>", restore_one_line_hint)
        self._direct_entry.bind("<Return>", lambda _event: self._send_direct_message())
        entry_window = composer.create_window(
            18,
            composer_height // 2,
            window=self._direct_entry,
            anchor="w",
            height=34,
            tags=("direct_composer_control",),
        )
        send_window: int | None = None
        for spec in _direct_chat_composer_action_specs():
            if spec["id"] != "send":
                continue
            send_width = 76
            send_height = 40
            send_button = tk.Canvas(
                composer,
                width=send_width,
                height=send_height,
                bg=layer_bg,
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
            self._draw_round_rect(
                send_button,
                3,
                4,
                send_width - 1,
                send_height - 1,
                20,
                fill=DIRECT_TK_SHADOW,
                outline="",
                tags=("direct_send_button",),
            )
            self._draw_round_rect(
                send_button,
                1,
                1,
                send_width - 4,
                send_height - 4,
                20,
                fill=DIRECT_ACTION_BG,
                outline=DIRECT_CHAMPAGNE,
                tags=("direct_send_button",),
            )
            send_button.create_text(
                send_width // 2 - 1,
                send_height // 2,
                text=str(spec["label"]),
                fill=INVERSE_TEXT,
                font=_tk_ui_font(11, bold=True),
                tags=("direct_send_button",),
            )
            send_button.tag_bind("direct_send_button", "<Button-1>", lambda _event: self._send_direct_message())
            send_button.bind("<Button-1>", lambda _event: self._send_direct_message())
            send_window = composer.create_window(
                0,
                composer_height // 2,
                window=send_button,
                anchor="e",
                width=send_width,
                height=send_height,
                tags=("direct_composer_control",),
            )

        def draw_direct_composer(event: tk.Event | None = None) -> None:
            width = int(getattr(event, "width", 0) or composer.winfo_width() or DIRECT_CHAT_COMPOSER_WIDTH)
            height = composer_height
            composer.delete("direct_composer_bubble")
            self._draw_round_rect(
                composer,
                3,
                4,
                width - 2,
                height - 1,
                24,
                fill=DIRECT_TK_SHADOW,
                outline="",
                tags=("direct_composer_bubble",),
            )
            self._draw_round_rect(
                composer,
                1,
                1,
                width - 5,
                height - 5,
                24,
                fill=DIRECT_INPUT_BG,
                outline=DIRECT_SURFACE_EDGE,
                tags=("direct_composer_bubble",),
            )
            composer.create_line(22, 5, max(24, width - 26), 5, fill=DIRECT_GLASS_HIGHLIGHT, tags=("direct_composer_bubble",))
            composer.create_line(24, height - 6, 88, height - 6, fill=DIRECT_CHAMPAGNE, tags=("direct_composer_bubble",))
            composer.coords(entry_window, 18, height // 2)
            right_padding = 104 if send_window is not None else 22
            composer.itemconfigure(entry_window, width=max(120, width - right_padding - 18), height=36)
            if send_window is not None:
                composer.coords(send_window, width - 12, height // 2)
            composer.tag_lower("direct_composer_bubble")

        composer.bind("<Configure>", draw_direct_composer)
        composer.after_idle(draw_direct_composer)

        self._position_direct_chat()
        self._direct_entry.focus_set()

    def _open_native_direct_surface(self, surface: str) -> None:
        self._native_direct_surface = _normalize_native_direct_surface(surface)
        self._native_direct_chat_visible = True
        self._hide_speech_surface()
        self._hide_hover_menu()
        self._position_direct_chat()

    def _run_rest_action(self) -> None:
        action = quick_action_by_id("rest")
        if action:
            self._run_quick_action(action)

    def _close_direct_chat(self) -> None:
        self.overlay.hide_image_layer("direct_chat")
        self._native_direct_chat_visible = False
        self._native_direct_surface = "chat"
        if self._direct_chat and self._direct_chat.winfo_exists():
            self._direct_chat.destroy()
        self._direct_chat = None
        self._direct_entry = None
        self._direct_chat_frame = None
        self._direct_companion_frame = None
        self._direct_help_frame = None
        self._direct_service_frame = None
        self._direct_artifact_frame = None
        self._direct_activity_frame = None
        self._direct_approval_frame = None
        self._direct_quick_frame = None
        self._direct_skills_frame = None
        self._direct_settings_frame = None
        self._direct_composer_frame = None
        self._direct_scroll_canvas = None
        self._direct_scrollbar = None
        self._direct_content_frame = None
        self._direct_surface_canvas = None
        self._direct_surface_window = None
        self._one_line_question_active = False
        self._direct_settings_visible = False
        self._direct_settings_picker_visible = False
        self._direct_settings_detail_visible = False
        self._direct_activity_more_visible = False
        self._direct_activity_empty_visible = False
        self._direct_activity_detail_visible = False
        self._direct_approval_feedback_visible = False
        self._direct_skills_picker_visible = False
        self._direct_skills_detail_visible = False
        self._direct_help_section = "overview"
        self._direct_artifact_category = ""
        self._direct_companion_visible = False
        self._direct_companion_more_visible = False
        self._direct_chat_scroll_offset = 0
        self._direct_name_var = None
        self._direct_purpose_var = None
        self._direct_tone_var = None
        self._direct_mode_var = None

    def _tuck_avatar_surfaces(self) -> None:
        self._hide_hover_menu()
        self._close_direct_chat()
        if self._panel and self._panel.winfo_exists():
            self._panel.destroy()
        self._panel = None
        self._approval_frame = None
        self._approval_anchor = None
        self._chat_frame = None
        self._activity_frame = None
        self._skills_frame = None
        self._close_settings()
        if self._artifact_panel and self._artifact_panel.winfo_exists():
            self._artifact_panel.destroy()
        self._artifact_panel = None
        self._hide_work_hud()
        self._hide_bubble()

    def open_panel(self) -> None:
        self._mark_activity()
        self.open_direct_chat()
        self.show_bubble("我把大面板收成头像旁边的气泡层了。直接说，或从悬浮入口继续展开。", state="speaking", duration=3600)
        return

    def _open_legacy_panel(self) -> None:
        # Legacy boxed control panel is retired; keep the method as a compatibility shim.
        self.open_panel()

    def _append_chat(self, role: str, text: str) -> None:
        message = " ".join(str(text or "").split())
        if not message:
            return
        self._chat_items.append({"role": role, "text": _clip(message, 180)})
        del self._chat_items[:-DIRECT_CHAT_HISTORY_LIMIT]
        self._direct_chat_scroll_offset = 0
        if self._stream_chat_index is not None:
            self._stream_chat_index = min(self._stream_chat_index, len(self._chat_items) - 1)
        self._persist_desktop_history()
        self._rebuild_chat_rows()
        self._rebuild_direct_chat_rows()
        if self._native_direct_chat_visible:
            self._position_direct_chat()

    def _upsert_assistant_chat(self, text: str) -> None:
        message = " ".join(str(text or "").split())
        if not message:
            return
        if (
            self._stream_chat_index is None
            or self._stream_chat_index >= len(self._chat_items)
            or self._chat_items[self._stream_chat_index].get("role") != "assistant"
        ):
            self._append_chat("assistant", message)
            self._stream_chat_index = len(self._chat_items) - 1
            return
        self._chat_items[self._stream_chat_index]["text"] = _clip(message, 180)
        self._direct_chat_scroll_offset = 0
        self._persist_desktop_history()
        self._rebuild_chat_rows()
        self._rebuild_direct_chat_rows()

    def _finish_assistant_stream(self, text: str = "", *, state: str = "") -> None:
        if text:
            self._upsert_assistant_chat(text)
            self._play_conversation_reaction(text, state=state)
        self._stream_chat_index = None

    def _clear_native_chat_thread(self, raw: str = "") -> None:
        self._chat_items = []
        self._stream_chat_index = None
        self._gateway_reply = ""
        self._direct_chat_scroll_offset = 0
        reply = "好，我把这段对话收起来了。长期记忆和当前 skill 还在。"
        if self._last_action:
            self._last_action.set("已清空当前对话")
        self._append_chat("assistant", reply)
        self._rebuild_direct_companion_card()
        self.show_bubble(reply, state="success", duration=3200)

    def _rebuild_chat_rows(self) -> None:
        # Legacy boxed chat log is retired; conversation is drawn by _rebuild_direct_chat_rows().
        if self._chat_frame and self._chat_frame.winfo_exists():
            self._chat_frame.pack_forget()

    def _rebuild_direct_chat_rows(self) -> None:
        if not self._direct_chat_frame:
            return
        for child in self._direct_chat_frame.winfo_children():
            child.destroy()
        preview = _conversation_preview_items(
            self._chat_items,
            offset=getattr(self, "_direct_chat_scroll_offset", 0),
        )
        if not preview:
            self._position_direct_chat()
            return
        for item in preview:
            role = str(item.get("role") or "assistant")
            is_user = role == "user"
            row = tk.Frame(self._direct_chat_frame, bg=self._transparent_bg)
            row.pack(fill="x", pady=(4, 0))
            message_text = str(item.get("text") or "")
            metrics = _direct_message_bubble_metrics(message_text, DIRECT_CHAT_WIDTH)
            bubble_width = int(metrics["width"])
            bubble_height = int(metrics["height"])
            bubble = tk.Canvas(
                row,
                width=bubble_width,
                height=bubble_height,
                bg=self._transparent_bg,
                bd=0,
                highlightthickness=0,
            )
            bubble.pack(side="right" if is_user else "left", padx=(58, 0) if is_user else (0, 58))
            fill = DIRECT_USER_BUBBLE if is_user else DIRECT_ASSISTANT_BUBBLE
            text_fill = INVERSE_TEXT if is_user else INK
            edge_fill = DIRECT_USER_BUBBLE_EDGE if is_user else DIRECT_SURFACE_EDGE
            x1 = 4 if is_user else 12
            x2 = bubble_width - 12 if is_user else bubble_width - 4
            y1 = 2
            y2 = bubble_height - 4
            radius = 18
            self._draw_round_rect(
                bubble,
                x1,
                y1,
                x2,
                y2,
                radius,
                fill=fill,
                outline=edge_fill,
                tags=("direct_message",),
            )
            bubble.create_text(
                x1 + 14,
                y1 + 14,
                text=message_text,
                fill=text_fill,
                anchor="nw",
                justify="left",
                width=int(metrics["text_width_limit"]),
                font=_tk_ui_font(11),
                tags=("direct_message_text",),
            )
        self._position_direct_chat()

    def _direct_frame_is_packed(self, frame: tk.Frame | None) -> bool:
        return bool(frame and frame.winfo_exists() and frame.winfo_manager() == "pack")

    def _focus_direct_feature_layer(self, keep: set[str] | tuple[str, ...] | list[str] = ()) -> None:
        keep_set = {str(item) for item in keep}
        frame_map = {
            "companion": self._direct_companion_frame,
            "help": self._direct_help_frame,
            "service": self._direct_service_frame,
            "artifacts": self._direct_artifact_frame,
            "activity": self._direct_activity_frame,
            "approval": self._direct_approval_frame,
            "quick": self._direct_quick_frame,
            "skills": self._direct_skills_frame,
            "settings": self._direct_settings_frame,
        }
        for name, frame in frame_map.items():
            if name not in keep_set and frame and frame.winfo_exists():
                frame.pack_forget()
        if "companion" not in keep_set:
            self._direct_companion_visible = False
            self._direct_companion_more_visible = False
        if "help" not in keep_set:
            self._direct_help_section = "overview"
        if "activity" not in keep_set:
            self._direct_activity_more_visible = False
            self._direct_activity_empty_visible = False
            self._direct_activity_detail_visible = False
        if "approval" not in keep_set:
            self._direct_approval_feedback_visible = False
        if "skills" not in keep_set:
            self._direct_skills_picker_visible = False
            self._direct_skills_detail_visible = False
            self._direct_skill_section = "recommended"
        if "settings" not in keep_set:
            self._direct_settings_visible = False
            self._direct_settings_picker_visible = False
            self._direct_settings_detail_visible = False

    def _current_presence_summary(self) -> dict[str, str]:
        companion = _companion_status(
            self._interaction_count,
            self._idle_companion_index,
            enabled=self._idle_companion_enabled,
        )
        latest_activity = self._activity_items[0] if self._activity_items else None
        return _presence_summary(
            state=self._state,
            has_pending_approval=bool(self._pending_approval),
            active_skill=self._active_skill_context,
            latest_activity=latest_activity,
            companion=companion,
            service=_direct_service_status_summary(read_service_status()),
        )

    def _current_memory_summary(self) -> dict[str, Any]:
        return _memory_summary(
            self._chat_items,
            self._activity_items,
            interaction_count=self._interaction_count,
            active_skill=self._active_skill_context,
            profile_memories=self._active_profile_memories(),
        )

    def _active_profile_memories(self) -> list[str]:
        twin = self._active_twin() or {}
        return normalize_twin_memories(twin.get("memories"))

    def _active_attention_names(self) -> list[str]:
        twin = self._active_twin() or {}
        return [str(twin.get("displayName") or "")]

    def _pack_direct_speech_bubble(
        self,
        parent: tk.Misc,
        *,
        title: str,
        detail: str,
        padx: int = 10,
        pady: tuple[int, int] = (8, 7),
    ) -> tk.Canvas:
        layer_bg = self._transparent_bg
        safe_title = _clip(str(title or ""), 34)
        safe_detail = _clip(str(detail or ""), 130)
        height = 70 + (18 if len(safe_detail) > 58 else 0)
        width_hint = _direct_speech_bubble_width(safe_title, safe_detail)
        bubble = tk.Canvas(
            parent,
            width=width_hint,
            height=height,
            bg=layer_bg,
            bd=0,
            highlightthickness=0,
        )
        bubble.pack(anchor="w", padx=padx, pady=pady)

        def draw_speech(event: tk.Event | None = None) -> None:
            width = int(getattr(event, "width", 0) or bubble.winfo_width() or width_hint)
            bubble.delete("direct_speech_bubble")
            self._draw_round_rect(
                bubble,
                13,
                5,
                width - 4,
                height - 1,
                24,
                fill=DIRECT_TK_SHADOW,
                outline="",
                tags=("direct_speech_bubble",),
            )
            self._draw_round_rect(
                bubble,
                9,
                1,
                width - 8,
                height - 6,
                24,
                fill=DIRECT_ASSISTANT_BUBBLE,
                outline=DIRECT_SURFACE_EDGE,
                tags=("direct_speech_bubble",),
            )
            bubble.create_line(31, 3, width - 32, 3, fill=DIRECT_GLASS_HIGHLIGHT, tags=("direct_speech_bubble",))
            bubble.create_line(31, height - 7, 78, height - 7, fill=DIRECT_CHAMPAGNE, tags=("direct_speech_bubble",))
            bubble.create_text(
                28,
                14,
                text=safe_title,
                fill=INK,
                anchor="nw",
                font=_tk_ui_font(10, bold=True),
                tags=("direct_speech_bubble",),
            )
            bubble.create_text(
                28,
                34,
                text=safe_detail,
                fill=MUTED,
                anchor="nw",
                justify="left",
                width=max(180, width - 50),
                font=_tk_ui_font(9),
                tags=("direct_speech_bubble",),
            )

        bubble.bind("<Configure>", draw_speech)
        bubble.after_idle(draw_speech)
        return bubble

    def _chat_assistant_name(self) -> str:
        twin = self._active_twin() or {}
        return str(twin.get("displayName") or "JiuMe")

    def _reply_with_presence_summary(self) -> None:
        summary = self._current_presence_summary()
        reply = f"我现在是「{summary['label']}」。{summary['detail']}"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(reply)
        mood = str(summary.get("mood") or "speaking")
        self.show_bubble(reply, state=mood if mood in AVATAR_STATUS_BADGES else "speaking", duration=4200)
        self._rebuild_direct_companion_card()

    def _reply_with_identity_summary(self) -> None:
        summary = _identity_summary(self._chat_assistant_name())
        reply = f"{summary['label']}。{summary['detail']}"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(str(summary["label"]))
        self._record_activity("interaction", "身份说明", "JiuMe 说明自己是人形桌面分身，不是宠物。")
        self.show_bubble(reply, state="speaking", duration=6200)
        self._start_interaction_effect("nod")
        self._rebuild_direct_companion_card()

    def _reply_with_help_summary(self) -> None:
        summary = _help_summary()
        reply = f"{summary['label']}：{summary['detail']}。"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(str(summary["label"]))
        self._record_activity("interaction", "能力说明", "用户查看 JiuMe 的桌面入口能力。")
        self._direct_help_section = "overview"
        self._show_direct_help_card()
        self.show_bubble(reply, state="speaking", duration=6200)
        self._rebuild_direct_companion_card()

    def _reply_with_attention_summary(self) -> None:
        summary = _attention_summary(self._active_skill_context)
        reply = str(summary["detail"])
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(str(summary["label"]))
        self._record_activity("interaction", "应声", reply)
        self._show_direct_help_card()
        self.show_bubble(reply, state="speaking", duration=4200)
        self._start_interaction_effect(str(summary.get("effect") or "wave"))
        self._rebuild_direct_companion_card()

    def _reply_with_settings_summary(self) -> None:
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return
        summary = _settings_summary(twin, size=self.size)
        reply = str(summary["detail"])
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(str(summary["label"]))
        self._record_activity("interaction", "设置回忆", "JiuMe 用第一人称说明当前分身设定。")
        self.show_bubble(reply, state="speaking", duration=6200)
        self._rebuild_direct_companion_card()

    def _reply_with_active_skill_summary(self) -> None:
        summary = _active_skill_summary(self._active_skill_context)
        reply = str(summary["detail"])
        self._append_chat("assistant", reply)
        self._direct_skill_section = "current"
        self._direct_skills_detail_visible = True
        self._rebuild_direct_skill_shortcuts()
        if self._last_action:
            self._last_action.set(str(summary["label"]))
        self._record_activity(
            "skill",
            "当前 skill",
            str(summary["displayName"]) if summary.get("hasSkill") else "未固定 skill",
        )
        state = "speaking" if summary.get("hasSkill") else "idle"
        if summary.get("hasSkill"):
            self._start_interaction_effect("peek")
        self.show_bubble(reply, state=state, duration=5600)
        self._rebuild_direct_companion_card()

    def _reply_with_skill_picker(self, raw: str = "") -> None:
        if not self._direct_chat or not self._direct_chat.winfo_exists():
            self.open_direct_chat()
        if raw:
            self._append_chat("user", raw)
        self._focus_direct_feature_layer({"skills"})
        skill_rows = self._direct_skill_rows()
        suggestions = _skill_picker_suggestions(skill_rows)
        summary = _skill_picker_reply(suggestions)
        reply = str(summary["detail"])
        self._append_chat("assistant", reply)
        self._direct_skill_section = "recommended"
        self._direct_skills_picker_visible = False
        self._direct_skills_detail_visible = False
        self._rebuild_direct_skill_shortcuts()
        if self._last_action:
            self._last_action.set(str(summary["label"]))
        self._record_activity(
            "skill",
            "头像旁选择 skill",
            "、".join(str(item.get("displayName") or item.get("id") or "") for item in suggestions[:3]) or "等待任务上下文",
        )
        self.show_bubble(reply, state="speaking", duration=6200)
        self._start_interaction_effect("nod")
        self._rebuild_direct_companion_card()

    def _reply_with_companion_plan(self) -> None:
        presence = self._current_presence_summary()
        memory = self._current_memory_summary()
        activity_summary = _direct_activity_summary(self._activity_items)
        suggestions = _direct_companion_suggestion_specs(
            presence=presence,
            activity_summary=activity_summary,
            active_skill=self._active_skill_context,
            has_artifact_tray=bool(_activity_artifact_cards(self._activity_items)),
        )
        summary = _companion_plan_summary(
            presence=presence,
            memory=memory,
            suggestions=suggestions,
            active_skill=self._active_skill_context,
        )
        reply = str(summary["detail"])
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(str(summary["label"]))
        self._record_activity("interaction", str(summary["label"]), reply)
        self._start_interaction_effect("nod")
        self._direct_companion_visible = True
        self._direct_companion_more_visible = False
        self._rebuild_direct_companion_card()
        mood = str(summary.get("mood") or "speaking")
        state = mood if mood in AVATAR_STATUS_BADGES and mood != "sleep" else "speaking"
        self.show_bubble(reply, state=state, duration=6200)

    def _hide_direct_help_card(self) -> None:
        if self._direct_help_frame and self._direct_help_frame.winfo_exists():
            self._direct_help_frame.pack_forget()
        self._position_direct_chat()

    def _set_direct_help_section(self, section: str) -> None:
        self._direct_help_section = _normalize_direct_help_section(section)
        self._show_direct_help_card()

    def _pack_direct_value_bubbles(
        self,
        parent: tk.Misc,
        items: list[dict[str, str]],
        *,
        padx: int = 0,
        pady: tuple[int, int] = (0, 6),
    ) -> None:
        if not items:
            return
        layer_bg = self._transparent_bg
        shell = tk.Frame(parent, bg=layer_bg, highlightthickness=0)
        shell.pack(fill="x", padx=padx, pady=pady)
        for index, item in enumerate(items):
            label = _clip(str(item.get("label") or ""), 16)
            value = _clip(str(item.get("value") or ""), 80)
            height = 56 + (16 if len(value) > 34 else 0)
            bubble_width = _direct_value_bubble_width(label, value)
            from_user_side = index % 2 == 1
            anchor_side = "e" if from_user_side else "w"
            bubble = tk.Canvas(
                shell,
                width=bubble_width,
                height=height,
                bg=layer_bg,
                bd=0,
                highlightthickness=0,
            )
            bubble.pack(anchor=anchor_side, padx=(24, 0) if from_user_side else (0, 24), pady=(0, 6))
            fill = DIRECT_INPUT_BG if from_user_side else DIRECT_ASSISTANT_BUBBLE
            text_x = 20 if not from_user_side else 18
            bubble_x1 = 1 if from_user_side else 4
            bubble_x2 = bubble_width - (13 if from_user_side else 7)
            self._draw_round_rect(
                bubble,
                bubble_x1 + (2 if from_user_side else 3),
                5,
                bubble_x2 + 4,
                height - 1,
                20,
                fill=DIRECT_TK_SHADOW,
                outline="",
                tags=("direct_value_bubble_shadow",),
            )
            self._draw_round_rect(
                bubble,
                bubble_x1,
                2,
                bubble_x2,
                height - 5,
                20,
                fill=fill,
                outline=DIRECT_SURFACE_EDGE,
                tags=("direct_value_bubble",),
            )
            bubble.create_text(
                text_x,
                14,
                text=label,
                anchor="nw",
                fill=MUTED,
                font=_tk_ui_font(9, bold=True),
                tags=("direct_value_label",),
            )
            bubble.create_text(
                text_x,
                31,
                text=value,
                anchor="nw",
                fill=INK,
                width=max(132, bubble_width - 46),
                font=_tk_ui_font(10),
                tags=("direct_value_text",),
            )

    def _pack_direct_text_preview_bubble(
        self,
        parent: tk.Misc,
        *,
        title: str,
        text: str,
        padx: int = 0,
        pady: tuple[int, int] = (0, 8),
    ) -> tk.Canvas:
        layer_bg = self._transparent_bg
        safe_title = _clip(str(title or "预览"), 24)
        safe_text = _clip(str(text or "这个产物没有可预览的文本。"), 430)
        lines = max(2, min(12, (len(safe_text) // 28) + 2))
        height = 54 + lines * 16
        width_hint = _direct_text_preview_bubble_width(safe_title, safe_text)
        bubble = tk.Canvas(
            parent,
            width=width_hint,
            height=height,
            bg=layer_bg,
            bd=0,
            highlightthickness=0,
        )
        bubble.pack(anchor="w", padx=padx, pady=pady)

        def draw_preview(event: tk.Event | None = None) -> None:
            width = int(getattr(event, "width", 0) or bubble.winfo_width() or width_hint)
            bubble.delete("direct_text_preview_bubble")
            self._draw_round_rect(
                bubble,
                6,
                6,
                width - 2,
                height - 1,
                22,
                fill=DIRECT_TK_SHADOW,
                outline="",
                tags=("direct_text_preview_bubble",),
            )
            self._draw_round_rect(
                bubble,
                2,
                2,
                width - 6,
                height - 6,
                22,
                fill=DIRECT_ASSISTANT_BUBBLE,
                outline=DIRECT_SURFACE_EDGE,
                tags=("direct_text_preview_bubble",),
            )
            bubble.create_text(
                18,
                15,
                text=safe_title,
                anchor="nw",
                fill=INK,
                font=_tk_ui_font(10, bold=True),
                tags=("direct_text_preview_bubble",),
            )
            bubble.create_text(
                18,
                38,
                text=safe_text,
                anchor="nw",
                justify="left",
                width=max(180, width - 38),
                fill=MUTED,
                font=_tk_ui_font(9),
                tags=("direct_text_preview_bubble",),
            )

        bubble.bind("<Configure>", draw_preview)
        bubble.after_idle(draw_preview)
        return bubble

    def _pack_direct_bubble_entry(
        self,
        parent: tk.Misc,
        variable: tk.StringVar,
        *,
        padx: int = 10,
        pady: tuple[int, int] = (0, 8),
    ) -> tk.Entry:
        layer_bg = self._transparent_bg
        height = 48
        bubble = tk.Canvas(
            parent,
            height=height,
            bg=layer_bg,
            bd=0,
            highlightthickness=0,
        )
        bubble.pack(fill="x", padx=padx, pady=pady)
        entry = tk.Entry(
            bubble,
            textvariable=variable,
            bg=DIRECT_INPUT_BG,
            fg=INK,
            relief="flat",
            insertbackground=INK,
            font=_tk_ui_font(10),
            bd=0,
            highlightthickness=0,
        )
        entry_window = bubble.create_window(
            18,
            height // 2,
            window=entry,
            anchor="w",
            height=30,
            tags=("direct_bubble_entry_control",),
        )

        def draw_entry_bubble(event: tk.Event | None = None) -> None:
            width = int(getattr(event, "width", 0) or bubble.winfo_width() or DIRECT_CHAT_WIDTH - 44)
            bubble.delete("direct_bubble_entry_bg")
            self._draw_round_rect(
                bubble,
                3,
                4,
                width - 2,
                height - 1,
                22,
                fill=DIRECT_TK_SHADOW,
                outline="",
                tags=("direct_bubble_entry_bg",),
            )
            self._draw_round_rect(
                bubble,
                1,
                1,
                width - 5,
                height - 5,
                22,
                fill=DIRECT_INPUT_BG,
                outline=DIRECT_SURFACE_EDGE,
                tags=("direct_bubble_entry_bg",),
            )
            bubble.coords(entry_window, 18, height // 2)
            bubble.itemconfigure(entry_window, width=max(120, width - 36), height=30)
            bubble.tag_lower("direct_bubble_entry_bg")

        bubble.bind("<Configure>", draw_entry_bubble)
        bubble.after_idle(draw_entry_bubble)
        return entry

    def _pack_direct_header_button(
        self,
        parent: tk.Misc,
        label: str,
        command: Callable[[], None],
        *,
        width: int = 30,
    ) -> tk.Canvas:
        layer_bg = self._transparent_bg
        height = 24
        button = tk.Canvas(
            parent,
            width=width,
            height=height,
            bg=layer_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        button.pack(side="right", padx=(4, 0))
        self._draw_round_rect(
            button,
            2,
            2,
            width - 2,
            height - 2,
            10,
            fill=DIRECT_INPUT_BG,
            outline=DIRECT_SURFACE_EDGE,
            tags=("direct_header_button",),
        )
        button.create_text(
            width // 2,
            height // 2,
            text=str(label),
            fill=MUTED,
            font=_tk_ui_font(10, bold=True),
            tags=("direct_header_button",),
        )
        button.tag_bind("direct_header_button", "<Button-1>", lambda _event: command())
        button.bind("<Button-1>", lambda _event: command())
        return button

    def _pack_direct_bubble_buttons(
        self,
        parent: tk.Misc,
        items: list[dict[str, Any]],
        on_select: Callable[[dict[str, Any]], None],
        *,
        active_id: str = "",
        primary_id: str = "",
        columns: int = 3,
        padx: int = 10,
        pady: tuple[int, int] = (0, 8),
    ) -> None:
        if not items:
            return
        layer_bg = self._transparent_bg
        shell = tk.Frame(parent, bg=layer_bg, highlightthickness=0)
        shell.pack(fill="x", padx=padx, pady=pady)
        spread = max(1, min(3, int(columns or 1)))
        for index, item in enumerate(items):
            item_id = str(item.get("id") or "").strip()
            label = str(item.get("label") or item_id or "选项")
            active = item_id == active_id or (not active_id and item_id == primary_id)
            from_user_side = index % 2 == 1
            anchor_side = "e" if from_user_side else "w"
            stagger = (index % spread) * 7
            width = max(68, min(152, 38 + len(label) * 13))
            height = 38
            bubble = tk.Canvas(
                shell,
                width=width,
                height=height,
                bg=layer_bg,
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            )
            bubble.pack(
                anchor=anchor_side,
                padx=(stagger, 22) if not from_user_side else (22, stagger),
                pady=(0, 5),
            )
            fill = ACCENT if active else (DIRECT_INPUT_BG if from_user_side else DIRECT_ASSISTANT_BUBBLE)
            text_fill = INVERSE_TEXT if active else INK
            outline_fill = "" if active else DIRECT_SURFACE_EDGE
            x1 = 4 if not from_user_side else 1
            x2 = width - 8 if not from_user_side else width - 13
            self._draw_round_rect(
                bubble,
                x1 + 2,
                4,
                x2 + 2,
                height - 1,
                18,
                fill=DIRECT_TK_SHADOW,
                outline="",
                tags=("direct_bubble_button_shadow",),
            )
            self._draw_round_rect(
                bubble,
                x1,
                1,
                x2,
                height - 4,
                18,
                fill=fill,
                outline=outline_fill,
                tags=("direct_bubble_button",),
            )
            if active:
                bubble.create_oval(
                    x2 - 12,
                    7,
                    x2 - 6,
                    13,
                    fill=DIRECT_CHAMPAGNE_SOFT,
                    outline="",
                    tags=("direct_bubble_button",),
                )
            bubble.create_text(
                (x1 + x2) // 2 - (4 if active else 0),
                height // 2,
                text=label,
                fill=text_fill,
                font=_tk_ui_font(9, bold=True),
                tags=("direct_bubble_button_text",),
            )
            bubble.bind("<Button-1>", lambda _event, current=dict(item): on_select(current))

    def _show_direct_help_card(self) -> None:
        if not self._direct_chat or not self._direct_chat.winfo_exists():
            self.open_direct_chat()
        if not self._direct_help_frame:
            return
        self._focus_direct_feature_layer({"help"})
        for child in self._direct_help_frame.winfo_children():
            child.destroy()

        pack_options: dict[str, Any] = {"fill": "x", "padx": 12, "pady": (0, 10)}
        if self._direct_frame_is_packed(self._direct_service_frame):
            pack_options["before"] = self._direct_service_frame
        elif self._direct_frame_is_packed(self._direct_artifact_frame):
            pack_options["before"] = self._direct_artifact_frame
        elif self._direct_frame_is_packed(self._direct_activity_frame):
            pack_options["before"] = self._direct_activity_frame
        elif self._direct_frame_is_packed(self._direct_approval_frame):
            pack_options["before"] = self._direct_approval_frame
        elif self._direct_frame_is_packed(self._direct_quick_frame):
            pack_options["before"] = self._direct_quick_frame
        elif self._direct_frame_is_packed(self._direct_skills_frame):
            pack_options["before"] = self._direct_skills_frame
        elif self._direct_frame_is_packed(self._direct_settings_frame):
            pack_options["before"] = self._direct_settings_frame
        self._direct_help_frame.pack(**pack_options)

        section_id = _normalize_direct_help_section(getattr(self, "_direct_help_section", "overview"))
        self._direct_help_section = section_id
        if section_id == "overview":
            section = {
                "id": "overview",
                "label": "说一句",
                "detail": "单击头像，输入一句话；我会交给 Agent。更多能力收在设置里。",
            }
        else:
            section = next(
                (item for item in _direct_help_section_specs() if item["id"] == section_id),
                {
                    "id": "overview",
                    "label": "说一句",
                    "detail": "单击头像，输入一句话；我会交给 Agent。",
                },
            )

        layer_bg = self._transparent_bg
        top = tk.Frame(self._direct_help_frame, bg=layer_bg)
        top.pack(fill="x", padx=10, pady=(8, 2))
        close_button = tk.Canvas(
            top,
            width=26,
            height=24,
            bg=layer_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        close_button.pack(side="right")
        self._draw_round_rect(
            close_button,
            2,
            2,
            24,
            22,
            10,
            fill=DIRECT_INPUT_BG,
            outline=DIRECT_SURFACE_EDGE,
            tags=("direct_help_close",),
        )
        close_button.create_text(
            13,
            12,
            text="×",
            fill=MUTED,
            font=_tk_ui_font(12, bold=True),
            tags=("direct_help_close",),
        )
        close_button.tag_bind("direct_help_close", "<Button-1>", lambda _event: self._hide_direct_help_card())
        close_button.bind("<Button-1>", lambda _event: self._hide_direct_help_card())

        self._pack_direct_speech_bubble(
            self._direct_help_frame,
            title=f"先从这里开始 · {section['label']}",
            detail=str(section["detail"]),
            padx=0,
            pady=(0, 7),
        )

        if section_id != "overview" and _direct_help_section_specs():
            self._pack_direct_bubble_buttons(
                self._direct_help_frame,
                _direct_help_section_specs(),
                lambda item: self._set_direct_help_section(str(item.get("id") or "")),
                active_id=section_id,
                columns=2,
                pady=(3, 7),
            )

        def run_help_item(spec: dict[str, Any]) -> None:
            target_section = str(spec.get("section") or "")
            if target_section:
                self._set_direct_help_section(target_section)
                return
            self._run_direct_help_action(str(spec.get("id") or ""))

        help_actions = _direct_help_action_specs(section_id)
        self._pack_direct_bubble_buttons(
            self._direct_help_frame,
            help_actions,
            run_help_item,
            primary_id=str(help_actions[0]["id"]) if help_actions else "",
            columns=3,
            pady=(0, 10),
        )
        self._position_direct_chat()

    def _run_direct_help_action(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        if action == "talk":
            self.open_direct_chat()
            if self._direct_entry:
                self._direct_entry.focus_set()
            self.show_bubble("直接说吧，我在这里。", state="speaking", duration=2600)
            return
        if action == "screen":
            self._send_screen_context_from_direct()
            return
        if action == "clipboard":
            self._send_clipboard_material_from_direct()
            return
        if action == "file":
            self._send_file_material_from_direct()
            return
        if action == "skills":
            self._reply_with_skill_picker()
            return
        if action == "current_skill":
            self._reply_with_active_skill_summary()
            return
        if action == "clear_skill":
            self._run_native_control_command("clear_skill")
            return
        if action == "settings":
            self._run_native_control_command("settings")
            return
        if action == "front":
            self._run_native_control_command("front")
            return
        if action == "progress":
            self._run_native_control_command("progress")
            return
        if action == "artifacts":
            self._show_artifact_tray()
            return
        if action == "focus":
            raw = f"陪我专注 {FOCUS_DEFAULT_MINUTES} 分钟"
            self._append_chat("user", raw)
            self._run_native_focus_command({"action": "start", "minutes": FOCUS_DEFAULT_MINUTES}, raw)
            return
        if action == "rps":
            self._append_chat("user", "猜拳")
            self._run_native_rps_command({"action": "start", "move": ""})
            return
        if action == "dice":
            self._append_chat("user", "掷骰子")
            self._run_native_dice_command({"sides": 6})
            return
        if action == "coin":
            self._append_chat("user", "抽签")
            self._run_native_coin_command({"mode": "draw"})
            return
        if action == "tuck":
            self._run_native_control_command("tuck")
            return
        self._show_direct_unhandled_action("help")

    def _show_direct_unhandled_action(self, surface: str = "") -> None:
        reply = _direct_unhandled_action_reply(surface)
        line = str(reply["line"])
        self.open_direct_chat()
        if self._direct_entry:
            self._direct_entry.focus_set()
        self._append_chat("assistant", line)
        self._record_activity("interaction", str(reply["label"]), line)
        self._rebuild_direct_companion_card()
        if self._last_action:
            self._last_action.set(str(reply["label"]))
        self.show_bubble(line, state=str(reply["state"]), duration=3600)

    def _reply_with_memory_summary(self) -> None:
        summary = self._current_memory_summary()
        reply = f"我记得：{summary['detail']}"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(reply)
        self.show_bubble(reply, state="speaking", duration=5200)
        self._rebuild_direct_companion_card()

    def _run_profile_memory_command(self, command: dict[str, str]) -> None:
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return
        memories, reply, changed = _apply_profile_memory_command(
            normalize_twin_memories(twin.get("memories")),
            command,
        )
        if changed:
            try:
                updated = self.store.update_twin(twin["id"], {"memories": memories})
                self._active_twin_id = updated["id"]
            except Exception as exc:  # noqa: BLE001
                self.show_bubble(f"保存长期记忆失败：{_clip(str(exc), 60)}", state="error", duration=4200)
                return
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(reply)
        self._record_activity("interaction", "长期记忆", reply)
        self._rebuild_direct_companion_card()
        self.show_bubble(reply, state="success" if changed else "speaking", duration=4200)

    def _rebuild_direct_companion_card(self) -> None:
        if not self._direct_companion_frame:
            return
        for child in self._direct_companion_frame.winfo_children():
            child.destroy()
        if not self._direct_companion_visible:
            self._direct_companion_frame.pack_forget()
            self._direct_companion_more_visible = False
            self._position_direct_chat()
            return
        status = _companion_status(
            self._interaction_count,
            self._idle_companion_index,
            enabled=self._idle_companion_enabled,
        )
        presence = self._current_presence_summary()
        memory = self._current_memory_summary()
        activity_summary = _direct_activity_summary(self._activity_items)
        suggestions = _direct_companion_suggestion_specs(
            presence=presence,
            activity_summary=activity_summary,
            active_skill=self._active_skill_context,
            has_artifact_tray=bool(_activity_artifact_cards(self._activity_items)),
        )
        pack_options: dict[str, Any] = {"fill": "x", "padx": 12, "pady": (0, 10)}
        if self._direct_frame_is_packed(self._direct_help_frame):
            pack_options["before"] = self._direct_help_frame
        elif self._direct_frame_is_packed(self._direct_service_frame):
            pack_options["before"] = self._direct_service_frame
        elif self._direct_frame_is_packed(self._direct_artifact_frame):
            pack_options["before"] = self._direct_artifact_frame
        elif self._direct_frame_is_packed(self._direct_activity_frame):
            pack_options["before"] = self._direct_activity_frame
        elif self._direct_frame_is_packed(self._direct_approval_frame):
            pack_options["before"] = self._direct_approval_frame
        elif self._direct_frame_is_packed(self._direct_quick_frame):
            pack_options["before"] = self._direct_quick_frame
        elif self._direct_frame_is_packed(self._direct_skills_frame):
            pack_options["before"] = self._direct_skills_frame
        elif self._direct_frame_is_packed(self._direct_settings_frame):
            pack_options["before"] = self._direct_settings_frame
        self._direct_companion_frame.pack(**pack_options)
        identity = _identity_summary()
        self._pack_direct_speech_bubble(
            self._direct_companion_frame,
            title=f"陪伴 Lv.{status['level']} · {status['label']}",
            detail=f"{' · '.join(str(item) for item in identity['badges'])}。{status['detail']}",
            padx=0,
            pady=(2, 6),
        )
        self._pack_direct_value_bubbles(
            self._direct_companion_frame,
            [
                {"label": f"我现在：{presence['label']}", "value": str(presence["detail"])},
                {"label": f"刚刚记得：{memory['label']}", "value": str(memory["detail"])},
            ],
            padx=0,
            pady=(0, 6),
        )
        if suggestions:
            self._pack_direct_speech_bubble(
                self._direct_companion_frame,
                title="我建议下一步",
                detail="点一个，我会继续从头像旁展开。",
                padx=0,
                pady=(0, 5),
            )
            suggestion_items = [dict(spec) for spec in suggestions[:3]]
            primary_id = next(
                (str(spec.get("id") or "") for spec in suggestion_items if str(spec.get("style") or "") == "primary"),
                "",
            )
            self._pack_direct_bubble_buttons(
                self._direct_companion_frame,
                suggestion_items,
                lambda item: self._run_direct_companion_suggestion(str(item.get("id") or "")),
                primary_id=primary_id,
                columns=3,
                pady=(0, 8),
            )
        if self._direct_companion_more_visible:
            self._pack_direct_speech_bubble(
                self._direct_companion_frame,
                title="轻互动",
                detail="这些只改变陪伴状态或玩一小局，不会新增任务。",
                padx=0,
                pady=(0, 5),
            )
            companion_items: list[dict[str, Any]] = []
            for action_id in DIRECT_COMPANION_ACTION_IDS:
                action = interaction_by_id(action_id)
                if not action:
                    continue
                companion_items.append({"id": action_id, "label": str(action.get("label") or action_id), "action": dict(action)})
            companion_items.append({
                "id": "toggle_idle",
                "label": "安静" if self._idle_companion_enabled else "恢复陪伴",
            })
            self._pack_direct_bubble_buttons(
                self._direct_companion_frame,
                companion_items,
                lambda item: (
                    self._toggle_idle_companion_from_direct()
                    if str(item.get("id") or "") == "toggle_idle"
                    else self._run_interaction_action(dict(item.get("action") or {}))
                ),
                primary_id="toggle_idle" if not self._idle_companion_enabled else "",
                columns=3,
                pady=(0, 8),
            )
            suggestion_ids = {str(item.get("id") or "") for item in suggestions if isinstance(item, dict)}
            play_actions = _direct_play_action_specs(suggestion_ids)
            if play_actions:
                self._pack_direct_bubble_buttons(
                    self._direct_companion_frame,
                    [dict(spec) for spec in play_actions],
                    lambda item: self._run_direct_help_action(str(item.get("id") or "")),
                    columns=3,
                    pady=(0, 8),
                )
            self._pack_direct_bubble_buttons(
                self._direct_companion_frame,
                [{"id": "companion_less", "label": "收起陪伴"}],
                lambda item: self._run_direct_companion_suggestion(str(item.get("id") or "")),
                columns=1,
                pady=(0, 9),
            )
        else:
            self._pack_direct_bubble_buttons(
                self._direct_companion_frame,
                [{"id": "companion_more", "label": "更多陪伴"}],
                lambda item: self._run_direct_companion_suggestion(str(item.get("id") or "")),
                primary_id="companion_more",
                columns=1,
                pady=(0, 9),
            )
        self._position_direct_chat()

    def _set_direct_companion_more_visible(self, visible: bool) -> None:
        self._direct_companion_more_visible = bool(visible)
        self._rebuild_direct_companion_card()
        line = "轻互动露出来了，想玩什么直接点。" if self._direct_companion_more_visible else "好，我先把轻互动收起来。"
        if self._last_action:
            self._last_action.set(line)
        self.show_bubble(line, state="speaking", duration=2400)

    def _run_direct_companion_suggestion(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        self._mark_activity()
        if action == "companion_more":
            self._set_direct_companion_more_visible(True)
            return
        if action == "companion_less":
            self._set_direct_companion_more_visible(False)
            return
        if action in {"screen", "clipboard", "file", "skills", "settings", "progress", "focus", "rps", "dice", "coin"}:
            self._run_direct_help_action(action)
            return
        if action == "wake":
            if self._state == "sleep":
                self._wake_from_sleep()
            else:
                self.open_direct_chat()
                self.show_bubble("我在，直接跟我说就行。", state="speaking", duration=2600)
            return
        if action in {"approval", "approval_accept", "approval_reject", "chat", "cheer", "quiet", "artifacts", "retry"}:
            self._run_direct_activity_action(action)
            return
        self._show_direct_unhandled_action("companion")

    def _rebuild_direct_service_card(self) -> None:
        if not self._direct_service_frame:
            return
        for child in self._direct_service_frame.winfo_children():
            child.destroy()
        summary = _direct_service_status_summary(read_service_status())
        pack_options: dict[str, Any] = {"fill": "x", "padx": 12, "pady": (0, 10)}
        if self._direct_frame_is_packed(self._direct_artifact_frame):
            pack_options["before"] = self._direct_artifact_frame
        elif self._direct_frame_is_packed(self._direct_activity_frame):
            pack_options["before"] = self._direct_activity_frame
        elif self._direct_frame_is_packed(self._direct_approval_frame):
            pack_options["before"] = self._direct_approval_frame
        elif self._direct_frame_is_packed(self._direct_quick_frame):
            pack_options["before"] = self._direct_quick_frame
        elif self._direct_frame_is_packed(self._direct_skills_frame):
            pack_options["before"] = self._direct_skills_frame
        elif self._direct_frame_is_packed(self._direct_settings_frame):
            pack_options["before"] = self._direct_settings_frame
        self._direct_service_frame.pack(**pack_options)
        self._pack_direct_speech_bubble(
            self._direct_service_frame,
            title=str(summary["label"]),
            detail=str(summary["detail"]),
            padx=0,
            pady=(2, 8),
        )
        self._pack_direct_bubble_buttons(
            self._direct_service_frame,
            [{"id": "refresh", "label": "刷新"}, {"id": "detail", "label": "详情"}],
            lambda item: (
                self._show_service_status()
                if str(item.get("id") or "") == "detail"
                else self._rebuild_direct_service_card()
            ),
            primary_id="refresh",
            columns=2,
            pady=(0, 8),
        )
        self._position_direct_chat()

    def _set_idle_companion_enabled(self, enabled: bool, *, record_chat: bool = False) -> None:
        self._idle_companion_enabled = bool(enabled)
        self._mark_activity()
        self._schedule_idle_companion()
        self._persist_companion_memory()
        self._rebuild_direct_companion_card()
        reply = "我会继续轻声陪着你，有需要时也会轻轻提醒。" if self._idle_companion_enabled else "好，我先安静守着，不会自己打扰你。"
        if self._last_action:
            self._last_action.set("待机陪伴已开启。" if self._idle_companion_enabled else "待机陪伴已安静。")
        if record_chat:
            self._append_chat("assistant", reply)
            self._record_activity(
                "interaction",
                "恢复陪伴" if self._idle_companion_enabled else "安静守候",
                "JiuMe 的待机陪伴偏好已更新。",
            )
        self.show_bubble(
            reply,
            state="speaking" if self._idle_companion_enabled else "idle",
            duration=2600,
        )

    def _toggle_idle_companion_from_direct(self) -> None:
        self._set_idle_companion_enabled(not self._idle_companion_enabled)

    def _rebuild_direct_activity_card(self) -> None:
        if not self._direct_activity_frame:
            return
        for child in self._direct_activity_frame.winfo_children():
            child.destroy()
        summary = _direct_activity_summary(self._activity_items)
        pack_options: dict[str, Any] = {"fill": "x", "padx": 12, "pady": (0, 10)}
        if self._direct_frame_is_packed(self._direct_approval_frame):
            pack_options["before"] = self._direct_approval_frame
        elif self._direct_frame_is_packed(self._direct_quick_frame):
            pack_options["before"] = self._direct_quick_frame
        elif self._direct_frame_is_packed(self._direct_skills_frame):
            pack_options["before"] = self._direct_skills_frame
        elif self._direct_frame_is_packed(self._direct_settings_frame):
            pack_options["before"] = self._direct_settings_frame
        if summary is None:
            if not self._direct_activity_empty_visible:
                self._direct_activity_frame.pack_forget()
                self._position_direct_chat()
                return
            self._direct_activity_frame.pack(**pack_options)
            self._pack_direct_speech_bubble(
                self._direct_activity_frame,
                title="现在没有任务进度",
                detail="我还没有正在接手的任务。你可以直接说一句，我会接住下一件事。",
                padx=0,
                pady=(2, 8),
            )
            self._pack_direct_bubble_buttons(
                self._direct_activity_frame,
                [
                    {"id": "chat", "label": "直接说"},
                    {"id": "close_progress", "label": "收起"},
                ],
                lambda item: self._run_direct_activity_action(str(item.get("id") or "")),
                primary_id="chat",
                columns=2,
                pady=(0, 10),
            )
            self._position_direct_chat()
            return
        self._direct_activity_frame.pack(**pack_options)
        detail_parts: list[str] = []
        if summary.get("time"):
            detail_parts.append(str(summary["time"]))
        if summary.get("stage"):
            detail_parts.append(f"阶段：{summary['stage']}")
        if summary.get("detail"):
            detail_parts.append(str(summary["detail"]))
        self._pack_direct_speech_bubble(
            self._direct_activity_frame,
            title=str(summary["title"]),
            detail=" · ".join(detail_parts) or "我会把最近一步放在这里。",
            padx=0,
            pady=(2, 8),
        )
        artifacts = summary.get("artifacts")
        artifact_tray_cards = _activity_artifact_cards(
            self._activity_items,
            limit=ARTIFACT_TRAY_LIMIT,
        )
        if not self._direct_activity_detail_visible:
            collapsed_actions: list[dict[str, Any]] = [
                {"id": "progress", "label": "展开进度"},
                {"id": "chat", "label": "补一句"},
            ]
            if str(summary.get("kind") or "") == "approval":
                collapsed_actions.insert(0, {"id": "approval", "label": "确认"})
            elif artifact_tray_cards:
                collapsed_actions.insert(1, {"id": "artifacts", "label": "产物"})
            collapsed_actions.append({"id": "close_progress", "label": "收起"})
            self._pack_direct_speech_bubble(
                self._direct_activity_frame,
                title="先收成一条进度",
                detail="需要细节时再展开；我不会把任务控制一次性铺满。",
                padx=0,
                pady=(0, 5),
            )
            self._pack_direct_bubble_buttons(
                self._direct_activity_frame,
                collapsed_actions,
                lambda item: self._run_direct_activity_action(str(item.get("id") or "")),
                primary_id=str(collapsed_actions[0]["id"]) if collapsed_actions else "",
                columns=2,
                pady=(0, 10),
            )
            self._position_direct_chat()
            return
        if isinstance(artifacts, list) and artifacts:
            artifact_action_items: list[dict[str, Any]] = []
            for artifact in artifacts:
                label = _clip(str(artifact.get("label") or "产物"), 14)
                if self._can_preview_artifact(artifact):
                    artifact_action_items.append({
                        "id": f"preview:{label}",
                        "label": f"看 {label}",
                        "kind": "preview",
                        "artifact": dict(artifact),
                    })
                if str(artifact.get("kind") or "") != "inline":
                    artifact_action_items.append({
                        "id": f"open:{label}",
                        "label": f"开 {label}",
                        "kind": "open",
                        "target": str(artifact.get("target") or ""),
                    })
            if artifact_tray_cards:
                artifact_action_items.append({"id": "all", "label": "全部", "kind": "all"})
            self._pack_direct_bubble_buttons(
                self._direct_activity_frame,
                artifact_action_items,
                lambda item: (
                    self._preview_activity_artifact(dict(item.get("artifact") or {}))
                    if str(item.get("kind") or "") == "preview"
                    else self._show_artifact_tray()
                    if str(item.get("kind") or "") == "all"
                    else self._open_activity_target(str(item.get("target") or ""))
                ),
                primary_id=str(artifact_action_items[0]["id"]) if artifact_action_items else "",
                columns=2,
                pady=(0, 9),
            )
        next_actions = _direct_activity_action_specs(
            summary,
            has_artifact_tray=bool(artifact_tray_cards),
            expanded=self._direct_activity_more_visible,
        )
        if next_actions:
            primary_id = next(
                (str(spec.get("id") or "") for spec in next_actions if str(spec.get("style") or "") == "primary"),
                "",
            )
            self._pack_direct_bubble_buttons(
                self._direct_activity_frame,
                [dict(spec) for spec in next_actions],
                lambda item: self._run_direct_activity_action(str(item.get("id") or "")),
                primary_id=primary_id,
                columns=3,
                pady=(0, 10),
            )
        self._position_direct_chat()

    def _run_direct_activity_action(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        self._mark_activity()
        if action == "chat":
            self.open_direct_chat()
            if self._direct_entry:
                self._direct_entry.focus_set()
            self.show_bubble(
                "你可以直接补一句，我会带着当前任务继续。",
                state="speaking",
                duration=2600,
            )
            return
        if action == "materials":
            self._direct_help_section = "materials"
            self._show_direct_help_card()
            self.show_bubble("材料入口展开了。选屏幕、剪贴板或文件就行。", state="speaking", duration=2800)
            return
        if action == "close_progress":
            self._direct_activity_empty_visible = False
            self._direct_activity_detail_visible = False
            self._direct_activity_more_visible = False
            self._rebuild_direct_activity_card()
            self.show_bubble("好，进度先收起来。", state="speaking", duration=2200)
            return
        if action == "progress":
            self._direct_activity_detail_visible = True
            self._rebuild_direct_activity_card()
            self.show_bubble("进度详情展开了，需要哪一步就点哪一步。", state="speaking", duration=2600)
            return
        if action == "more":
            self._direct_activity_detail_visible = True
            self._direct_activity_more_visible = True
            self._rebuild_direct_activity_card()
            self.show_bubble("更多任务动作展开了。", state="speaking", duration=2400)
            return
        if action == "less":
            self._direct_activity_more_visible = False
            self._rebuild_direct_activity_card()
            self.show_bubble("我先收回细动作。", state="speaking", duration=2200)
            return
        if action == "approval":
            if self._pending_approval:
                self.open_direct_chat()
                self._rebuild_direct_approval_card()
                self.show_bubble("我把确认放到你旁边了。", state="waiting_approval", duration=None)
                return
            self._run_native_control_command("progress")
            return
        if action == "approval_accept":
            self._answer_pending_approval_from_avatar("accept")
            return
        if action == "approval_reject":
            self._answer_pending_approval_from_avatar("reject")
            return
        if action == "cheer":
            self._run_interaction_by_id("cheer")
            return
        if action == "nudge":
            self._nudge_current_task_from_direct()
            return
        if action == "quiet":
            self._run_task_runtime_command("quiet")
            return
        if action == "artifacts":
            self._show_artifact_tray()
            return
        if action == "retry":
            self._retry_latest_task_from_direct()
            return
        if action == "cancel":
            self._request_task_interrupt()
            return
        self._show_direct_unhandled_action("activity")

    def _rebuild_direct_approval_card(self) -> None:
        if not self._direct_approval_frame:
            return
        for child in self._direct_approval_frame.winfo_children():
            child.destroy()
        self._direct_approval_frame.pack_forget()
        self._direct_approval_feedback_visible = False
        if not self._approval_frame or not self._approval_frame.winfo_exists():
            self._approval_feedback_var = None
        self._position_direct_chat()

    def _run_direct_approval_action(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        if action == "add_note":
            self._direct_approval_feedback_visible = True
            self._rebuild_direct_approval_card()
            if self._approval_feedback_var is None:
                self._approval_feedback_var = tk.StringVar(value="")
            self.show_bubble("好，补充输入展开了。", state="waiting_approval", duration=None)
            return
        if action == "hide_note":
            self._direct_approval_feedback_visible = False
            self._rebuild_direct_approval_card()
            self.show_bubble("补充先收起来，直接同意或拒绝也可以。", state="waiting_approval", duration=None)
            return
        self._send_approval_answer(action or "reject")

    def _direct_quick_actions(self) -> list[dict[str, Any]]:
        return _direct_quick_action_shortcuts(quick_actions())

    def _rebuild_direct_quick_actions(self) -> None:
        if not self._direct_quick_frame:
            return
        for child in self._direct_quick_frame.winfo_children():
            child.destroy()
        shortcuts = self._direct_quick_actions()
        if not shortcuts:
            self._direct_quick_frame.pack_forget()
            self._position_direct_chat()
            return
        if self._direct_frame_is_packed(self._direct_skills_frame):
            self._direct_quick_frame.pack(fill="x", padx=12, pady=(0, 8), before=self._direct_skills_frame)
        elif self._direct_frame_is_packed(self._direct_settings_frame):
            self._direct_quick_frame.pack(fill="x", padx=12, pady=(0, 8), before=self._direct_settings_frame)
        else:
            self._direct_quick_frame.pack(fill="x", padx=12, pady=(0, 8))
        self._pack_direct_speech_bubble(
            self._direct_quick_frame,
            title="直接开工",
            detail="点一个，我会从头像旁开始处理。",
            padx=0,
            pady=(2, 5),
        )
        rows_by_id = {str(action.get("id") or ""): action for action in quick_actions()}
        action_items: list[dict[str, Any]] = []
        for shortcut in shortcuts:
            action = rows_by_id.get(str(shortcut["id"]))
            if not action:
                continue
            action_items.append({"id": str(shortcut["id"]), "label": str(shortcut["label"]), "action": dict(action)})
        self._pack_direct_bubble_buttons(
            self._direct_quick_frame,
            action_items,
            lambda item: self._run_quick_action(dict(item.get("action") or {})),
            primary_id=str(action_items[0]["id"]) if action_items else "",
            columns=3,
            pady=(0, 4),
        )
        self._position_direct_chat()

    def _direct_skill_rows(self) -> list[dict[str, Any]]:
        enabled_ids = self._enabled_skill_ids()
        return filter_recommended_skills(enabled_skill_ids=enabled_ids)

    def _direct_skill_shortcuts(self) -> list[dict[str, Any]]:
        return _direct_skill_shortcuts(self._direct_skill_rows())

    def _set_direct_skill_section(self, section: str) -> None:
        self._direct_skill_section = _normalize_direct_skill_section(
            section,
            has_active_skill=bool(self._active_skill_context),
        )
        self._direct_skills_picker_visible = False
        self._direct_skills_detail_visible = True
        self._rebuild_direct_skill_shortcuts()

    def _open_skill_shelf_from_direct(self) -> None:
        if self._redirect_first_run_to_setup():
            return
        if not self._direct_chat or not self._direct_chat.winfo_exists():
            self.open_direct_chat()
        self._focus_direct_feature_layer({"skills"})
        self._direct_skill_section = "recommended"
        self._direct_skills_picker_visible = False
        self._direct_skills_detail_visible = False
        self._rebuild_direct_skill_shortcuts()
        if self._last_action:
            self._last_action.set("skill 入口已在头像旁打开。")
        self.show_bubble("skill 入口先收着，点展开再看下一层。", state="speaking", duration=3600)

    def _set_active_skill_context(self, skill: dict[str, Any] | None) -> None:
        self._active_skill_context = _active_skill_snapshot(skill)
        self._persist_desktop_history()
        self._rebuild_direct_skill_shortcuts()
        self._render_avatar_frame()

    def _clear_active_skill_context(self) -> None:
        if not self._active_skill_context:
            return
        self._active_skill_context = None
        self._direct_skill_section = "recommended"
        self._direct_skills_picker_visible = False
        self._direct_skills_detail_visible = False
        self._persist_desktop_history()
        self._rebuild_direct_skill_shortcuts()
        self._render_avatar_frame()
        if self._last_action:
            self._last_action.set("已回到普通对话。")
        self.show_bubble("好，先不固定 skill。你直接说任务就行。", state="speaking", duration=2800)

    def _run_native_control_command(self, command: str, raw: str = "") -> None:
        key = str(command or "").strip()
        if key == "tuck":
            line = "好，我把旁边的面板都收起来，只留我在桌面上。"
            self._append_chat("assistant", line)
            self._interaction_count += 1
            self._persist_companion_memory()
            self._record_activity("interaction", "收起桌面浮层", line)
            if self._last_action:
                self._last_action.set("已收起旁边面板，只留 JiuMe。")
            self._tuck_avatar_surfaces()
            self._start_interaction_effect("nod")
            return

        if key in {"direct_chat", "settings", "skills", "progress", "status"} and self._redirect_first_run_to_setup():
            return
        if key == "settings":
            self.open_settings()
            return

        if _uses_native_direct_chat() and key in {"direct_chat", "settings", "skills", "progress"}:
            if key == "direct_chat":
                self._focus_direct_feature_layer()
                self._open_native_direct_surface("chat")
                return
            if key == "skills":
                self._focus_direct_feature_layer({"skills"})
                self._direct_skill_section = "recommended"
                self._direct_skills_picker_visible = False
                self._direct_skills_detail_visible = False
                if self._last_action:
                    self._last_action.set("skill 入口已在头像旁打开。")
                self._open_native_direct_surface("skills")
                return
            self._focus_direct_feature_layer({"activity", "approval", "artifacts"})
            self._direct_activity_empty_visible = True
            self._direct_activity_detail_visible = False
            self._direct_activity_more_visible = False
            if self._last_action:
                self._last_action.set("任务进度已打开。")
            self._open_native_direct_surface("progress")
            return

        if key == "direct_chat":
            if not self._direct_chat or not self._direct_chat.winfo_exists():
                self.open_direct_chat()
            self._focus_direct_feature_layer()
            line = "我在，直接跟我说就行。"
            self._append_chat("assistant", line)
            if self._last_action:
                self._last_action.set("直接说话已打开。")
            self.show_bubble(line, state="speaking", duration=2800)
            self._start_interaction_effect("wave")
            return

        if key == "front":
            windows = (
                self.root,
                self._direct_chat,
                self._panel,
                self._artifact_panel,
                self._work_hud,
                self._bubble,
            )
            try:
                for window in windows:
                    if window and window.winfo_exists():
                        window.lift()
                        window.attributes("-topmost", True)
            except tk.TclError:
                self.show_bubble("我现在没法浮到最前，稍后再试一下。", state="error", duration=3200)
                return
            line = "我到前面了，会继续浮在桌面上。"
            self._append_chat("assistant", line)
            if self._last_action:
                self._last_action.set("JiuMe 已保持在最前。")
            self.show_bubble(line, state="speaking", duration=2800)
            self._start_interaction_effect("peek")
            return

        if key == "skills":
            self._focus_direct_feature_layer({"skills"})
            self._append_chat("assistant", "我把 skill 入口放到头像旁边了。")
            self._open_skill_shelf_from_direct()
            return

        if key == "progress":
            if not self._direct_chat or not self._direct_chat.winfo_exists():
                self.open_direct_chat()
            self._focus_direct_feature_layer({"activity", "approval", "artifacts"})
            self._direct_activity_empty_visible = True
            self._direct_activity_detail_visible = False
            self._direct_activity_more_visible = False
            self._rebuild_direct_activity_card()
            summary = _direct_activity_summary(self._activity_items)
            has_artifact_tray = bool(_activity_artifact_cards(self._activity_items))
            reply = _task_progress_reply(summary, has_artifact_tray=has_artifact_tray)
            if summary:
                title = str(summary.get("title") or "最近任务")
                detail = str(summary.get("detail") or "")
                state = str(
                    reply.get("state") or _work_hud_state_for_activity(str(summary.get("kind") or "")) or "speaking"
                )
                self._show_work_hud(title, detail or "最近任务进度在头像旁。", state=state)
                self._append_chat("assistant", str(reply["detail"]))
                effect = str(reply.get("effect") or "")
                if effect:
                    self._start_interaction_effect(effect)
                self.show_bubble(_clip(str(reply["detail"]), 96), state=str(reply["state"]), duration=3600)
            else:
                self._append_chat("assistant", str(reply["detail"]))
                effect = str(reply.get("effect") or "")
                if effect:
                    self._start_interaction_effect(effect)
                self.show_bubble(str(reply["detail"]), state=str(reply["state"]), duration=3200)
            return

        if key == "status":
            if not self._direct_chat or not self._direct_chat.winfo_exists():
                self.open_direct_chat()
            self._focus_direct_feature_layer({"service"})
            self._refresh_service_status()
            self._append_chat("assistant", "我把后台连接状态刷新给你看。")
            self._show_service_status()
            return

        if key in {"login_install", "login_uninstall", "login_status"}:
            action = key.removeprefix("login_")
            self._run_login_item_command(action, raw)
            return

        if key == "clear_skill":
            if self._active_skill_context:
                name = self._active_skill_context.get("displayName") or "当前 skill"
                self._append_chat("assistant", f"好，先取消固定「{name}」。")
                self._clear_active_skill_context()
            else:
                self._append_chat("assistant", "现在没有固定 skill。")
                self.show_bubble("现在没有固定 skill，直接说任务就行。", state="speaking", duration=2800)
            return

        self.show_bubble(_clip(raw or "我还不认识这个本地控制。", 72), state="speaking", duration=2800)

    def _has_active_work_context(self) -> bool:
        if getattr(self, "_gateway_request_id", None):
            return True
        work_hud = getattr(self, "_work_hud", None)
        if work_hud and work_hud.winfo_exists() and work_hud.state() != "withdrawn":
            return getattr(self, "_work_hud_state", "") in {"thinking", "working", "waiting_approval"}
        return _work_hud_resume_activity(getattr(self, "_activity_items", [])) is not None

    def _show_agent_unavailable_status(self, detail: str = AGENT_UNAVAILABLE_DETAIL) -> None:
        message = str(detail or "").strip() or AGENT_UNAVAILABLE_DETAIL
        self._record_activity("error", AGENT_UNAVAILABLE_TITLE, message)
        if self._last_action:
            self._last_action.set(message)
        self.show_bubble(_clip(message, 72), state="error", duration=3600)
        try:
            self.root.after(1300, lambda: self.set_state("idle"))
        except tk.TclError:
            self.set_state("idle")

    def _run_task_runtime_command(self, command: str, note: str = "") -> None:
        key = str(command or "").strip()
        if key == "quiet":
            self._hide_work_hud()
            self.show_bubble("好，我先安静跑着。需要补充时再叫我。", state="working", duration=2600)
            if self._last_action:
                self._last_action.set("任务已安静后台跑。")
            return
        if key == "nudge":
            self._nudge_current_task_from_direct()
            return
        if key == "cancel":
            self._request_task_interrupt()
            return
        if key == "progress":
            self._run_native_control_command("progress")
            return
        if key != "note":
            return

        detail = str(note or "").strip()
        if not detail:
            self.open_direct_chat()
            self.show_bubble("你可以直接补一句，我会带着继续。", state="speaking", duration=2600)
            return
        message = _task_followup_message(detail)
        agent_message = _active_skill_followup_message(message, self._active_skill_context)
        self._append_chat("user", f"补一句：{detail}")
        self._record_activity("user", "补充当前任务", detail)
        self._show_work_hud("补充当前任务", detail, state="thinking")
        if self._last_action:
            self._last_action.set(f"已补充：{_clip(detail, 42)}")
        self.show_bubble("补充收到了，我带着继续。", state="thinking", duration=1800)
        if self.gateway:
            self._gateway_reply = ""
            self._stream_chat_index = None
            self.gateway.send_chat(
                agent_message,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=agent_message: self._post_gateway_event(msg, event),
            )
            return
        self._show_agent_unavailable_status()

    def _nudge_current_task_from_direct(self) -> None:
        summary = _direct_activity_summary(self._activity_items)
        reply = _task_nudge_reply(summary)
        detail = str(reply["detail"])
        self._append_chat("assistant", detail)
        self._record_activity("interaction", str(reply["title"]), detail)
        resumable = _work_hud_resume_activity(self._activity_items)
        if resumable:
            self._show_work_hud(
                resumable["title"],
                resumable["detail"],
                state=resumable["state"],
                kind=resumable["kind"],
            )
        if self._last_action:
            self._last_action.set(detail)
        self._start_interaction_effect(str(reply["effect"]))
        self.show_bubble(detail, state=str(reply["state"]), duration=3000)

    def _send_task_continuation_from_direct(self, raw: str, summary: dict[str, Any]) -> bool:
        detail = _task_continuation_command(raw)
        if not detail:
            return False

        message = _task_continuation_message(detail, summary)
        if not message:
            return False
        agent_message = _active_skill_followup_message(message, self._active_skill_context)
        self._append_chat("user", raw)
        self._record_activity("user", "继续最近任务", detail)
        self._show_work_hud("继续最近任务", detail, state="thinking")
        if self._last_action:
            self._last_action.set(f"带着刚才继续：{_clip(detail, 36)}")
        self.show_bubble("我带着刚才那件事继续。", state="thinking", duration=1800)
        if self.gateway:
            self._gateway_reply = ""
            self._stream_chat_index = None
            self.gateway.send_chat(
                agent_message,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=agent_message: self._post_gateway_event(msg, event),
            )
            return True
        self._show_agent_unavailable_status()
        return True

    def _retry_latest_task_from_direct(self) -> None:
        summary = _task_continuation_summary(self._activity_items)
        if summary and self._send_task_continuation_from_direct("重试", summary):
            return
        self._run_native_control_command("progress")
        self.show_bubble("我还没有能直接重试的最近任务，先把进度打开给你。", state="speaking", duration=3200)

    def _request_task_interrupt_from_menu(self) -> None:
        if self._has_active_work_context():
            self._request_task_interrupt()
            return
        self._run_native_control_command("progress")
        self.show_bubble("现在没有正在执行的任务。", state="speaking", duration=3000)

    def _request_task_interrupt(self) -> None:
        detail = "我正在停下当前任务。"
        self._record_activity("interrupt", "请求停止任务", detail)
        self._show_work_hud("请求停止当前任务", detail, state="working")
        if self._last_action:
            self._last_action.set("正在请求停止当前任务。")
        self.show_bubble("收到，我先停下这件事。", state="working", duration=2400)
        if self.gateway:
            self.gateway.send_interrupt(
                intent="cancel",
                on_event=lambda event: self._post_task_interrupt_result(event),
            )
            return
        self._handle_task_interrupt_result(
            GatewayEvent(kind="error", error="这件事现在还不能继续执行。")
        )

    def _post_task_interrupt_result(self, event: GatewayEvent) -> None:
        try:
            self.root.after(0, lambda: self._handle_task_interrupt_result(event))
        except tk.TclError:
            return

    def _handle_task_interrupt_result(self, event: GatewayEvent) -> None:
        if event.kind == "response" and event.ok:
            detail = gateway_event_text(event) or "已请求停止当前任务。"
            self._record_activity("interrupt", "已请求停止任务", detail)
            self._show_work_hud("已请求停止任务", detail, state="success")
            self._schedule_work_hud_hide(2600)
            if self._last_action:
                self._last_action.set("停止请求已发出。")
            self.show_bubble("停止请求已发给 Agent。", state="success", duration=2600)
            return
        if event.kind == "event" and event.event == "chat.interrupt_result":
            detail = gateway_event_text(event) or "Agent 已处理停止请求。"
            ok = bool((event.payload or {}).get("success", True))
            self._record_activity("interrupt" if ok else "error", "任务已停止" if ok else "停止任务失败", detail)
            self._show_work_hud("任务已停止" if ok else "停止任务失败", detail, state="success" if ok else "error")
            self._schedule_work_hud_hide(3200 if ok else 5200)
            if self._last_action:
                self._last_action.set(detail)
            self.show_bubble(detail, state="success" if ok else "error", duration=3200 if ok else 4200)
            return
        detail = gateway_event_text(event) or event.error or "停止请求失败。"
        self._record_activity("error", "停止任务失败", detail)
        self._show_work_hud("停止任务失败", detail, state="error")
        self._schedule_work_hud_hide(5200)
        if self._last_action:
            self._last_action.set("停止请求失败。")
        self.show_bubble(_clip(detail, 72), state="error", duration=4200)

    def _focus_direct_entry_for_skill(self) -> None:
        if self._direct_entry:
            try:
                self._direct_entry.focus_set()
            except tk.TclError:
                pass
        self.show_bubble("直接说你想让我处理什么，我会自己判断要不要用 skill。", state="speaking", duration=4200)

    def _open_direct_skill_detail_layer(self) -> None:
        self._direct_skills_picker_visible = True
        self._direct_skills_detail_visible = False
        self._direct_skill_section = _normalize_direct_skill_section(
            self._direct_skill_section,
            has_active_skill=bool(self._active_skill_context),
        )
        self._rebuild_direct_skill_shortcuts()

    def _hide_direct_skill_layer(self) -> None:
        self._direct_skills_picker_visible = False
        self._direct_skills_detail_visible = False
        self._direct_skill_section = "recommended"
        self._rebuild_direct_skill_shortcuts()

    def _rebuild_direct_skill_shortcuts(self) -> None:
        if not self._direct_skills_frame:
            return
        layer_bg = self._transparent_bg
        for child in self._direct_skills_frame.winfo_children():
            child.destroy()
        skill_rows = self._direct_skill_rows()
        shortcuts = _direct_skill_shortcuts(skill_rows)
        if not shortcuts and not self._active_skill_context:
            self._direct_skills_frame.pack_forget()
            self._position_direct_chat()
            return
        section_id = _normalize_direct_skill_section(
            self._direct_skill_section,
            has_active_skill=bool(self._active_skill_context),
        )
        self._direct_skill_section = section_id
        section = next(
            (item for item in _direct_skill_section_specs(has_active_skill=bool(self._active_skill_context)) if item["id"] == section_id),
            _direct_skill_section_specs(has_active_skill=bool(self._active_skill_context))[0],
        )
        if self._direct_frame_is_packed(self._direct_settings_frame):
            self._direct_skills_frame.pack(fill="x", padx=12, pady=(0, 8), before=self._direct_settings_frame)
        else:
            self._direct_skills_frame.pack(fill="x", padx=12, pady=(0, 8))
        if not self._direct_skills_detail_visible and not self._direct_skills_picker_visible:
            self._pack_direct_speech_bubble(
                self._direct_skills_frame,
                title="skill",
                detail="skill 先不全部展开。你可以直接说任务，或只打开推荐、当前、更多这一层。",
                padx=0,
                pady=(2, 7),
            )
            self._pack_direct_bubble_buttons(
                self._direct_skills_frame,
                [
                    {"id": "talk", "label": "直接说"},
                    {"id": "layers", "label": "展开 skill"},
                    {"id": "close", "label": "收起"},
                ],
                lambda item: (
                    self._open_direct_skill_detail_layer()
                    if str(item.get("id") or "") == "layers"
                    else self._hide_direct_skill_layer()
                    if str(item.get("id") or "") == "close"
                    else self._focus_direct_entry_for_skill()
                ),
                primary_id="layers",
                columns=3,
                pady=(0, 7),
            )
            self._position_direct_chat()
            return
        if self._direct_skills_picker_visible and not self._direct_skills_detail_visible:
            self._pack_direct_speech_bubble(
                self._direct_skills_frame,
                title="skill 分层",
                detail="先选一个 skill 层，我再只展开那一层。",
                padx=0,
                pady=(2, 7),
            )
            self._pack_direct_bubble_buttons(
                self._direct_skills_frame,
                _direct_skill_section_specs(has_active_skill=bool(self._active_skill_context)),
                lambda item: self._set_direct_skill_section(str(item.get("id") or "")),
                active_id=section_id,
                columns=3,
                pady=(0, 7),
            )
            self._pack_direct_bubble_buttons(
                self._direct_skills_frame,
                [
                    {"id": "talk", "label": "直接说"},
                    {"id": "close", "label": "收起"},
                ],
                lambda item: (
                    self._hide_direct_skill_layer()
                    if str(item.get("id") or "") == "close"
                    else self._focus_direct_entry_for_skill()
                ),
                primary_id="talk",
                columns=2,
                pady=(0, 7),
            )
            self._position_direct_chat()
            return
        self._pack_direct_speech_bubble(
            self._direct_skills_frame,
            title=f"skill · {section['label']}",
            detail=str(section["detail"]),
            padx=0,
            pady=(2, 7),
        )
        self._pack_direct_bubble_buttons(
            self._direct_skills_frame,
            _direct_skill_section_specs(has_active_skill=bool(self._active_skill_context)),
            lambda item: self._set_direct_skill_section(str(item.get("id") or "")),
            active_id=section_id,
            columns=3,
            pady=(0, 7),
        )

        if section_id == "current" and self._active_skill_context:
            active = self._active_skill_context
            active_summary = _active_skill_summary(active)
            self._pack_direct_value_bubbles(
                self._direct_skills_frame,
                [
                    {"label": "当前用", "value": _clip(str(active["displayName"]), 32)},
                    {"label": "我会这样接", "value": str(active_summary["detail"])},
                ],
                padx=0,
                pady=(0, 6),
            )
            self._pack_direct_bubble_buttons(
                self._direct_skills_frame,
                [{"id": "clear", "label": "取消固定"}],
                lambda _item: self._clear_active_skill_context(),
                primary_id="clear",
                columns=1,
                pady=(0, 7),
            )
        elif section_id == "current":
            self._pack_direct_value_bubbles(
                self._direct_skills_frame,
                [{"label": "当前 skill", "value": "现在没有固定 skill。可以先去「推荐」里选一个。"}],
                padx=0,
                pady=(0, 7),
            )
        elif section_id == "materials" and self._active_skill_context:
            self._pack_direct_bubble_buttons(
                self._direct_skills_frame,
                [dict(spec) for spec in _active_skill_material_action_specs()],
                lambda item: self._run_active_skill_material_action(str(item.get("id") or "")),
                primary_id="screen",
                columns=3,
                pady=(0, 7),
            )
        elif section_id == "recommended":
            rows_by_id = {str(skill.get("id") or ""): skill for skill in skill_rows}
            shortcut_items: list[dict[str, Any]] = []
            for shortcut in shortcuts:
                skill = rows_by_id.get(str(shortcut["id"]))
                if not skill:
                    continue
                enabled = bool(shortcut.get("isEnabled"))
                shortcut_items.append(
                    {
                        "id": str(shortcut["id"]),
                        "label": ("用 " if enabled else "装 ") + str(shortcut["displayName"]),
                        "skill": dict(skill),
                        "enabled": enabled,
                    }
                )
            self._pack_direct_bubble_buttons(
                self._direct_skills_frame,
                shortcut_items,
                lambda item: (
                    self._start_skill_task(dict(item["skill"]))
                    if item.get("enabled")
                    else self._set_skill_enabled(dict(item["skill"]), True)
                ),
                primary_id=str(shortcut_items[0]["id"]) if shortcut_items else "",
                columns=2,
                pady=(0, 7),
            )
        elif section_id == "more":
            overflow = _direct_skill_overflow_count(skill_rows)
            if overflow:
                self._pack_direct_value_bubbles(
                    self._direct_skills_frame,
                    [{"label": "更多 skill", "value": f"还有 {overflow} 个也可以在这里接住。"}],
                    padx=0,
                    pady=(0, 6),
                )
            more_items: list[dict[str, Any]] = []
            for skill in skill_rows[:8]:
                skill_id = str(skill.get("id") or "").strip()
                if not skill_id:
                    continue
                enabled = bool(skill.get("isEnabled"))
                display_name = _clip(str(skill.get("displayName") or skill_id), 20)
                more_items.append(
                    {
                        "id": skill_id,
                        "label": ("用 " if enabled else "装 ") + display_name,
                        "skill": dict(skill),
                        "enabled": enabled,
                    }
                )
            self._pack_direct_bubble_buttons(
                self._direct_skills_frame,
                more_items,
                lambda item: (
                    self._start_skill_task(dict(item["skill"]))
                    if item.get("enabled")
                    else self._set_skill_enabled(dict(item["skill"]), True)
                ),
                primary_id=str(more_items[0]["id"]) if more_items else "",
                columns=2,
                pady=(0, 7),
            )
        self._position_direct_chat()

    def _run_active_skill_material_action(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        if action == "screen":
            self._send_screen_context_from_direct()
            return
        if action == "clipboard":
            self._send_clipboard_material_from_direct()
            return
        if action == "file":
            self._send_file_material_from_direct()
            return
        self._show_direct_unhandled_action("skill_material")

    def _show_native_onboarding(self) -> None:
        twin = self._active_twin()
        if not twin:
            self.show_bubble("先完成原生配置窗口。照片生成并启用后，我再常驻桌面。", state="speaking", duration=5200)
            self._native_onboarding_pending = False
            return
        prompt = _native_onboarding_prompt(twin)
        self._append_chat("assistant", prompt["detail"])
        if self._last_action:
            self._last_action.set(prompt["label"])
        self.open_settings()
        self.show_bubble("设置中心打开了。你可以在里面改名字、用途和桌面行为。", state="speaking", duration=5200)
        self._native_onboarding_pending = False

    def _toggle_direct_settings(self) -> None:
        if self._redirect_first_run_to_setup():
            return
        if not self._direct_chat or not self._direct_chat.winfo_exists():
            self.open_direct_chat()
        if not self._direct_settings_visible:
            self._focus_direct_feature_layer({"settings"})
        self._direct_settings_visible = not self._direct_settings_visible
        if self._direct_settings_visible:
            self._direct_settings_picker_visible = False
            self._direct_settings_detail_visible = False
        else:
            self._direct_settings_detail_visible = False
        self._rebuild_direct_settings_card()

    def _set_direct_settings_section(self, section: str) -> None:
        self._direct_settings_section = _normalize_direct_settings_section(section)
        self._direct_settings_detail_visible = True
        self._direct_settings_picker_visible = False
        self._rebuild_direct_settings_card()

    def _toggle_direct_settings_picker(self) -> None:
        if self._direct_settings_picker_visible:
            self._direct_settings_detail_visible = True
            self._direct_settings_picker_visible = False
        else:
            self._direct_settings_detail_visible = False
            self._direct_settings_picker_visible = True
        self._rebuild_direct_settings_card()

    def _open_direct_settings_detail_layer(self) -> None:
        self._direct_settings_detail_visible = False
        self._direct_settings_picker_visible = True
        self._rebuild_direct_settings_card()

    def _hide_direct_settings_layer(self) -> None:
        self._direct_settings_visible = False
        self._direct_settings_detail_visible = False
        self._direct_settings_picker_visible = False
        self._rebuild_direct_settings_card()

    def _rebuild_direct_settings_card(self) -> None:
        if not self._direct_settings_frame:
            return
        layer_bg = self._transparent_bg
        for child in self._direct_settings_frame.winfo_children():
            child.destroy()
        if not self._direct_settings_visible:
            self._direct_settings_frame.pack_forget()
            self._position_direct_chat()
            return
        twin = self._active_twin()
        snapshot = _direct_settings_snapshot(twin)
        self._direct_name_var = tk.StringVar(value=snapshot["displayName"])
        self._direct_purpose_var = tk.StringVar(value=snapshot["purpose"])
        self._direct_tone_var = tk.StringVar(value=snapshot["tone"])
        self._direct_mode_var = tk.StringVar(value=snapshot["defaultMode"])
        self._direct_appearance_var = tk.StringVar(value=snapshot["appearanceId"])
        pack_options: dict[str, Any] = {"fill": "x", "padx": 12, "pady": (0, 10)}
        self._direct_settings_frame.pack(**pack_options)

        onboarding = _native_onboarding_prompt(twin)
        section_id = "identity" if self._native_onboarding_pending else _normalize_direct_settings_section(
            self._direct_settings_section
        )
        self._direct_settings_section = section_id
        section = next(
            (item for item in _direct_settings_section_specs() if item["id"] == section_id),
            _direct_settings_section_specs()[0],
        )
        self._pack_direct_speech_bubble(
            self._direct_settings_frame,
            title=onboarding["label"] if self._native_onboarding_pending else f"怎么配合你，{snapshot['displayName']}？",
            detail=(
                onboarding["detail"]
                if self._native_onboarding_pending
                else "先选一个设置层，我再只展开那一层。"
                if self._direct_settings_picker_visible and not self._direct_settings_detail_visible
                else "设置先不全部展开。你可以直接说一句，或只打开一个设置层。"
                if not self._direct_settings_detail_visible and not self._direct_settings_picker_visible
                else str(section["detail"])
            ),
        )

        if (
            not self._native_onboarding_pending
            and not self._direct_settings_detail_visible
            and not self._direct_settings_picker_visible
        ):
            self._pack_direct_bubble_buttons(
                self._direct_settings_frame,
                [
                    {"id": "talk", "label": "直接说"},
                    {"id": "layers", "label": "展开设置"},
                    {"id": "close", "label": "收起"},
                ],
                lambda item: (
                    self._open_direct_settings_detail_layer()
                    if str(item.get("id") or "") == "layers"
                    else self._hide_direct_settings_layer()
                    if str(item.get("id") or "") == "close"
                    else self._focus_direct_entry_for_settings()
                ),
                primary_id="talk",
                columns=3,
                pady=(0, 10),
            )
            self._position_direct_chat()
            return

        if not self._native_onboarding_pending and self._direct_settings_picker_visible:
            self._pack_direct_bubble_buttons(
                self._direct_settings_frame,
                _direct_settings_section_specs(),
                lambda item: self._set_direct_settings_section(str(item.get("id") or "")),
                active_id=section_id,
                columns=3,
                pady=(0, 8),
            )
            if not self._direct_settings_detail_visible:
                self._pack_direct_bubble_buttons(
                    self._direct_settings_frame,
                    [
                        {"id": "talk", "label": "直接说"},
                        {"id": "close", "label": "收起"},
                    ],
                    lambda item: (
                        self._hide_direct_settings_layer()
                        if str(item.get("id") or "") == "close"
                        else self._focus_direct_entry_for_settings()
                    ),
                    primary_id="talk",
                    columns=2,
                    pady=(0, 10),
                )
                self._position_direct_chat()
                return

        layer = tk.Frame(self._direct_settings_frame, bg=layer_bg)
        layer.pack(fill="x", padx=10, pady=(0, 9))

        if section_id == "identity":
            self._pack_direct_value_bubbles(
                layer,
                [
                    {"label": "现在的名字", "value": snapshot["displayName"]},
                    {"label": "现在的用途", "value": snapshot["purpose"]},
                    {"label": "想改的话", "value": "直接说：以后叫你小九，或者用途改成写作搭档。"},
                ],
            )
        elif section_id == "tone":
            self._pack_direct_bubble_buttons(
                layer,
                [{"id": value, "label": label} for label, value in DIRECT_TONE_PRESETS],
                lambda item: (
                    self._direct_tone_var.set(str(item.get("id") or "")),
                    self._rebuild_direct_settings_card(),
                ) if self._direct_tone_var else None,
                active_id=self._direct_tone_var.get() if self._direct_tone_var else "",
                columns=3,
                padx=0,
                pady=(0, 4),
            )
        elif section_id == "permission":
            self._pack_direct_bubble_buttons(
                layer,
                [{"id": value, "label": label} for label, value in DIRECT_PERMISSION_PRESETS],
                lambda item: (
                    self._direct_mode_var.set(str(item.get("id") or "")),
                    self._rebuild_direct_settings_card(),
                ) if self._direct_mode_var else None,
                active_id=self._direct_mode_var.get() if self._direct_mode_var else "",
                columns=3,
                padx=0,
                pady=(0, 4),
            )
        elif section_id == "size":
            current_size = _normalize_avatar_size(self.size)
            self._pack_direct_bubble_buttons(
                layer,
                [{"id": str(value), "label": label, "size": value} for label, value in DIRECT_SIZE_PRESETS],
                lambda item: self._set_avatar_size(int(item.get("size") or DEFAULT_AVATAR_SIZE)),
                active_id=str(current_size),
                columns=3,
                padx=0,
                pady=(0, 4),
            )
        elif section_id == "appearance":
            self._pack_direct_bubble_buttons(
                layer,
                [{"id": str(preset["id"]), "label": str(preset["label"])[:4]} for preset in appearance_presets()],
                lambda item: (
                    self._direct_appearance_var.set(str(item.get("id") or "")),
                    self._rebuild_direct_settings_card(),
                ) if self._direct_appearance_var else None,
                active_id=self._direct_appearance_var.get() if self._direct_appearance_var else "",
                columns=3,
                padx=0,
                pady=(0, 4),
            )

        action_items: list[dict[str, Any]] = (
            [{"id": "talk", "label": "直接说给我"}]
            if section_id == "identity"
            else [{"id": "save", "label": "记住这一层"}]
        )
        if not self._native_onboarding_pending:
            action_items.append(
                {
                    "id": "layers",
                    "label": "换一层",
                }
            )
        self._pack_direct_bubble_buttons(
            self._direct_settings_frame,
            action_items,
            lambda item: (
                self._toggle_direct_settings_picker()
                if str(item.get("id") or "") == "layers"
                else self._focus_direct_entry_for_settings()
                if str(item.get("id") or "") == "talk"
                else self._save_direct_settings()
            ),
            primary_id="save",
            columns=2,
            pady=(0, 10),
        )
        self._position_direct_chat()

    def _focus_direct_entry_for_settings(self) -> None:
        if self._direct_entry:
            try:
                self._direct_entry.focus_set()
            except tk.TclError:
                pass
        self.show_bubble("直接说一句就行，比如“以后叫你小九”或“用途改成写作搭档”。", state="speaking", duration=5200)

    def _save_direct_settings(self, *, close_card: bool = True) -> dict[str, Any] | None:
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return None
        before = _direct_settings_snapshot(twin)
        display_name = self._direct_name_var.get() if self._direct_name_var else ""
        purpose = self._direct_purpose_var.get() if self._direct_purpose_var else ""
        tone = self._direct_tone_var.get() if self._direct_tone_var else ""
        mode = self._direct_mode_var.get() if self._direct_mode_var else "confirm_before_act"
        appearance_id = self._direct_appearance_var.get() if self._direct_appearance_var else before["appearanceId"]
        try:
            updated = self.store.update_twin(
                twin["id"],
                _direct_settings_payload(
                    tone,
                    mode,
                    display_name=display_name,
                    purpose=purpose,
                    appearance=appearance_id,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.show_bubble(f"保存失败：{_clip(str(exc), 70)}", state="error", duration=4200)
            return None
        self._active_twin_id = updated["id"]
        self._refresh_twin_name()
        if close_card:
            self._direct_settings_visible = False
            self._direct_settings_detail_visible = False
            self._direct_settings_picker_visible = False
            self._rebuild_direct_settings_card()
        if self._last_action:
            self._last_action.set("分身设置已更新。")
        if close_card:
            appearance_label = twin_appearance_label(updated.get("appearance"))
            self._append_chat(
                "assistant",
                f"我会用「{_permission_mode_label(mode)}」的权限、新语气和「{appearance_label}」外观配合你。",
            )
            self.show_bubble("好，我记住了。桌面形象继续使用当前 Codex pet 包。", state="success", duration=3000)
        return updated

    def _apply_native_settings_update(self, update: dict[str, Any]) -> None:
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return

        snapshot = _direct_settings_snapshot(twin)
        display_name = str(update.get("displayName") or snapshot["displayName"])
        purpose = str(update.get("purpose") or snapshot["purpose"])
        tone = str(update.get("tone") or snapshot["tone"])
        mode = str(update.get("defaultMode") or snapshot["defaultMode"])
        appearance = normalize_twin_appearance(update.get("appearance") or snapshot["appearanceId"])
        profile_changed = any(
            key in update for key in ("displayName", "purpose", "tone", "defaultMode", "appearance")
        )
        updated = twin
        try:
            if profile_changed:
                updated = self.store.update_twin(
                    twin["id"],
                    _direct_settings_payload(
                        tone,
                        mode,
                        display_name=display_name,
                        purpose=purpose,
                        appearance=appearance,
                    ),
                )
                self._active_twin_id = updated["id"]
        except Exception as exc:  # noqa: BLE001
            self.show_bubble(f"保存失败：{_clip(str(exc), 70)}", state="error", duration=4200)
            return

        if "size" in update:
            self._set_avatar_size(int(update["size"]))
        else:
            self._rebuild_direct_settings_card()
        self._refresh_twin_name()

        change_lines: list[str] = []
        if "displayName" in update:
            change_lines.append(f"名字叫「{_clip(display_name, 18)}」")
        if "purpose" in update:
            change_lines.append(f"用途是「{_clip(purpose, 28)}」")
        if "tone" in update:
            change_lines.append(f"语气改成「{_tone_label(tone)}」")
        if "defaultMode" in update:
            change_lines.append(f"权限改成「{_permission_mode_label(mode)}」")
        if "appearance" in update:
            change_lines.append(f"外观偏好记为「{twin_appearance_label(updated.get('appearance'))}」")
        if "size" in update:
            change_lines.append(f"桌面大小改成「{_avatar_size_label(self.size)}」")
        reply = "我记住了：" + "，".join(change_lines) + "。"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set("分身设置已更新。")
        self.show_bubble(reply, state="success", duration=3200)

    def _run_avatar_makeover_command(self, command: str) -> None:
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return

        key = str(command or "").strip()
        if key != "next_appearance":
            self.show_bubble("JiuMe 现在只导入 Codex pet 包，不在桌面里生成形象。", state="speaking", duration=4200)
            return
        appearance = _next_appearance_preset(twin.get("appearance"))
        try:
            updated = self.store.update_twin(
                twin["id"],
                _direct_settings_payload(
                    str(twin.get("tone") or ""),
                    str((twin.get("permissions") or {}).get("defaultMode") or "confirm_before_act")
                    if isinstance(twin.get("permissions"), dict)
                    else "confirm_before_act",
                    display_name=str(twin.get("displayName") or "JiuMe"),
                    purpose=str(twin.get("purpose") or ""),
                    appearance=appearance,
                ),
            )
            self._active_twin_id = updated["id"]
        except Exception as exc:  # noqa: BLE001
            self.show_bubble(f"保存外观偏好失败：{_clip(str(exc), 70)}", state="error", duration=4200)
            return
        if self._direct_appearance_var:
            self._direct_appearance_var.set(appearance["id"])
        self._rebuild_direct_settings_card()
        label = twin_appearance_label(updated.get("appearance"))
        reply = f"好，我把外观偏好记为「{label}」。桌面形象继续使用当前 Codex pet 包。"
        title = "记录外观偏好"
        self._append_chat("assistant", reply)
        self._record_activity("interaction", title, reply)
        if self._last_action:
            self._last_action.set(reply)
        self.show_bubble(reply, state="success", duration=3400)
        self._start_interaction_effect("dance")
        self.root.after(1400, lambda: self.set_state("idle"))

    def _rebuild_quick_action_rows(self) -> None:
        # Legacy boxed quick actions are retired; starts now live in direct avatar bubbles.
        if self._quick_actions_frame and self._quick_actions_frame.winfo_exists():
            self._quick_actions_frame.pack_forget()

    def _run_quick_action(self, action: dict[str, Any], *, user_line: str | None = None) -> None:
        title = str(action.get("title") or action.get("label") or "快捷动作")
        fallback = str(action.get("fallback") or "")
        state = str(action.get("state") or "speaking")
        if str(action.get("id") or "") == "focus":
            raw = user_line if user_line is not None else title
            self._append_chat("user", raw)
            self._run_native_focus_command(
                {"action": "start", "minutes": _focus_minutes_from_text(raw)},
                raw,
            )
            return
        if action.get("kind") == "local":
            if user_line:
                self._append_chat("user", user_line)
            self._append_chat("assistant", fallback or title)
            self._record_activity("interaction", title, fallback)
            if self._last_action:
                self._last_action.set(fallback or title)
            self.show_bubble(fallback or title, state=state, duration=4200 if state != "sleep" else None)
            return

        prompt = str(action.get("prompt") or "").strip()
        if not prompt:
            return
        self._append_chat("user", user_line if user_line is not None else title)
        self._append_chat("assistant", f"我来处理「{title}」。")
        self._record_activity("quick", f"快捷动作：{title}", prompt)
        if self._last_action:
            self._last_action.set(f"快捷动作：{title}")
        self.show_bubble(f"好，我来处理「{title}」。", state=state, duration=1800)
        if self.gateway:
            self._gateway_reply = ""
            self._stream_chat_index = None
            self.gateway.send_chat(
                prompt,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=prompt: self._post_gateway_event(msg, event),
            )
            return
        if fallback:
            self.root.after(420, lambda text=fallback: self._finish_quick_action_fallback(text))

    def _finish_quick_action_fallback(self, text: str) -> None:
        self._finish_assistant_stream(text, state="speaking")
        if self._last_action:
            self._last_action.set(_clip(text, 54))
        self.show_bubble(text, state="speaking", duration=5200)

    def _service_status_text(self) -> str:
        return _format_service_status(read_service_status())

    def _refresh_service_status(self) -> None:
        text = self._service_status_text()
        if self._service_status_label and self._service_status_label.winfo_exists():
            self._service_status_label.configure(text=text)
        self._rebuild_direct_service_card()

    def _show_service_status(self) -> None:
        if not self._direct_chat or not self._direct_chat.winfo_exists():
            self.open_direct_chat()
        self._rebuild_direct_service_card()
        text = self._service_status_text()
        if self._last_action:
            self._last_action.set(_clip("后台状态：" + text.replace("\n", "；"), 64))
        self.show_bubble(text, state="speaking", duration=5200)

    def _run_login_item_command(self, command: str, raw: str = "") -> None:
        key = str(command or "").strip()
        args = _login_item_command_args(
            key,
            size=self.size,
            gateway_url=self.gateway_url,
            agent_mode=self.agent_mode,
        )
        if not args:
            self.show_bubble("我还不认识这个登录启动指令。", state="speaking", duration=2800)
            return
        self._mark_activity()
        title_by_key = {"install": "开启登录启动", "uninstall": "关闭登录启动", "status": "查看登录启动"}
        title = title_by_key.get(key, "登录启动")
        self._record_activity("interaction", title, "JiuMe 正在处理 macOS 登录项。")
        try:
            result = subprocess.run(
                args,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=12,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            reply = f"{title}失败：{_clip(str(exc), 70)}"
            self._append_chat("assistant", reply)
            self.show_bubble(reply, state="error", duration=4200)
            return

        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
        detail = output or ("登录启动已处理。" if result.returncode == 0 else "登录启动命令没有返回详情。")
        if result.returncode != 0:
            reply = f"{title}失败：{_clip(detail, 90)}"
            state = "error"
        elif key == "install":
            reply = "好，我会在你下次登录后自动出现。"
            state = "success"
        elif key == "uninstall":
            reply = "好，我已关闭登录后自动出现。"
            state = "success"
        else:
            installed = "not installed" not in detail.lower()
            reply = "登录启动已开启。" if installed else "登录启动还没有开启。"
            state = "speaking"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(_clip(reply, 54))
        self.show_bubble(reply, state=state, duration=3800)

    def _clear_entry_placeholder(self, _event: tk.Event) -> None:
        if self._chat_entry and self._chat_entry.get() == "对分身说一句...":
            self._chat_entry.delete(0, "end")

    def _native_direct_chat_image(
        self,
        *,
        width: int,
        height: int,
        render_scale: float = 1.0,
    ) -> tuple[Image.Image, list[tuple[int, int, int, int, str]], dict[str, Any]]:
        scale = _native_render_scale(render_scale)
        image = Image.new("RGBA", (_scaled_int(width, scale), _scaled_int(height, scale)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        send_font = _desktop_font(_scaled_int(12, scale), bold=True)
        zones: list[tuple[int, int, int, int, str]] = []

        composer_width = min(DIRECT_CHAT_COMPOSER_WIDTH, max(214, width - 86))
        composer_height = DIRECT_CHAT_COMPOSER_HEIGHT
        composer_x = max(18, width - composer_width - 24)
        composer_y = max(10, (height - composer_height) // 2)
        if composer_y + composer_height > height - 2:
            composer_y = height - composer_height - 2

        _draw_smooth_round_rect(
            image,
            _scaled_box(
                (composer_x + 3, composer_y + 4, composer_x + composer_width - 2, composer_y + composer_height - 1),
                scale,
            ),
            radius=_scaled_int(24, scale),
            fill=_hex_rgba(DIRECT_SURFACE_SHADOW, DIRECT_MESSAGE_SHADOW_ALPHA),
        )
        _draw_smooth_round_rect(
            image,
            _scaled_box(
                (composer_x + 1, composer_y + 1, composer_x + composer_width - 5, composer_y + composer_height - 5),
                scale,
            ),
            radius=_scaled_int(24, scale),
            fill=_hex_rgba(DIRECT_INPUT_BG, 248),
            outline=_hex_rgba(DIRECT_SURFACE_EDGE, 112),
        )

        send_width = 76
        send_height = 40
        send_x = composer_x + composer_width - send_width - 12
        send_y = composer_y + 8
        action_label = "发送"
        _draw_smooth_round_rect(
            image,
            _scaled_box((send_x, send_y, send_x + send_width - 3, send_y + send_height - 3), scale),
            radius=_scaled_int(20, scale),
            fill=_hex_rgba(DIRECT_ACTION_BG, 255),
            outline=None,
        )
        label_width = _text_width(action_label, send_font)
        draw.text(
            (
                _scaled_int(send_x, scale) + (_scaled_int(send_width, scale) - label_width) // 2 - _scaled_int(1, scale),
                _scaled_int(send_y + 10, scale),
            ),
            action_label,
            font=send_font,
            fill=_hex_rgba(INVERSE_TEXT),
        )
        entry_x = composer_x + 18
        entry_y = composer_y + 17
        entry_width = max(84, send_x - entry_x - 10)
        text_input = {
            "frame": (entry_x, entry_y, entry_width, 32),
            "placeholder": ONE_LINE_INPUT_HINT,
            "on_submit": self._send_native_direct_message,
            "action_label": action_label,
            "font_size": 14,
            "text_color": INK,
        }
        zones.append((send_x, send_y, send_width, send_height, "send"))
        return image, zones, text_input

    def _native_direct_feature_image(
        self,
        *,
        surface: str,
        width: int,
        height: int,
    ) -> tuple[Image.Image, list[tuple[int, int, int, int, str]], dict[str, Any]]:
        key = _normalize_native_direct_surface(surface)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        title_font = _desktop_font(14, bold=True)
        body_font = _desktop_font(12)
        chip_font = _desktop_font(11, bold=True)
        zones: list[tuple[int, int, int, int, str]] = []

        if key == "settings":
            snapshot = _direct_settings_snapshot(self._active_twin())
            title = "设置"
            detail = "身份、语气、权限和外观分层调整；也可以直接在下面说一句。"
            values = [
                ("名字", snapshot["displayName"]),
                ("语气", _tone_label(snapshot["tone"])),
                ("权限", snapshot["defaultModeLabel"]),
                ("外观", snapshot["appearanceLabel"]),
            ]
            actions = [
                {"id": f"settings:{item['id']}", "label": item["label"]}
                for item in _direct_settings_section_specs()[:5]
            ]
            placeholder = "直接说：以后叫你小九..."
        elif key == "skills":
            skill_rows = self._direct_skill_rows()
            shortcuts = _direct_skill_shortcuts(skill_rows)
            active = _active_skill_snapshot(self._active_skill_context)
            title = "技能"
            detail = "先只露出常用 skill；点一个装载或使用，也可以直接说任务。"
            values = [
                ("当前", active["displayName"] if active else "未固定 skill"),
                ("可用", f"{len(skill_rows)} 个推荐 skill"),
            ]
            actions = []
            rows_by_id = {str(skill.get("id") or ""): dict(skill) for skill in skill_rows}
            for shortcut in shortcuts[:4]:
                skill_id = str(shortcut.get("id") or "")
                if not skill_id or skill_id not in rows_by_id:
                    continue
                prefix = "用 " if shortcut.get("isEnabled") else "装 "
                actions.append({"id": f"skill:{skill_id}", "label": prefix + _clip(str(shortcut.get("displayName") or skill_id), 8)})
            if not actions:
                actions = [{"id": "skills:more", "label": "更多"}]
            placeholder = "说：用会议纪要 skill..."
        else:
            summary = _direct_activity_summary(self._activity_items)
            title = "进度"
            if summary:
                detail = _clip(str(summary.get("detail") or summary.get("title") or "最近任务"), 84)
                values = [
                    ("任务", str(summary.get("title") or "最近任务")),
                    ("阶段", str(summary.get("stage") or _activity_stage_label(str(summary.get("kind") or "")))),
                ]
            else:
                detail = "现在没有正在执行的任务。你可以直接说一句，我会接住下一件事。"
                values = [("状态", "没有正在执行的任务"), ("下一步", "点头像说一句")]
            actions = [
                {"id": "progress:detail", "label": "展开进度"},
                {"id": "chat", "label": "补一句"},
            ]
            placeholder = "补一句当前任务..."

        card_x = 8
        card_y = 8
        card_w = min(348, width - 50)
        card_h = 78
        draw.rounded_rectangle(
            (card_x + 3, card_y + 4, card_x + card_w + 3, card_y + card_h + 4),
            radius=20,
            fill=_hex_rgba(DIRECT_SURFACE_SHADOW, DIRECT_MESSAGE_SHADOW_ALPHA),
        )
        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_w, card_y + card_h),
            radius=20,
            fill=_hex_rgba(DIRECT_ASSISTANT_BUBBLE, 248),
            outline=_hex_rgba(DIRECT_SURFACE_EDGE, 210),
        )
        draw.line((card_x + 18, card_y + 2, card_x + card_w - 22, card_y + 2), fill=_hex_rgba(DIRECT_GLASS_HIGHLIGHT, 140), width=1)
        draw.line((card_x + 18, card_y + card_h - 2, card_x + 70, card_y + card_h - 2), fill=_hex_rgba(DIRECT_CHAMPAGNE, 100), width=1)
        draw.text((card_x + 18, card_y + 13), title, font=title_font, fill=_hex_rgba(INK))
        _draw_pil_text(
            draw,
            (card_x + 18, card_y + 40),
            detail,
            font=body_font,
            fill=MUTED,
            max_width=card_w - 36,
            max_lines=2,
            line_gap=2,
        )

        value_y = card_y + card_h + 12
        value_w = (card_w - 8) // 2
        value_h = 42
        for index, (label, value) in enumerate(values[:4]):
            col = index % 2
            row = index // 2
            x1 = card_x + col * (value_w + 8)
            y1 = value_y + row * (value_h + 8)
            draw.rounded_rectangle(
                (x1, y1, x1 + value_w, y1 + value_h),
                radius=16,
                fill=_hex_rgba(DIRECT_INPUT_BG, 246),
                outline=_hex_rgba(DIRECT_SURFACE_EDGE, 150),
            )
            draw.text((x1 + 11, y1 + 7), str(label), font=chip_font, fill=_hex_rgba(MUTED))
            _draw_pil_text(
                draw,
                (x1 + 11, y1 + 22),
                _clip(str(value), 24),
                font=body_font,
                fill=INK,
                max_width=value_w - 22,
                max_lines=1,
                line_gap=1,
            )

        value_rows = max(1, (len(values[:4]) + 1) // 2)
        action_y = value_y + value_rows * (value_h + 8)
        chip_x = card_x
        for index, action in enumerate(actions[:5]):
            label = str(action.get("label") or "")
            chip_w = max(58, min(110, _text_width(label, chip_font) + 24))
            if chip_x + chip_w > card_x + card_w:
                chip_x = card_x
                action_y += 31
            active = index == 0
            fill = ACCENT if active else DIRECT_INPUT_BG
            text_fill = INVERSE_TEXT if active else INK
            draw.rounded_rectangle(
                (chip_x, action_y, chip_x + chip_w, action_y + 25),
                radius=12,
                fill=_hex_rgba(fill, 248),
                outline=_hex_rgba(DIRECT_SURFACE_EDGE, 150) if not active else None,
            )
            label_w = _text_width(label, chip_font)
            draw.text(
                (chip_x + (chip_w - label_w) // 2, action_y + 6),
                label,
                font=chip_font,
                fill=_hex_rgba(text_fill),
            )
            zones.append((chip_x, action_y, chip_w, 25, str(action.get("id") or "")))
            chip_x += chip_w + 8

        composer_width = min(DIRECT_CHAT_COMPOSER_WIDTH, max(214, width - 86))
        composer_height = DIRECT_CHAT_COMPOSER_HEIGHT
        composer_x = max(18, width - composer_width - 24)
        composer_y = height - composer_height - 4
        draw.rounded_rectangle(
            (composer_x + 3, composer_y + 4, composer_x + composer_width - 2, composer_y + composer_height - 1),
            radius=24,
            fill=_hex_rgba(DIRECT_SURFACE_SHADOW, DIRECT_MESSAGE_SHADOW_ALPHA),
        )
        draw.rounded_rectangle(
            (composer_x + 1, composer_y + 1, composer_x + composer_width - 5, composer_y + composer_height - 5),
            radius=24,
            fill=_hex_rgba(DIRECT_INPUT_BG, 248),
            outline=_hex_rgba(DIRECT_SURFACE_EDGE, 155),
        )
        send_width = 76
        send_height = 40
        send_x = composer_x + composer_width - send_width - 12
        send_y = composer_y + 8
        draw.rounded_rectangle(
            (send_x, send_y, send_x + send_width - 3, send_y + send_height - 3),
            radius=20,
            fill=_hex_rgba(DIRECT_ACTION_BG, 255),
            outline=_hex_rgba(DIRECT_CHAMPAGNE, 170),
        )
        send_label = "发送"
        send_label_w = _text_width(send_label, chip_font)
        draw.text(
            (send_x + (send_width - send_label_w) // 2 - 1, send_y + 10),
            send_label,
            font=chip_font,
            fill=_hex_rgba(INVERSE_TEXT),
        )
        entry_x = composer_x + 18
        entry_y = composer_y + 17
        entry_width = max(84, send_x - entry_x - 10)
        zones.append((send_x, send_y, send_width, send_height, "send"))
        return image, zones, {
            "frame": (entry_x, entry_y, entry_width, 30),
            "placeholder": placeholder,
            "on_submit": self._send_native_direct_message,
            "font_size": 14,
            "text_color": INK,
        }

    def _native_direct_surface_image(
        self,
        *,
        surface: str,
        width: int,
        height: int,
        render_scale: float = 1.0,
    ) -> tuple[Image.Image, list[tuple[int, int, int, int, str]], dict[str, Any]]:
        key = _normalize_native_direct_surface(surface)
        if key == "chat":
            return self._native_direct_chat_image(width=width, height=height, render_scale=render_scale)
        image, zones, text_input = self._native_direct_feature_image(surface=key, width=width, height=height)
        scale = _native_render_scale(render_scale)
        if scale > 1.0:
            image = image.resize((_scaled_int(width, scale), _scaled_int(height, scale)), Image.Resampling.LANCZOS)
        return image, zones, text_input

    def _position_native_direct_chat(self) -> None:
        width = DIRECT_CHAT_WIDTH
        surface = _normalize_native_direct_surface(getattr(self, "_native_direct_surface", "chat"))
        if surface == "chat":
            natural_height = ONE_LINE_DIRECT_HEIGHT
        else:
            natural_height = 326
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        height = _direct_chat_window_height(natural_height, screen_height)
        try:
            render_scale = self.overlay.native_backing_scale()
        except Exception:
            render_scale = 1.0
        image, zones, text_input = self._native_direct_surface_image(
            surface=surface,
            width=width,
            height=height,
            render_scale=render_scale,
        )
        icon_x = self.root.winfo_x()
        icon_y = self.root.winfo_y()
        geometry = _direct_chat_geometry_for_avatar(
            icon_x=icon_x,
            icon_y=icon_y,
            size=self.size,
            width=width,
            height=height,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        self.overlay.show_image_layer(
            "direct_chat",
            image,
            x=int(geometry["x"]),
            y=int(geometry["y"]),
            click_zones=zones,
            on_click=self._handle_native_direct_action,
            on_scroll=None,
            text_input=text_input,
            logical_size=(width, height),
        )

    def _handle_native_direct_scroll(self, delta_y: float) -> None:
        if _normalize_native_direct_surface(getattr(self, "_native_direct_surface", "chat")) != "chat":
            return
        try:
            delta = float(delta_y)
        except (TypeError, ValueError):
            return
        if abs(delta) < 0.01:
            return
        current = max(0, int(getattr(self, "_direct_chat_scroll_offset", 0) or 0))
        maximum = _conversation_max_scroll_offset(self._chat_items)
        next_offset = current + (1 if delta > 0 else -1)
        next_offset = max(0, min(maximum, next_offset))
        if next_offset == current:
            return
        self._direct_chat_scroll_offset = next_offset
        self._position_direct_chat()

    def _handle_native_direct_action(self, action_id: str) -> None:
        action = str(action_id or "").strip()
        if action in {"chat", "settings", "skills", "progress"}:
            self._run_native_control_command("direct_chat" if action == "chat" else action)
            return
        if action.startswith("settings:"):
            self.open_settings()
            return
        if action.startswith("skill:"):
            skill_id = action.split(":", 1)[1]
            skill = next((row for row in self._direct_skill_rows() if str(row.get("id") or "") == skill_id), None)
            if skill:
                if bool(skill.get("isEnabled")):
                    self._start_skill_task(dict(skill))
                else:
                    self._set_skill_enabled(dict(skill), True)
            return
        if action == "skills:more":
            self._direct_skill_section = "more"
            self._open_native_direct_surface("skills")
            return
        if action == "progress:detail":
            self._direct_activity_detail_visible = True
            self._open_native_direct_surface("progress")
            return
        if action == "materials":
            self._direct_help_section = "materials"
            self._open_native_direct_surface("chat")
            self.show_bubble("材料可以直接拖给我，也可以在输入框里贴路径。", state="speaking", duration=2600)
            return
        if action == "send":
            self.show_bubble("直接输入任务，按回车或点发送。", state="speaking", duration=2200)
            return

    def _send_native_direct_message(self, raw: str) -> None:
        message = str(raw or "").strip()
        if not message:
            self.show_bubble("我在，直接说一句就行。", state="speaking", duration=2600)
            return
        self._close_direct_chat()
        self._set_one_line_capsule(working_capsule("在想"))
        self._send_text_message(message)

    def _position_direct_chat(self) -> None:
        if self._native_direct_chat_visible and _uses_native_direct_chat():
            self._position_native_direct_chat()
            return
        if not self._direct_chat or not self._direct_chat.winfo_exists():
            return
        width = DIRECT_CHAT_WIDTH
        self._direct_chat_scroll_offset = max(
            0,
            min(
                int(getattr(self, "_direct_chat_scroll_offset", 0) or 0),
                _conversation_max_scroll_offset(self._chat_items),
            ),
        )
        natural_height = _direct_chat_height(
            len(
                _conversation_preview_items(
                    self._chat_items,
                    offset=getattr(self, "_direct_chat_scroll_offset", 0),
                )
            ),
            has_approval=self._direct_frame_is_packed(self._direct_approval_frame),
            has_skill_shortcuts=self._direct_frame_is_packed(self._direct_skills_frame),
            has_settings=self._direct_settings_visible,
            has_activity=self._direct_frame_is_packed(self._direct_activity_frame),
            has_artifacts=self._direct_frame_is_packed(self._direct_artifact_frame),
            has_companion=self._direct_companion_visible and self._direct_frame_is_packed(self._direct_companion_frame),
            has_service=self._direct_frame_is_packed(self._direct_service_frame),
            has_help=self._direct_frame_is_packed(self._direct_help_frame),
            has_quick_actions=self._direct_frame_is_packed(self._direct_quick_frame),
        )
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        content_height = 0
        if self._direct_content_frame and self._direct_content_frame.winfo_exists():
            try:
                self._direct_content_frame.update_idletasks()
                content_height = int(self._direct_content_frame.winfo_reqheight())
            except tk.TclError:
                content_height = 0
        if content_height > 0:
            natural_height = max(natural_height, _direct_chat_content_window_height(content_height))
        height = _direct_chat_window_height(natural_height, screen_height)
        if self._direct_surface_canvas and self._direct_surface_canvas.winfo_exists():
            rect = _direct_chat_content_rect(width, height)
            self._direct_surface_canvas.configure(width=width, height=height)
            if self._direct_surface_window is not None:
                self._direct_surface_canvas.coords(self._direct_surface_window, rect["x"], rect["y"])
                self._direct_surface_canvas.itemconfigure(
                    self._direct_surface_window,
                    width=rect["width"],
                    height=rect["height"],
                )
            self._draw_direct_chat_surface(width=width, height=height)
        if self._direct_scroll_canvas and self._direct_scroll_canvas.winfo_exists():
            self._direct_scroll_canvas.configure(height=_direct_chat_scroll_height(height))
        icon_x = self.root.winfo_x()
        icon_y = self.root.winfo_y()
        geometry = _direct_chat_geometry_for_avatar(
            icon_x=icon_x,
            icon_y=icon_y,
            size=self.size,
            width=width,
            height=height,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        self._direct_chat.geometry(f"{width}x{height}+{int(geometry['x'])}+{int(geometry['y'])}")

    def _position_panel(self) -> None:
        # Legacy boxed control panel is retired; direct chat positions the avatar-side bubbles.
        if self._panel and self._panel.winfo_exists():
            self._panel.withdraw()

    def open_settings(self) -> None:
        self._mark_activity()
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return
        from jiume.desktop.settings_center import SettingsCenterCallbacks, SettingsCenterWindow

        if self._settings_center is None:
            self._settings_center = SettingsCenterWindow(
                root=self.root,
                store=self.store,
                active_twin_id=str(twin["id"]),
                current_size=self.size,
                gateway_url=self.gateway_url,
                agent_mode=self.agent_mode,
                callbacks=SettingsCenterCallbacks(
                    on_saved=self._after_settings_center_saved,
                    on_quit=self.root.destroy,
                ),
            )
        else:
            self._settings_center.active_twin_id = str(twin["id"])
            self._settings_center.current_size = self.size
            self._settings_center.gateway_url = self.gateway_url
            self._settings_center.agent_mode = self.agent_mode
        self._settings_center.open()

    def _after_settings_center_saved(self) -> None:
        self._refresh_twin_name()
        saved_window_state = read_window_state()
        if isinstance(saved_window_state.get("size"), int):
            self._set_avatar_size(_normalize_avatar_size(saved_window_state["size"], default=self.size))
        if self._active_twin_id:
            try:
                self._manifest = self.avatars.get_manifest(self._active_twin_id)
            except (FileNotFoundError, KeyError, OSError):
                pass
        self._avatar_cache.clear()
        self._render_avatar_frame()
        self._last_action.set("设置已更新。") if self._last_action else None

    def _open_legacy_settings_panel(self, twin: dict[str, Any]) -> None:
        self.open_settings()

    def _close_settings(self) -> None:
        self._direct_settings_visible = False
        self._direct_settings_detail_visible = False
        self._direct_settings_picker_visible = False
        self._rebuild_direct_settings_card()

    def _record_activity(
        self,
        kind: str,
        title: str,
        detail: str = "",
        artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        item = {
            "kind": kind,
            "title": title,
            "detail": _clip(detail, 120),
            "artifacts": artifacts or [],
            "time": time.strftime("%H:%M"),
        }
        self._activity_items.insert(0, item)
        del self._activity_items[8:]
        self._direct_activity_more_visible = False
        self._direct_activity_detail_visible = False
        self._persist_desktop_history()
        self._rebuild_activity_rows()
        self._rebuild_direct_activity_card()
        self._mark_activity()
        self._sync_work_hud_from_activity(kind, title, detail)

    def _rebuild_activity_rows(self) -> None:
        # Legacy boxed activity log is retired; progress lives in the direct avatar bubble layer.
        if self._activity_frame and self._activity_frame.winfo_exists():
            self._activity_frame.pack_forget()

    @staticmethod
    def _artifact_type_label(category: str) -> str:
        labels = {
            "image": "图片",
            "code": "代码",
            "table": "表格",
            "text": "文本",
            "link": "链接",
            "file": "文件",
        }
        return labels.get(str(category or ""), "产物")

    @staticmethod
    def _artifact_preview_action_specs(
        artifact: dict[str, Any],
        *,
        can_copy: bool = False,
    ) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []
        if can_copy or JiuMeDesktopAvatar._artifact_copy_target(artifact):
            actions.append({"id": "copy", "label": "复制"})
        target = str(artifact.get("target") or "").strip()
        if target and str(artifact.get("kind") or "") != "inline":
            actions.append({"id": "open", "label": "打开"})
        return actions

    @staticmethod
    def _artifact_copy_target(artifact: dict[str, Any]) -> str:
        target = str(artifact.get("target") or "").strip()
        if not target or target.startswith("inline:") or str(artifact.get("kind") or "") == "inline":
            return ""
        if target.startswith("file://"):
            parsed = urlparse(target)
            return unquote(parsed.path) or target
        return target

    @staticmethod
    def _image_artifact_path(artifact: dict[str, Any]) -> Path | None:
        target = str(artifact.get("target") or "").strip()
        if not target:
            return None
        if target.startswith("file://"):
            parsed = urlparse(target)
            target = unquote(parsed.path)
        elif target.startswith(("http://", "https://", "inline:")):
            return None
        path = Path(target).expanduser()
        if path.exists() and path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}:
            return path
        return None

    @staticmethod
    def _can_preview_artifact(artifact: dict[str, Any]) -> bool:
        category = str(artifact.get("category") or "")
        if category == "image":
            return JiuMeDesktopAvatar._image_artifact_path(artifact) is not None
        if str(artifact.get("preview") or "").strip():
            return True
        target = str(artifact.get("target") or "")
        if str(artifact.get("kind") or "") != "file" or not target:
            return False
        path = Path(target).expanduser()
        return path.exists() and path.is_file() and path.suffix.lower() in {
            ".txt",
            ".md",
            ".markdown",
            ".json",
            ".csv",
            ".tsv",
            ".log",
            ".yaml",
            ".yml",
            ".py",
            ".js",
            ".ts",
            ".tsx",
        } and path.stat().st_size <= 512 * 1024

    def _artifact_preview_text(self, artifact: dict[str, Any]) -> str:
        preview = str(artifact.get("preview") or "").strip()
        if preview:
            return preview
        target = str(artifact.get("target") or "")
        path = Path(target).expanduser()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(target)
        return path.read_text(encoding="utf-8", errors="replace")

    def _pack_direct_artifact_frame(self) -> bool:
        if not self._direct_chat or not self._direct_chat.winfo_exists():
            self.open_direct_chat()
        if not self._direct_artifact_frame:
            return False
        if self._artifact_panel and self._artifact_panel.winfo_exists():
            self._artifact_panel.destroy()
        self._artifact_panel = None
        pack_options: dict[str, Any] = {"fill": "x", "padx": 12, "pady": (0, 10)}
        if self._direct_frame_is_packed(self._direct_activity_frame):
            pack_options["before"] = self._direct_activity_frame
        elif self._direct_frame_is_packed(self._direct_approval_frame):
            pack_options["before"] = self._direct_approval_frame
        elif self._direct_frame_is_packed(self._direct_quick_frame):
            pack_options["before"] = self._direct_quick_frame
        elif self._direct_frame_is_packed(self._direct_skills_frame):
            pack_options["before"] = self._direct_skills_frame
        elif self._direct_frame_is_packed(self._direct_settings_frame):
            pack_options["before"] = self._direct_settings_frame
        self._direct_artifact_frame.pack(**pack_options)
        return True

    def _clear_direct_artifact_frame(self) -> None:
        if not self._direct_artifact_frame:
            return
        for child in self._direct_artifact_frame.winfo_children():
            child.destroy()
        self._direct_artifact_frame.pack_forget()
        self._position_direct_chat()

    def _show_direct_artifact_preview(
        self,
        artifact: dict[str, Any],
        *,
        preview_text: str = "",
        image: Image.Image | None = None,
        image_path: Path | None = None,
    ) -> None:
        if not self._pack_direct_artifact_frame() or not self._direct_artifact_frame:
            return
        for child in self._direct_artifact_frame.winfo_children():
            child.destroy()
        layer_bg = self._transparent_bg
        title = _clip(str(artifact.get("label") or image_path or "产物预览"), 32)
        self._pack_direct_speech_bubble(
            self._direct_artifact_frame,
            title=title,
            detail="我把这个产物拿到头像旁边了。",
            padx=0,
            pady=(2, 5),
        )
        header_actions = [{"id": "close", "label": "收起"}]
        if _activity_artifact_cards(self._activity_items):
            header_actions.insert(0, {"id": "list", "label": "列表"})
        self._pack_direct_bubble_buttons(
            self._direct_artifact_frame,
            header_actions,
            lambda item: (
                self._rebuild_direct_artifact_tray(category=self._direct_artifact_category)
                if str(item.get("id") or "") == "list"
                else self._clear_direct_artifact_frame()
            ),
            primary_id="list" if len(header_actions) > 1 else "close",
            columns=2,
            padx=0,
            pady=(0, 7),
        )

        if image is not None:
            self._artifact_photo = ImageTk.PhotoImage(image)
            image_canvas = tk.Canvas(
                self._direct_artifact_frame,
                bg=layer_bg,
                bd=0,
                highlightthickness=0,
                width=max(1, self._artifact_photo.width()),
                height=max(1, self._artifact_photo.height()),
            )
            image_canvas.pack(padx=0, pady=(2, 10))
            image_canvas.create_image(0, 0, image=self._artifact_photo, anchor="nw")
        else:
            self._pack_direct_text_preview_bubble(
                self._direct_artifact_frame,
                title="预览内容",
                text=preview_text or "这个产物没有可预览的文本。",
                padx=0,
                pady=(2, 10),
            )

        actions = self._artifact_preview_action_specs(artifact, can_copy=bool(preview_text))
        if actions:
            self._pack_direct_bubble_buttons(
                self._direct_artifact_frame,
                [dict(spec) for spec in actions],
                lambda item: self._run_artifact_preview_action(str(item.get("id") or ""), artifact, preview_text),
                primary_id="copy" if any(str(spec.get("id") or "") == "copy" for spec in actions) else str(actions[0]["id"]),
                columns=2,
                pady=(0, 8),
            )
        self._position_direct_chat()

    def _preview_activity_artifact(self, artifact: dict[str, Any]) -> None:
        if str(artifact.get("category") or "") == "image":
            self._preview_image_artifact(artifact)
            return
        try:
            text = self._artifact_preview_text(artifact)
        except Exception as exc:  # noqa: BLE001
            self.show_bubble(f"预览失败：{_clip(str(exc), 58)}", state="error", duration=3200)
            return
        preview_text = text[:ARTIFACT_PREVIEW_CHAR_LIMIT]
        self._show_direct_artifact_preview(artifact, preview_text=preview_text)

    def _run_artifact_preview_action(self, action_id: str, artifact: dict[str, Any], preview_text: str = "") -> None:
        action = str(action_id or "").strip()
        if action == "copy":
            self._copy_artifact_to_clipboard(artifact, preview_text=preview_text)
            return
        if action == "open":
            target = str(artifact.get("target") or "")
            self._open_activity_target(target)

    def _preview_image_artifact(self, artifact: dict[str, Any]) -> None:
        path = self._image_artifact_path(artifact)
        if path is None:
            self.show_bubble("这个图片产物暂时只能打开，不能直接预览。", state="speaking", duration=3200)
            return
        try:
            image = Image.open(path).convert("RGBA")
            image.thumbnail((520, 360), Image.Resampling.LANCZOS)
        except Exception as exc:  # noqa: BLE001
            self.show_bubble(f"图片预览失败：{_clip(str(exc), 58)}", state="error", duration=3200)
            return
        self._show_direct_artifact_preview(artifact, image=image, image_path=path)

    def _copy_artifact_to_clipboard(self, artifact: dict[str, Any], *, preview_text: str = "") -> None:
        text = str(preview_text or "").strip()
        copied_target = False
        if not text and self._can_preview_artifact(artifact) and str(artifact.get("category") or "") != "image":
            try:
                text = self._artifact_preview_text(artifact)[:ARTIFACT_PREVIEW_CHAR_LIMIT]
            except Exception:
                text = ""
        if not text:
            text = self._artifact_copy_target(artifact)
            copied_target = bool(text)
        if not text:
            self.show_bubble("这个产物没有可复制的内容或位置。", state="speaking", duration=2600)
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError as exc:
            self.show_bubble(f"复制失败：{_clip(str(exc), 58)}", state="error", duration=3200)
            return
        label = _clip(str(artifact.get("label") or "产物"), 24)
        if self._last_action:
            self._last_action.set(f"已复制：{label}")
        noun = "位置" if copied_target else "预览内容"
        self.show_bubble(f"已复制「{label}」的{noun}。", state="success", duration=2400)

    def _rebuild_direct_artifact_tray(self, *, category: str = "") -> None:
        cards = _activity_artifact_cards(
            self._activity_items,
            category=category,
            limit=ARTIFACT_TRAY_LIMIT,
        )
        self._direct_artifact_category = category
        if not cards:
            self._append_chat("assistant", "我这里还没有能列出来的产物。")
            self.show_bubble("现在还没有产物托盘内容。", state="speaking", duration=2800)
            self._clear_direct_artifact_frame()
            return
        if not self._pack_direct_artifact_frame() or not self._direct_artifact_frame:
            return
        for child in self._direct_artifact_frame.winfo_children():
            child.destroy()
        detail = f"找到 {len(cards)} 个"
        if category:
            detail = f"{self._artifact_type_label(category)} · {detail}"
        self._pack_direct_speech_bubble(
            self._direct_artifact_frame,
            title="最近产物",
            detail=detail,
            padx=0,
            pady=(2, 5),
        )
        self._pack_direct_bubble_buttons(
            self._direct_artifact_frame,
            [{"id": "close", "label": "收起"}],
            lambda item: self._clear_direct_artifact_frame(),
            primary_id="close",
            columns=1,
            padx=0,
            pady=(0, 7),
        )
        for card in cards:
            artifact = dict(card.get("artifact") or {})
            meta = str(card.get("activityTitle") or "")
            if card.get("activityTime"):
                meta = f"{meta} · {card['activityTime']}"
            self._pack_direct_value_bubbles(
                self._direct_artifact_frame,
                [
                    {
                        "label": f"{self._artifact_type_label(str(card['category']))} · {card['label']}",
                        "value": meta or "最近任务产物",
                    }
                ],
                padx=0,
                pady=(0, 4),
            )
            action_items: list[dict[str, Any]] = []
            if self._can_preview_artifact(artifact):
                action_items.append({"id": "preview", "label": "查看", "artifact": dict(artifact)})
            if self._can_preview_artifact(artifact) or self._artifact_copy_target(artifact):
                action_items.append({"id": "copy", "label": "复制", "artifact": dict(artifact)})
            if str(artifact.get("kind") or "") != "inline":
                action_items.append({"id": "open", "label": "打开", "target": str(artifact.get("target") or "")})
            self._pack_direct_bubble_buttons(
                self._direct_artifact_frame,
                action_items,
                lambda item: (
                    self._preview_activity_artifact(dict(item.get("artifact") or {}))
                    if str(item.get("id") or "") == "preview"
                    else self._copy_artifact_to_clipboard(dict(item.get("artifact") or {}))
                    if str(item.get("id") or "") == "copy"
                    else self._open_activity_target(str(item.get("target") or ""))
                ),
                primary_id="preview" if any(str(item.get("id") or "") == "preview" for item in action_items) else "",
                columns=3,
                padx=0,
                pady=(0, 8),
            )
        if self._last_action:
            self._last_action.set(f"最近产物：{len(cards)} 个")
        self.show_bubble(f"我把最近 {len(cards)} 个产物列出来了。", state="speaking", duration=2600)
        self._position_direct_chat()

    def _show_artifact_tray(self, raw: str = "", *, category: str = "") -> None:
        self._rebuild_direct_artifact_tray(category=category)

    def _run_native_artifact_command(self, command: dict[str, str], raw: str = "") -> None:
        self._append_chat("user", raw)
        action = str(command.get("action") or "preview")
        if action == "list":
            self._show_artifact_tray(raw, category=str(command.get("category") or ""))
            return
        artifact = _latest_activity_artifact(
            self._activity_items,
            category=str(command.get("category") or ""),
        )
        if not artifact:
            self._append_chat("assistant", "我这里还没有能直接拿出来的产物。我先把最近任务进度打开给你。")
            self.show_bubble("还没有可直接查看的产物，我先打开最近进度。", state="speaking", duration=3200)
            self._run_native_control_command("progress", raw)
            return

        label = _clip(str(artifact.get("label") or artifact.get("target") or "最近产物"), 24)
        reply = f"我把最近产物拿出来：{label}。"
        self._append_chat("assistant", reply)
        if self._last_action:
            self._last_action.set(reply)
        self.show_bubble(reply, state="success", duration=2600)

        target = str(artifact.get("target") or "")
        if action == "copy":
            self._copy_artifact_to_clipboard(artifact)
            return
        if action == "open" and str(artifact.get("kind") or "") != "inline":
            self._open_activity_target(target)
            return
        if self._can_preview_artifact(artifact):
            self._preview_activity_artifact(artifact)
            return
        if target:
            self._open_activity_target(target)
            return
        self.show_bubble("这个产物没有可打开的路径或预览内容。", state="error", duration=3200)

    def _open_activity_target(self, target: str) -> None:
        value = str(target or "").strip()
        if not value:
            return
        try:
            path = Path(value).expanduser()
            if value.startswith(("http://", "https://", "file://")):
                webbrowser.open(value)
            elif path.exists():
                webbrowser.open(path.resolve().as_uri())
            else:
                self.show_bubble(f"找不到产物：{_clip(value, 58)}", state="error", duration=3200)
        except Exception as exc:  # noqa: BLE001
            self.show_bubble(f"打不开产物：{_clip(str(exc), 58)}", state="error", duration=3200)

    def _rebuild_skill_rows(self) -> None:
        # Legacy boxed skill shelf is retired; skills now use the layered direct bubble flow.
        if self._skills_frame and self._skills_frame.winfo_exists():
            self._skills_frame.pack_forget()
        enabled_ids = self._enabled_skill_ids()
        if self._skill_filter_summary_var:
            mounted_count = len(enabled_ids)
            self._skill_filter_summary_var.set(f"{mounted_count} 个 skill 已装载")

    def _install_local_skill_from_panel(self) -> None:
        source = self._local_skill_path_var.get().strip() if self._local_skill_path_var else ""
        self._install_local_skill_from_source(source)

    def _install_local_skill_from_source(self, source: str, *, activate: bool = False) -> None:
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return
        source = str(source or "").strip()
        if not source:
            self.show_bubble("把本地 skill 文件夹路径贴进输入框，我就能导入。", state="speaking", duration=3200)
            return
        self._mark_activity()
        self.set_state("working")
        self._show_work_hud("正在导入本地 skill", source, state="working")
        try:
            record = install_local_skill(store=self.store, twin_id=twin["id"], source=source)
        except Exception as exc:  # noqa: BLE001
            self.set_state("error")
            self.show_bubble(f"导入失败：{_clip(str(exc), 64)}", state="error", duration=4200)
            self._show_work_hud("本地 skill 导入失败", str(exc), state="error")
            self._schedule_work_hud_hide(5200)
            return
        name = str(record["name"])
        if self._skill_search_var:
            self._skill_search_var.set(name)
        self._rebuild_skill_rows()
        self._rebuild_direct_skill_shortcuts()
        if activate:
            self._set_active_skill_context(
                {
                    "id": str(record["id"]),
                    "displayName": name,
                    "category": "个人",
                    "risk": "unknown",
                    "summary": "本地导入并挂载到 JiuMe 的个人 skill。",
                    "whyJiume": "这是用户给当前分身安装的本地能力。",
                }
            )
        self._record_activity("skill", "本地 skill 已导入", name)
        if self._last_action:
            self._last_action.set(f"已导入并装载「{name}」。")
        if activate:
            self.show_bubble(f"已导入并切到「{name}」。把材料或要求直接发我。", state="success", duration=3800)
        else:
            self.show_bubble(f"已导入并装载「{name}」。可以直接点“使用”。", state="success", duration=3600)
        self._show_work_hud("本地 skill 已装载", name, state="success")
        self._schedule_work_hud_hide(3200)
        self.root.after(1300, lambda: self.set_state("idle"))

    def _run_native_skill_command(self, command: dict[str, Any], raw: str = "") -> None:
        action = str(command.get("action") or "")
        if action == "choose":
            self._reply_with_skill_picker(raw)
            return

        skill = command.get("skill")
        if action != "use" or not isinstance(skill, dict):
            return
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return

        skill_id = str(skill.get("id") or "").strip()
        name = str(skill.get("displayName") or skill.get("name") or skill_id or "skill")
        enabled_ids = set(self._enabled_skill_ids())
        mounted_now = skill_id not in enabled_ids
        try:
            if mounted_now:
                self.store.enable_skill(twin["id"], skill_id)
        except Exception as exc:  # noqa: BLE001
            self.show_bubble(f"装载「{_clip(name, 18)}」失败：{_clip(str(exc), 48)}", state="error", duration=4200)
            if self._last_action:
                self._last_action.set("技能装载失败。")
            return

        full_skill = _recommended_skill_by_id(skill_id) or skill
        if mounted_now:
            self._record_activity("skill", "对话装载 skill", name)
        self._rebuild_skill_rows()
        self._rebuild_direct_skill_shortcuts()
        self._start_skill_task(full_skill, user_line=raw)
        if mounted_now and self._last_action:
            self._last_action.set(f"已装上并切到「{name}」。")

    def _set_skill_enabled(self, skill: dict[str, Any], enabled: bool) -> None:
        twin = self._active_twin()
        if not twin:
            self.show_bubble("还没有可用分身，请先完成初始化。", state="error", duration=3200)
            return
        action = "装载" if enabled else "卸载"
        name = str(skill["displayName"])
        if self._last_action:
            self._last_action.set(f"正在{action}「{name}」...")
        self.show_bubble(f"正在{action}「{name}」...", state="working", duration=1800)
        self._show_work_hud(f"正在{action}技能", name, state="working")
        self.set_state("working")
        try:
            if enabled:
                self.store.enable_skill(twin["id"], str(skill["id"]))
            else:
                self.store.disable_skill(twin["id"], str(skill["id"]))
        except Exception as exc:  # noqa: BLE001
            self.set_state("error")
            self.show_bubble(f"{action}失败：{_clip(str(exc), 60)}", state="error", duration=4200)
            self._show_work_hud(f"{action}失败", str(exc), state="error")
            self._schedule_work_hud_hide(5200)
            if self._last_action:
                self._last_action.set("技能状态更新失败。")
            return
        if not enabled and self._active_skill_context and self._active_skill_context.get("id") == str(skill.get("id") or ""):
            self._active_skill_context = None
            self._persist_desktop_history()
            self._render_avatar_frame()
        self._rebuild_skill_rows()
        self._rebuild_direct_skill_shortcuts()
        self._record_activity("skill", f"技能已{action}", name)
        self.root.after(360, lambda: self._finish_skill_toggle(name, action))

    def _finish_skill_toggle(self, name: str, action: str) -> None:
        self.set_state("success" if action == "装载" else "idle")
        if self._last_action:
            self._last_action.set(f"已{action}「{name}」。")
        self.show_bubble(f"已{action}「{name}」。", state="success" if action == "装载" else "speaking", duration=3000)
        self._show_work_hud(f"技能已{action}", name, state="success" if action == "装载" else "thinking")
        self._schedule_work_hud_hide(2600)
        self.root.after(1300, lambda: self.set_state("idle"))

    def _start_skill_task(self, skill: dict[str, Any], *, user_line: str | None = None) -> None:
        name = str(skill.get("displayName") or skill.get("id") or "skill")
        prompt = self._skill_task_prompt(skill)
        self._set_active_skill_context(skill)
        self._record_activity("skill", "启动 skill", name)
        self._append_chat("user", user_line if user_line is not None else f"使用「{name}」")
        self._append_chat("assistant", f"我用「{name}」接手。")
        if self._last_action:
            self._last_action.set(f"正在使用「{name}」。")
        self.show_bubble(f"我用「{name}」接手。", state="thinking", duration=1800)
        self._show_work_hud(f"启动 skill：{name}", "正在把这个 skill 交给 Agent。", state="thinking")
        if self.gateway:
            self._gateway_reply = ""
            self._stream_chat_index = None
            self.gateway.send_chat(
                prompt,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=prompt: self._post_gateway_event(msg, event),
            )
            return
        if self._chat_entry:
            self._chat_entry.delete(0, "end")
            self._chat_entry.insert(0, f"把材料发我，我会按「{name}」处理。")
        self.show_bubble(f"已切到「{name}」。把材料贴给我，我会按这个 skill 处理。", state="speaking", duration=4200)

    @staticmethod
    def _skill_task_prompt(skill: dict[str, Any]) -> str:
        name = str(skill.get("displayName") or skill.get("id") or "mounted skill")
        summary = str(skill.get("summary") or "")
        category = str(skill.get("category") or "")
        risk = str(skill.get("risk") or "unknown")
        why = str(skill.get("whyJiume") or "")
        return (
            f"Use the mounted JiuMe skill \"{name}\" for the next task.\n"
            f"Category: {category}. Risk: {risk}.\n"
            f"Skill summary: {summary}\n"
            f"Why this skill fits JiuMe: {why}\n"
            "Start by briefly telling me this skill is active. If you need source material, files, constraints, "
            "or permission before acting, ask for exactly the missing items instead of giving a generic answer."
        )

    def _send_user_message(self) -> None:
        if not self._chat_entry:
            return
        raw = self._chat_entry.get().strip()
        if not raw or raw == "对分身说一句...":
            self.show_bubble("你可以直接问我能做什么，或者说“装一个会议纪要”。", state="speaking", duration=3200)
            return
        self._chat_entry.delete(0, "end")
        self._send_text_message(raw)

    def _set_one_line_capsule(self, capsule: TaskCapsule | None, *, auto_hide_ms: int | None = None) -> None:
        timer = getattr(self, "_one_line_capsule_timer", None)
        root = getattr(self, "root", None)
        if timer and root is not None:
            try:
                root.after_cancel(timer)
            except (AttributeError, tk.TclError):
                pass
        self._one_line_capsule_timer = None
        self._one_line_capsule = capsule
        self._one_line_question_active = bool(capsule and capsule.mode == "need_user")
        if capsule is not None and auto_hide_ms is not None and root is not None:
            def clear_capsule() -> None:
                if getattr(self, "_one_line_capsule", None) is capsule:
                    self._set_one_line_capsule(None)

            timer_id = root.after(
                auto_hide_ms,
                clear_capsule,
            )
            if getattr(self, "_one_line_capsule", None) is capsule:
                self._one_line_capsule_timer = timer_id

    def _show_one_line_capsule(self, capsule: TaskCapsule, *, auto_hide_ms: int | None = None) -> None:
        self._set_one_line_capsule(capsule, auto_hide_ms=auto_hide_ms)
        state = "waiting_approval" if capsule.mode == "need_user" else "working" if capsule.mode == "working" else "speaking"
        self.show_bubble(capsule.primary_text, state=state, duration=auto_hide_ms)

    def _send_direct_message(self) -> None:
        if not self._direct_entry:
            return
        raw = self._direct_entry.get().strip()
        if self._one_line_question_active and raw == ONE_LINE_INPUT_HINT:
            raw = ""
        if not raw:
            self.show_bubble("我在，直接说一句就行。", state="speaking", duration=2600)
            return
        self._close_direct_chat()
        self._set_one_line_capsule(working_capsule("在想"))
        self._send_text_message(raw)

    def _send_clipboard_material_from_direct(self, instruction: str = "") -> None:
        self._mark_activity()
        try:
            raw = self.root.clipboard_get()
        except tk.TclError:
            self.show_bubble("剪贴板现在没有可读取的文本或路径。", state="speaking", duration=3200)
            return

        payload = _clipboard_material_payload(raw)
        if not payload:
            self.show_bubble("剪贴板现在是空的。复制一段文字或文件路径再交给我。", state="speaking", duration=3400)
            return

        title = str(payload["title"])
        detail = str(payload["detail"])
        message = _message_with_material_instruction(str(payload["message"]), instruction)
        agent_message = _active_skill_followup_message(message, self._active_skill_context)
        self._append_chat("user", f"{title}：{detail}")
        self._record_activity("user", title, detail)
        self._show_work_hud(title, detail, state="thinking")
        if self._last_action:
            self._last_action.set(f"你交给我：{_clip(detail, 42)}")
        active_name = self._active_skill_context.get("displayName") if self._active_skill_context else ""
        line = f"收到剪贴板材料，我按「{_clip(active_name, 18)}」交给 Agent。" if active_name else "收到剪贴板材料，我交给 Agent。"
        self.show_bubble(line, state="thinking", duration=1700)
        if self.gateway:
            self._gateway_reply = ""
            self._stream_chat_index = None
            self.gateway.send_chat(
                agent_message,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=agent_message: self._post_gateway_event(msg, event),
            )
            return
        self._show_agent_unavailable_status()

    def _send_file_material_from_direct(self, instruction: str = "") -> None:
        self._mark_activity()
        try:
            selected = filedialog.askopenfilenames(
                parent=self._direct_chat if self._direct_chat and self._direct_chat.winfo_exists() else self.root,
                title="选择要交给 JiuMe 的文件",
            )
        except tk.TclError as exc:
            self.show_bubble(f"打开文件选择失败：{_clip(str(exc), 56)}", state="error", duration=4200)
            return
        payload = _file_material_payload(tuple(selected or ()))
        if not payload:
            self.show_bubble("还没有选中文件。", state="speaking", duration=2600)
            return

        title = str(payload["title"])
        detail = str(payload["detail"])
        artifacts = [dict(item) for item in payload.get("artifacts", []) if isinstance(item, dict)]
        message = _message_with_material_instruction(str(payload["message"]), instruction)
        agent_message = _active_skill_followup_message(message, self._active_skill_context)
        self._append_chat("user", f"{title}：{detail}")
        self._record_activity("user", title, detail, artifacts)
        self._show_work_hud(title, detail, state="thinking")
        active_name = self._active_skill_context.get("displayName") if self._active_skill_context else ""
        if self._last_action:
            prefix = f"文件交给「{_clip(active_name, 14)}」" if active_name else "文件已交给 JiuMe"
            self._last_action.set(prefix)
        line = f"收到文件，我按「{_clip(active_name, 18)}」交给 Agent。" if active_name else "收到文件，我交给 Agent。"
        self.show_bubble(line, state="thinking", duration=1800)
        if self.gateway:
            self._gateway_reply = ""
            self._stream_chat_index = None
            self.gateway.send_chat(
                agent_message,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=agent_message: self._post_gateway_event(msg, event),
            )
            return
        self._show_agent_unavailable_status()

    def _send_path_material_from_direct(self, raw: str) -> bool:
        payload = _direct_path_material_payload(raw)
        if not payload:
            return False

        self._mark_activity()
        title = str(payload["title"])
        detail = str(payload["detail"])
        artifacts = [dict(item) for item in payload.get("artifacts", []) if isinstance(item, dict)]
        message = str(payload["message"])
        agent_message = _active_skill_followup_message(message, self._active_skill_context)
        self._append_chat("user", f"{title}：{detail}")
        self._record_activity("user", title, detail, artifacts)
        self._show_work_hud(title, detail, state="thinking")
        active_name = self._active_skill_context.get("displayName") if self._active_skill_context else ""
        if self._last_action:
            prefix = f"路径交给「{_clip(active_name, 14)}」" if active_name else "路径已交给 JiuMe"
            self._last_action.set(prefix)
        line = f"收到路径里的文件，我按「{_clip(active_name, 18)}」交给 Agent。" if active_name else "收到路径里的文件，我交给 Agent。"
        self.show_bubble(line, state="thinking", duration=1800)
        if self.gateway:
            self._gateway_reply = ""
            self._stream_chat_index = None
            self.gateway.send_chat(
                agent_message,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=agent_message: self._post_gateway_event(msg, event),
            )
            return True
        self._show_agent_unavailable_status()
        return True

    def _send_screen_context_from_direct(self, instruction: str = "") -> None:
        self._mark_activity()
        command = shutil.which("screencapture")
        if not command:
            self.show_bubble("当前系统没有 screencapture，暂时不能直接看屏幕。", state="error", duration=3800)
            return

        path = _screen_capture_path(get_jiume_root())
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [command, "-x", str(path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=SCREEN_CAPTURE_TIMEOUT_SECONDS,
            )
            if not path.exists() or path.stat().st_size <= 0:
                raise OSError("screen capture file was not created")
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            self.show_bubble(f"看屏幕失败：{_clip(str(exc), 56)}。可能需要给终端/应用屏幕录制权限。", state="error", duration=5200)
            return

        payload = _screen_material_payload(path)
        title = str(payload["title"])
        detail = str(payload["detail"])
        artifact = dict(payload["artifact"])
        message = _message_with_material_instruction(str(payload["message"]), instruction)
        agent_message = _active_skill_followup_message(message, self._active_skill_context)
        self._append_chat("user", f"{title}：{detail}")
        self._record_activity("user", title, detail, [artifact])
        self._show_work_hud(title, "已截取当前屏幕，正在交给 Agent。", state="thinking")
        active_name = self._active_skill_context.get("displayName") if self._active_skill_context else ""
        if self._last_action:
            prefix = f"屏幕交给「{_clip(active_name, 14)}」" if active_name else "屏幕已交给 JiuMe"
            self._last_action.set(prefix)
        line = f"我看到了当前屏幕，会按「{_clip(active_name, 18)}」处理。" if active_name else "我看到了当前屏幕，交给 Agent。"
        self.show_bubble(line, state="thinking", duration=1900)
        if self.gateway:
            self._gateway_reply = ""
            self._stream_chat_index = None
            self.gateway.send_chat(
                agent_message,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=agent_message: self._post_gateway_event(msg, event),
            )
            return
        self._show_agent_unavailable_status()

    def _clear_gateway_request_guard(self) -> None:
        self._gateway_request_id = None
        self._gateway_request_message = ""
        if getattr(self, "_native_direct_chat_visible", False):
            try:
                self._position_direct_chat()
            except tk.TclError:
                pass

    def _ignore_duplicate_gateway_submit(self, raw: str) -> bool:
        if not getattr(self, "_gateway_request_id", None):
            return False
        message = str(raw or getattr(self, "_gateway_request_message", "") or "").strip()
        detail = message or "上一条消息"
        self._record_activity("processing", "正在回复", detail)
        if self._last_action:
            self._last_action.set("上一条消息还在回复。")
        self.show_bubble("上一条消息还在回复。", state="thinking", duration=1800)
        return True

    def _active_twin_for_gateway_prompt(self) -> dict[str, Any] | None:
        try:
            return self._active_twin()
        except (AttributeError, OSError):
            return None

    def _send_text_message(self, raw: str) -> None:
        if self._pending_approval:
            approval_reply = _approval_reply_from_text(raw)
            if approval_reply:
                decision, feedback = approval_reply
                self._send_approval_answer(decision, feedback_override=feedback)
                return

        agent_conversation_query = _native_agent_conversation_query(
            raw,
            names=self._active_attention_names(),
        )

        if self.gateway and self._ignore_duplicate_gateway_submit(raw):
            return

        # Free-form typed text always belongs to the Agent; UI buttons/menus call local actions directly.
        agent_body = raw
        if agent_conversation_query:
            agent_body = _jiume_agent_conversation_message(raw, self._active_twin_for_gateway_prompt())
        agent_message = _active_skill_followup_message(agent_body, self._active_skill_context)
        if self._last_action:
            active_name = self._active_skill_context.get("displayName") if self._active_skill_context else ""
            prefix = f"你交给「{_clip(active_name, 14)}」：" if active_name else "你说："
            self._last_action.set(f"{prefix}{_clip(raw, 42)}")
        self._append_chat("user", raw)
        self._record_activity("user", "发起任务", raw)
        self._show_one_line_capsule(working_capsule("在想"))
        if self.gateway:
            pending_id = "pending"
            self._gateway_request_id = pending_id
            self._gateway_request_message = raw
            self._gateway_reply = ""
            self._stream_chat_index = None
            request_id = self.gateway.send_chat(
                agent_message,
                twin_id=self._active_twin_id,
                on_event=lambda event, msg=agent_message: self._post_gateway_event(msg, event),
            )
            if getattr(self, "_gateway_request_id", None) == pending_id:
                self._gateway_request_id = request_id or pending_id
            if getattr(self, "_native_direct_chat_visible", False):
                try:
                    self._position_direct_chat()
                except tk.TclError:
                    pass
            return
        self._show_agent_unavailable_status()

    def _post_gateway_event(self, message: str, event: GatewayEvent) -> None:
        self._post_to_ui(lambda: self._handle_gateway_event(message, event))

    def _handle_gateway_event(self, message: str, event: GatewayEvent) -> None:
        state = desktop_state_for_gateway_event(event)
        capsule = capsule_for_gateway_event(event, current_reply=self._gateway_reply)
        if state:
            self.set_state(state)

        if event.kind == "response":
            if event.ok:
                self._record_activity("accepted", "已接收", "我在等它回复。")
                if self._last_action:
                    self._last_action.set("已接收，我在等它回复。")
                self._show_one_line_capsule(capsule or working_capsule("在想"))
                return
            error_text = gateway_event_text(event) or "这件事现在还不能继续执行。"
            self._clear_gateway_request_guard()
            self._record_activity("error", "执行受阻", error_text)
            self._finish_assistant_stream(error_text, state="error")
            self._show_one_line_capsule(capsule or failed_capsule(error_text), auto_hide_ms=3600)
            self.root.after(1300, lambda: self.set_state("idle"))
            return

        if event.kind == "error":
            error_text = gateway_event_text(event) or "这件事现在还不能继续执行。"
            self._clear_gateway_request_guard()
            self._record_activity("error", "执行受阻", error_text)
            self._finish_assistant_stream(error_text, state="error")
            if self._last_action:
                self._last_action.set("这件事现在还不能继续执行。")
            self._show_one_line_capsule(capsule or failed_capsule(error_text), auto_hide_ms=3600)
            self.root.after(1300, lambda: self.set_state("idle"))
            return

        text = gateway_event_text(event)
        if event.event == "chat.delta":
            if text:
                if not self._gateway_reply:
                    self._record_activity("reply", "开始回复", text)
                self._gateway_reply += text
                if self._last_action:
                    self._last_action.set("JiuMe 正在回复。")
                self._upsert_assistant_chat(self._gateway_reply)
                self._show_one_line_capsule(capsule or working_capsule("快好了"))
            return

        if event.event == "chat.final":
            final_text = text or self._gateway_reply
            self._gateway_reply = final_text
            self._record_activity("final", "任务完成", final_text, gateway_event_artifacts(event))
            if final_text:
                self._finish_assistant_stream(final_text, state="success")
                if self._last_action:
                    self._last_action.set((capsule or done_capsule(final_text)).primary_text)
                self._show_one_line_capsule(capsule or done_capsule(final_text), auto_hide_ms=4200)
            else:
                self._stream_chat_index = None
                if self._last_action:
                    self._last_action.set("任务已结束。")
            self._clear_gateway_request_guard()
            self.root.after(1300, lambda: self.set_state("idle"))
            return

        if event.event == "chat.processing_status":
            if not (event.payload or {}).get("is_processing"):
                final_text = self._gateway_reply
                self._gateway_reply = final_text
                self._record_activity("final", "任务已结束", final_text, gateway_event_artifacts(event))
                if final_text:
                    self._finish_assistant_stream(final_text, state="success")
                    if self._last_action:
                        self._last_action.set((capsule or done_capsule(final_text)).primary_text)
                else:
                    self._stream_chat_index = None
                    if self._last_action:
                        self._last_action.set("任务已结束。")
                if final_text:
                    self._show_one_line_capsule(capsule or done_capsule(final_text), auto_hide_ms=4200)
                self._clear_gateway_request_guard()
                self.root.after(1300, lambda: self.set_state("idle"))
                return
            if (text or capsule) and not self._gateway_reply:
                self._record_activity("processing", "开始处理", text)
                self._show_one_line_capsule(capsule or working_capsule("在整理"))
            return

        if event.event == "chat.subtask_update":
            payload = event.payload or {}
            status = str(payload.get("status") or "").strip().lower()
            index = payload.get("index")
            total = payload.get("total")
            title = "子任务更新"
            if isinstance(index, int) and isinstance(total, int) and total > 0:
                title = f"子任务 {index}/{total}"
            if gateway_subtask_status_is_completed(status):
                title = f"{title} 完成"
            elif gateway_subtask_status_is_failed(status):
                title = f"{title} 失败"
            self._record_activity("subtask", title, text, gateway_event_artifacts(event))
            subtask_capsule = capsule or working_capsule("在整理")
            self._show_one_line_capsule(
                subtask_capsule,
                auto_hide_ms=3600 if subtask_capsule.mode == "done" else None,
            )
            return

        if event.event == "chat.ask_user_question":
            self._record_activity("approval", "等待确认", text, gateway_event_artifacts(event))
            self._set_pending_approval(event.payload or {})
            return

        if event.event in {"chat.file", "chat.media", "chat.session_result", "session_result"}:
            self._record_activity("artifact", "收到产物", text or "Agent 返回了产物。", gateway_event_artifacts(event))
            self._show_one_line_capsule(capsule or done_capsule("收到产物。", has_artifact=True), auto_hide_ms=4200)
            return

        if event.event == "chat.error":
            self._clear_gateway_request_guard()
        if event.event in {"chat.tool_call", "chat.tool_result", "chat.error"}:
            title = "调用工具" if event.event == "chat.tool_call" else "工具返回" if event.event == "chat.tool_result" else "任务出错"
            self._record_activity("tool", title, text, gateway_event_artifacts(event))
            if self._last_action:
                self._last_action.set("任务出错" if event.event == "chat.error" else "我还在处理。")
            if event.event == "chat.error":
                self._show_one_line_capsule(capsule or failed_capsule(text), auto_hide_ms=3600)
                self.root.after(1300, lambda: self.set_state("idle"))
            else:
                self._show_one_line_capsule(working_capsule("在整理"))

    def _set_pending_approval(self, payload: dict[str, Any]) -> None:
        self._pending_approval = dict(payload)
        self._approval_feedback_var = tk.StringVar(value="")
        self._direct_approval_feedback_visible = False
        prompt = gateway_event_text(GatewayEvent(kind="event", event="chat.ask_user_question", payload=payload))
        capsule = need_user_capsule(prompt)
        self._append_chat("assistant", f"需要你确认下一步：{capsule.question}")
        if self._last_action:
            self._last_action.set(_clip(f"需要确认：{capsule.question}", 54))
        self._show_one_line_capsule(capsule)
        self.open_direct_chat()

    def _rebuild_approval_card(self) -> None:
        # Legacy boxed approval card is retired; confirmations render beside the avatar.
        if self._approval_frame and self._approval_frame.winfo_exists():
            self._approval_frame.pack_forget()
        self._rebuild_direct_approval_card()

    def _send_approval_answer(self, decision: str, *, feedback_override: str | None = None) -> None:
        if not self._pending_approval:
            return
        if not self.gateway:
            self._show_one_line_capsule(failed_capsule(""), auto_hide_ms=3600)
            return
        request_id = str(self._pending_approval.get("request_id") or "").strip()
        if not request_id:
            self._show_one_line_capsule(failed_capsule("request_id"), auto_hide_ms=3600)
            return
        source = str(self._pending_approval.get("source") or "")
        feedback = (
            str(feedback_override or "").strip()
            if feedback_override is not None
            else self._approval_feedback_var.get().strip() if self._approval_feedback_var else ""
        )
        answers = answers_for_decision(
            self._pending_approval,
            "accept" if decision == "accept" else "reject",
            feedback=feedback,
        )
        label = "同意" if decision == "accept" else "拒绝"
        answer_line = label if not feedback else f"{label}。{feedback}"
        self._append_chat("user", answer_line)
        self.gateway.send_user_answer(
            request_id=request_id,
            source=source,
            answers=answers,
            feedback=feedback,
            on_event=lambda event, label=label: self._post_approval_result(label, event),
        )
        self._pending_approval = None
        self._rebuild_approval_card()
        self._rebuild_direct_approval_card()
        if self._last_action:
            self._last_action.set(f"已{label}，继续处理。")
        self._show_one_line_capsule(working_capsule("在想"))

    def _answer_pending_approval_from_avatar(self, decision: str) -> None:
        if self._pending_approval:
            self._send_approval_answer(decision)
            return
        self._run_native_control_command("progress")
        self.show_bubble("现在没有正在等待确认的任务。", state="speaking", duration=2800)

    def _post_approval_result(self, label: str, event: GatewayEvent) -> None:
        self._post_to_ui(lambda: self._handle_approval_result(label, event))

    def _handle_approval_result(self, label: str, event: GatewayEvent) -> None:
        if event.kind == "response" and event.ok:
            self._record_activity("approval", f"已{label}", "Agent 已收到确认。")
            if self._last_action:
                self._last_action.set(f"Agent 已收到你的{label}。")
            return
        text = gateway_event_text(event) or event.error or "确认回复失败。"
        self._record_activity("error", "确认回复失败", text)
        self._show_one_line_capsule(failed_capsule(text), auto_hide_ms=3600)

    def show_bubble(self, text: str, *, state: str = "speaking", duration: int | None = 3800) -> None:
        if self._bubble_timer:
            try:
                self.root.after_cancel(self._bubble_timer)
            except tk.TclError:
                pass
            self._bubble_timer = None
        self._hide_hover_menu()
        if state:
            self.set_state(state)
        if _legacy_dialogue_layers_disabled():
            self._hide_speech_surface()
            if duration is not None and state not in {"idle", "working", "waiting_approval"}:
                self._bubble_timer = self.root.after(duration, self._hide_bubble)
            return
        if _uses_native_desktop_layers() and _direct_chat_suppresses_speech(self._native_direct_chat_visible, state):
            self._hide_speech_surface()
            if duration is not None and state != "idle":
                self._bubble_timer = self.root.after(duration, self._hide_bubble)
            return
        if _uses_native_desktop_layers():
            self._bubble_text = text
            self._bubble_height = _speech_bubble_height(text)
            self._position_bubble()
            if duration is not None:
                self._bubble_timer = self.root.after(duration, self._hide_bubble)
            return
        if not self._bubble or not self._bubble.winfo_exists():
            bubble = tk.Toplevel(self.root)
            self._bubble = bubble
            bubble.overrideredirect(True)
            bubble.attributes("-topmost", True)
            bubble.configure(bg=self._transparent_bg)
            self.overlay.apply_transparent_layer(bubble, kind="bubble")
            try:
                bubble.wm_attributes("-transparentcolor", self._transparent_bg)
            except tk.TclError:
                pass
            canvas = tk.Canvas(
                bubble,
                bg=self._transparent_bg,
                bd=0,
                highlightthickness=0,
                width=BUBBLE_WIDTH,
                height=BUBBLE_MIN_HEIGHT,
            )
            self._bubble_canvas = canvas
            canvas.pack(fill="both", expand=True)
        self._bubble_text = text
        self._bubble_height = _speech_bubble_height(text)
        self._position_bubble()
        self._bubble.deiconify()
        if duration is not None:
            self._bubble_timer = self.root.after(duration, self._hide_bubble)

    def _position_bubble(self) -> None:
        if _legacy_dialogue_layers_disabled():
            self._hide_speech_surface()
            return
        if _uses_native_desktop_layers():
            if _direct_chat_suppresses_speech(self._native_direct_chat_visible, self._state):
                self._hide_speech_surface()
                return
            layout = _speech_bubble_layout(
                text=self._bubble_text,
                icon_x=self.root.winfo_x(),
                icon_y=self.root.winfo_y(),
                size=self.size,
                screen_width=self.root.winfo_screenwidth(),
                screen_height=self.root.winfo_screenheight(),
            )
            image = _native_speech_bubble_image(self._bubble_text, layout)
            self.overlay.show_image_layer(
                "speech",
                image,
                x=int(layout["x"]),
                y=int(layout["y"]),
            )
            return
        if not self._bubble or not self._bubble.winfo_exists():
            return
        layout = _speech_bubble_layout(
            text=self._bubble_text,
            icon_x=self.root.winfo_x(),
            icon_y=self.root.winfo_y(),
            size=self.size,
            screen_width=self.root.winfo_screenwidth(),
            screen_height=self.root.winfo_screenheight(),
        )
        if self._bubble_canvas and self._bubble_canvas.winfo_exists():
            self._bubble_canvas.configure(width=int(layout["width"]), height=int(layout["height"]))
            self._draw_speech_bubble(self._bubble_canvas, layout)
        self._bubble.geometry(
            f"{int(layout['width'])}x{int(layout['height'])}+{int(layout['x'])}+{int(layout['y'])}"
        )

    def _hide_speech_surface(self) -> None:
        if self._bubble_timer:
            try:
                self.root.after_cancel(self._bubble_timer)
            except tk.TclError:
                pass
            self._bubble_timer = None
        self.overlay.hide_image_layer("speech")
        if self._bubble and self._bubble.winfo_exists():
            try:
                self._bubble.withdraw()
            except tk.TclError:
                pass

    def _hide_bubble(self) -> None:
        self._hide_speech_surface()
        if self._state not in {"working", "waiting_approval"}:
            self.set_state("idle")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the standalone JiuMe human desktop avatar.")
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="JiuwenSwarm Gateway WebSocket URL. Use an empty value for local-only replies.")
    parser.add_argument("--agent-mode", default=DEFAULT_AGENT_MODE, help="Agent mode used for chat.send.")
    parser.add_argument("--open-panel", action="store_true", help="Open the avatar-side conversation layer on launch.")
    args = parser.parse_args()
    store = TwinStore()
    if store.get_active_twin_id() is None:
        from jiume.setup.server import NativeSetupWindow

        NativeSetupWindow().run()
        if store.get_active_twin_id() is None:
            return
    avatar = JiuMeDesktopAvatar(
        size=args.size,
        gateway_url=args.gateway_url,
        agent_mode=args.agent_mode,
    )
    if args.open_panel:
        avatar.root.after(500, avatar.open_direct_chat)
    avatar.run()

if __name__ == "__main__":
    main()
