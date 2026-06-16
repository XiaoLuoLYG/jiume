"""Appearance presets for JiuMe desktop twins."""

from __future__ import annotations

from typing import Any

DEFAULT_APPEARANCE_ID = "blue"

APPEARANCE_PRESETS: tuple[dict[str, str], ...] = (
    {"id": "blue", "label": "清爽蓝", "outfitColor": "#5B8DEF"},
    {"id": "mint", "label": "薄荷绿", "outfitColor": "#14B8A6"},
    {"id": "pink", "label": "草莓粉", "outfitColor": "#EC4899"},
    {"id": "purple", "label": "葡萄紫", "outfitColor": "#8B5CF6"},
    {"id": "sun", "label": "暖阳黄", "outfitColor": "#F59E0B"},
    {"id": "ink", "label": "极简黑", "outfitColor": "#111827"},
)


def appearance_presets() -> list[dict[str, str]]:
    return [dict(item) for item in APPEARANCE_PRESETS]


def appearance_preset_by_id(preset_id: str) -> dict[str, str] | None:
    needle = str(preset_id or "").strip().lower()
    for preset in APPEARANCE_PRESETS:
        if preset["id"] == needle:
            return dict(preset)
    return None


def normalize_twin_appearance(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        preset = appearance_preset_by_id(value)
        if preset:
            return preset
    if isinstance(value, dict):
        preset = appearance_preset_by_id(str(value.get("id") or ""))
        if preset:
            return preset
        color = str(value.get("outfitColor") or value.get("outfit_color") or "").strip()
        if color.startswith("#") and len(color) in {4, 7}:
            return {
                "id": "custom",
                "label": str(value.get("label") or "自定义").strip() or "自定义",
                "outfitColor": color.upper(),
            }
    return dict(APPEARANCE_PRESETS[0])


def twin_appearance_label(value: Any) -> str:
    return normalize_twin_appearance(value)["label"]
