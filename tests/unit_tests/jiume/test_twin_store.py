from __future__ import annotations

import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from PIL import Image, ImageDraw

import jiume.desktop.app as desktop_app
import jiume.launcher as jiume_launcher
from jiume.avatar.service import AVATAR_VIEW_NAMES, ANIMATION_FRAMES_PER_STATE, DESKTOP_STATES, AvatarService, _openai_avatar_prompt
from jiume.api.assets import resolve_asset_path
from jiume.desktop.overlay import DesktopOverlayHost
from jiume.config import get_image_provider_config
from jiume.setup.server import NativeSetupController, NativeSetupWindow, _public_manifest
from jiume.setup.progress import GenerationProgress, classify_generation_error
from jiume.desktop.actions import quick_action_by_id, quick_action_prompt, quick_actions
from jiume.desktop.one_line_companion import DAILY_FORBIDDEN_LABELS
from jiume.desktop.app import (
    DIRECT_CHAT_WIDTH,
    ONE_LINE_DIRECT_HEIGHT,
    ONE_LINE_INPUT_HINT,
    JiuMeDesktopAvatar,
    _active_skill_followup_message,
    _active_skill_badge_label,
    _active_skill_material_action_specs,
    _active_skill_snapshot,
    _active_skill_summary,
    _animation_transform,
    _activity_effect_for_kind,
    _activity_artifact_cards,
    _activity_stage_label,
    _attention_name_aliases,
    _attention_summary,
    _apply_profile_memory_command,
    _avatar_context_action_specs,
    _avatar_manifest_signature,
    _approval_reply_from_text,
    _avatar_size_from_state,
    _avatar_size_label,
    _avatar_opacity_from_state,
    _avatar_opacity_label,
    _avatar_status_badge_style,
    _avatar_placement_geometry,
    _avatar_window_geometry,
    _chat_heading,
    _chat_role_label,
    _clipboard_file_targets,
    _clipboard_material_payload,
    _clipboard_text_preview,
    _companion_status,
    _companion_plan_summary,
    _conversation_preview_items,
    _conversation_reaction,
    _direct_chat_composer_action_specs,
    _direct_activity_action_specs,
    _direct_companion_suggestion_specs,
    _native_control_command,
    _direct_activity_summary,
    _direct_chat_height,
    _direct_chat_content_window_height,
    _direct_chat_scroll_height,
    _direct_speech_bubble_width,
    _direct_value_bubble_width,
    _direct_text_preview_bubble_width,
    _direct_chat_window_height,
    _direct_chat_content_rect,
    _direct_chat_composer_rect,
    _direct_chat_geometry_for_avatar,
    _direct_chat_surface_rect,
    _direct_chat_surface_bubbles,
    _desktop_state_event_is_ignored,
    _direct_message_bubble_height,
    _desktop_layer_background,
    _desktop_state_event_is_stale,
    _direct_chat_suppresses_speech,
    _direct_path_material_payload,
    _direct_help_action_specs,
    _direct_help_section_specs,
    _direct_play_action_specs,
    _direct_quick_action_shortcuts,
    _direct_settings_payload,
    _direct_settings_snapshot,
    _direct_settings_section_specs,
    _direct_service_status_summary,
    _direct_skill_section_specs,
    _direct_skill_overflow_count,
    _direct_skill_shortcuts,
    _direct_unhandled_action_reply,
    _coin_flip,
    _dice_roll,
    _skill_picker_reply,
    _skill_picker_suggestions,
    _draw_avatar_aura,
    _draw_avatar_status_badge,
    _draw_active_skill_badge,
    _draw_reaction_chip,
    _file_material_payload,
    _focus_minutes_from_text,
    _format_service_status,
    _help_summary,
    _avatar_hover_hint,
    _hover_effect_for_state,
    _hover_menu_action_specs,
    _hover_menu_geometry,
    _hover_menu_item_positions,
    _identity_summary,
    _interaction_effect_transform,
    _idle_companion_moment_for_context,
    _latest_activity_artifact,
    _merge_avatar_transforms,
    _native_companion_command,
    _native_companion_plan_command,
    _native_coin_command,
    _native_dice_command,
    _native_focus_command,
    _native_help_command,
    _native_identity_command,
    _native_interaction_command,
    _message_with_material_instruction,
    _memory_summary,
    _native_artifact_command,
    _native_attention_command,
    _native_clear_chat_command,
    _native_material_command,
    _native_memory_command,
    _native_login_item_command,
    _native_onboarding_prompt,
    _native_opacity_command,
    _native_placement_command,
    _native_avatar_makeover_command,
    _native_profile_memory_command,
    _native_presence_command,
    _native_quick_action_command,
    _native_rps_command,
    _native_settings_query_command,
    _native_settings_update,
    _native_active_skill_query_command,
    _native_skill_import_command,
    _native_skill_command,
    _permission_mode_label,
    _presence_summary,
    _profile_memory_summary,
    _reaction_chip_for_effect,
    _rps_round,
    _settings_summary,
    _next_appearance_preset,
    _normalize_direct_help_section,
    _normalize_direct_settings_section,
    _normalize_direct_skill_section,
    _normalize_avatar_opacity,
    _screen_capture_path,
    _screen_material_payload,
    _should_wake_on_click,
    _speech_bubble_height,
    _speech_bubble_layout,
    _state_file,
    _task_followup_message,
    _task_nudge_reply,
    _task_continuation_command,
    _task_continuation_message,
    _task_continuation_summary,
    _task_progress_reply,
    _task_runtime_command,
    _native_tuck_command,
    _native_wake_command,
    _window_position_geometry,
    _wake_line,
    _login_item_command_args,
    _work_hud_action_specs,
    _work_hud_auto_hide_ms,
    _work_hud_bubble_line,
    _work_hud_phase_label,
    _work_hud_resume_activity,
    _work_hud_state_for_activity,
)

CODEX_PET_FRAME_COUNTS = {
    "idle": 6,
    "running-right": 8,
    "running-left": 8,
    "waving": 4,
    "jumping": 5,
    "failed": 8,
    "waiting": 6,
    "running": 6,
    "review": 6,
}
CODEX_PET_CELL = (192, 208)
CODEX_PET_GRID = (8, 9)


def _assert_codex_pet_atlas(path: Path) -> None:
    atlas = Image.open(path).convert("RGBA")
    assert atlas.size == (CODEX_PET_CELL[0] * CODEX_PET_GRID[0], CODEX_PET_CELL[1] * CODEX_PET_GRID[1])
    assert not any(pixel[3] == 0 and any(pixel[:3]) for pixel in atlas.getdata())
    for row, (state, frame_count) in enumerate(CODEX_PET_FRAME_COUNTS.items()):
        for column in range(CODEX_PET_GRID[0]):
            cell = atlas.crop(
                (
                    column * CODEX_PET_CELL[0],
                    row * CODEX_PET_CELL[1],
                    (column + 1) * CODEX_PET_CELL[0],
                    (row + 1) * CODEX_PET_CELL[1],
                )
            )
            has_pixels = cell.getchannel("A").getbbox() is not None
            assert has_pixels is (column < frame_count), f"{state} column {column}"


def _assert_rgb_close(actual: tuple[int, int, int], expected: tuple[int, int, int], tolerance: int = 4) -> None:
    assert all(abs(a - b) <= tolerance for a, b in zip(actual, expected)), (actual, expected)


def _png_bytes(image: Image.Image) -> bytes:
    import io

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _fake_openai_base_png() -> bytes:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((196, 258, 316, 430), radius=42, fill=(28, 31, 42, 255))
    draw.ellipse((154, 94, 358, 298), fill=(255, 218, 196, 255))
    draw.pieslice((148, 72, 364, 250), 180, 360, fill=(27, 24, 24, 255))
    draw.ellipse((198, 172, 218, 192), fill=(31, 41, 55, 255))
    draw.ellipse((294, 172, 314, 192), fill=(31, 41, 55, 255))
    return _png_bytes(image)


def _fake_openai_row_png(state: str) -> bytes:
    row_index = list(CODEX_PET_FRAME_COUNTS).index(state)
    frame_count = CODEX_PET_FRAME_COUNTS[state]
    image = Image.new("RGBA", (1024, 1024), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    slot_width = image.width / frame_count
    for index in range(frame_count):
        cx = int(slot_width * (index + 0.5))
        color = (
            35 + (row_index * 23 + index * 19) % 180,
            30 + (row_index * 31 + index * 17) % 170,
            45 + (row_index * 41 + index * 29) % 160,
            255,
        )
        dy = [0, -26, -10, 16, 0, -18, 12, 0][index % 8]
        draw.rounded_rectangle((cx - 34, 450 + dy, cx + 34, 790 + dy), radius=26, fill=color)
        draw.ellipse((cx - 46, 274 + dy, cx + 46, 386 + dy), fill=(255, 220, 200, 255))
        draw.pieslice((cx - 50, 246 + dy, cx + 50, 358 + dy), 180, 360, fill=(25, 24, 24, 255))
        if state == "waving":
            draw.line((cx + 22, 510 + dy, cx + 54, 380 + dy), fill=(255, 220, 200, 255), width=16)
        if state in {"running-right", "running-left"}:
            direction = 1 if state == "running-right" else -1
            draw.line((cx, 775 + dy, cx + direction * 44, 870 + dy), fill=color, width=14)
            draw.line((cx, 775 + dy, cx - direction * 34, 858 + dy), fill=color, width=14)
    return _png_bytes(image)


def _fake_openai_checkerboard_row_png(state: str) -> bytes:
    row_index = list(CODEX_PET_FRAME_COUNTS).index(state)
    frame_count = CODEX_PET_FRAME_COUNTS[state]
    image = Image.new("RGBA", (512, 512), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    tile = 16
    for y in range(0, image.height, tile):
        for x in range(0, image.width, tile):
            color = (238, 238, 238, 255) if ((x // tile) + (y // tile)) % 2 else (255, 255, 255, 255)
            draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=color)
    slot_width = image.width / frame_count
    for index in range(frame_count):
        cx = int(slot_width * (index + 0.5))
        dy = [0, -10, 8, -4, 12, -8, 4, 0][index % 8]
        body = (
            50 + (row_index * 29 + index * 17) % 120,
            54 + (row_index * 19 + index * 13) % 120,
            65 + (row_index * 11 + index * 23) % 120,
            255,
        )
        draw.rounded_rectangle((cx - 42, 262 + dy, cx + 42, 456 + dy), radius=22, fill=(255, 255, 255, 255))
        draw.rounded_rectangle((cx - 32, 272 + dy, cx + 32, 448 + dy), radius=18, fill=body)
        draw.ellipse((cx - 42, 126 + dy, cx + 42, 220 + dy), fill=(255, 255, 255, 255))
        draw.ellipse((cx - 34, 134 + dy, cx + 34, 212 + dy), fill=(255, 220, 200, 255))
        draw.pieslice((cx - 38, 112 + dy, cx + 38, 196 + dy), 180, 360, fill=(25, 24, 24, 255))
        draw.ellipse((cx - 18, 170 + dy, cx - 10, 178 + dy), fill=(31, 41, 55, 255))
        draw.ellipse((cx + 10, 170 + dy, cx + 18, 178 + dy), fill=(31, 41, 55, 255))
    return _png_bytes(image)


def _fake_openai_green_spill_row_png(state: str) -> bytes:
    frame_count = CODEX_PET_FRAME_COUNTS[state]
    image = Image.new("RGBA", (768, 512), (0, 255, 0, 255))
    draw = ImageDraw.Draw(image)
    slot_width = image.width / frame_count
    for index in range(frame_count):
        cx = int(slot_width * (index + 0.5))
        dy = [0, -8, 6, -4, 10, -6, 4, 0][index % 8]
        draw.rectangle((cx - 40, 120 + dy, cx + 44, 362 + dy), fill=(90, 244, 54, 255))
        draw.rounded_rectangle((cx - 48, 246 + dy, cx + 48, 430 + dy), radius=20, fill=(18, 18, 24, 255))
        draw.rounded_rectangle((cx - 54, 240 + dy, cx + 54, 436 + dy), radius=24, outline=(218, 255, 230, 255), width=3)
        draw.rectangle((cx - 44, 252 + dy, cx - 6, 366 + dy), fill=(54, 171, 124, 255))
        draw.rectangle((cx + 6, 252 + dy, cx + 44, 366 + dy), fill=(38, 142, 112, 255))
        draw.ellipse((cx - 42, 116 + dy, cx + 42, 206 + dy), fill=(255, 220, 200, 255))
        draw.pieslice((cx - 48, 96 + dy, cx + 48, 190 + dy), 180, 360, fill=(80, 22, 32, 255))
        draw.line((cx + 40, 112 + dy, cx + 60, 432 + dy), fill=(230, 235, 238, 255), width=6)
    return _png_bytes(image)


def _visible_average_rgb(path: Path) -> tuple[int, int, int]:
    image = Image.open(path).convert("RGBA")
    pixels = [pixel[:3] for pixel in image.getdata() if pixel[3] > 16]
    assert pixels
    count = len(pixels)
    return (
        sum(pixel[0] for pixel in pixels) // count,
        sum(pixel[1] for pixel in pixels) // count,
        sum(pixel[2] for pixel in pixels) // count,
    )
from jiume.desktop.companion import (
    IDLE_COMPANION_SECONDS,
    idle_companion_moment,
    idle_companion_moments,
    should_run_idle_companion,
)
from jiume.desktop.settings_center import (
    SETTINGS_CENTER_SECTIONS,
    build_agent_settings_snapshot,
    build_desktop_settings_snapshot,
)
from jiume.desktop.gateway_client import (
    GatewayEvent,
    JiuMeGatewayChatClient,
    answers_for_decision,
    build_interrupt_request,
    build_user_answer_request,
    desktop_state_for_gateway_event,
    gateway_event_artifacts,
    gateway_event_text,
    normalize_gateway_frame,
)
from jiume.desktop.interactions import interaction_actions, interaction_by_id
from jiume.desktop.menus import (
    app_menu_labels,
    companion_menu_labels,
    material_menu_labels,
    play_menu_labels,
    skill_menu_labels,
    state_menu_labels,
    task_menu_labels,
)
from jiume.desktop.state import (
    get_companion_state_path,
    get_conversation_state_path,
    get_window_state_path,
    read_companion_state,
    read_conversation_state,
    read_service_status,
    read_window_state,
    set_service_status,
    write_companion_state,
    write_conversation_state,
    write_window_state,
)
from jiume.launcher import (
    LAUNCH_AGENT_LABEL,
    _build_launch_plan,
    _claim_launcher_lock,
    _gateway_endpoint,
    _launch_agent_payload,
    _launcher_args_for_login,
    _read_launcher_pid,
    _release_launcher_lock,
    _should_open_desktop_avatar,
)
from jiume.personal_distillation.engine import PersonalDistillationEngine
from jiume.runtime.context import enrich_gateway_message
from jiume.skills.catalog import (
    RECOMMENDED_SKILLS,
    SKILL_FILTER_ALL,
    catalog_payload,
    filter_recommended_skills,
    mounted_skill_cards,
    skill_categories,
    skill_risks,
)
from jiume.skills.local_install import install_local_skill, resolve_local_skill_source
from jiume.twins.store import TwinStore
from jiume.twins.appearance import normalize_twin_appearance


@pytest.fixture(autouse=True)
def _isolate_jiume_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "jiume-home"
    twins = root / "twins"
    monkeypatch.setattr("jiume.paths.get_jiume_root", lambda: root)
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: twins)
    monkeypatch.setattr("jiume.config.get_jiume_root", lambda: root)
    monkeypatch.setattr("jiume.desktop.state.get_jiume_root", lambda: root)
    monkeypatch.setattr("jiume.twins.store.get_twins_root", lambda: twins)
    monkeypatch.setattr("jiume.audit.logger.get_twin_root", lambda twin_id: twins / str(twin_id))


def test_twin_crud_and_skill_mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")

    twin = store.create_twin(
        {
            "displayName": "Ada",
            "selectedSkillIds": ["meeting-minutes"],
            "memories": ["喜欢中文简洁回复", "喜欢中文简洁回复", ""],
        }
    )
    second = store.create_twin({"displayName": "Grace", "selectedSkillIds": ["knowledge-research"]})

    assert twin["displayName"] == "Ada"
    assert twin["appearance"]["id"] == "blue"
    assert twin["memories"] == ["喜欢中文简洁回复"]
    assert store.get_active_twin_id() == second["id"]
    assert store.get_twin(twin["id"])["permissions"]["allowedSkillIds"] == ["meeting-minutes"]
    empty = store.create_twin({"displayName": "NoSkill", "selectedSkillIds": []})
    assert store.get_twin(empty["id"])["permissions"]["allowedSkillIds"] == []

    updated = store.enable_skill(twin["id"], "knowledge-research")
    assert "knowledge-research" in updated["permissions"]["allowedSkillIds"]

    updated = store.disable_skill(twin["id"], "meeting-minutes")
    assert "meeting-minutes" not in updated["permissions"]["allowedSkillIds"]

    updated = store.update_twin(
        twin["id"],
        {
            "displayName": "Ada Twin",
            "purpose": "Represent Ada in focused work.",
            "tone": "warm and concise",
            "appearance": {"id": "mint"},
            "memories": ["当前项目是 JiuMe", "偏好先给结论"],
            "permissions": {"defaultMode": "draft"},
        },
    )
    assert updated["displayName"] == "Ada Twin"
    assert updated["purpose"] == "Represent Ada in focused work."
    assert updated["tone"] == "warm and concise"
    assert updated["appearance"]["label"] == "薄荷绿"
    assert updated["memories"] == ["当前项目是 JiuMe", "偏好先给结论"]
    assert updated["permissions"]["defaultMode"] == "draft"


def test_twin_creation_can_defer_activation_until_avatar_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")

    twin = store.create_twin({"displayName": "Draft", "activate": False})

    assert twin["status"] == "creating"
    assert store.get_active_twin_id() is None
    ready = store.update_twin(twin["id"], {"status": "ready"})
    assert ready["status"] == "ready"
    assert store.get_active_twin_id() is None
    with pytest.raises(ValueError, match="not active"):
        store.set_active_twin(twin["id"])
    activated = store.activate_twin(twin["id"])
    assert activated["status"] == "active"
    assert store.get_active_twin_id() == twin["id"]


def test_avatar_manifest_and_asset_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Bo", "appearance": {"id": "pink"}})

    manifest = AvatarService(store).generate_mock_avatar(twin["id"])["manifest"]
    idle_path = tmp_path / "twins" / twin["id"] / "avatar" / "idle.png"
    idle_image = Image.open(idle_path).convert("RGBA")

    assert manifest["provider"] == "mock"
    assert manifest["style"] == "q-version-2d-human-desktop-twin"
    assert manifest["identity"]["form"] == "person-shaped"
    assert manifest["identity"]["agentEntryPoint"] is True
    assert manifest["appearance"]["label"] == "草莓粉"
    assert "spritePack" in manifest
    assert "codexPet" not in manifest
    assert tuple(DESKTOP_STATES) == tuple(CODEX_PET_FRAME_COUNTS)
    assert tuple(manifest["states"]) == tuple(CODEX_PET_FRAME_COUNTS)
    assert set(manifest["views"]) == set(AVATAR_VIEW_NAMES)
    for row, (state, frame_count) in enumerate(CODEX_PET_FRAME_COUNTS.items()):
        frames = manifest["states"][state]["frames"]
        assert len(frames) == frame_count
        assert manifest["states"][state]["fps"] == 6
        assert manifest["spritePack"]["animations"][state]["frames"] == [
            row * CODEX_PET_GRID[0] + column for column in range(frame_count)
        ]
        for frame in frames:
            assert Path(frame["file"]).exists()
    assert idle_path.exists()
    for view in manifest["views"].values():
        assert Path(view["file"]).exists()
    assert idle_image.getpixel((0, 0))[3] == 0
    assert idle_image.getpixel((128, 122))[3] > 0
    assert idle_image.getpixel((128, 184))[3] > 0
    _assert_rgb_close(idle_image.getpixel((128, 176))[:3], (236, 72, 153))
    spritesheet = tmp_path / "twins" / twin["id"] / "avatar" / "spritesheet.webp"
    assert spritesheet.exists()
    _assert_codex_pet_atlas(spritesheet)
    assert (tmp_path / "twins" / twin["id"] / "avatar" / "avatar_pack.json").exists()
    pet_json = json.loads((tmp_path / "twins" / twin["id"] / "avatar" / "pet.json").read_text(encoding="utf-8"))
    assert pet_json == {
        "id": twin["id"],
        "displayName": "Bo",
        "description": twin["purpose"],
        "spritesheetPath": "spritesheet.webp",
    }


def test_source_image_generates_visible_local_avatar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Ada", "appearance": {"id": "mint"}})
    source_path = tmp_path / "source.png"
    Image.new("RGB", (220, 220), (14, 96, 210)).save(source_path)
    service = AvatarService(store)
    service.upload_source(
        twin["id"],
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )

    manifest = service.generate_mock_avatar(twin["id"])["manifest"]
    idle_path = tmp_path / "twins" / twin["id"] / "avatar" / "idle.png"
    idle_image = Image.open(idle_path).convert("RGBA")

    assert manifest["provider"] == "source-local"
    assert manifest["base"].endswith("base_source.png")
    assert manifest["sourceImage"]["role"] == "avatar-reference"
    assert Path(manifest["sourceImage"]["file"]).exists()
    assert set(manifest["views"]) == set(AVATAR_VIEW_NAMES)
    assert len(manifest["states"]["waving"]["frames"]) == CODEX_PET_FRAME_COUNTS["waving"]
    assert all(Path(frame["file"]).exists() for frame in manifest["states"]["waving"]["frames"])
    assert idle_image.getpixel((0, 0))[3] == 0
    assert idle_image.getpixel((128, 82))[:3] == (14, 96, 210)
    assert idle_image.getpixel((128, 208))[:3] == (14, 96, 210)
    assert idle_image.getpixel((128, 208))[:3] != (20, 184, 166)
    front_image = Image.open(Path(manifest["views"]["front"]["file"])).convert("RGBA")
    left_image = Image.open(Path(manifest["views"]["left"]["file"])).convert("RGBA")
    right_image = Image.open(Path(manifest["views"]["right"]["file"])).convert("RGBA")
    back_image = Image.open(Path(manifest["views"]["back"]["file"])).convert("RGBA")
    assert left_image.tobytes() != front_image.tobytes()
    assert right_image.tobytes() != front_image.tobytes()
    assert left_image.tobytes() != right_image.tobytes()
    assert left_image.getpixel((128, 82))[:3] == (14, 96, 210)
    assert right_image.getpixel((128, 82))[:3] == (14, 96, 210)
    _assert_rgb_close(left_image.getpixel((64, 102))[:3], (40, 74, 122))
    _assert_rgb_close(right_image.getpixel((192, 102))[:3], (40, 74, 122))
    _assert_rgb_close(back_image.getpixel((128, 82))[:3], (40, 74, 122))
    assert left_image.getpixel((64, 102))[:3] != (47, 36, 29)
    assert back_image.getpixel((128, 82))[:3] != (47, 36, 29)
    waving_image = Image.open(tmp_path / "twins" / twin["id"] / "avatar" / "waving.png").convert("RGBA")
    assert waving_image.tobytes() != idle_image.tobytes()
    service_source = Path("jiume/avatar/service.py").read_text(encoding="utf-8")
    assert "def _side_view_from_base" in service_source
    source_avatar_body = service_source.split("def _source_photo_avatar_base", 1)[1].split(
        "def _shift_transparent", 1
    )[0]
    assert "initials =" not in source_avatar_body
    assert "_center_text(" not in source_avatar_body
    assert "105, 185, 151, 231" not in source_avatar_body
    assert "_has_alpha_cutout(source)" in source_avatar_body
    assert "_source_masked_photo_avatar_base(source)" in source_avatar_body
    assert "draw.rounded_rectangle((45, 12" not in source_avatar_body


def test_transparent_source_image_is_used_as_desktop_cutout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Cutout", "appearance": {"id": "mint"}})
    source_path = tmp_path / "cutout.png"
    source = Image.new("RGBA", (180, 220), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.rounded_rectangle((52, 18, 128, 202), radius=36, fill=(232, 80, 72, 255))
    draw.ellipse((42, 30, 138, 130), fill=(232, 80, 72, 255))
    source.save(source_path)

    service = AvatarService(store)
    service.upload_source(
        twin["id"],
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )

    manifest = service.generate_mock_avatar(twin["id"])["manifest"]
    base_image = Image.open(tmp_path / "twins" / twin["id"] / "avatar" / "base_source.png").convert("RGBA")
    idle_image = Image.open(tmp_path / "twins" / twin["id"] / "avatar" / "idle.png").convert("RGBA")

    assert manifest["provider"] == "source-local"
    assert base_image.getpixel((0, 0))[3] == 0
    assert base_image.getpixel((128, 120))[:3] == (232, 80, 72)
    assert base_image.getpixel((128, 208))[:3] == (232, 80, 72)
    assert base_image.getpixel((128, 208))[:3] != (20, 184, 166)
    assert idle_image.getbbox() is not None
    assert len(manifest["states"]["idle"]["frames"]) == CODEX_PET_FRAME_COUNTS["idle"]


def test_simple_photo_background_is_cut_out_for_local_avatar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Photo", "appearance": {"id": "mint"}})
    source_path = tmp_path / "photo.png"
    source = Image.new("RGB", (260, 260), (236, 240, 246))
    draw = ImageDraw.Draw(source)
    draw.rounded_rectangle((96, 96, 164, 236), radius=28, fill=(232, 80, 72))
    draw.ellipse((76, 38, 184, 146), fill=(232, 80, 72))
    source.save(source_path)

    service = AvatarService(store)
    service.upload_source(
        twin["id"],
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )

    manifest = service.generate_mock_avatar(twin["id"])["manifest"]
    base_image = Image.open(tmp_path / "twins" / twin["id"] / "avatar" / "base_source.png").convert("RGBA")

    assert manifest["provider"] == "source-local"
    assert base_image.getpixel((0, 0))[3] == 0
    assert base_image.getpixel((128, 118))[:3] == (232, 80, 72)
    assert base_image.getpixel((128, 208))[:3] == (232, 80, 72)
    assert base_image.getpixel((128, 208))[:3] != (20, 184, 166)


def test_auto_avatar_generation_uses_uploaded_source_without_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.delenv("JIUME_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Ada"})
    source_path = tmp_path / "source.png"
    Image.new("RGB", (240, 240), (231, 90, 72)).save(source_path)
    service = AvatarService(store)
    service.upload_source(
        twin["id"],
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )

    manifest = service.generate_avatar(twin["id"], "auto")["manifest"]
    base_image = Image.open(tmp_path / "twins" / twin["id"] / "avatar" / "base_source.png").convert("RGBA")

    assert manifest["provider"] == "source-local"
    assert set(manifest["states"]) >= set(DESKTOP_STATES)
    assert Path(manifest["states"]["idle"]["file"]).exists()
    assert base_image.getpixel((0, 0))[3] == 0
    assert base_image.getpixel((128, 118))[:3] == (231, 90, 72)
    assert base_image.getpixel((128, 224))[:3] == (231, 90, 72)
    assert base_image.getpixel((75, 224))[3] < 16


def test_native_setup_requires_model_key_before_creating_twin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.delenv("JIUME_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    source_path = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (231, 90, 72)).save(source_path)
    controller = NativeSetupController(store=store, avatars=AvatarService(store))

    with pytest.raises(ValueError, match="image model"):
        controller.create_twin_from_photo(
            display_name="Ada",
            source_image={
                "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
                "mimeType": "image/png",
                "consent": True,
            },
        )

    assert store.list_twins() == []
    assert store.get_active_twin_id() is None


def test_native_setup_generates_ready_twin_then_requires_enable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setenv("JIUME_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    source_path = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (84, 112, 230)).save(source_path)

    def fake_generate_model_avatar(self: AvatarService, twin_id: str) -> dict[str, Any]:
        avatar_dir = tmp_path / "twins" / twin_id / "avatar"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        image_path = avatar_dir / "idle.png"
        Image.new("RGBA", (32, 32), (84, 112, 230, 255)).save(image_path)
        manifest = {
            "provider": "openai",
            "states": {"idle": {"file": str(image_path), "frames": [{"file": str(image_path)}]}},
            "views": {},
            "spritePack": {"spritesheet": str(avatar_dir / "spritesheet.webp")},
            "generated_at": "test",
        }
        return {"id": "job_test", "twin_id": twin_id, "status": "completed", "provider": "openai", "manifest": manifest}

    monkeypatch.setattr(AvatarService, "generate_model_avatar", fake_generate_model_avatar)
    controller = NativeSetupController(store=store, avatars=AvatarService(store))

    created = controller.create_twin_from_photo(
        display_name="Ada",
        source_image={
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )

    assert created["twin"]["status"] == "ready"
    assert created["job"]["provider"] == "openai"
    assert store.get_active_twin_id() is None
    assert store.get_twin(created["twin"]["id"])["status"] == "ready"

    enabled = controller.enable_twin(created["twin"]["id"])

    assert enabled["status"] == "active"
    assert store.get_active_twin_id() == created["twin"]["id"]


def test_native_setup_generation_does_not_write_desktop_state_before_enable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    monkeypatch.setenv("JIUME_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    source_path = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (84, 112, 230)).save(source_path)
    desktop_events: list[tuple[str, str, str, str]] = []

    def fake_set_desktop_state(state: str, *, twin_id: str = "", message: str = "", source: str = "") -> None:
        desktop_events.append((state, twin_id, message, source))

    def fake_generate_model_avatar(self: AvatarService, twin_id: str) -> dict[str, Any]:
        avatar_dir = tmp_path / "twins" / twin_id / "avatar"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        image_path = avatar_dir / "idle.png"
        Image.new("RGBA", (32, 32), (84, 112, 230, 255)).save(image_path)
        manifest = {
            "provider": "openai",
            "states": {"idle": {"file": str(image_path), "frames": [{"file": str(image_path)}]}},
            "views": {},
            "spritePack": {"spritesheet": str(avatar_dir / "spritesheet.webp")},
            "generated_at": "test",
        }
        return {"id": "job_test", "twin_id": twin_id, "status": "completed", "provider": "openai", "manifest": manifest}

    monkeypatch.setattr(AvatarService, "generate_model_avatar", fake_generate_model_avatar)
    monkeypatch.setattr("jiume.setup.server.set_desktop_state", fake_set_desktop_state)
    controller = NativeSetupController(store=store, avatars=AvatarService(store))

    created = controller.create_twin_from_photo(
        display_name="Ada",
        source_image={
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )

    assert created["twin"]["status"] == "ready"
    assert desktop_events == []

    controller.enable_twin(created["twin"]["id"])

    assert desktop_events == [("success", created["twin"]["id"], "我已经换成你的桌面分身", "setup")]
    setup_source = Path("jiume/setup/server.py").read_text(encoding="utf-8")
    assert 'source="setup"' in setup_source


def test_native_setup_accepts_empty_optional_provider_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIUME_OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("JIUME_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("API_BASE", raising=False)
    monkeypatch.delenv("JIUME_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_MODEL", raising=False)
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    controller = NativeSetupController(store=store, avatars=AvatarService(store))

    controller.save_provider_config(api_key="test-key", base_url="", model="")
    config = get_image_provider_config()

    assert config.base_url == ""
    assert config.model == "gpt-image-2"
    assert store.get_active_twin_id() is None


def test_generation_progress_and_failure_classifier_are_specific() -> None:
    progress = GenerationProgress(stage="states", title="生成状态", detail="正在生成 idle/speaking 动作", percent=0.62)

    missing_key = classify_generation_error(ValueError("image model API key is required before creating a twin."))
    timeout = classify_generation_error(TimeoutError("request timed out"))
    connection = classify_generation_error(ConnectionError("connection refused"))
    unknown = classify_generation_error(RuntimeError("unexpected provider payload"))

    assert progress.as_dict() == {
        "stage": "states",
        "title": "生成状态",
        "detail": "正在生成 idle/speaking 动作",
        "percent": 0.62,
    }
    assert missing_key.code == "config_missing"
    assert "图片模型 API Key" in missing_key.title
    assert timeout.code == "timeout"
    assert "超时" in timeout.title
    assert connection.code == "network"
    assert "网络" in connection.title
    assert unknown.code == "unknown"
    assert "unexpected provider payload" in unknown.detail


def test_setup_generation_worker_uses_ui_queue_instead_of_thread_tk_after() -> None:
    setup_source = Path("jiume/setup/server.py").read_text(encoding="utf-8")
    init_source = setup_source.split("def __init__", 1)[1].split("def _build_shell", 1)[0]
    worker_source = setup_source.split("def _generate_worker", 1)[1].split(
        "def _handle_generation_progress",
        1,
    )[0]

    assert "from queue import Empty, SimpleQueue" in setup_source
    assert "self._ui_events: SimpleQueue[Callable[[], None]]" in init_source
    assert "def _post_to_ui" in setup_source
    assert "def _drain_ui_events" in setup_source
    assert "progress=lambda stage: self._post_to_ui(" in worker_source
    assert "lambda s=stage, a=attempt_id: self._handle_generation_progress(a, s)" in worker_source
    assert "self._post_to_ui(lambda e=exc, a=attempt_id:" in worker_source
    assert "self._post_to_ui(lambda r=result, a=attempt_id:" in worker_source
    assert "self.root.after" not in worker_source


def test_native_setup_reports_creation_progress_stages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setenv("JIUME_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    source_path = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (84, 112, 230)).save(source_path)

    def fake_generate_model_avatar(self: AvatarService, twin_id: str) -> dict[str, Any]:
        avatar_dir = tmp_path / "twins" / twin_id / "avatar"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        image_path = avatar_dir / "idle.png"
        Image.new("RGBA", (32, 32), (84, 112, 230, 255)).save(image_path)
        manifest = {
            "provider": "openai",
            "states": {"idle": {"file": str(image_path), "frames": [{"file": str(image_path)}]}},
            "views": {},
            "spritePack": {"spritesheet": str(avatar_dir / "spritesheet.webp")},
            "generated_at": "test",
        }
        return {"id": "job_test", "twin_id": twin_id, "status": "completed", "provider": "openai", "manifest": manifest}

    monkeypatch.setattr(AvatarService, "generate_model_avatar", fake_generate_model_avatar)
    controller = NativeSetupController(store=store, avatars=AvatarService(store))
    stages: list[str] = []

    created = controller.create_twin_from_photo(
        display_name="Ada",
        source_image={
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
        progress=stages.append,
    )

    assert created["twin"]["status"] == "ready"
    assert stages == ["photo", "model", "states", "enable"]


def test_native_setup_cancel_removes_generated_twin_before_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setenv("JIUME_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    source_path = tmp_path / "source.png"
    Image.new("RGB", (32, 32), (84, 112, 230)).save(source_path)

    def fake_generate_model_avatar(self: AvatarService, twin_id: str) -> dict[str, Any]:
        avatar_dir = tmp_path / "twins" / twin_id / "avatar"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        image_path = avatar_dir / "idle.png"
        Image.new("RGBA", (32, 32), (84, 112, 230, 255)).save(image_path)
        manifest = {
            "provider": "openai",
            "states": {"idle": {"file": str(image_path), "frames": [{"file": str(image_path)}]}},
            "views": {},
            "spritePack": {"spritesheet": str(avatar_dir / "spritesheet.webp")},
            "generated_at": "test",
        }
        return {"id": "job_test", "twin_id": twin_id, "status": "completed", "provider": "openai", "manifest": manifest}

    monkeypatch.setattr(AvatarService, "generate_model_avatar", fake_generate_model_avatar)
    controller = NativeSetupController(store=store, avatars=AvatarService(store))

    with pytest.raises(RuntimeError, match="generation cancelled"):
        controller.create_twin_from_photo(
            display_name="Ada",
            source_image={
                "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
                "mimeType": "image/png",
                "consent": True,
            },
            is_cancelled=lambda: bool(store.list_twins()),
        )

    assert store.list_twins() == []
    assert store.get_active_twin_id() is None


def test_native_setup_late_success_callback_deletes_cancelled_ready_twin(tmp_path: Path) -> None:
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Ada", "activate": False})
    ready = store.update_twin(twin["id"], {"status": "ready"})
    window = object.__new__(NativeSetupWindow)
    window.controller = NativeSetupController(store=store, avatars=AvatarService(store))
    window.generation_attempt_id = "attempt-1"
    window.generation_cancelled = True
    window.created_twin_id = ""

    NativeSetupWindow._generation_succeeded(window, "attempt-1", {"twin": ready})

    assert store.list_twins() == []
    assert window.created_twin_id == ""


def test_source_preview_generates_avatar_pack_without_creating_twin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    source_path = tmp_path / "preview.png"
    source = Image.new("RGB", (260, 260), (236, 240, 246))
    draw = ImageDraw.Draw(source)
    draw.rounded_rectangle((92, 96, 168, 236), radius=30, fill=(84, 112, 230))
    draw.ellipse((74, 36, 186, 148), fill=(84, 112, 230))
    source.save(source_path)

    job = AvatarService(store).generate_source_preview(
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
        "Ada Preview",
    )
    manifest = job["manifest"]
    preview_id = job["twin_id"]
    public_manifest = _public_manifest(manifest, preview_id)

    assert preview_id.startswith("preview_")
    assert job["provider"] == "source-local-preview"
    assert store.list_twins() == []
    assert store.get_active_twin_id() is None
    assert manifest["identity"]["form"] == "person-shaped"
    assert set(manifest["states"]) >= set(DESKTOP_STATES)
    assert set(manifest["views"]) == set(AVATAR_VIEW_NAMES)
    assert len(manifest["states"]["idle"]["frames"]) == CODEX_PET_FRAME_COUNTS["idle"]
    assert Path(manifest["states"]["idle"]["file"]).exists()
    assert Path(manifest["spritePack"]["spritesheet"]).exists()
    assert public_manifest["provider"] == "source-local-preview"
    assert public_manifest["states"]["idle"]["src"].startswith(f"/assets/{preview_id}/idle.png")
    assert "file" not in public_manifest["states"]["idle"]
    assert "file" not in public_manifest["states"]["idle"]["frames"][0]
    target, mime = resolve_asset_path(preview_id, Path(manifest["states"]["idle"]["file"]).name)
    assert target.exists()
    assert mime == "image/png"
    assert Path(manifest["states"]["waving"]["file"]).exists()
    assert len(manifest["states"]["idle"]["frames"]) == CODEX_PET_FRAME_COUNTS["idle"]
    assert set(manifest["views"]) == set(AVATAR_VIEW_NAMES)


def test_openai_avatar_generates_hatch_pet_style_sprite_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    monkeypatch.setattr("jiume.avatar.service.get_twin_root", lambda twin_id: tmp_path / "twins" / str(twin_id))
    monkeypatch.setattr(
        "jiume.avatar.service.get_image_provider_config",
        lambda: SimpleNamespace(api_key="test-key", base_url="", model="gpt-image-2", config_path=tmp_path / "config.env"),
    )
    store = TwinStore(root=tmp_path / "twins")
    service = AvatarService(store)
    source_path = tmp_path / "source.png"
    Image.new("RGB", (64, 64), (240, 225, 210)).save(source_path)
    twin = store.create_twin({"displayName": "Rows"})
    service.upload_source(
        twin["id"],
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )
    calls: list[dict[str, Any]] = []

    class FakeImages:
        def edit(self, **kwargs: Any) -> SimpleNamespace:
            calls.append({**kwargs, "image_name": Path(kwargs["image"].name).name})
            prompt = str(kwargs.get("prompt") or "")
            for state in CODEX_PET_FRAME_COUNTS:
                if f"Animation row state: {state}." in prompt:
                    return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(_fake_openai_row_png(state)).decode("ascii"))])
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(_fake_openai_base_png()).decode("ascii"))])

    class FakeOpenAI:
        def __init__(self, **_kwargs: Any) -> None:
            self.images = FakeImages()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    job = service.generate_openai_avatar(twin["id"])
    manifest = job["manifest"]
    avatar_dir = tmp_path / "twins" / twin["id"] / "avatar"

    assert job["provider"] == "openai"
    assert len(calls) == 1 + len(CODEX_PET_FRAME_COUNTS)
    assert calls[0]["image_name"].startswith("source_")
    assert all(call["image_name"] == "base_openai.png" for call in calls[1:])
    assert all("hatch-pet-style Codex animation row strip" in str(call["prompt"]) for call in calls[1:])
    assert all("#FF00FF" in str(call["prompt"]) for call in calls[1:])
    assert all("checkerboard" in str(call["prompt"]).lower() for call in calls[1:])
    assert all(call.get("background") is None for call in calls[1:])
    for state, frame_count in CODEX_PET_FRAME_COUNTS.items():
        assert (avatar_dir / f"row_{state}.png").exists()
        assert len(manifest["states"][state]["frames"]) == frame_count
        assert all(Path(frame["file"]).exists() for frame in manifest["states"][state]["frames"])
    assert _visible_average_rgb(avatar_dir / "idle.png") != _visible_average_rgb(avatar_dir / "idle_1.png")
    _assert_codex_pet_atlas(avatar_dir / "spritesheet.webp")


def test_openai_avatar_removes_generated_checkerboard_background(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    monkeypatch.setattr("jiume.avatar.service.get_twin_root", lambda twin_id: tmp_path / "twins" / str(twin_id))
    monkeypatch.setattr(
        "jiume.avatar.service.get_image_provider_config",
        lambda: SimpleNamespace(api_key="test-key", base_url="", model="gpt-image-2", config_path=tmp_path / "config.env"),
    )
    store = TwinStore(root=tmp_path / "twins")
    service = AvatarService(store)
    source_path = tmp_path / "source.png"
    Image.new("RGB", (64, 64), (240, 225, 210)).save(source_path)
    twin = store.create_twin({"displayName": "Checker"})
    service.upload_source(
        twin["id"],
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )

    class FakeImages:
        def edit(self, **kwargs: Any) -> SimpleNamespace:
            prompt = str(kwargs.get("prompt") or "")
            for state in CODEX_PET_FRAME_COUNTS:
                if f"Animation row state: {state}." in prompt:
                    return SimpleNamespace(
                        data=[SimpleNamespace(b64_json=base64.b64encode(_fake_openai_checkerboard_row_png(state)).decode("ascii"))]
                    )
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(_fake_openai_base_png()).decode("ascii"))])

    class FakeOpenAI:
        def __init__(self, **_kwargs: Any) -> None:
            self.images = FakeImages()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    job = service.generate_openai_avatar(twin["id"])
    avatar_dir = tmp_path / "twins" / twin["id"] / "avatar"
    row_idle = Image.open(avatar_dir / "row_idle.png").convert("RGBA")
    idle = Image.open(avatar_dir / "idle.png").convert("RGBA")
    idle_bbox = idle.getchannel("A").getbbox()

    assert job["provider"] == "openai"
    assert row_idle.getpixel((0, 0))[3] == 0
    assert row_idle.getchannel("A").getbbox() != (0, 0, row_idle.width, row_idle.height)
    assert idle_bbox is not None
    assert idle_bbox[2] - idle_bbox[0] > 45
    assert all(idle.getpixel(point)[3] == 0 for point in [(0, 0), (191, 0), (0, 207), (191, 207)])
    _assert_codex_pet_atlas(avatar_dir / "spritesheet.webp")


def test_openai_avatar_removes_green_chroma_spill_without_erasing_green_outfit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    monkeypatch.setattr("jiume.avatar.service.get_twin_root", lambda twin_id: tmp_path / "twins" / str(twin_id))
    monkeypatch.setattr(
        "jiume.avatar.service.get_image_provider_config",
        lambda: SimpleNamespace(api_key="test-key", base_url="", model="gpt-image-2", config_path=tmp_path / "config.env"),
    )
    store = TwinStore(root=tmp_path / "twins")
    service = AvatarService(store)
    source_path = tmp_path / "source.png"
    Image.new("RGB", (64, 64), (240, 225, 210)).save(source_path)
    twin = store.create_twin({"displayName": "Spill"})
    service.upload_source(
        twin["id"],
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )

    class FakeImages:
        def edit(self, **kwargs: Any) -> SimpleNamespace:
            prompt = str(kwargs.get("prompt") or "")
            for state in CODEX_PET_FRAME_COUNTS:
                if f"Animation row state: {state}." in prompt:
                    return SimpleNamespace(
                        data=[SimpleNamespace(b64_json=base64.b64encode(_fake_openai_green_spill_row_png(state)).decode("ascii"))]
                    )
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(_fake_openai_base_png()).decode("ascii"))])

    class FakeOpenAI:
        def __init__(self, **_kwargs: Any) -> None:
            self.images = FakeImages()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    service.generate_openai_avatar(twin["id"])
    avatar_dir = tmp_path / "twins" / twin["id"] / "avatar"
    idle = Image.open(avatar_dir / "idle.png").convert("RGBA")
    row_idle = Image.open(avatar_dir / "row_idle.png").convert("RGBA")
    bright_spill = [
        pixel
        for pixel in idle.getdata()
        if pixel[3] > 16 and pixel[1] >= 185 and pixel[1] - max(pixel[0], pixel[2]) >= 64 and pixel[2] <= pixel[0] + 52
    ]
    tinted_outline = [
        pixel
        for pixel in idle.getdata()
        if pixel[3] > 16 and min(pixel[:3]) >= 180 and pixel[1] - max(pixel[0], pixel[2]) >= 18
    ]
    outfit_pixels = [
        pixel
        for pixel in idle.getdata()
        if pixel[3] > 16 and 32 <= pixel[0] <= 72 and 125 <= pixel[1] <= 190 and 90 <= pixel[2] <= 150
    ]

    assert row_idle.getpixel((0, 0))[3] == 0
    assert bright_spill == []
    assert tinted_outline == []
    assert len(outfit_pixels) > 40
    _assert_codex_pet_atlas(avatar_dir / "spritesheet.webp")


def test_openai_avatar_retries_without_transparent_background_when_model_rejects_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    monkeypatch.setattr("jiume.avatar.service.get_twin_root", lambda twin_id: tmp_path / "twins" / str(twin_id))
    monkeypatch.setattr(
        "jiume.avatar.service.get_image_provider_config",
        lambda: SimpleNamespace(api_key="test-key", base_url="", model="gpt-image-2", config_path=tmp_path / "config.env"),
    )
    store = TwinStore(root=tmp_path / "twins")
    service = AvatarService(store)
    source_path = tmp_path / "source.png"
    Image.new("RGB", (64, 64), (240, 225, 210)).save(source_path)
    twin = store.create_twin({"displayName": "Retry"})
    service.upload_source(
        twin["id"],
        {
            "contentBase64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
            "consent": True,
        },
    )
    calls: list[dict[str, Any]] = []
    client_kwargs: list[dict[str, Any]] = []
    did_reject_transparency = False

    class FakeImages:
        def edit(self, **kwargs: Any) -> SimpleNamespace:
            nonlocal did_reject_transparency
            calls.append(kwargs)
            if kwargs.get("background") == "transparent" and not did_reject_transparency:
                did_reject_transparency = True
                raise RuntimeError("Transparent background is not supported for this model.")
            prompt = str(kwargs.get("prompt") or "")
            for state in CODEX_PET_FRAME_COUNTS:
                if f"Animation row state: {state}." in prompt:
                    return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(_fake_openai_row_png(state)).decode("ascii"))])
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(_fake_openai_base_png()).decode("ascii"))])

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            client_kwargs.append(kwargs)
            self.images = FakeImages()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    job = service.generate_openai_avatar(twin["id"])

    assert [call.get("background") for call in calls[:2]] == ["transparent", None]
    assert len(calls) == 2 + len(CODEX_PET_FRAME_COUNTS)
    assert client_kwargs == [{"api_key": "test-key", "timeout": 180.0}]
    assert job["provider"] == "openai"
    assert (tmp_path / "twins" / twin["id"] / "avatar" / "idle.png").exists()


def test_public_manifest_cache_busts_avatar_urls() -> None:
    manifest = {
        "generated_at": "2026-05-23T09:00:00+00:00",
        "states": {
            "idle": {
                "file": "/tmp/avatar/idle.png",
                "src": "old",
                "frames": [
                    {"file": "/tmp/avatar/idle.png", "src": "old"},
                    {"file": "/tmp/avatar/idle_1.png", "src": "old"},
                ],
            }
        },
        "views": {"front": {"file": "/tmp/avatar/view_front.png", "src": "old"}},
        "spritePack": {"manifest": "old", "compatFile": "old", "spritesheet": "old"},
        "sourceImage": {"file": "/tmp/avatar/source.png", "src": "old", "role": "avatar-reference"},
    }

    public = _public_manifest(manifest, "twin_safe")

    assert public["states"]["idle"]["src"] == "/assets/twin_safe/idle.png?v=2026-05-23T09:00:00+00:00"
    assert public["states"]["idle"]["frames"][1]["src"] == "/assets/twin_safe/idle_1.png?v=2026-05-23T09:00:00+00:00"
    assert public["views"]["front"]["src"] == "/assets/twin_safe/view_front.png?v=2026-05-23T09:00:00+00:00"
    assert public["sourceImage"]["src"] == "/assets/twin_safe/source.png?v=2026-05-23T09:00:00+00:00"
    assert "file" not in public["states"]["idle"]
    assert "file" not in public["states"]["idle"]["frames"][0]
    assert "file" not in public["views"]["front"]
    assert "file" not in public["sourceImage"]
    assert public["spritePack"]["spritesheet"].endswith("spritesheet.webp?v=2026-05-23T09:00:00+00:00")


def test_first_run_placeholder_manifest_does_not_create_twin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    launcher_source = Path("jiume/launcher.py").read_text(encoding="utf-8")

    assert "_setup_placeholder_manifest" not in app_source
    assert "setup-placeholder" not in app_source
    assert "NativeSetupWindow" in Path("jiume/setup/server.py").read_text(encoding="utf-8")
    assert "first run: native setup is the primary surface" in launcher_source


def test_desktop_state_file_uses_manifest_animation_frames() -> None:
    manifest = {
        "states": {
            "idle": {
                "file": "/tmp/idle.png",
                "frames": [
                    {"file": "/tmp/idle.png"},
                    {"file": "/tmp/idle_1.png"},
                    {"file": "/tmp/idle_2.png"},
                ],
            },
            "waving": {
                "file": "/tmp/waving.png",
                "frames": [{"file": "/tmp/waving.png"}, {"file": "/tmp/waving_1.png"}],
            },
            "running": {
                "file": "/tmp/running.png",
                "frames": [{"file": "/tmp/running.png"}, {"file": "/tmp/running_1.png"}],
            },
            "waiting": {"file": "/tmp/waiting.png", "frames": [{"file": "/tmp/waiting.png"}]},
            "review": {"file": "/tmp/review.png", "frames": [{"file": "/tmp/review.png"}]},
            "failed": {"file": "/tmp/failed.png", "frames": [{"file": "/tmp/failed.png"}]},
        }
    }

    assert _state_file(manifest, "idle", 0) == Path("/tmp/idle.png")
    assert _state_file(manifest, "idle", 1) == Path("/tmp/idle_1.png")
    assert _state_file(manifest, "speaking", 3) == Path("/tmp/waving_1.png")
    assert _state_file(manifest, "thinking", 3) == Path("/tmp/running_1.png")
    assert _state_file(manifest, "working", 3) == Path("/tmp/running_1.png")
    assert _state_file(manifest, "waiting_approval", 0) == Path("/tmp/waiting.png")
    assert _state_file(manifest, "success", 0) == Path("/tmp/review.png")
    assert _state_file(manifest, "error", 0) == Path("/tmp/failed.png")
    assert _state_file(manifest, "sleep", 2) == Path("/tmp/idle_2.png")
    first_signature = _avatar_manifest_signature(
        {
            "generated_at": "same",
            "provider": "source-local",
            "sourceImage": {"file": "/tmp/source-a.png"},
            "states": {"idle": {"file": "/tmp/idle.png", "frames": [{"file": "/tmp/idle_1.png"}]}},
            "views": {"front": {"file": "/tmp/front.png"}},
            "spritePack": {"spritesheet": "/tmp/sheet-a.webp"},
        }
    )
    second_signature = _avatar_manifest_signature(
        {
            "generated_at": "same",
            "provider": "source-local",
            "sourceImage": {"file": "/tmp/source-b.png"},
            "states": {"idle": {"file": "/tmp/idle.png", "frames": [{"file": "/tmp/idle_2.png"}]}},
            "views": {"front": {"file": "/tmp/front.png"}},
            "spritePack": {"spritesheet": "/tmp/sheet-b.webp"},
        }
    )
    assert first_signature != second_signature
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    watch_source = app_source.split("def _watch_state_file", 1)[1].split("def _keep_topmost", 1)[0]
    sync_source = app_source.split("def _sync_active_manifest", 1)[1].split("def _watch_state_file", 1)[0]
    assert "payload.get(\"twin_id\")" in watch_source
    assert "_apply_external_state(s, m, t)" in watch_source
    assert "self._sync_active_manifest(twin_id)" in watch_source
    assert "next_manifest = self.avatars.get_manifest(target)" in sync_source
    assert "_avatar_manifest_signature" in sync_source
    assert "self._avatar_cache.clear()" in sync_source
    assert "self._native_onboarding_pending = False" in sync_source
    assert "self._direct_settings_detail_visible = False" in sync_source
    assert "我已经换成你的桌面分身。单击就直接说话。" in app_source


def test_setup_page_copy_prioritizes_person_twin_creation() -> None:
    setup_source = Path("jiume/setup/server.py").read_text(encoding="utf-8")
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    menu_source = Path("jiume/desktop/menus.py").read_text(encoding="utf-8")

    assert not Path("jiume/resources/setup/index.html").exists()
    assert "NativeSetupController" in setup_source
    assert "NativeSetupWindow" in setup_source
    assert "ThreadingHTTPServer" not in setup_source
    assert "BaseHTTPRequestHandler" not in setup_source
    assert "SETUP_HTML" not in setup_source
    assert "do_GET" not in setup_source
    assert "do_POST" not in setup_source
    assert "webbrowser.open(runtime_config_url())" in setup_source
    assert "配置入口" not in menu_source
    assert "webbrowser.open(self.setup_url)" not in app_source
    assert "_setup_placeholder_manifest" not in app_source
    assert "open_panel(self)" in app_source
    assert "Legacy boxed control panel is retired" in app_source
    return

    html = Path("jiume/resources/setup/index.html").read_text(encoding="utf-8")

    assert _is_setup_page_path("/")
    assert _is_setup_page_path("/setup")
    assert _is_setup_page_path("/setup/")
    assert not _is_setup_page_path("/api/setup")
    assert "上传照片，让 JiuMe 像你。" in html
    assert html.index("上传照片，让 JiuMe 像你。") < html.index("让分身留在桌面。")
    assert "1 / 3" not in html
    assert '<span class="step-count" id="stepCount">1 / 2</span>' in html
    assert 'data-panel="2"' not in html
    assert 'data-step-jump="2"' not in html
    assert "桌面人形分身" in html
    assert "待上传照片" in html
    assert "ambient-status" in html
    assert '<header class="topbar">' not in html
    assert 'class="progress-row" aria-hidden="true"' in html
    assert "[hidden] {\n        display: none !important;\n      }" in html
    assert "dialogue-step" in html
    assert "Dialogue-stage refinement" in html
    assert "Avatar-first pass" in html
    assert ".side {\n        order: -1;" in html
    assert "data-config-mode=\"local\"" in html
    assert "data-config-mode=\"model\"" in html
    assert '<div class="model-form" id="modelForm">' in html
    assert '<div class="model-form is-visible" id="modelForm">' not in html
    assert "modelFormExpanded = false" in html
    assert "Two-step-first-run pass" in html
    assert "确认后，我会从这里常驻到桌面。高级图片模型以后再接。" in html
    assert "Dialogue-action-bubbles pass" in html
    assert "Personal-stage-final pass" in html
    assert "const previewReadyLabel = '继续进入';" in html
    assert '<span id="nextLabel">生成预览</span>' in html
    assert '<span id="nextLabel">下一步</span>' not in html
    assert ".ghost-button:disabled {\n        visibility: hidden;" in html
    assert ".actions {\n        flex-direction: row-reverse;" in html
    assert 'id="consent" type="checkbox" checked' in html
    assert "body::before {\n        display: none;" in html
    assert "grid-template-columns: minmax(420px, 1.2fr) minmax(320px, .8fr)" in html
    assert ".main,\n      .panel,\n      .side,\n      .avatar-card,\n      .avatar-stage,\n      .desktop-frame" in html
    assert "高级图片模型" in html
    assert 'id="advancedConfigToggle"' in html
    assert 'id="advancedConfigMode" aria-label="高级头像生成方式" hidden' in html
    assert 'id="configHint" hidden' in html
    assert "let advancedConfigVisible = false" in html
    assert "advancedConfigMode.hidden = !advancedConfigVisible" in html
    assert "modelForm.classList.toggle('is-visible', advancedConfigVisible && modelFormExpanded)" in html
    assert "'生成预览'" in html
    assert "'保存并继续'" not in html
    assert "renderConfigMode()" in html
    assert "button.dataset.configMode === 'model'" in html
    assert "avatar-placeholder" in html
    assert "source-avatar" in html
    assert "source-avatar-cutout" in html
    assert "source-avatar-photo" in html
    assert "source-cutout-image" in html
    assert "source-photo-bust" in html
    assert "source-photo-card" not in html
    assert "Source-avatar-as-person pass" in html
    assert "Focused-first-run-clarity pass" in html
    assert "bust.className = 'source-photo-bust';" in html
    assert "上传照片人形半身预览" in html
    assert "sourceHasTransparentPixels" in html
    assert "window.jiumeSourceHasTransparentPixels = sourceHasTransparentPixels" in html
    assert "mode === 'source-cutout'" in html
    assert "preview.dataset.sourcePreview" in html
    assert "preview.dataset.previewMode" in html
    assert "has-photo-preview" in html
    assert "has-generated-avatar" in html
    assert "is-generating-preview" in html
    assert "Conversation-polish pass" in html
    assert "Companion-onboarding pass" in html
    assert 'id="photoHeadline"' in html
    assert "photoHeadlineReady = '照片已放进 JiuMe 预览。'" in html
    assert "photoHeadlineGenerated = '你的 JiuMe 分身已生成。'" in html
    assert "? photoHeadlineGenerated" in html
    assert ".source-avatar-photo .source-face-ring" in html
    assert "body[data-upload-preview=\"empty\"] .orbit-nav" in html
    assert "body[data-upload-preview=\"empty\"] .actions {\n        display: none !important;" in html
    assert 'body[data-upload-preview="empty"] .consent {\n        display: none !important;' in html
    assert "body.has-photo-preview .orbit-nav button:nth-child(2)" in html
    assert ".upload-card {\n        grid-template-columns: 50px minmax(0, 1fr) max-content;" in html
    assert "grid-column: 3;" in html
    assert ".dialogue-step h1::after" in html
    assert ".orbit-nav {\n        pointer-events: none;" in html
    assert ".orbit-nav button {\n        pointer-events: auto;" in html
    assert "body.is-generating .desktop-frame" in html
    assert "ambientStatusText.textContent = hasSourcePreview" in html
    assert "根据上传照片生成的 JiuMe 预览" in html
    assert "根据透明照片生成的 JiuMe 抠图预览" in html
    assert "我看到了透明主体，会直接用它生成桌面分身。" in html
    assert "我看到了这张照片，会先尝试抠出你再生成多状态分身。" in html
    assert "generateAvatarPreviewFromPhoto" in html
    assert "fetch(apiUrl('/api/avatar-preview')" in html
    assert "previewManifest = result.manifest" in html
    assert "renderStateStrip(previewManifest)" in html
    assert "renderViewStrip(previewManifest)" in html
    assert "Instant-upload-preview pass" in html
    assert "setPreviewImage(selectedPhotoPreviewUrl, 'source');" in html
    assert "照片已经先变成预览。勾选授权后会立刻生成 idle、speaking、thinking 等状态。" in html
    assert "consent.checked ? '' : 'error'" not in html
    assert "分身已生成。点角色周围的小气泡" in html
    assert "角色动作已就绪" in html
    assert "动作和视角已经围在我身边" in html
    assert "nextLabel.textContent = '生成中';" in html
    assert "nextButton.classList.toggle('is-ready'" in html
    assert "nextLabel.textContent = previewReadyLabel;" in html
    assert "#nextButton.is-ready" in html
    assert "if (!previewManifest && !setupCompleted)" in html
    assert "consent.addEventListener('change'" in html
    assert "state-strip" in html
    assert "state-chip" in html
    assert "view-strip" in html
    assert "view-chip" in html
    assert "Preview-layer-tray pass" in html
    assert "Immediate-avatar-layer-feedback pass" in html
    assert "Setup-upload-bubble pass" in html
    assert "Creation-focus pass" in html
    assert "Generated-avatar-conversation-focus pass" in html
    assert "body.has-generated-avatar .main" in html
    assert "clip-path: inset(50%)" in html
    assert "body.has-generated-avatar .status" in html
    assert "Character-control-ring pass" in html
    assert "body.has-generated-avatar .avatar-layers:not(.is-pending)" in html
    assert "position: absolute;\n        left: 50%;" in html
    assert "body.has-generated-avatar .avatar-layers:not(.is-pending) .state-chip:nth-child(8)" in html
    assert "body.has-generated-avatar .avatar-layers:not(.is-pending) .view-chip:nth-child(4)" in html
    assert "width: 52px;" in html
    assert "opacity: 0;\n        pointer-events: none;" in html
    assert ".state-chip:hover span" in html
    assert ".view-chip:focus-visible span" in html
    assert "border-radius: 999px;" in html
    assert "body.has-generated-avatar .avatar-layers:not(.is-pending) .state-chip,\n        body.has-generated-avatar .avatar-layers:not(.is-pending) .view-chip {\n          position: relative;" in html
    assert ".upload-action {\n        display: none;" in html
    assert 'id="uploadTitle">选择你的照片</strong>' in html
    assert "const uploadTitle = document.getElementById('uploadTitle');" in html
    assert "uploadTitle.textContent = file ? '照片已接住' : '选择你的照片';" in html
    assert "uploadTitle.textContent = '换一张照片';" in html
    assert "function syncConsentState()" in html
    assert "document.body.dataset.consent = consent.checked ? 'granted' : 'needed';" in html
    assert 'body.has-photo-preview[data-consent="granted"] .consent' in html
    assert ".upload-card.has-file .upload-copy span {\n        display: block;" in html
    assert ".consent {\n        width: fit-content;" in html
    assert 'class="photo-thumb" id="photoThumb" hidden' in html
    assert "const photoThumb = document.getElementById('photoThumb');" in html
    assert "function setPhotoThumb(src)" in html
    assert "function renderPendingAvatarLayers(src)" in html
    assert "preview-chip-pending" in html
    assert "renderPendingAvatarLayers(selectedPhotoPreviewUrl);" in html
    assert "setPhotoThumb(selectedPhotoPreviewUrl);" in html
    assert "setPhotoThumb('');" in html
    assert "avatarLayers.classList.add('is-pending')" in html
    assert "avatarLayers.classList.remove('is-pending')" in html
    assert 'class="avatar-layers" id="avatarLayers" hidden' in html
    assert "updateAvatarLayersVisibility" in html
    assert "avatarLayers.hidden = Boolean(stateStrip.hidden && viewStrip.hidden)" in html
    assert '<span class="avatar-layer-label">状态</span>' in html
    assert '<span class="avatar-layer-label">视角</span>' in html
    assert "viewLabels" in html
    assert "以后我在桌面上转身时，会用这组角色角度。" in html
    assert "chip.setAttribute('aria-label', `${stateLabels[state] || state}状态`)" in html
    assert "chip.setAttribute('aria-label', `${viewLabels[view] || view}视角`)" in html
    assert "playAvatarFrames(item.frames, item.src)" in html
    assert "previewAnimationTimer = window.setInterval" in html
    assert "renderViewStrip(activeManifest)" in html
    assert "chip.dataset.state = state" in html
    assert "chip.dataset.view = view" in html
    assert "orbit-nav" in html
    assert "data-step-jump=\"0\"" in html
    assert "Exploration-stage pass" in html
    assert "Transparent-avatar-stage pass" in html
    assert ".progress-row {\n        display: none !important;" in html
    assert ".desktop-frame::before {\n        display: none;" in html
    assert "Final-avatar-dialogue pass" in html
    assert ".ambient-status,\n      .progress-row,\n      .avatar-meta,\n      .mini-list {\n        display: none !important;" in html
    assert "body.has-photo-preview #nextButton" in html
    assert "body.has-photo-preview .dialogue-step .lead" in html
    assert "function setUploadPreviewPhase(phase)" in html
    assert "document.body.dataset.uploadPreview = value" in html
    assert "preview.dataset.uploadPreview = value" in html
    assert "document.body.dataset.previewMode = src ? previewMode : 'placeholder';" in html
    assert "setUploadPreviewPhase('source')" in html
    assert "setUploadPreviewPhase('empty');" in html
    assert "setUploadPreviewPhase('generating')" in html
    assert "setUploadPreviewPhase('generated')" in html
    assert "setUploadPreviewPhase('source-error')" in html
    assert "setUploadPreviewPhase('desktop')" in html
    assert 'body[data-upload-preview="source"] .desktop-frame' in html
    assert 'body[data-upload-preview="generated"] .desktop-frame' in html
    assert "@keyframes pickedPulse" in html
    assert ".avatar-card,\n      .avatar-stage,\n      .desktop-frame,\n      .summary,\n      .model-form" in html
    assert ".avatar-meta,\n      .mini-list" in html
    assert "clip: rect(0 0 0 0)" in html
    assert "'waiting_approval', 'success', 'error', 'sleep'" in html
    assert "setPreviewImage(item.src, 'avatar')" in html
    assert "setupCompleted = true" in html
    assert "Desktop-handoff pass" in html
    assert "document.body.classList.add('has-entered-desktop')" in html
    assert "window.__jiumeSetupCompleted = true" in html
    assert "桌面分身已生成；launcher 会把这个人形分身放到桌面。悬浮它先看四个入口。" in html
    assert "桌面分身已生成，正在交给 launcher 放到桌面。" in html
    assert "悬浮它，只会先展开聊天、设置、技能、进度四个入口。" in html
    assert "nextLabel.textContent = '桌面待命'" in html
    assert "先创建你的桌面分身，之后再挂 skill。" in html
    assert "本地生成可用" in html
    assert "summaryName.textContent = providerReady ? '图片模型已连接' : '本地照片生成';" in html
    assert "summaryPurpose.textContent = '四个入口';" in html
    assert "summaryName.textContent = providerReady ? '已连接' : '待连接';" not in html
    assert "summaryPurpose.textContent = '进入后设置';" not in html
    assert "未填写 API Key，将使用本地照片生成。" in html
    for retired_copy in (
        "照片可选",
        "不上传也能先用默认形象",
        "默认形象",
        "本地 mock 可用",
        "代表我处理会议",
        "API Key 是唯一必填项",
        "请输入 API Key 后继续",
    ):
        assert retired_copy not in html


def test_native_setup_window_is_step_wizard_with_preview_and_collapsed_advanced_options() -> None:
    setup_source = Path("jiume/setup/server.py").read_text(encoding="utf-8")

    assert "SETUP_WIZARD_STEPS" in setup_source
    assert "SETUP_PROGRESS_STAGES" in setup_source
    assert '"runtime": "runtime"' in setup_source
    assert '("runtime", "Agent")' in setup_source
    assert 'self.current_step = "photo"' in setup_source
    assert "self.advanced_visible = tk.BooleanVar(value=False)" in setup_source
    assert "self.photo_preview_label" in setup_source
    assert "self.generated_preview_label" in setup_source
    assert "def _set_step(self, step: str)" in setup_source
    assert "def _set_progress_stage(self, stage: str)" in setup_source
    assert "def _render_runtime_step(self)" in setup_source
    assert "def _refresh_runtime_status(self," in setup_source
    assert "def _runtime_diagnostic(self)" in setup_source
    assert "check_gateway_health(DEFAULT_GATEWAY_URL" in setup_source
    assert "runtime_diagnostic_from_health" in setup_source
    assert "def _open_runtime_config(self)" in setup_source
    assert "def _load_photo_preview(self, path: Path)" in setup_source
    assert "def _toggle_advanced_options(self)" in setup_source
    assert "Base URL / 模型（可选）" in setup_source
    assert "self.controller.create_twin_from_photo(" in setup_source
    assert "lambda s=stage, a=attempt_id: self._handle_generation_progress(a, s)" in setup_source


def test_native_setup_window_uses_premium_fixed_layout_and_synced_progress() -> None:
    setup_source = Path("jiume/setup/server.py").read_text(encoding="utf-8")

    assert "PREMIUM_SETUP_COLORS" in setup_source
    assert "SETUP_STEP_TO_STAGE" in setup_source
    assert "def _sync_progress_stage_for_step(self, step: str)" in setup_source
    assert "self._sync_progress_stage_for_step(step)" in setup_source
    assert "self._set_progress_stage(\"model\")" in setup_source
    assert "self.progress_canvas" in setup_source
    assert "self.stage_canvas" in setup_source
    assert "def _draw_progress_track(self)" in setup_source
    assert "def _draw_generation_track(self)" in setup_source
    assert "self.content_frame.grid_propagate(False)" in setup_source
    assert "self.footer_frame.grid_propagate(False)" in setup_source
    assert "sticky=\"sew\"" in setup_source
    assert "ttk.Progressbar" not in setup_source
    assert "#147d82" not in setup_source
    assert "#dce9ea" not in setup_source


def test_native_setup_window_generation_flow_has_attempt_guard_timer_and_cancel() -> None:
    setup_source = Path("jiume/setup/server.py").read_text(encoding="utf-8")

    assert "self.generation_attempt_id" in setup_source
    assert "self.generation_cancelled" in setup_source
    assert "self.generation_started_at" in setup_source
    assert "self.generation_detail = tk.StringVar" in setup_source
    assert "self.generation_failure = tk.StringVar" in setup_source
    assert "def _cancel_generation(self)" in setup_source
    assert "def _retry_generation(self)" in setup_source
    assert "def _tick_generation_timer(self, attempt_id: str)" in setup_source
    assert "def _generation_failed(self, attempt_id: str, error: BaseException | str)" in setup_source
    assert "def _generation_succeeded(self, attempt_id: str, result: dict[str, Any])" in setup_source
    assert "if attempt_id != self.generation_attempt_id or self.generation_cancelled" in setup_source
    assert "lambda e=exc" in setup_source
    assert "已取消。本次图片模型返回会被忽略。" in setup_source


def test_native_setup_buttons_avoid_platform_native_white_button_rendering() -> None:
    setup_source = Path("jiume/setup/server.py").read_text(encoding="utf-8")

    assert "def _make_button(self, parent: tk.Widget, *, text: str, command: Callable[[], None], variant: str) -> tk.Label" in setup_source
    assert "tk.Button(" not in setup_source
    assert "button.bind(\"<Button-1>\", invoke)" in setup_source
    assert "button.bind(\"<Return>\", invoke)" in setup_source
    assert "disabledforeground" in setup_source


def test_openai_avatar_prompt_keeps_jiume_human_not_pet() -> None:
    prompt = _openai_avatar_prompt({"displayName": "阿眠", "purpose": "桌面个人分身助手"})

    assert "person-shaped human desktop twin" in prompt
    assert "This is not a pet" in prompt
    assert "animal ears" in prompt
    assert "mascot" in prompt
    assert "阿眠" in prompt
    assert "桌面个人分身助手" in prompt


def test_avatar_asset_path_blocks_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    twin_root = tmp_path / "twins" / "twin_safe"
    avatar_dir = twin_root / "avatar"
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "idle.png").write_bytes(b"fake")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr("jiume.api.assets.get_twin_root", lambda twin_id: twin_root)

    path, mime = resolve_asset_path("twin_safe", "idle.png")

    assert path == avatar_dir / "idle.png"
    assert mime == "image/png"
    with pytest.raises(ValueError):
        resolve_asset_path("twin_safe", "../secret.txt")


def test_distill_job_install_enables_generated_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_root = tmp_path / "agent" / "workspace" / "skills"
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: tmp_path / "twins")
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Chen"})

    engine = PersonalDistillationEngine(store=store, twins_root=tmp_path / "twins", skills_dir=skill_root)
    job = engine.create_job(twin["id"], {"goal": "Meeting minutes", "recipe": "Summarize decisions."})
    installed = engine.install_job(twin["id"], job.id)

    skill_name = installed.generated_skill["name"]
    layers = {artifact.layer.value for artifact in installed.artifacts}
    assert installed.status.value == "installed"
    assert {"profile", "style", "procedural", "personal_skill"}.issubset(layers)
    assert (skill_root / skill_name / "SKILL.md").exists()
    assert skill_name in store.get_twin(twin["id"])["permissions"]["allowedSkillIds"]


def test_recommended_skill_catalog_is_mountable(tmp_path: Path) -> None:
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Skill Twin", "selectedSkillIds": []})

    seen: set[str] = set()
    for skill in RECOMMENDED_SKILLS:
        skill_id = skill["id"]
        assert skill_id not in seen
        seen.add(skill_id)
        assert skill["displayName"]
        assert skill["category"]

    first = RECOMMENDED_SKILLS[0]
    updated = store.enable_skill(twin["id"], first["id"])

    assert first["id"] in updated["permissions"]["allowedSkillIds"]
    assert catalog_payload()["source"].startswith("https://swarmskills.openjiuwen.com")
    assert mounted_skill_cards([first["id"]])[0]["displayName"] == first["displayName"]


def test_skill_catalog_filters_for_desktop_shelf() -> None:
    meeting = RECOMMENDED_SKILLS[0]
    rows = filter_recommended_skills(query="会议", enabled_skill_ids=[meeting["id"]])

    assert rows[0]["id"] == meeting["id"]
    assert rows[0]["isEnabled"] is True
    assert all("会议" in " ".join(str(row.get(key) or "") for key in ("displayName", "summary", "whyJiume")) for row in rows)
    assert filter_recommended_skills(query="PRD", category="产品")[0]["displayName"] == "PRD评审委员会"
    assert all(row["risk"] == "high" for row in filter_recommended_skills(risk="high"))
    assert filter_recommended_skills(query="not-a-real-jiume-skill") == []
    assert skill_categories()[0] == SKILL_FILTER_ALL
    assert "研发" in skill_categories()
    assert skill_risks()[0] == SKILL_FILTER_ALL
    assert {"low", "medium", "high"}.issubset(set(skill_risks()))


def test_local_skill_install_copies_and_mounts_for_twin(tmp_path: Path) -> None:
    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Local Skill Twin", "selectedSkillIds": []})
    source = tmp_path / "source skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: local-reviewer\n---\n# Local Reviewer\nUse for local review.\n",
        encoding="utf-8",
    )
    (source / "notes.txt").write_text("keep me", encoding="utf-8")

    source_dir, skill_md, skill_name = resolve_local_skill_source(source / "SKILL.md")
    record = install_local_skill(
        store=store,
        twin_id=twin["id"],
        source=source,
        skills_dir=tmp_path / "agent-skills",
    )

    assert source_dir == source.resolve()
    assert skill_md == (source / "SKILL.md").resolve()
    assert skill_name == "local-reviewer"
    assert record["name"] == "local-reviewer"
    assert (tmp_path / "agent-skills" / "local-reviewer" / "SKILL.md").exists()
    assert (tmp_path / "agent-skills" / "local-reviewer" / "notes.txt").read_text(encoding="utf-8") == "keep me"
    assert "local-reviewer" in store.get_twin(twin["id"])["permissions"]["allowedSkillIds"]
    custom = filter_recommended_skills(query="local-reviewer", enabled_skill_ids=["local-reviewer"])
    assert custom == [
        {
            "id": "local-reviewer",
            "displayName": "local-reviewer",
            "category": "个人",
            "risk": "unknown",
            "summary": "本地导入并挂载到 JiuMe 的个人 skill。Agent 会在本地 skills 目录中解析它。",
            "whyJiume": "这是用户给当前分身安装的本地能力。",
            "installsAllTime": 0,
            "stars": 0,
            "isEnabled": True,
            "isLocal": True,
        }
    ]


def test_gateway_context_includes_mounted_skill_cards() -> None:
    store = TwinStore()
    meeting = RECOMMENDED_SKILLS[0]
    twin = store.create_twin(
        {
            "displayName": "Ada",
            "selectedSkillIds": [meeting["id"], "custom-review"],
            "memories": ["喜欢中文简洁回复"],
        }
    )
    msg = SimpleNamespace(
        params={"content": "帮我整理会议纪要", "twin_id": twin["id"]},
        metadata={"method": "chat.send"},
        session_id="sess-1",
    )

    enriched = enrich_gateway_message(msg)

    content = enriched.params["content"]
    assert "[JiuMe Twin Context]" in content
    assert meeting["displayName"] in content
    assert meeting["summary"] in content
    assert "custom-review" in content
    assert "Long-term memories" in content
    assert "喜欢中文简洁回复" in content
    assert content.endswith("帮我整理会议纪要")
    assert enriched.metadata["jiume_twin_id"] == twin["id"]


def test_desktop_skill_task_prompt_names_active_skill() -> None:
    skill = RECOMMENDED_SKILLS[0]

    prompt = JiuMeDesktopAvatar._skill_task_prompt(skill)
    followup = _active_skill_followup_message("这是后续材料", skill)
    snapshot = _active_skill_snapshot(skill)
    summary = _active_skill_summary(skill)

    assert skill["displayName"] in prompt
    assert skill["summary"] in prompt
    assert "mounted JiuMe skill" in prompt
    assert snapshot is not None
    assert snapshot["id"] == skill["id"]
    assert _active_skill_badge_label(skill) == "会议"
    assert _active_skill_badge_label({"id": "local-reviewer", "displayName": "local-reviewer"}) == "LR"
    assert _active_skill_badge_label(None) == ""
    assert skill["displayName"] in followup
    assert "这是后续材料" in followup
    assert "active mounted JiuMe skill" in followup
    assert _active_skill_followup_message("plain", None) == "plain"
    assert summary["hasSkill"] is True
    assert skill["displayName"] in summary["label"]
    assert "屏幕、剪贴板或文件" in summary["detail"]
    assert _active_skill_summary(None)["hasSkill"] is False


def test_native_active_skill_query_answers_what_jiume_is_holding() -> None:
    assert _native_active_skill_query_command("当前 skill 是什么") is True
    assert _native_active_skill_query_command("你现在拿着哪个 skill") is True
    assert _native_active_skill_query_command("which skill is active?") is True
    assert _native_active_skill_query_command("打开技能货架") is False
    assert _native_active_skill_query_command("取消当前 skill") is False
    assert _native_active_skill_query_command("帮我选一个 skill") is False
    assert _native_active_skill_query_command("帮我写一个 current skill UI") is False


def test_native_material_commands_route_person_like_requests() -> None:
    assert _native_material_command("你看一下屏幕，帮我总结弹窗") == "screen"
    assert _native_material_command("贴一下剪贴板里的材料") == "clipboard"
    assert _native_material_command("我想选择文件给你") == "file"
    assert _native_material_command("普通任务继续聊") is None
    assert _message_with_material_instruction("请处理材料", "帮我找风险") == "请处理材料\n\n用户补充：帮我找风险"
    assert _message_with_material_instruction("请处理材料", "") == "请处理材料"


def test_native_interaction_commands_route_playful_requests() -> None:
    assert _native_interaction_command("挥挥手") == "wave"
    assert _native_interaction_command("拍拍肩") == "pat"
    assert _native_interaction_command("摸摸头") == "pat"
    assert _native_interaction_command("给我打气") == "cheer"
    assert _native_interaction_command("点点头") == "nod"
    assert _native_interaction_command("伸个懒腰") == "stretch"
    assert _native_interaction_command("一起深呼吸") == "breathe"
    assert _native_interaction_command("探头看看") == "peek"
    assert _native_interaction_command("开心一下") == "dance"
    assert _native_interaction_command("给我比个心") == "heart"
    assert _native_interaction_command("陪我一下") == "companion"
    assert _native_interaction_command("你先安静休息") == "rest"
    assert _native_interaction_command("帮我整理会议纪要") is None


def test_native_wake_command_only_handles_short_personal_wake_lines() -> None:
    assert _native_wake_command("醒醒") is True
    assert _native_wake_command("小九醒醒，回来一下") is True
    assert _native_wake_command("wake up") is True
    assert _native_wake_command("come back") is True
    assert _native_wake_command("你醒着吗") is False
    assert _native_wake_command("回来帮我整理会议纪要") is False
    assert _native_wake_command("帮我写 wake word feature") is False


def test_native_attention_command_answers_short_name_calls_locally() -> None:
    assert _native_attention_command("JiuMe") is True
    assert _native_attention_command("hey JiuMe") is True
    assert _native_attention_command("Xiaojiu") is True
    assert _native_attention_command("小九") is True
    assert _native_attention_command("小九醒醒，回来一下") is True
    assert _attention_name_aliases(["Ada JiuMe", "阿眠"]) == ("adajiume", "ada", "阿眠")
    assert _native_attention_command("阿眠", names=["阿眠"]) is True
    assert _native_attention_command("嘿阿眠", names=["阿眠"]) is True
    assert _native_attention_command("Ada", names=["Ada JiuMe"]) is True
    assert _native_attention_command("JiuMe 是什么") is False
    assert _native_attention_command("JiuMe 帮我整理会议纪要") is False
    assert _native_attention_command("阿眠帮我整理会议纪要", names=["阿眠"]) is False
    assert _native_attention_command("帮我写 hey JiuMe feature") is False

    plain = _attention_summary()
    skilled = _attention_summary({"id": "meeting", "displayName": "会议纪要精炼"})
    assert plain["label"] == "我在"
    assert plain["actions"] == ["说一句", "交给 Agent"]
    assert "就在桌面上" in plain["detail"]
    assert "点头像后直接说一句" in plain["detail"]
    assert skilled["actions"] == ["补一句", "继续处理"]
    assert "会议纪要精炼" in skilled["detail"]
    assert "点头像后直接补一句" in skilled["detail"]
    daily_attention_copy = " ".join(
        [str(plain["detail"]), *plain["actions"], str(skilled["detail"]), *skilled["actions"]]
    )
    for label in DAILY_FORBIDDEN_LABELS:
        assert label not in daily_attention_copy


def test_legacy_rps_helper_remains_compatibility_only_not_daily_entry() -> None:
    assert _native_rps_command("猜拳") == {"action": "start", "move": ""}
    assert _native_rps_command("石头剪刀布") == {"action": "start", "move": ""}
    assert _native_rps_command("我出石头") == {"action": "play", "move": "rock"}
    assert _native_rps_command("出剪刀") == {"action": "play", "move": "scissors"}
    assert _native_rps_command("我出布") == {"action": "play", "move": "paper"}
    assert _native_rps_command("帮我布置会议任务") is None

    user_win = _rps_round("rock", "scissors")
    jiume_win = _rps_round("paper", "scissors")
    draw = _rps_round("paper", "paper")

    assert user_win["result"] == "user_win"
    assert user_win["effect"] == "cheer"
    assert jiume_win["result"] == "jiume_win"
    assert jiume_win["effect"] == "dance"
    assert draw["result"] == "draw"
    assert draw["effect"] == "nod"


def test_legacy_dice_helper_remains_compatibility_only_not_daily_entry() -> None:
    assert _native_dice_command("掷骰子") == {"sides": 6}
    assert _native_dice_command("摇一个 20 面骰") == {"sides": 20}
    assert _native_dice_command("roll d12") == {"sides": 12}
    assert _native_dice_command("帮我设计一个骰子功能") is None

    normal = _dice_roll(6, seed=2)
    max_roll = _dice_roll(6, seed=5)
    min_roll = _dice_roll(6, seed=0)

    assert normal["result"] == 3
    assert normal["effect"] == "cheer"
    assert max_roll["result"] == 6
    assert max_roll["effect"] == "dance"
    assert min_roll["result"] == 1
    assert min_roll["effect"] == "nod"


def test_legacy_coin_helper_remains_compatibility_only_not_daily_entry() -> None:
    assert _native_coin_command("抛硬币") == {"mode": "coin"}
    assert _native_coin_command("flip a coin") == {"mode": "coin"}
    assert _native_coin_command("抽一签") == {"mode": "draw"}
    assert _native_coin_command("今日签") == {"mode": "draw"}
    assert _native_coin_command("帮我写一个 coin flip feature") is None

    heads = _coin_flip("coin", seed=0)
    tails = _coin_flip("coin", seed=1)
    draw = _coin_flip("draw", seed=0)

    assert heads["result"] == "正面"
    assert heads["effect"] == "cheer"
    assert tails["result"] == "反面"
    assert tails["effect"] == "nod"
    assert draw["mode"] == "draw"
    assert "向前一步" in draw["line"]


def test_native_companion_command_controls_idle_presence_without_stealing_task_or_rest() -> None:
    assert _native_companion_command("你先安静守着") == "quiet"
    assert _native_companion_command("别主动说话，少打扰") == "quiet"
    assert _native_companion_command("恢复陪伴，主动一点") == "resume"
    assert _native_companion_command("check in again") == "resume"
    assert _native_companion_command("安静跑") is None
    assert _native_companion_command("你先安静休息") is None
    assert _native_companion_command("帮我整理会议纪要") is None


def test_native_focus_command_starts_local_desktop_focus_sessions() -> None:
    assert _native_focus_command("陪我专注15分钟") == {"action": "start", "minutes": 15}
    assert _native_focus_command("开始番茄钟") == {"action": "start", "minutes": 25}
    assert _native_focus_command("focus with me for 45 minutes") == {"action": "start", "minutes": 45}
    assert _native_focus_command("专注还剩多久") == {"action": "status", "minutes": 0}
    assert _native_focus_command("结束专注") == {"action": "stop", "minutes": 0}
    assert _native_focus_command("帮我整理会议纪要") is None
    assert _focus_minutes_from_text("专注2分钟") == 5
    assert _focus_minutes_from_text("专注120分钟") == 90
    assert _focus_minutes_from_text("半小时专注") == 30


def test_native_control_commands_open_desktop_surfaces() -> None:
    assert _native_control_command("打开对话") == "direct_chat"
    assert _native_control_command("我想和你聊聊") == "direct_chat"
    assert _native_control_command("talk to you") == "direct_chat"
    assert _native_control_command("到前面来") == "front"
    assert _native_control_command("别被挡住") == "front"
    assert _native_control_command("stay on top") == "front"
    assert _native_control_command("打开设置") == "settings"
    assert _native_control_command("打开技能货架") == "skills"
    assert _native_control_command("看进度") == "progress"
    assert _native_control_command("后台状态怎么样") == "status"
    assert _native_control_command("取消当前 skill") == "clear_skill"
    assert _native_control_command("收起面板") == "tuck"
    assert _native_control_command("只留头像") == "tuck"
    assert _native_control_command("hide panels") == "tuck"
    assert _native_tuck_command("帮我把旁边收起来") is True
    assert _native_tuck_command("你先休息安静一下") is False
    assert _native_tuck_command("帮我写一个收起面板功能") is False
    assert _native_control_command("登录后自动出现") == "login_install"
    assert _native_control_command("关闭开机自启") == "login_uninstall"
    assert _native_control_command("登录启动状态") == "login_status"
    assert _native_login_item_command("enable login item") == "install"
    assert _native_login_item_command("帮我整理会议纪要") is None
    assert _native_control_command("帮我整理会议纪要") is None
    assert _native_control_command("帮我写一个聊天 UI") is None
    assert _native_control_command("帮我实现 stay on top 功能") is None


def test_native_help_command_answers_capabilities_without_stealing_tasks() -> None:
    assert _native_help_command("你会什么") is True
    assert _native_help_command("怎么用你") is True
    assert _native_help_command("what can you do?") is True
    assert _native_help_command("help") is True
    assert _native_help_command("帮我整理会议纪要") is False
    assert _native_help_command("help me write a PRD") is False
    assert _native_help_command("后台状态怎么样") is False

    summary = _help_summary()
    assert summary["label"] == "直接跟我说就行"
    assert summary["entries"] == ["聊天", "设置", "技能", "进度"]
    assert "右键菜单打开" in summary["detail"]
    assert "聊天、设置、技能、进度" not in summary["detail"]
    assert "只展开那一层" not in summary["detail"]
    assert "屏幕、剪贴板或文件" not in summary["detail"]
    assert "透明度" not in summary["detail"]
    assert "猜拳" not in summary["detail"]
    assert "骰子" not in summary["detail"]
    assert "抽签" not in summary["detail"]


def test_native_identity_command_keeps_jiume_a_human_desktop_twin() -> None:
    assert _native_identity_command("你是谁") is True
    assert _native_identity_command("JiuMe 是什么") is True
    assert _native_identity_command("你是宠物吗") is True
    assert _native_identity_command("are you a pet?") is True
    assert _native_identity_command("你是什么状态") is False
    assert _native_identity_command("帮我设计一个桌面宠物 app") is False
    assert _native_identity_command("帮我写一段你是谁的介绍") is False

    summary = _identity_summary()
    named = _identity_summary("阿眠")
    assert "桌面个人分身" in summary["label"]
    assert named["label"] == "我是阿眠，你的桌面个人分身"
    assert "人形分身「阿眠」" in named["detail"]
    assert "JiuMe 是这套桌面分身能力的名字" in named["detail"]
    assert "不是宠物" in summary["detail"]
    assert "Agent" in summary["detail"]
    assert summary["badges"] == ["人形分身", "Agent 主入口", "常驻桌面"]


def test_identity_question_uses_gateway_when_agent_is_available() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    sent: list[dict[str, Any]] = []
    chat: list[tuple[str, str]] = []
    activity: list[tuple[str, str, str]] = []
    bubbles: list[str] = []
    last_action: list[str] = []

    class FakeGateway:
        def send_chat(self, content: str, *, twin_id: str | None, on_event: Callable[[GatewayEvent], None]) -> str:
            sent.append({"content": content, "twin_id": twin_id, "on_event": on_event})
            return "req-1"

    avatar.gateway = FakeGateway()
    avatar._pending_approval = None
    avatar._state = "idle"
    avatar._active_skill_context = None
    avatar._active_twin_id = "twin_1"
    avatar._activity_items = []
    avatar._gateway_reply = "stale"
    avatar._stream_chat_index = 3
    avatar._active_attention_names = lambda: []
    avatar._enabled_skill_ids = lambda: []
    avatar._active_twin = lambda: {
        "displayName": "阿眠",
        "purpose": "桌面个人分身助手",
        "tone": "温和",
    }
    avatar._last_action = SimpleNamespace(set=lambda value: last_action.append(value))
    avatar._append_chat = lambda role, text: chat.append((role, text))
    avatar._record_activity = lambda kind, title, detail, *args: activity.append((kind, title, detail))
    avatar.show_bubble = lambda text, **kwargs: bubbles.append(text)

    JiuMeDesktopAvatar._send_text_message(avatar, "你是谁")

    assert len(sent) == 1
    assert sent[0]["twin_id"] == "twin_1"
    assert "JiuMe desktop personal twin context" in sent[0]["content"]
    assert "Active twin name: 阿眠" in sent[0]["content"]
    assert "User original message:" in sent[0]["content"]
    assert "你是谁" in sent[0]["content"]
    assert "Do not introduce yourself as JiuwenSwarm" in sent[0]["content"]
    assert "Do not mention the current time" in sent[0]["content"]
    assert "Do not mention model names" in sent[0]["content"]
    assert chat == [("user", "你是谁")]
    assert activity == [("user", "发起任务", "你是谁")]
    assert avatar._gateway_reply == ""
    assert avatar._stream_chat_index is None
    assert avatar._gateway_request_id == "req-1"
    assert "你说：你是谁" in last_action
    assert avatar._one_line_capsule.mode == "working"
    assert avatar._one_line_capsule.primary_text == "在想"
    assert bubbles == ["在想"]


def test_conversational_queries_use_gateway_instead_of_local_canned_replies() -> None:
    prompts = [
        "你能做什么",
        "你现在怎么样",
        "你还记得什么",
        "你今天怎么陪我",
        "当前 skill",
        "当前设置",
        "小九",
    ]

    for prompt in prompts:
        avatar = object.__new__(JiuMeDesktopAvatar)
        sent: list[dict[str, Any]] = []
        chat: list[tuple[str, str]] = []
        activity: list[tuple[str, str, str]] = []

        class FakeGateway:
            def send_chat(
                self,
                content: str,
                *,
                twin_id: str | None,
                on_event: Callable[[GatewayEvent], None],
            ) -> str:
                sent.append({"content": content, "twin_id": twin_id, "on_event": on_event})
                return "req-1"

        avatar.gateway = FakeGateway()
        avatar._pending_approval = None
        avatar._state = "idle"
        avatar._active_skill_context = None
        avatar._active_twin_id = "twin_1"
        avatar._activity_items = []
        avatar._gateway_reply = "stale"
        avatar._stream_chat_index = 3
        avatar._direct_help_section = "overview"
        avatar._direct_skill_section = "recommended"
        avatar._direct_skills_detail_visible = False
        avatar._direct_companion_visible = False
        avatar._direct_companion_more_visible = False
        avatar.size = 128
        avatar._active_attention_names = lambda: ["小九"]
        avatar._enabled_skill_ids = lambda: []
        avatar._active_twin = lambda: {
            "displayName": "JiuMe",
            "purpose": "桌面个人分身助手",
            "tone": "温和",
        }
        avatar._current_presence_summary = lambda: {"label": "在桌面待命", "detail": "我在。", "mood": "idle"}
        avatar._current_memory_summary = lambda: {"label": "刚开始认识", "detail": "还没有新的上下文。"}
        avatar._last_action = SimpleNamespace(set=lambda _value: None)
        avatar._append_chat = lambda role, text: chat.append((role, text))
        avatar._record_activity = lambda kind, title, detail, *args: activity.append((kind, title, detail))
        avatar.show_bubble = lambda *_args, **_kwargs: None
        avatar._rebuild_direct_companion_card = lambda: None
        avatar._show_direct_help_card = lambda: None
        avatar._rebuild_direct_skill_shortcuts = lambda: None
        avatar._start_interaction_effect = lambda _effect: None

        JiuMeDesktopAvatar._send_text_message(avatar, prompt)

        assert len(sent) == 1
        assert sent[0]["twin_id"] == "twin_1"
        assert "JiuMe desktop personal twin context" in sent[0]["content"]
        assert "User original message:" in sent[0]["content"]
        assert prompt in sent[0]["content"]
        assert "Do not introduce yourself as JiuwenSwarm" in sent[0]["content"]
        assert "Do not mention the current time" in sent[0]["content"]
        assert "Do not mention model names" in sent[0]["content"]
        assert chat == [("user", prompt)]
        assert activity == [("user", "发起任务", prompt)]
        assert avatar._gateway_reply == ""
        assert avatar._stream_chat_index is None


def test_typed_desktop_commands_are_sent_to_gateway_not_local_actions() -> None:
    prompts = [
        "打开设置",
        "看进度",
        "后台状态怎么样",
        "取消当前 skill",
        "透明一点",
        "陪我专注一下",
        "重画一下你",
        "用数据分析 skill",
        "剪贴板",
        "猜拳",
        "掷骰子",
        "抽签",
        "清空对话",
        "收起面板",
    ]

    for prompt in prompts:
        avatar = object.__new__(JiuMeDesktopAvatar)
        sent: list[dict[str, Any]] = []
        chat: list[tuple[str, str]] = []
        local_calls: list[str] = []

        class FakeGateway:
            def send_chat(
                self,
                content: str,
                *,
                twin_id: str | None,
                on_event: Callable[[GatewayEvent], None],
            ) -> str:
                sent.append({"content": content, "twin_id": twin_id, "on_event": on_event})
                return "req-1"

        avatar.gateway = FakeGateway()
        avatar._pending_approval = None
        avatar._state = "idle"
        avatar._active_skill_context = None
        avatar._active_twin_id = "twin_1"
        avatar._activity_items = []
        avatar._gateway_reply = ""
        avatar._stream_chat_index = None
        avatar._active_attention_names = lambda: []
        avatar._enabled_skill_ids = lambda: []
        avatar._active_twin = lambda: {"displayName": "JiuMe"}
        avatar._last_action = SimpleNamespace(set=lambda _value: None)
        avatar._append_chat = lambda role, text: chat.append((role, text))
        avatar._record_activity = lambda *_args, **_kwargs: None
        avatar.show_bubble = lambda *_args, **_kwargs: None

        avatar.open_settings = lambda: local_calls.append("open_settings")  # type: ignore[method-assign]
        avatar._run_native_control_command = lambda command, raw="": local_calls.append(f"control:{command}")  # type: ignore[method-assign]
        avatar._run_native_opacity_command = lambda command: local_calls.append(f"opacity:{command}")  # type: ignore[method-assign]
        avatar._run_native_focus_command = lambda command, raw="": local_calls.append("focus")  # type: ignore[method-assign]
        avatar._run_avatar_makeover_command = lambda command: local_calls.append("makeover")  # type: ignore[method-assign]
        avatar._run_native_skill_command = lambda command, raw="": local_calls.append("skill")  # type: ignore[method-assign]
        avatar._send_clipboard_material_from_direct = lambda raw="": local_calls.append("clipboard")  # type: ignore[method-assign]
        avatar._run_native_rps_command = lambda command: local_calls.append("rps")  # type: ignore[method-assign]
        avatar._run_native_dice_command = lambda command: local_calls.append("dice")  # type: ignore[method-assign]
        avatar._run_native_coin_command = lambda command: local_calls.append("coin")  # type: ignore[method-assign]
        avatar._clear_native_chat_thread = lambda raw="": local_calls.append("clear")  # type: ignore[method-assign]
        avatar._tuck_avatar_surfaces = lambda: local_calls.append("tuck")  # type: ignore[method-assign]

        JiuMeDesktopAvatar._send_text_message(avatar, prompt)

        assert len(sent) == 1, prompt
        assert prompt in sent[0]["content"]
        assert chat == [("user", prompt)]
        assert local_calls == []


def test_duplicate_text_submit_while_gateway_request_active_is_ignored() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    sent: list[dict[str, Any]] = []
    chat: list[tuple[str, str]] = []
    activity: list[tuple[str, str, str]] = []
    bubbles: list[str] = []
    last_action: list[str] = []

    class FakeGateway:
        def send_chat(self, content: str, *, twin_id: str | None, on_event: Callable[[GatewayEvent], None]) -> str:
            sent.append({"content": content, "twin_id": twin_id, "on_event": on_event})
            return f"req-{len(sent)}"

    avatar.gateway = FakeGateway()
    avatar._pending_approval = None
    avatar._state = "idle"
    avatar._active_skill_context = None
    avatar._active_twin_id = "twin_1"
    avatar._activity_items = []
    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._active_attention_names = lambda: []
    avatar._enabled_skill_ids = lambda: []
    avatar._active_twin = lambda: {"displayName": "JiuMe"}
    avatar._last_action = SimpleNamespace(set=lambda value: last_action.append(value))
    avatar._append_chat = lambda role, text: chat.append((role, text))
    avatar._record_activity = lambda kind, title, detail, *args: activity.append((kind, title, detail))
    avatar.show_bubble = lambda text, **kwargs: bubbles.append(text)

    JiuMeDesktopAvatar._send_text_message(avatar, "你是谁")
    JiuMeDesktopAvatar._send_text_message(avatar, "你是谁")

    assert len(sent) == 1
    assert chat == [("user", "你是谁")]
    assert activity[0] == ("user", "发起任务", "你是谁")
    assert activity[-1] == ("processing", "正在回复", "你是谁")
    assert last_action[-1] == "上一条消息还在回复。"
    assert bubbles[-1] == "上一条消息还在回复。"


def test_gateway_final_clears_active_request_guard() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    sent: list[dict[str, Any]] = []

    class FakeGateway:
        def send_chat(self, content: str, *, twin_id: str | None, on_event: Callable[[GatewayEvent], None]) -> str:
            sent.append({"content": content, "twin_id": twin_id, "on_event": on_event})
            return f"req-{len(sent)}"

    class FakeRoot:
        def after(self, _delay: int, callback: Callable[[], Any]) -> str:
            callback()
            return "after-1"

    avatar.gateway = FakeGateway()
    avatar.root = FakeRoot()
    avatar._pending_approval = None
    avatar._state = "idle"
    avatar._active_skill_context = None
    avatar._active_twin_id = "twin_1"
    avatar._activity_items = []
    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._active_attention_names = lambda: []
    avatar._enabled_skill_ids = lambda: []
    avatar._active_twin = lambda: {"displayName": "JiuMe"}
    avatar._last_action = SimpleNamespace(set=lambda _value: None)
    avatar._append_chat = lambda *_args, **_kwargs: None
    avatar._record_activity = lambda *_args, **_kwargs: None
    avatar.show_bubble = lambda *_args, **_kwargs: None
    avatar._finish_assistant_stream = lambda *_args, **_kwargs: None
    avatar.set_state = lambda _state: None

    JiuMeDesktopAvatar._send_text_message(avatar, "你是谁")
    assert avatar._gateway_request_id == "req-1"

    JiuMeDesktopAvatar._handle_gateway_event(
        avatar,
        sent[0]["content"],
        GatewayEvent(kind="event", event="chat.final", payload={"content": "我是 JiuMe。"}),
    )
    assert avatar._gateway_request_id is None

    JiuMeDesktopAvatar._send_text_message(avatar, "继续")
    assert len(sent) == 2
    assert avatar._gateway_request_id == "req-2"


def test_identity_question_does_not_use_local_fallback_when_agent_is_unavailable() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    chat: list[tuple[str, str]] = []
    activity: list[tuple[str, str, str]] = []
    bubbles: list[str] = []
    states: list[str] = []
    typed: list[str] = []

    class FakeRoot:
        def after(self, _delay: int, callback: Callable[[], Any]) -> str:
            callback()
            return "after-1"

    avatar.gateway = None
    avatar.root = FakeRoot()
    avatar._pending_approval = None
    avatar._state = "idle"
    avatar._active_skill_context = None
    avatar._active_twin_id = "twin_1"
    avatar._activity_items = []
    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._active_attention_names = lambda: []
    avatar._enabled_skill_ids = lambda: []
    avatar._last_action = SimpleNamespace(set=lambda _value: None)
    avatar._append_chat = lambda role, text: chat.append((role, text))
    avatar._record_activity = lambda kind, title, detail, *args: activity.append((kind, title, detail))
    avatar.show_bubble = lambda text, **_kwargs: bubbles.append(text)
    avatar.set_state = lambda state: states.append(state)
    avatar._start_typing_reply = lambda message: typed.append(message)
    avatar._start_interaction_effect = lambda _effect: None
    avatar._rebuild_direct_companion_card = lambda: None
    avatar._chat_assistant_name = lambda: "JiuMe"

    JiuMeDesktopAvatar._send_text_message(avatar, "你是谁")

    assert chat == [("user", "你是谁")]
    assert typed == []
    assert any(kind == "error" for kind, _title, _detail in activity)
    assert bubbles[-1] == "没有收到后端回复，未生成本地兜底。"
    assert states[-1] == "idle"


def test_offline_chat_does_not_generate_local_canned_assistant_reply() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    chat: list[tuple[str, str]] = []
    activity: list[tuple[str, str, str]] = []
    typed: list[str] = []

    class FakeRoot:
        def after(self, _delay: int, callback: Callable[[], Any]) -> str:
            callback()
            return "after-1"

    avatar.gateway = None
    avatar.root = FakeRoot()
    avatar._pending_approval = None
    avatar._state = "idle"
    avatar._active_skill_context = None
    avatar._active_twin_id = "twin_1"
    avatar._activity_items = []
    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._active_attention_names = lambda: []
    avatar._enabled_skill_ids = lambda: []
    avatar._last_action = SimpleNamespace(set=lambda _value: None)
    avatar._append_chat = lambda role, text: chat.append((role, text))
    avatar._record_activity = lambda kind, title, detail, *args: activity.append((kind, title, detail))
    avatar.show_bubble = lambda *_args, **_kwargs: None
    avatar.set_state = lambda _state: None
    avatar._start_typing_reply = lambda message: typed.append(message)

    JiuMeDesktopAvatar._send_text_message(avatar, "普通聊天")

    assert chat == [("user", "普通聊天")]
    assert typed == []
    assert activity[-1] == ("error", "后端无回复", "没有收到后端回复，未生成本地兜底。")


def test_gateway_error_does_not_start_local_canned_reply() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    activity: list[tuple[str, str, str]] = []
    finished: list[tuple[str, str]] = []
    typed: list[str] = []

    class FakeRoot:
        def after(self, _delay: int, callback: Callable[[], Any]) -> str:
            callback()
            return "after-1"

    avatar.root = FakeRoot()
    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._last_action = SimpleNamespace(set=lambda _value: None)
    avatar.set_state = lambda _state: None
    avatar._record_activity = lambda kind, title, detail, *args: activity.append((kind, title, detail))
    avatar._finish_assistant_stream = lambda text, *, state="": finished.append((text, state))
    avatar.show_bubble = lambda *_args, **_kwargs: None
    avatar._start_typing_reply = lambda message: typed.append(message)

    JiuMeDesktopAvatar._handle_gateway_event(
        avatar,
        "普通聊天",
        GatewayEvent(kind="error", error="boom"),
    )

    assert activity == [("error", "执行受阻", "boom")]
    assert finished == [("boom", "error")]
    assert typed == []


def test_gateway_final_uses_short_done_capsule_instead_of_full_stream_bubble() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    bubbles: list[tuple[str, dict[str, Any]]] = []
    recorded: list[tuple[str, str, str]] = []
    finished: list[tuple[str, str]] = []
    states: list[str] = []

    avatar._gateway_reply = "这是一个非常长的完整回答，包含很多步骤和解释，不应该直接出现在日常气泡里。"
    avatar._stream_chat_index = 1
    avatar._gateway_request_id = "req-1"
    avatar._gateway_request_message = "帮我整理报告"
    avatar._last_action = SimpleNamespace(set=lambda _value: None)
    avatar._native_direct_chat_visible = False
    avatar._one_line_capsule = None
    avatar._one_line_capsule_timer = None
    avatar._one_line_question_active = False
    avatar.root = SimpleNamespace(after=lambda _delay, callback: "after-1", after_cancel=lambda _timer: None)
    avatar.set_state = lambda state: states.append(state)
    avatar._record_activity = lambda kind, title, detail="", artifacts=None: recorded.append((kind, title, detail))
    avatar._finish_assistant_stream = lambda text, *, state="": finished.append((text, state))
    avatar.show_bubble = lambda text, **kwargs: bubbles.append((text, kwargs))

    final_text = "这是一个非常长的完整回答，包含很多步骤和解释，不应该直接出现在日常气泡里。"
    JiuMeDesktopAvatar._handle_gateway_event(
        avatar,
        "帮我整理报告",
        GatewayEvent(kind="event", event="chat.final", payload={"content": final_text}),
    )

    assert avatar._one_line_capsule.mode == "done"
    assert avatar._one_line_capsule.summary
    assert len(avatar._one_line_capsule.summary) <= 28
    assert final_text not in [text for text, _kwargs in bubbles]
    assert bubbles[-1][0] == avatar._one_line_capsule.summary
    assert bubbles[-1][1]["state"] == "speaking"
    assert bubbles[-1][1]["duration"] == 4200
    assert finished == [(final_text, "success")]
    assert avatar._gateway_request_id is None


def test_gateway_question_opens_one_question_capsule_not_approval_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    chat: list[tuple[str, str]] = []
    bubbles: list[tuple[str, dict[str, Any]]] = []
    opened: list[str] = []
    direct_cards: list[str] = []
    panel_cards: list[str] = []
    last_action: list[str] = []

    class FakeStringVar:
        def __init__(self, value: str = "") -> None:
            self.value = value

        def get(self) -> str:
            return self.value

    avatar._pending_approval = None
    avatar._one_line_capsule = None
    avatar._one_line_capsule_timer = None
    avatar._one_line_question_active = False
    avatar.root = SimpleNamespace(after=lambda _delay, callback: "after-1", after_cancel=lambda _timer: None)
    avatar._append_chat = lambda role, text: chat.append((role, text))
    avatar._last_action = SimpleNamespace(set=lambda value: last_action.append(value))
    avatar.show_bubble = lambda text, **kwargs: bubbles.append((text, kwargs))
    avatar.open_direct_chat = lambda: opened.append("open")  # type: ignore[method-assign]
    avatar._rebuild_direct_approval_card = lambda: direct_cards.append("direct")  # type: ignore[method-assign]
    avatar._rebuild_approval_card = lambda: panel_cards.append("panel")  # type: ignore[method-assign]
    avatar._direct_chat = SimpleNamespace(winfo_exists=lambda: True)
    avatar._panel = SimpleNamespace(winfo_exists=lambda: True)
    monkeypatch.setattr(desktop_app.tk, "StringVar", FakeStringVar)

    JiuMeDesktopAvatar._set_pending_approval(
        avatar,
        {
            "request_id": "ask-1",
            "source": "permission_interrupt",
            "questions": [{"question": "允许我继续整理这些文件吗？"}],
        },
    )

    assert avatar._pending_approval["request_id"] == "ask-1"
    assert avatar._one_line_capsule.mode == "need_user"
    assert avatar._one_line_capsule.question == "允许我继续整理这些文件吗？"
    assert [action.label for action in avatar._one_line_capsule.actions] == ["好的", "取消"]
    assert opened == ["open"]
    assert direct_cards == []
    assert panel_cards == []
    assert chat == [("assistant", "需要你确认下一步：允许我继续整理这些文件吗？")]
    assert last_action == ["需要确认：允许我继续整理这些文件吗？"]
    assert bubbles[-1][0] == "允许我继续整理这些文件吗？"
    assert bubbles[-1][1]["state"] == "waiting_approval"


def test_gateway_delta_shows_short_working_capsule_not_full_assistant_reply() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    bubbles: list[tuple[str, dict[str, Any]]] = []
    activity: list[tuple[str, str, str]] = []
    chat_updates: list[str] = []

    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._last_action = SimpleNamespace(set=lambda _value: None)
    avatar._one_line_capsule = None
    avatar._one_line_capsule_timer = None
    avatar._one_line_question_active = False
    avatar.root = SimpleNamespace(after=lambda _delay, callback: "after-1", after_cancel=lambda _timer: None)
    avatar.set_state = lambda _state: None
    avatar._record_activity = lambda kind, title, detail="", artifacts=None: activity.append((kind, title, detail))
    avatar._upsert_assistant_chat = lambda text: chat_updates.append(text)
    avatar.show_bubble = lambda text, **kwargs: bubbles.append((text, kwargs))

    first = "我已经读完了材料，下面会给你一个很长很长的总结。"
    second = "这里继续补充更多完整内容，但日常气泡不能展示这些全文。"
    JiuMeDesktopAvatar._handle_gateway_event(
        avatar,
        "帮我整理报告",
        GatewayEvent(kind="event", event="chat.delta", payload={"content": first}),
    )
    JiuMeDesktopAvatar._handle_gateway_event(
        avatar,
        "帮我整理报告",
        GatewayEvent(kind="event", event="chat.delta", payload={"content": second}),
    )

    assert avatar._gateway_reply == first + second
    assert chat_updates[-1] == first + second
    assert all(text == "快好了" for text, _kwargs in bubbles)
    assert first not in [text for text, _kwargs in bubbles]
    assert second not in [text for text, _kwargs in bubbles]
    assert avatar._one_line_capsule.mode == "working"
    assert avatar._one_line_capsule.short_status == "快好了"


def test_gateway_error_uses_infra_safe_failed_capsule() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    bubbles: list[tuple[str, dict[str, Any]]] = []
    finished: list[tuple[str, str]] = []
    activity: list[tuple[str, str, str]] = []
    states: list[str] = []

    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._gateway_request_id = "req-1"
    avatar._gateway_request_message = "帮我整理报告"
    avatar._last_action = SimpleNamespace(set=lambda _value: None)
    avatar._native_direct_chat_visible = False
    avatar._one_line_capsule = None
    avatar._one_line_capsule_timer = None
    avatar._one_line_question_active = False
    avatar.root = SimpleNamespace(after=lambda _delay, callback: "after-1", after_cancel=lambda _timer: None)
    avatar.set_state = lambda state: states.append(state)
    avatar._record_activity = lambda kind, title, detail="", artifacts=None: activity.append((kind, title, detail))
    avatar._finish_assistant_stream = lambda text, *, state="": finished.append((text, state))
    avatar.show_bubble = lambda text, **kwargs: bubbles.append((text, kwargs))

    JiuMeDesktopAvatar._handle_gateway_event(
        avatar,
        "帮我整理报告",
        GatewayEvent(kind="error", error="Gateway websocket request_id ask-1 failed"),
    )

    assert avatar._one_line_capsule.mode == "done"
    assert avatar._one_line_capsule.summary == "这件事现在还不能继续。"
    assert bubbles[-1][0] == "这件事现在还不能继续。"
    assert "Gateway" not in bubbles[-1][0]
    assert "request_id" not in bubbles[-1][0]
    assert bubbles[-1][1]["state"] == "speaking"
    assert bubbles[-1][1]["duration"] == 3600
    assert finished == [("Gateway websocket request_id ask-1 failed", "error")]


def test_gateway_failed_subtask_update_uses_failed_capsule() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    bubbles: list[tuple[str, dict[str, Any]]] = []
    activity: list[tuple[str, str, str]] = []

    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._last_action = SimpleNamespace(set=lambda _value: None)
    avatar._one_line_capsule = None
    avatar._one_line_capsule_timer = None
    avatar._one_line_question_active = False
    avatar.root = SimpleNamespace(after=lambda _delay, callback: "after-1", after_cancel=lambda _timer: None)
    avatar.set_state = lambda _state: None
    avatar._record_activity = lambda kind, title, detail="", artifacts=None: activity.append((kind, title, detail))
    avatar.show_bubble = lambda text, **kwargs: bubbles.append((text, kwargs))

    JiuMeDesktopAvatar._handle_gateway_event(
        avatar,
        "帮我整理报告",
        GatewayEvent(
            kind="event",
            event="chat.subtask_update",
            payload={
                "status": "failed",
                "index": 1,
                "total": 2,
                "message": "Gateway websocket request_id subtask-1 failed",
            },
        ),
    )

    assert activity[0][:2] == ("subtask", "子任务 1/2 失败")
    assert "Gateway websocket request_id subtask-1 failed" in activity[0][2]
    assert avatar._one_line_capsule.mode == "done"
    assert avatar._one_line_capsule.summary == "这件事现在还不能继续。"
    assert bubbles[-1][0] == "这件事现在还不能继续。"
    assert "Gateway" not in bubbles[-1][0]
    assert "request_id" not in bubbles[-1][0]
    assert bubbles[-1][1]["state"] == "speaking"
    assert bubbles[-1][1]["duration"] == 3600


def test_gateway_processing_finished_shows_short_done_capsule() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    bubbles: list[tuple[str, dict[str, Any]]] = []
    activity: list[tuple[str, str, str]] = []
    finished: list[tuple[str, str]] = []
    last_action: list[str] = []
    states: list[str] = []

    avatar._gateway_reply = "整理好了，这里是完整报告内容，日常气泡不应该直接展示整段回复。"
    avatar._stream_chat_index = 1
    avatar._gateway_request_id = "req-1"
    avatar._gateway_request_message = "帮我整理报告"
    avatar._last_action = SimpleNamespace(set=lambda value: last_action.append(value))
    avatar._native_direct_chat_visible = False
    avatar._one_line_capsule = None
    avatar._one_line_capsule_timer = None
    avatar._one_line_question_active = False
    avatar.root = SimpleNamespace(after=lambda _delay, callback: "after-1", after_cancel=lambda _timer: None)
    avatar.set_state = lambda state: states.append(state)
    avatar._record_activity = lambda kind, title, detail="", artifacts=None: activity.append((kind, title, detail))
    avatar._finish_assistant_stream = lambda text, *, state="": finished.append((text, state))
    avatar.show_bubble = lambda text, **kwargs: bubbles.append((text, kwargs))

    JiuMeDesktopAvatar._handle_gateway_event(
        avatar,
        "帮我整理报告",
        GatewayEvent(kind="event", event="chat.processing_status", payload={"is_processing": False}),
    )

    assert activity == [("final", "任务已结束", "整理好了，这里是完整报告内容，日常气泡不应该直接展示整段回复。")]
    assert finished == [("整理好了，这里是完整报告内容，日常气泡不应该直接展示整段回复。", "success")]
    assert avatar._one_line_capsule.mode == "done"
    assert avatar._one_line_capsule.summary
    assert len(avatar._one_line_capsule.summary) <= 28
    assert bubbles[-1][0] == avatar._one_line_capsule.summary
    assert bubbles[-1][0] != "整理好了，这里是完整报告内容，日常气泡不应该直接展示整段回复。"
    assert bubbles[-1][1]["state"] == "speaking"
    assert bubbles[-1][1]["duration"] == 4200
    assert last_action[-1] == avatar._one_line_capsule.summary
    assert avatar._gateway_request_id is None


def test_approval_result_error_uses_infra_safe_failed_capsule() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    bubbles: list[tuple[str, dict[str, Any]]] = []
    activity: list[tuple[str, str, str]] = []

    avatar._one_line_capsule = None
    avatar._one_line_capsule_timer = None
    avatar._one_line_question_active = False
    avatar.root = SimpleNamespace(after=lambda _delay, callback: "after-1", after_cancel=lambda _timer: None)
    avatar._record_activity = lambda kind, title, detail="", artifacts=None: activity.append((kind, title, detail))
    avatar.show_bubble = lambda text, **kwargs: bubbles.append((text, kwargs))

    JiuMeDesktopAvatar._handle_approval_result(
        avatar,
        "同意",
        GatewayEvent(kind="error", error="Gateway websocket request_id ask-1 failed"),
    )

    assert activity == [("error", "确认回复失败", "Gateway websocket request_id ask-1 failed")]
    assert avatar._one_line_capsule.mode == "done"
    assert avatar._one_line_capsule.summary == "这件事现在还不能继续。"
    assert bubbles[-1][0] == "这件事现在还不能继续。"
    assert "Gateway" not in bubbles[-1][0]
    assert "request_id" not in bubbles[-1][0]
    assert bubbles[-1][1]["duration"] == 3600


def test_native_presence_command_answers_person_state_without_backend_status() -> None:
    assert _native_presence_command("你现在怎么样") is True
    assert _native_presence_command("心情怎么样") is True
    assert _native_presence_command("are you there?") is True
    assert _native_presence_command("后台状态怎么样") is False
    assert _native_presence_command("帮我整理会议纪要") is False


def test_native_memory_command_recaps_recent_person_context() -> None:
    assert _native_memory_command("你还记得什么") is True
    assert _native_memory_command("刚才我们做了什么") is True
    assert _native_memory_command("what did we do?") is True
    assert _native_memory_command("最近任务") is False
    assert _native_memory_command("帮我整理会议纪要") is False


def test_native_clear_chat_command_resets_only_the_local_thread() -> None:
    assert _native_clear_chat_command("清空刚才的对话") is True
    assert _native_clear_chat_command("重新开始聊天") is True
    assert _native_clear_chat_command("new chat") is True
    assert _native_clear_chat_command("start a new conversation") is True
    assert _native_clear_chat_command("清空长期记忆") is False
    assert _native_clear_chat_command("clear current skill") is False
    assert _native_clear_chat_command("帮我设计一个 new chat UI") is False
    assert _native_clear_chat_command("帮我实现一个新聊天系统") is False
    assert _native_clear_chat_command("帮我整理会议纪要") is False


def test_native_profile_memory_command_updates_long_term_twin_memory() -> None:
    assert _native_profile_memory_command("记住：我喜欢中文简洁回复") == {
        "action": "add",
        "text": "我喜欢中文简洁回复",
    }
    assert _native_profile_memory_command("你长期记得什么") == {"action": "list", "text": ""}
    assert _native_profile_memory_command("忘记 中文简洁") == {"action": "forget", "text": "中文简洁"}
    assert _native_profile_memory_command("忘记全部") == {"action": "clear", "text": ""}
    assert _native_profile_memory_command("帮我整理会议纪要") is None

    memories, reply, changed = _apply_profile_memory_command(
        [],
        {"action": "add", "text": "我喜欢中文简洁回复"},
    )
    assert memories == ["我喜欢中文简洁回复"]
    assert changed is True
    assert "我记住了" in reply

    memories, reply, changed = _apply_profile_memory_command(
        memories,
        {"action": "forget", "text": "中文简洁"},
    )
    assert memories == []
    assert changed is True
    assert "忘掉" in reply

    summary = _profile_memory_summary(["我喜欢中文简洁回复", "当前项目是 JiuMe"])
    assert summary["label"] == "2 条长期记忆"
    assert "当前项目是 JiuMe" in summary["detail"]


def test_native_artifact_command_finds_recent_results_by_talking() -> None:
    assert _native_artifact_command("看结果") == {"action": "preview", "category": ""}
    assert _native_artifact_command("打开最近产物") == {"action": "open", "category": ""}
    assert _native_artifact_command("看刚才那张图") == {"action": "preview", "category": "image"}
    assert _native_artifact_command("产物列表") == {"action": "list", "category": ""}
    assert _native_artifact_command("图片产物列表") == {"action": "list", "category": "image"}
    assert _native_artifact_command("复制最近产物") == {"action": "copy", "category": ""}
    assert _native_artifact_command("copy latest result") == {"action": "copy", "category": ""}
    assert _native_artifact_command("看进度") is None
    assert _native_artifact_command("帮我整理会议纪要") is None

    items = [
        {
            "title": "任务完成",
            "artifacts": [
                {"label": "report.md", "target": "/tmp/report.md", "kind": "file", "category": "text"},
                {"label": "screen.png", "target": "/tmp/screen.png", "kind": "file", "category": "image"},
            ],
        }
    ]

    assert _latest_activity_artifact(items)["label"] == "report.md"
    assert _latest_activity_artifact(items, category="image")["label"] == "screen.png"
    assert _latest_activity_artifact(items, category="table") is None
    cards = _activity_artifact_cards(items)
    image_cards = _activity_artifact_cards(items, category="image")
    assert [card["label"] for card in cards] == ["report.md", "screen.png"]
    assert cards[0]["activityTitle"] == "任务完成"
    assert image_cards[0]["label"] == "screen.png"


def test_native_placement_command_moves_desktop_avatar() -> None:
    assert _native_placement_command("别挡我，躲一下") == "avoid"
    assert _native_placement_command("把自己靠右一点") == "right"
    assert _native_placement_command("去左下角") == "bottom_left"
    assert _native_placement_command("回到右下角") == "bottom_right"
    assert _native_placement_command("居中") == "center"
    assert _native_placement_command("你过来一下") == "summon"
    assert _native_placement_command("到我这边来") == "summon"
    assert _native_placement_command("come here") == "summon"
    assert _native_placement_command("右键菜单怎么打开") is None
    assert _native_placement_command("帮我整理会议纪要") is None
    assert _native_placement_command("帮我过来看看这个方案") is None

    assert _avatar_placement_geometry(
        "bottom_right",
        size=128,
        screen_width=1440,
        screen_height=900,
    ) == "128x128+1276+676"
    assert _avatar_placement_geometry(
        "left",
        size=128,
        screen_width=1440,
        screen_height=900,
    ) == "128x128+36+386"
    assert _avatar_placement_geometry(
        "center",
        size=128,
        screen_width=1440,
        screen_height=900,
    ) == "128x128+656+386"
    assert _avatar_placement_geometry(
        "summon",
        size=128,
        screen_width=1440,
        screen_height=900,
    ) == "128x128+656+386"
    assert _avatar_placement_geometry(
        "avoid",
        size=128,
        screen_width=1440,
        screen_height=900,
        current_x=1300,
    ) == "128x128+36+676"


def test_native_opacity_command_keeps_floating_avatar_unobtrusive() -> None:
    assert _native_opacity_command("透明一点，别那么显眼") == "softer"
    assert _native_opacity_command("半透明一点") == "softer"
    assert _native_opacity_command("清楚一点") == "clearer"
    assert _native_opacity_command("恢复不透明") == "full"
    assert _native_opacity_command("我要透明背景 PNG") is None
    assert _native_opacity_command("帮我整理会议纪要") is None
    assert _normalize_avatar_opacity(0.1) == 0.35
    assert _normalize_avatar_opacity(1.8) == 1.0
    assert _avatar_opacity_from_state({"opacity": 0.62}) == 0.62
    assert _avatar_opacity_label(0.5) == "很低调"
    assert _avatar_opacity_label(0.7) == "半透明"
    assert _avatar_opacity_label(1.0) == "清晰"


def test_native_quick_action_command_starts_common_work_by_talking() -> None:
    focus = _native_quick_action_command("陪我专注一下")
    today = _native_quick_action_command("帮我整理今天的优先级")
    picker = _native_quick_action_command("帮我选一个 skill")

    assert focus is not None
    assert focus["id"] == "focus"
    assert today is not None
    assert today["id"] == "today"
    assert picker is not None
    assert picker["id"] == "skill_picker"
    assert _native_quick_action_command("打开技能货架") is None
    assert _native_quick_action_command("帮我整理会议纪要") is None


def test_native_skill_command_switches_skills_conversationally() -> None:
    data = _native_skill_command("用数据分析 skill")
    code = _native_skill_command("切到代码评审")
    custom = _native_skill_command("使用 local-reviewer skill", ["local-reviewer"])

    assert data is not None
    assert data["action"] == "use"
    assert data["skill"]["displayName"] == "数据分析团队"
    assert code is not None
    assert code["skill"]["displayName"] == "代码评审专业组"
    assert custom is not None
    assert custom["skill"]["displayName"] == "local-reviewer"
    assert _native_skill_command("打开技能货架") is None
    assert _native_skill_command("取消当前 skill") is None
    assert _native_skill_command("用这个方案帮我写一段") is None
    assert _native_skill_command("你现在有哪些skill") is None
    assert _native_skill_command("你有哪些技能") is None
    assert _native_skill_command("what skills do you have?") is None
    assert _native_skill_command("使用 skill") == {"action": "choose"}


def test_native_skill_import_command_accepts_local_skill_paths(tmp_path: Path) -> None:
    skill_dir = tmp_path / "my skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\n", encoding="utf-8")

    assert _native_skill_import_command(f"导入本地 skill：{skill_dir}") == str(skill_dir.resolve())
    assert _native_skill_import_command(f'import skill "{skill_dir}"') == str(skill_dir.resolve())
    assert _native_skill_import_command("导入本地 skill") is None
    assert _native_skill_import_command("把这个文件当材料给你") is None
    assert _native_skill_import_command(f"导入本地 skill：{tmp_path / 'missing'}") is None


def test_presence_summary_reads_like_a_desktop_person() -> None:
    pending = _presence_summary(state="idle", has_pending_approval=True)
    waiting_state = _presence_summary(state="waiting_approval")
    working = _presence_summary(
        state="working",
        active_skill={"displayName": "会议纪要精炼团队"},
        latest_activity={"title": "整理会议", "detail": "正在提取待办"},
    )
    ready = _presence_summary(
        state="idle",
        active_skill={"displayName": "数据分析团队"},
        companion={"label": "陪伴升温"},
        service={"state": "offline"},
    )

    assert pending["label"] == "等你确认"
    assert pending["mood"] == "waiting_approval"
    assert waiting_state["label"] == "等你确认"
    assert working["label"] == "正用「会议纪要精炼团队」"
    assert "整理会议" in working["detail"]
    assert ready["label"] == "拿着「数据分析团队」待命"
    assert "本地分身模式" not in ready["detail"]
    assert "Agent 暂时不在线" not in ready["detail"]


def test_daily_avatar_copy_never_mentions_backend_offline_diagnostics() -> None:
    forbidden = ("Agent 不在线", "离线分身模式", "Gateway 未连接", "Agent 暂时不在线", "Agent/Gateway 在线")

    hover = _presence_summary(
        state="idle",
        active_skill=None,
        latest_activity=None,
        has_pending_approval=False,
        service={"state": "offline"},
    )
    assert not any(token in hover["detail"] for token in forbidden)

    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    assert "def _local_reply_plan" not in app_source
    assert "def _start_typing_reply" not in app_source
    daily_sources = [
        app_source.split("def _presence_summary", 1)[1].split("def _memory_summary", 1)[0],
        app_source.split("def _request_task_interrupt", 1)[1].split("def _post_task_interrupt_result", 1)[0],
        app_source.split("def _send_approval_answer", 1)[1].split("def _post_approval_result", 1)[0],
    ]
    for source in daily_sources:
        assert not any(token in source for token in forbidden)


def test_memory_summary_combines_recent_chat_activity_and_active_skill() -> None:
    empty = _memory_summary([], [])
    summary = _memory_summary(
        [{"role": "assistant", "text": "我在"}, {"role": "user", "text": "帮我整理会议纪要"}],
        [{"kind": "final", "title": "任务完成", "detail": "整理好了行动项"}],
        interaction_count=2,
        active_skill={"displayName": "会议纪要精炼团队"},
        profile_memories=["我喜欢中文简洁回复"],
    )

    assert empty["hasMemory"] is False
    assert empty["label"] == "刚开始认识"
    assert summary["hasMemory"] is True
    assert summary["label"] == "任务完成"
    assert "帮我整理会议纪要" in summary["detail"]
    assert "会议纪要精炼团队" in summary["detail"]
    assert "我喜欢中文简洁回复" in summary["detail"]
    assert "2 次桌面互动" in summary["detail"]


def test_companion_plan_answers_how_jiume_will_stay_with_the_user() -> None:
    assert _native_companion_plan_command("今天怎么陪我") is True
    assert _native_companion_plan_command("陪伴计划") is True
    assert _native_companion_plan_command("how will you stay with me?") is True
    assert _native_companion_plan_command("帮我整理今天的优先级") is False
    assert _native_companion_plan_command("plan today") is False

    working = _companion_plan_summary(
        presence={"label": "正在处理", "mood": "working"},
        memory={"label": "整理会议"},
        suggestions=[{"label": "看进度"}, {"label": "补一句"}, {"label": "安静跑"}],
    )
    skilled = _companion_plan_summary(
        presence={"label": "拿着 skill 待命", "mood": "ready"},
        memory={"label": "最近对话"},
        suggestions=[{"label": "交屏幕"}],
        active_skill={"id": "meeting-minutes", "displayName": "会议纪要精炼团队"},
    )
    idle = _companion_plan_summary(
        presence={"label": "在桌面待命", "mood": "idle"},
        memory={"label": "刚开始认识"},
        suggestions=_direct_companion_suggestion_specs(presence={"mood": "idle"}),
    )

    assert working["label"] == "今天我这样陪你"
    assert "正在处理" in working["detail"]
    assert "安静跑完" in working["detail"]
    assert working["actions"] == ["补一句", "安静跑"]
    assert "会议纪要精炼团队" in skilled["detail"]
    assert "下一句话" in skilled["detail"]
    assert "点头像说一句" in idle["detail"]
    assert idle["actions"] == ["说一句", "设置"]
    plan_copy = " ".join(
        [
            str(working["detail"]),
            *working["actions"],
            str(skilled["detail"]),
            *skilled["actions"],
            str(idle["detail"]),
            *idle["actions"],
        ]
    )
    for label in DAILY_FORBIDDEN_LABELS:
        assert label not in plan_copy


def test_native_settings_update_parser_handles_conversational_changes() -> None:
    update = _native_settings_update("权限改成只读，语气温和点，变大一点，衣服换成草莓粉")

    assert update is not None
    assert update["defaultMode"] == "read_only"
    assert update["tone"] == "warm and concise"
    assert update["size"] == 168
    assert update["appearance"]["id"] == "pink"
    assert _native_settings_update("自主执行") == {"defaultMode": "autonomous"}
    assert _native_settings_update("set permissions to read-only") == {"defaultMode": "read_only"}
    assert _native_settings_update("make yourself bigger") == {"size": 168}
    assert _native_settings_update("换成薄荷绿外观") == {"appearance": normalize_twin_appearance("mint")}
    assert _native_settings_update("以后叫你小九，定位改成写作搭档") == {
        "displayName": "小九",
        "purpose": "写作搭档",
    }
    assert _native_settings_update("帮我整理会议纪要") is None


def test_native_avatar_makeover_command_handles_person_like_appearance_requests() -> None:
    assert _native_avatar_makeover_command("重画一下你") == "redraw"
    assert _native_avatar_makeover_command("刷新你的形象") == "redraw"
    assert _native_avatar_makeover_command("换套衣服") == "next_appearance"
    assert _native_avatar_makeover_command("换个样子") == "next_appearance"
    assert _native_avatar_makeover_command("refresh your avatar") == "redraw"
    assert _native_avatar_makeover_command("change your outfit") == "next_appearance"
    assert _native_avatar_makeover_command("帮我重画一张产品图") is None
    assert _native_avatar_makeover_command("帮我设计一个头像") is None
    assert _native_avatar_makeover_command("帮我整理会议纪要") is None
    assert _next_appearance_preset("blue") == normalize_twin_appearance("mint")
    assert _next_appearance_preset("ink") == normalize_twin_appearance("blue")


def test_native_settings_query_answers_current_twin_configuration_locally() -> None:
    twin = {
        "displayName": "小九",
        "purpose": "陪我写作和复盘",
        "tone": "warm and concise",
        "appearance": {"id": "mint"},
        "permissions": {"defaultMode": "read_only"},
    }
    summary = _settings_summary(twin, size=168)

    assert _native_settings_query_command("当前设置是什么") is True
    assert _native_settings_query_command("你怎么配合我") is True
    assert _native_settings_query_command("what are your current settings?") is True
    assert _native_settings_query_command("what are your settings?") is True
    assert _native_settings_query_command("打开设置") is False
    assert _native_settings_query_command("帮我写一个当前设置页面") is False
    assert summary["label"] == "小九的配合方式"
    assert "陪我写作和复盘" in summary["detail"]
    assert "只读" in summary["detail"]
    assert "温和" in summary["detail"]
    assert "薄荷绿" in summary["detail"]
    assert "大" in summary["detail"]


def test_approval_reply_parser_accepts_person_like_confirmation() -> None:
    assert _approval_reply_from_text("同意，限制只读") == ("accept", "限制只读")
    assert _approval_reply_from_text("可以继续") == ("accept", "")
    assert _approval_reply_from_text("拒绝，原因是风险太高") == ("reject", "风险太高")
    assert _approval_reply_from_text("不同意") == ("reject", "")
    assert _approval_reply_from_text("帮我整理会议纪要") is None


def test_task_runtime_commands_handle_in_progress_talk() -> None:
    assert _task_runtime_command("安静跑") == ("quiet", "")
    assert _task_runtime_command("看进度") == ("progress", "")
    assert _task_runtime_command("戳一下，看看还在跑吗") == ("nudge", "")
    assert _task_runtime_command("poke task") == ("nudge", "")
    assert _task_runtime_command("取消当前任务") == ("cancel", "")
    assert _task_runtime_command("stop current task") == ("cancel", "")
    assert _task_runtime_command("补一句：只读，不要改文件") == ("note", "只读，不要改文件")
    assert _task_runtime_command("追加 先检查风险") == ("note", "先检查风险")
    assert _task_runtime_command("帮我整理会议纪要") is None
    nudge = _task_nudge_reply({"title": "整理会议", "detail": "正在提取行动项"})
    assert nudge["state"] == "working"
    assert nudge["effect"] == "peek"
    assert "整理会议" in nudge["detail"]
    assert "正在提取行动项" in nudge["detail"]
    followup = _task_followup_message("只读，不要改文件")
    assert "Additional instruction" in followup
    assert "只读，不要改文件" in followup


def test_task_continuation_uses_latest_finished_task_context() -> None:
    items = [
        {
            "kind": "final",
            "title": "任务完成",
            "detail": "整理好了会议纪要和行动项",
            "artifacts": [{"label": "report.md", "target": "/tmp/report.md", "kind": "file"}],
        }
    ]

    summary = _task_continuation_summary(items)
    command = _task_continuation_command("再短一点")

    assert summary is not None
    assert summary["kind"] == "final"
    assert command == "再短一点"
    assert _task_continuation_command("重试") == "重试"
    assert _task_continuation_command("try again") == "try again"
    assert _task_continuation_command("继续聊") is None
    assert _task_continuation_command("帮我整理会议纪要") is None
    assert _task_continuation_summary([{"kind": "processing", "title": "处理中"}]) is None
    message = _task_continuation_message(command, summary)
    assert "Continue from the latest JiuMe task" in message
    assert "任务完成" in message
    assert "/tmp/report.md" in message
    assert "User continuation: 再短一点" in message


def test_desktop_runtime_does_not_keep_offline_reply_plan_copy() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")

    assert "我先帮你装上" not in app_source
    assert "已经装上了" not in app_source
    assert "收到。我可以先聊天" not in app_source
    assert "会议纪要、数据分析、PRD" not in app_source


def test_desktop_avatar_animation_and_interaction_lines_are_stateful() -> None:
    assert _animation_transform("idle", 0) == _animation_transform("idle", 2)
    assert _animation_transform("idle", 0)["dx"] == 0
    assert _animation_transform("idle", 0)["dy"] == 0
    assert _animation_transform("idle", 0)["scale"] == 1
    assert _hover_effect_for_state("idle") == ""
    assert _avatar_hover_hint("idle")["effect"] == ""
    assert _animation_transform("working", 1) == _animation_transform("idle", 0)
    assert _animation_transform("waiting_approval", 2)["scale"] == 1
    assert _animation_transform("sleep", 0)["alpha"] == 1
    assert _avatar_status_badge_style("working", 3)["label"] == "做"
    assert _avatar_status_badge_style("waiting_approval", 2)["pulse"] > 0
    assert _avatar_status_badge_style("missing", 0)["label"] == "在"
    idle_aura_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    _draw_avatar_aura(idle_aura_canvas, "idle", 3)
    assert idle_aura_canvas.getbbox() is None
    working_aura_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    _draw_avatar_aura(working_aura_canvas, "working", 3)
    assert working_aura_canvas.getbbox() is None
    badge_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    _draw_avatar_status_badge(badge_canvas, "working", 3)
    assert badge_canvas.getbbox() is not None
    assert badge_canvas.getpixel((112, 16))[3] > 0
    skill_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    _draw_active_skill_badge(skill_canvas, {"id": "meeting-minutes", "displayName": "会议纪要精炼团队"}, 2)
    assert skill_canvas.getbbox() is not None
    assert skill_canvas.getpixel((14, 110))[3] > 0
    reaction_canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    _draw_reaction_chip(reaction_canvas, "cheer", 1)
    assert _reaction_chip_for_effect("cheer")["label"] == "YES"
    assert _reaction_chip_for_effect("peek")["label"] == "?"
    assert _reaction_chip_for_effect("heart")["label"] == "LOVE"
    assert _reaction_chip_for_effect("missing") == {}
    assert reaction_canvas.getbbox() is not None
    assert reaction_canvas.getpixel((14, 14))[3] > 0
    assert _interaction_effect_transform("wave", 1)["rotation"] != 0
    assert _interaction_effect_transform("cheer", 1)["dy"] < 0
    assert _interaction_effect_transform("nod", 2)["dy"] > 0
    assert _interaction_effect_transform("pat", 1)["scale"] > 1
    assert _interaction_effect_transform("peek", 0)["dx"] > 0
    assert _interaction_effect_transform("glance", 1)["dx"] > 0
    assert _interaction_effect_transform("dance", 1)["dy"] < 0
    assert _interaction_effect_transform("heart", 1)["scale"] > 1
    assert _interaction_effect_transform("missing", 1) is None
    assert _interaction_effect_transform("wave", 18) is None
    merged = _merge_avatar_transforms(
        {"scale": 1.02, "dx": 1, "dy": 0, "rotation": 1, "alpha": 0.9},
        {"scale": 1.04, "dx": 2, "dy": -3, "rotation": -2, "alpha": 0.8},
    )
    assert merged["scale"] > 1.05
    assert merged["dx"] == 3
    assert merged["dy"] == -3
    assert merged["rotation"] == -1
    assert merged["alpha"] == pytest.approx(0.72)

    assert JiuMeDesktopAvatar._interaction_line(0) != JiuMeDesktopAvatar._interaction_line(1)
    assert JiuMeDesktopAvatar._interaction_line(0) == JiuMeDesktopAvatar._interaction_line(4)
    assert _wake_line(0) != _wake_line(1)
    assert _wake_line(0) == _wake_line(3)
    assert _should_wake_on_click("sleep", drag_moved=False)
    assert not _should_wake_on_click("sleep", drag_moved=True)
    assert not _should_wake_on_click("idle", drag_moved=False)


def test_desktop_runtime_keeps_idle_avatar_on_first_static_frame(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    first = avatar_dir / "idle.png"
    second = avatar_dir / "idle_1.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(first)
    Image.new("RGBA", (4, 4), (0, 0, 255, 255)).save(second)

    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._manifest = {
        "states": {
            "idle": {
                "file": str(first),
                "frames": [{"file": str(first)}, {"file": str(second)}],
            }
        }
    }
    avatar._avatar_cache = {}
    avatar._animation_frame = 1

    image = desktop_app.JiuMeDesktopAvatar._state_image(avatar, "idle")

    assert image is not None
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert _hover_effect_for_state("idle") == ""
    assert _hover_effect_for_state("success") == "glance"
    assert _hover_effect_for_state("working") == ""
    assert _hover_effect_for_state("sleep") == ""
    hover_skill = _avatar_hover_hint(
        "idle",
        active_skill={"id": "meeting-minutes", "displayName": "会议纪要精炼团队"},
    )
    hover_work = _avatar_hover_hint(
        "idle",
        latest_activity={"kind": "processing", "title": "整理会议", "detail": "提取行动项"},
    )
    hover_approval = _avatar_hover_hint("idle", has_pending_approval=True)
    hover_done = _avatar_hover_hint("success", latest_activity={"kind": "final", "title": "任务完成"})
    hover_idle = _avatar_hover_hint("idle")
    assert "会议纪要精炼团队" in hover_skill["line"]
    assert "直接把要求说给我" in hover_skill["line"]
    assert "右键" not in hover_skill["line"]
    assert hover_skill["effect"] == ""
    assert "整理会议" in hover_work["line"]
    assert hover_work["state"] == "thinking"
    assert hover_approval["state"] == "waiting_approval"
    assert hover_done["effect"] == "cheer"
    assert hover_idle["line"] == "我在。单击就直接说话。"
    assert "右键" not in hover_idle["line"]
    assert hover_idle["effect"] == ""
    assert _chat_role_label("user") == "你"
    assert _chat_role_label("assistant") == "JiuMe"
    assert _chat_role_label("assistant", assistant_name="阿眠") == "阿眠"
    assert _conversation_reaction("我整理好了。", state="success") == {"label": "开心收尾", "effect": "cheer"}
    assert _conversation_reaction("需要你确认下一步", state="waiting_approval") == {"label": "等你点头", "effect": "nod"}
    assert _conversation_reaction("剪贴板材料我接住了") == {"label": "接住材料", "effect": "peek"}
    assert _conversation_reaction("打不开这个文件", state="error") == {"label": "皱眉检查", "effect": "peek"}
    assert _conversation_reaction("我先安静休息", state="sleep") == {"label": "安静休息", "effect": ""}
    assert _conversation_reaction("hello", role="user") == {"label": "", "effect": ""}
    assert _chat_heading("assistant", "怎么继续？") == "JiuMe · 认真听着"
    assert _chat_heading("assistant", "怎么继续？", assistant_name="阿眠") == "阿眠 · 认真听着"
    assert _chat_heading("user", "怎么继续？") == "你"


def test_desktop_ignores_stale_transient_external_state_events() -> None:
    now = datetime(2026, 5, 25, 8, 0, tzinfo=timezone.utc)
    stale_success = {
        "state": "success",
        "updated_at": (now - timedelta(seconds=60)).isoformat(),
        "message": "已迁移并启用刚生成的 JiuMe 分身",
    }
    fresh_success = {
        "state": "success",
        "updated_at": (now - timedelta(seconds=10)).isoformat(),
    }
    stale_working = {
        "state": "working",
        "updated_at": (now - timedelta(seconds=60)).isoformat(),
    }
    persistent_sleep = {
        "state": "sleep",
        "updated_at": (now - timedelta(seconds=60)).isoformat(),
    }

    assert _desktop_state_event_is_stale(stale_success, now=now)
    assert not _desktop_state_event_is_stale(fresh_success, now=now)
    assert _desktop_state_event_is_stale(stale_working, now=now)
    assert not _desktop_state_event_is_stale(persistent_sleep, now=now)
    assert not _desktop_state_event_is_stale({"state": "idle"}, now=now)


def test_desktop_ignores_setup_origin_and_non_active_twin_events() -> None:
    assert _desktop_state_event_is_ignored(
        {"state": "success", "source": "setup", "twin_id": "new"},
        active_twin_id="old",
    )
    assert _desktop_state_event_is_ignored(
        {"state": "success", "twin_id": "new"},
        active_twin_id="old",
    )
    assert not _desktop_state_event_is_ignored(
        {"state": "success", "twin_id": "old"},
        active_twin_id="old",
    )


def test_direct_chat_suppresses_all_head_top_bubbles() -> None:
    assert _direct_chat_suppresses_speech(True, "speaking")
    assert _direct_chat_suppresses_speech(True, "success")
    assert _direct_chat_suppresses_speech(True, "error")
    assert _direct_chat_suppresses_speech(True, "working")
    assert not _direct_chat_suppresses_speech(False, "speaking")


def test_position_bubble_does_not_resurrect_speech_when_direct_chat_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Root:
        def winfo_x(self) -> int:
            return 120

        def winfo_y(self) -> int:
            return 240

        def winfo_screenwidth(self) -> int:
            return 1440

        def winfo_screenheight(self) -> int:
            return 900

    class Overlay:
        def __init__(self) -> None:
            self.shown: list[str] = []
            self.hidden: list[str] = []

        def show_image_layer(self, layer_id: str, *_args: Any, **_kwargs: Any) -> None:
            self.shown.append(layer_id)

        def hide_image_layer(self, layer_id: str) -> None:
            self.hidden.append(layer_id)

    monkeypatch.setattr(desktop_app, "_uses_native_desktop_layers", lambda platform=sys.platform: True)
    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar.root = Root()
    avatar.overlay = Overlay()
    avatar.size = 128
    avatar._state = "speaking"
    avatar._bubble_text = "我在，直接说。"
    avatar._bubble_timer = None
    avatar._bubble = None
    avatar._native_direct_chat_visible = True

    JiuMeDesktopAvatar._position_bubble(avatar)

    assert "speech" not in avatar.overlay.shown
    assert "speech" in avatar.overlay.hidden


def test_show_bubble_never_draws_legacy_speech_layer_without_direct_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Root:
        def winfo_x(self) -> int:
            return 120

        def winfo_y(self) -> int:
            return 240

        def winfo_screenwidth(self) -> int:
            return 1440

        def winfo_screenheight(self) -> int:
            return 900

    class Overlay:
        def __init__(self) -> None:
            self.shown: list[str] = []
            self.hidden: list[str] = []

        def show_image_layer(self, layer_id: str, *_args: Any, **_kwargs: Any) -> None:
            self.shown.append(layer_id)

        def hide_image_layer(self, layer_id: str) -> None:
            self.hidden.append(layer_id)

    monkeypatch.setattr(desktop_app, "_uses_native_desktop_layers", lambda platform=sys.platform: True)
    monkeypatch.setattr(JiuMeDesktopAvatar, "set_state", lambda self, state: setattr(self, "_state", state))
    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar.root = Root()
    avatar.overlay = Overlay()
    avatar.size = 128
    avatar._state = "idle"
    avatar._bubble_text = ""
    avatar._bubble_timer = None
    avatar._bubble = None
    avatar._hover_hide_timer = None
    avatar._hover_menu = None
    avatar._native_direct_chat_visible = False

    JiuMeDesktopAvatar.show_bubble(avatar, "我在，直接说。", state="speaking", duration=None)

    assert "speech" not in avatar.overlay.shown
    assert "speech" in avatar.overlay.hidden
    assert "hover" in avatar.overlay.hidden


def test_position_hover_menu_does_not_resurrect_hover_when_direct_chat_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Overlay:
        def __init__(self) -> None:
            self.shown: list[str] = []
            self.hidden: list[str] = []

        def show_image_layer(self, layer_id: str, *_args: Any, **_kwargs: Any) -> None:
            self.shown.append(layer_id)

        def hide_image_layer(self, layer_id: str) -> None:
            self.hidden.append(layer_id)

    def fail_if_drawn() -> tuple[Any, list[Any]]:
        raise AssertionError("hover menu should stay hidden while direct chat is visible")

    monkeypatch.setattr(desktop_app, "_uses_native_desktop_layers", lambda platform=sys.platform: True)
    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar.overlay = Overlay()
    avatar._hover_hide_timer = None
    avatar._hover_menu = None
    avatar._native_direct_chat_visible = True
    avatar._native_hover_menu_image = fail_if_drawn

    JiuMeDesktopAvatar._position_hover_menu(avatar)

    assert "hover" not in avatar.overlay.shown
    assert "hover" in avatar.overlay.hidden


def test_show_hover_menu_never_draws_legacy_hover_layer_without_direct_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Overlay:
        def __init__(self) -> None:
            self.shown: list[str] = []
            self.hidden: list[str] = []

        def show_image_layer(self, layer_id: str, *_args: Any, **_kwargs: Any) -> None:
            self.shown.append(layer_id)

        def hide_image_layer(self, layer_id: str) -> None:
            self.hidden.append(layer_id)

    def fail_if_drawn() -> tuple[Any, list[Any]]:
        raise AssertionError("hover menu should never be drawn")

    monkeypatch.setattr(desktop_app, "_uses_native_desktop_layers", lambda platform=sys.platform: True)
    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar.overlay = Overlay()
    avatar._bubble_timer = None
    avatar._bubble = None
    avatar._hover_hide_timer = None
    avatar._hover_menu = None
    avatar._native_direct_chat_visible = False
    avatar._native_hover_menu_image = fail_if_drawn

    JiuMeDesktopAvatar._show_hover_menu(avatar, mode="prompt")

    assert "hover" not in avatar.overlay.shown
    assert "speech" in avatar.overlay.hidden
    assert "hover" in avatar.overlay.hidden


def test_open_native_direct_surface_hides_hover_and_speech_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Overlay:
        def __init__(self) -> None:
            self.hidden: list[str] = []

        def hide_image_layer(self, layer_id: str) -> None:
            self.hidden.append(layer_id)

    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar.overlay = Overlay()
    avatar._bubble_timer = None
    avatar._bubble = None
    avatar._hover_hide_timer = None
    avatar._hover_menu = None
    avatar._native_direct_chat_visible = False
    avatar._native_direct_surface = "chat"
    positioned: list[bool] = []

    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_position_direct_chat",
        lambda self: positioned.append(bool(self._native_direct_chat_visible)),
    )

    JiuMeDesktopAvatar._open_native_direct_surface(avatar, "chat")

    assert avatar._native_direct_chat_visible
    assert positioned == [True]
    assert "speech" in avatar.overlay.hidden
    assert "hover" in avatar.overlay.hidden


def test_native_avatar_move_hides_direct_chat_without_resurrecting_other_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar._native_direct_chat_visible = True
    avatar._native_direct_surface = "chat"
    calls: list[str] = []

    monkeypatch.setattr(JiuMeDesktopAvatar, "_close_direct_chat", lambda self: calls.append("close"))
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_position_direct_chat",
        lambda self: (_ for _ in ()).throw(AssertionError("direct chat should stay hidden while dragging")),
    )
    monkeypatch.setattr(JiuMeDesktopAvatar, "_position_panel", lambda self: calls.append("panel"))
    monkeypatch.setattr(JiuMeDesktopAvatar, "_position_work_hud", lambda self: calls.append("work"))
    monkeypatch.setattr(JiuMeDesktopAvatar, "_hide_speech_surface", lambda self: calls.append("hide_speech"))
    monkeypatch.setattr(JiuMeDesktopAvatar, "_hide_hover_menu", lambda self: calls.append("hide_hover"))
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_position_bubble",
        lambda self: (_ for _ in ()).throw(AssertionError("speech should not be repositioned")),
    )
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_position_hover_menu",
        lambda self: (_ for _ in ()).throw(AssertionError("hover should not be repositioned")),
    )

    JiuMeDesktopAvatar._native_avatar_moved(avatar, 40, 80)

    assert calls == ["close", "panel", "work", "hide_speech", "hide_hover"]


def test_avatar_left_click_closes_visible_direct_chat_instead_of_reopening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar._state = "idle"
    avatar._drag_moved = False
    avatar._native_direct_chat_visible = True

    monkeypatch.setattr(JiuMeDesktopAvatar, "_hide_hover_menu", lambda self: calls.append("hide_hover"))
    monkeypatch.setattr(JiuMeDesktopAvatar, "_close_direct_chat", lambda self: calls.append("close"))
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "open_direct_chat",
        lambda self: (_ for _ in ()).throw(AssertionError("click should close visible chat")),
    )

    JiuMeDesktopAvatar._native_avatar_left_click(avatar, False)

    assert calls == ["hide_hover", "close"]


def test_avatar_tk_click_release_closes_visible_direct_chat_instead_of_reopening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar._state = "idle"
    avatar._drag_moved = False
    avatar._drag_origin = (0, 0, 100, 100)
    avatar._native_direct_chat_visible = True

    monkeypatch.setattr(JiuMeDesktopAvatar, "_hide_hover_menu", lambda self: calls.append("hide_hover"))
    monkeypatch.setattr(JiuMeDesktopAvatar, "_close_direct_chat", lambda self: calls.append("close"))
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "open_direct_chat",
        lambda self: (_ for _ in ()).throw(AssertionError("click release should close visible chat")),
    )

    JiuMeDesktopAvatar._end_drag_or_click(avatar, object())  # type: ignore[arg-type]

    assert calls == ["hide_hover", "close"]
    assert avatar._drag_origin is None
    assert avatar._drag_moved is False


def test_avatar_tk_click_jitter_does_not_move_window_before_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry_calls: list[str] = []

    class FakeRoot:
        def geometry(self, value: str) -> None:
            geometry_calls.append(value)

    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar.root = FakeRoot()
    avatar._drag_origin = (10, 20, 100, 200)
    avatar._drag_moved = False

    for method_name in (
        "_position_direct_chat",
        "_position_panel",
        "_position_work_hud",
        "_position_bubble",
        "_position_hover_menu",
    ):
        monkeypatch.setattr(
            JiuMeDesktopAvatar,
            method_name,
            lambda self: (_ for _ in ()).throw(AssertionError("click jitter should not reposition surfaces")),
        )

    JiuMeDesktopAvatar._drag(
        avatar,
        SimpleNamespace(x_root=12, y_root=23),  # type: ignore[arg-type]
    )

    assert geometry_calls == []
    assert avatar._drag_moved is False


def test_avatar_tk_drag_temporarily_hides_visible_direct_chat_until_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeRoot:
        def geometry(self, value: str) -> None:
            calls.append(("geometry", value))

    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar.root = FakeRoot()
    avatar._drag_origin = (10, 20, 100, 200)
    avatar._drag_moved = False
    avatar._native_direct_chat_visible = True
    avatar._native_direct_surface = "skills"

    monkeypatch.setattr(desktop_app, "_uses_native_direct_chat", lambda: True)
    for method_name in (
        "_position_panel",
        "_position_work_hud",
        "_position_bubble",
        "_position_hover_menu",
    ):
        monkeypatch.setattr(JiuMeDesktopAvatar, method_name, lambda self: None)
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_position_direct_chat",
        lambda self: (_ for _ in ()).throw(AssertionError("drag should hide direct chat instead of repositioning it")),
    )
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_close_direct_chat",
        lambda self: (
            calls.append(("close", str(self._native_direct_surface))),
            setattr(self, "_native_direct_chat_visible", False),
        ),
    )
    monkeypatch.setattr(JiuMeDesktopAvatar, "_hide_hover_menu", lambda self: calls.append(("hide_hover", "")))
    monkeypatch.setattr(JiuMeDesktopAvatar, "_persist_window_position", lambda self: calls.append(("persist", "")))
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_open_native_direct_surface",
        lambda self, surface: calls.append(("restore", str(surface))),
    )

    JiuMeDesktopAvatar._drag(
        avatar,
        SimpleNamespace(x_root=18, y_root=32),  # type: ignore[arg-type]
    )
    JiuMeDesktopAvatar._drag(
        avatar,
        SimpleNamespace(x_root=24, y_root=40),  # type: ignore[arg-type]
    )

    assert calls.count(("close", "skills")) == 1
    assert ("restore", "skills") not in calls

    JiuMeDesktopAvatar._end_drag_or_click(avatar, object())  # type: ignore[arg-type]

    assert calls[-2:] == [("persist", ""), ("restore", "skills")]
    assert avatar._drag_origin is None
    assert avatar._drag_moved is False


def test_native_avatar_drag_temporarily_hides_visible_direct_chat_until_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar._state = "idle"
    avatar._native_direct_chat_visible = True
    avatar._native_direct_surface = "progress"

    monkeypatch.setattr(desktop_app, "_uses_native_direct_chat", lambda: True)
    for method_name in (
        "_position_direct_chat",
        "_position_panel",
        "_position_work_hud",
        "_position_bubble",
        "_position_hover_menu",
    ):
        monkeypatch.setattr(JiuMeDesktopAvatar, method_name, lambda self: calls.append((method_name, "")))
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_close_direct_chat",
        lambda self: (
            calls.append(("close", str(self._native_direct_surface))),
            setattr(self, "_native_direct_chat_visible", False),
        ),
    )
    monkeypatch.setattr(JiuMeDesktopAvatar, "_hide_speech_surface", lambda self: calls.append(("hide_speech", "")))
    monkeypatch.setattr(JiuMeDesktopAvatar, "_hide_hover_menu", lambda self: calls.append(("hide_hover", "")))
    monkeypatch.setattr(JiuMeDesktopAvatar, "_persist_window_position", lambda self: calls.append(("persist", "")))
    monkeypatch.setattr(
        JiuMeDesktopAvatar,
        "_open_native_direct_surface",
        lambda self, surface: calls.append(("restore", str(surface))),
    )

    JiuMeDesktopAvatar._native_avatar_moved(avatar, 40, 80)

    assert calls[0] == ("close", "progress")
    assert ("restore", "progress") not in calls

    JiuMeDesktopAvatar._native_avatar_left_click(avatar, True)

    assert calls[-2:] == [("persist", ""), ("restore", "progress")]


def test_one_line_daily_window_height_ignores_retired_direct_chat_layers() -> None:
    items = [
        {"role": "user", "text": "one"},
        {"role": "assistant", "text": "two"},
        {"role": "user", "text": "three"},
        {"role": "assistant", "text": "four"},
    ]

    preview = _conversation_preview_items(items)

    assert [item["text"] for item in preview] == ["two", "three", "four"]
    assert preview[0]["role"] == "assistant"
    assert [item["text"] for item in _conversation_preview_items(items, offset=1)] == ["one", "two", "three"]
    assert _direct_chat_height(0) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(1) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(4) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_approval=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_skill_shortcuts=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_settings=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_activity=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_companion=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_service=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_help=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_quick_actions=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_height(2, has_artifacts=True) == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_content_window_height(52) == 142

    full_direct_bubble_height = _direct_chat_height(
        3,
        has_approval=True,
        has_quick_actions=True,
        has_skill_shortcuts=True,
        has_settings=True,
        has_activity=True,
        has_artifacts=True,
        has_companion=True,
        has_service=True,
        has_help=True,
    )
    clamped_height = _direct_chat_window_height(full_direct_bubble_height, 900)
    assert full_direct_bubble_height == ONE_LINE_DIRECT_HEIGHT
    assert clamped_height == ONE_LINE_DIRECT_HEIGHT
    assert _direct_chat_window_height(240, 900) == 240
    assert _direct_chat_scroll_height(clamped_height) >= 160
    assert _direct_chat_composer_action_specs() == [{"id": "send", "label": "发送"}]
    assert _direct_speech_bubble_width("设置", "先选一个设置层，我再只展开那一层。") < DIRECT_CHAT_WIDTH
    assert _direct_speech_bubble_width("长标题", "这是一段非常长的说明，用来确认头像旁说明气泡不会撑成整条网页式横向面板。") <= 292
    assert _direct_value_bubble_width("当前 skill", "现在没有固定 skill。") < 270
    assert _direct_value_bubble_width("长标签", "这是一段非常长的设置值，用来确认信息泡泡不会退回整齐等宽的列表面板。") <= 270
    assert _direct_text_preview_bubble_width("产物", "短预览") < DIRECT_CHAT_WIDTH
    assert _direct_text_preview_bubble_width("长产物", "这是一段很长的产物预览，用来确认预览不会撑成整条结果卡片。") <= 292
    one_line_surface = _direct_chat_surface_rect(DIRECT_CHAT_WIDTH, ONE_LINE_DIRECT_HEIGHT)
    one_line_composer_surface = _direct_chat_composer_rect(DIRECT_CHAT_WIDTH, ONE_LINE_DIRECT_HEIGHT)
    one_line_surfaces = _direct_chat_surface_bubbles(DIRECT_CHAT_WIDTH, ONE_LINE_DIRECT_HEIGHT)
    one_line_content = _direct_chat_content_rect(DIRECT_CHAT_WIDTH, ONE_LINE_DIRECT_HEIGHT)
    for rect in one_line_surfaces:
        if not rect.get("draw", True):
            continue
        assert 0 <= rect["x"] < DIRECT_CHAT_WIDTH
        assert 0 <= rect["y"] < ONE_LINE_DIRECT_HEIGHT
        assert rect["x"] + rect["width"] <= DIRECT_CHAT_WIDTH
        assert rect["y"] + rect["height"] <= ONE_LINE_DIRECT_HEIGHT
    assert one_line_content["y"] + one_line_content["height"] <= ONE_LINE_DIRECT_HEIGHT
    assert one_line_content["height"] >= desktop_app.DIRECT_CHAT_COMPOSER_HEIGHT + 14
    assert one_line_content["width"] >= desktop_app.DIRECT_CHAT_COMPOSER_WIDTH + 14
    assert one_line_surface["height"] < ONE_LINE_DIRECT_HEIGHT
    assert one_line_composer_surface["height"] == desktop_app.DIRECT_CHAT_COMPOSER_HEIGHT
    surface = _direct_chat_surface_rect(348, 360)
    composer_surface = _direct_chat_composer_rect(348, 360)
    surfaces = _direct_chat_surface_bubbles(348, 360)
    content = _direct_chat_content_rect(348, 360)
    assert surface == {
        "x": 6,
        "y": 4,
        "width": 306,
        "height": 278,
        "radius": 34,
        "draw": True,
    }
    assert composer_surface == {
        "x": 62,
        "y": 302,
        "width": 262,
        "height": 48,
        "radius": 24,
        "draw": True,
    }
    assert surfaces == [surface, composer_surface]
    assert content == {"x": 24, "y": 17, "width": 274, "height": 332}
    assert content["x"] > surface["x"]
    assert content["width"] < surface["width"]
    assert surface["height"] + composer_surface["height"] < 360
    assert _direct_message_bubble_height("短句") == 52
    assert desktop_app._direct_message_bubble_width("你好") < 120
    assert desktop_app._direct_message_bubble_width("你好") < desktop_app._direct_message_bubble_width(
        "这是一段比较长的对话，会被画成头像旁边的小气泡而不是方框面板。"
    )
    assert (
        _direct_message_bubble_height(
            "This longer desktop message should wrap into multiple rows beside the avatar.",
            container_width=180,
        )
        > _direct_message_bubble_height("短句")
    )
    assert _direct_message_bubble_height("JiuMe · 接住材料：" + "我先把 skill 入口放在头像旁；" * 5) <= 128
    assert _direct_message_bubble_height(
        "# 评估报告 ## 构建状态 未执行 lint/type-check/unit tests: 当前评估模式为 "
        "`runtime_extension_gap_assessment`，不涉及代码库..."
    ) <= 110
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    assert "ONE_LINE_DIRECT_HEIGHT = 84" in app_source
    assert "ONE_LINE_DIRECT_WIDTH = DIRECT_CHAT_WIDTH" in app_source
    assert "return ONE_LINE_DIRECT_HEIGHT" in app_source
    assert "rows = max(0, min(DIRECT_CHAT_PREVIEW_LIMIT" not in app_source.split(
        "def _direct_chat_height",
        1,
    )[1].split("def _direct_chat_window_height", 1)[0]
    assert '"height": max(42, height - 28)' in app_source
    assert "DIRECT_GLASS_BG" in app_source
    assert "DIRECT_GLASS_BORDER" in app_source
    assert '"#FFFDF8"' not in app_source
    assert '"#FFF8EC"' not in app_source
    open_direct_source = app_source.split("def open_direct_chat", 1)[1].split("def _run_rest_action", 1)[0]
    open_direct_body = app_source.split("def open_direct_chat", 1)[1].split(
        "def _open_native_direct_surface",
        1,
    )[0]
    assert "if self._redirect_first_run_to_setup():\n            return" in open_direct_source
    assert "if _uses_native_direct_chat():" in open_direct_source
    assert open_direct_body.index("self._redirect_first_run_to_setup()") < open_direct_body.index(
        "chat = tk.Toplevel(self.root)"
    )
    assert "ONE_LINE_INPUT_HINT" in open_direct_body
    assert "self._one_line_question_active = True" in open_direct_body
    assert "composer = tk.Canvas(" in open_direct_body
    assert "composer = tk.Frame(shell, bg=DIRECT_LAYER_BG" not in open_direct_body
    assert "width=DIRECT_CHAT_COMPOSER_WIDTH" in open_direct_body
    assert 'composer.pack(anchor="e"' in open_direct_body
    assert 'composer.pack(fill="x"' not in open_direct_body
    assert "self._direct_entry.pack(" not in open_direct_body
    assert "composer.create_window(" in open_direct_body
    assert "draw_direct_composer" in open_direct_body
    assert "_direct_composer_tail_points(width, height)" not in open_direct_body
    assert "direct_composer_tail" not in open_direct_body
    assert "tk.Button(" not in open_direct_body
    assert "close_button = tk.Canvas(" not in open_direct_body
    assert "scroll_shell = tk.Frame(" not in open_direct_body
    assert "tk.Scrollbar(" not in open_direct_body
    assert "self._direct_scroll_canvas = None" in open_direct_body
    assert "_handle_native_direct_scroll" in app_source
    native_position_source = app_source.split("def _position_native_direct_chat", 1)[1].split(
        "def _handle_native_direct_scroll",
        1,
    )[0]
    assert "on_scroll=None" in native_position_source
    assert "send_button = tk.Canvas(" in open_direct_body
    assert "_rebuild_direct_chat_rows()" not in open_direct_body
    assert "_rebuild_direct_companion_card()" not in open_direct_body
    assert "_rebuild_direct_activity_card()" not in open_direct_body
    assert "_rebuild_direct_approval_card()" not in open_direct_body
    assert "_rebuild_direct_settings_card()" not in open_direct_body
    assert "_focus_direct_feature_layer()" not in open_direct_body
    for retired_name in (
        "_direct_chat_frame",
        "_direct_companion_frame",
        "_direct_help_frame",
        "_direct_service_frame",
        "_direct_artifact_frame",
        "_direct_activity_frame",
        "_direct_approval_frame",
        "_direct_quick_frame",
        "_direct_skills_frame",
        "_direct_settings_frame",
    ):
        assert f"self.{retired_name} = tk.Frame" not in open_direct_body
    surface_source = app_source.split("def _draw_direct_chat_surface", 1)[1].split("def _show_hover_menu", 1)[0]
    assert "_direct_chat_surface_bubbles(width, height)" in surface_source
    assert 'if not rect.get("draw", True):' in surface_source
    assert "def _focus_direct_feature_layer" in app_source
    assert "has_approval=self._direct_frame_is_packed(self._direct_approval_frame)" in app_source
    focus_layer_source = app_source.split("def _focus_direct_feature_layer", 1)[1].split(
        "def _current_presence_summary",
        1,
    )[0]
    assert '"settings": self._direct_settings_frame' in focus_layer_source
    assert '"skills": self._direct_skills_frame' in focus_layer_source
    assert '"activity": self._direct_activity_frame' in focus_layer_source
    assert "frame.pack_forget()" in focus_layer_source
    assert "self._direct_settings_visible = False" in focus_layer_source
    assert "self._direct_skills_picker_visible = False" in focus_layer_source


def test_direct_chat_geometry_places_surface_opposite_avatar_side() -> None:
    left = _direct_chat_geometry_for_avatar(
        icon_x=80,
        icon_y=300,
        size=128,
        width=348,
        height=280,
        screen_width=1200,
        screen_height=800,
    )
    right = _direct_chat_geometry_for_avatar(
        icon_x=960,
        icon_y=300,
        size=128,
        width=348,
        height=280,
        screen_width=1200,
        screen_height=800,
    )

    assert left["side"] == "right"
    assert left["x"] > 80 + 128
    assert right["side"] == "left"
    assert right["x"] + 348 < 960
    assert 20 <= left["y"] <= 800 - 280 - 20
    assert 20 <= right["y"] <= 800 - 280 - 20


def test_direct_chat_visual_has_no_tail_or_pointer() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    native_source = app_source.split("def _native_direct_chat_image", 1)[1].split(
        "def _native_direct_feature_image",
        1,
    )[0]
    position_source = app_source.split("def _position_native_direct_chat", 1)[1].split(
        "def _handle_native_direct_action",
        1,
    )[0]
    focus_layer_source = app_source.split("def _focus_direct_feature_layer", 1)[1].split(
        "def _current_presence_summary",
        1,
    )[0]
    forbidden = (
        "direct_chat_tail",
        "direct_value_tail",
        "direct_bubble_button_tail",
        "direct_input_tail",
        "pointer",
        "draw.polygon",
    )

    for token in forbidden:
        assert token not in native_source
    assert "_direct_chat_geometry_for_avatar" in position_source
    assert "self._direct_activity_detail_visible = False" in focus_layer_source
    direct_rows_source = app_source.split("def _rebuild_direct_chat_rows", 1)[1].split(
        "def _direct_frame_is_packed",
        1,
    )[0]
    assert "bubble = tk.Canvas(" in direct_rows_source
    assert "bubble = tk.Frame(" not in direct_rows_source
    assert "direct_empty_message_text" not in direct_rows_source
    assert "直接跟我说一句，我会在头像旁回应。" not in direct_rows_source
    assert "最近对话会像小气泡一样留在我旁边。" not in direct_rows_source
    assert "direct_message_text" in direct_rows_source
    speech_source = app_source.split("def _pack_direct_speech_bubble", 1)[1].split(
        "def _chat_assistant_name",
        1,
    )[0]
    assert "width_hint = _direct_speech_bubble_width(safe_title, safe_detail)" in speech_source
    assert 'bubble.pack(anchor="w"' in speech_source
    assert 'bubble.pack(fill="x"' not in speech_source
    position_source = app_source.split("def _position_direct_chat", 1)[1].split("def _position_panel", 1)[0]
    assert "if self._native_direct_chat_visible and _uses_native_direct_chat():" in position_source
    assert 'self.overlay.show_image_layer(\n            "direct_chat"' in app_source
    assert "has_companion=True" not in position_source
    assert "has_companion=self._direct_companion_visible" in position_source


def test_direct_chat_fallback_draws_one_glass_layer_without_legacy_tails() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    surface_rect_source = app_source.split("def _direct_chat_surface_rect", 1)[1].split(
        "def _direct_chat_composer_rect",
        1,
    )[0]
    composer_rect_source = app_source.split("def _direct_chat_composer_rect", 1)[1].split(
        "def _direct_chat_surface_bubbles",
        1,
    )[0]
    draw_surface_source = app_source.split("def _draw_direct_chat_surface", 1)[1].split(
        "def _show_hover_menu",
        1,
    )[0]
    open_direct_source = app_source.split("def open_direct_chat", 1)[1].split(
        "def _open_native_direct_surface",
        1,
    )[0]
    direct_rows_source = app_source.split("def _rebuild_direct_chat_rows", 1)[1].split(
        "def _direct_frame_is_packed",
        1,
    )[0]
    direct_speech_source = app_source.split("def _pack_direct_speech_bubble", 1)[1].split(
        "def _chat_assistant_name",
        1,
    )[0]
    direct_values_source = app_source.split("def _pack_direct_value_bubbles", 1)[1].split(
        "def _pack_direct_text_preview_bubble",
        1,
    )[0]
    direct_buttons_source = app_source.split("def _pack_direct_bubble_buttons", 1)[1].split(
        "def _show_direct_help_card",
        1,
    )[0]

    assert '"draw": True' in surface_rect_source
    assert '"draw": True' in composer_rect_source
    assert "DIRECT_GLASS_FROST" in draw_surface_source
    assert "DIRECT_GLASS_HIGHLIGHT" in draw_surface_source
    assert "DIRECT_GLASS_BORDER" in draw_surface_source
    assert "_hide_speech_surface()" in open_direct_source
    assert "create_polygon" not in direct_rows_source
    assert "create_polygon" not in direct_speech_source
    assert "direct_value_tail" not in direct_values_source
    assert "create_polygon" not in direct_values_source
    assert "direct_bubble_button_tail" not in direct_buttons_source
    assert "create_polygon" not in direct_buttons_source


def test_speech_bubble_layout_floats_above_avatar_when_possible() -> None:
    layout = _speech_bubble_layout(
        text="我在，直接说。",
        icon_x=600,
        icon_y=300,
        size=128,
        screen_width=1440,
        screen_height=900,
    )
    low_room_layout = _speech_bubble_layout(
        text="我在，直接说。",
        icon_x=20,
        icon_y=20,
        size=128,
        screen_width=320,
        screen_height=240,
    )

    assert _speech_bubble_height("短句") == 78
    assert _speech_bubble_height("JiuMe · 接住材料：我先把 skill 入口放在头像旁；推荐里会有很多内容，不能被裁掉。") >= 132
    assert layout == {"width": 286, "height": 78, "x": 521, "y": 212, "tail": "bottom", "tail_x": 143}
    assert low_room_layout["tail"] == "top"
    assert low_room_layout["x"] == 8
    assert low_room_layout["y"] == 154
    image = desktop_app._native_speech_bubble_image("我在，直接说。", layout)
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((image.width - 1, 0))[3] == 0
    assert image.getpixel((image.width // 2, image.height // 2))[3] > 200
    assert desktop_app.DIRECT_SHADOW_ALPHA <= 48
    assert desktop_app.DIRECT_MESSAGE_SHADOW_ALPHA <= desktop_app.DIRECT_SHADOW_ALPHA
    assert desktop_app.DIRECT_TK_FONT == "PingFang SC"
    assert desktop_app.DIRECT_CHAMPAGNE == "#71CFC5"
    assert desktop_app.DIRECT_GLASS_FROST_ALPHA >= 160
    assert desktop_app.DIRECT_GLASS_SHEEN_ALPHA <= desktop_app.DIRECT_GLASS_FROST_ALPHA
    assert desktop_app.DIRECT_ASSISTANT_BUBBLE != desktop_app.DIRECT_USER_BUBBLE


def test_macos_tk_layers_use_readable_background_instead_of_black_systemtransparent() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")

    assert _desktop_layer_background("darwin") == desktop_app.DIRECT_LAYER_BG
    assert _desktop_layer_background("linux") == "#ff00ff"
    assert desktop_app._uses_native_desktop_layers("darwin") is True
    assert desktop_app._uses_native_direct_chat("darwin") is True
    assert desktop_app._uses_native_desktop_layers("linux") is False
    assert '"systemTransparent" if sys.platform == "darwin"' not in app_source
    assert "self._transparent_bg = _desktop_layer_background(sys.platform)" in app_source
    assert 'return platform == "darwin"' in app_source
    assert "return _uses_native_desktop_layers(platform)" in app_source


def test_desktop_overlay_uses_appkit_adapter_and_avatar_has_no_visible_chrome() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    overlay_source = Path("jiume/desktop/overlay.py").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    render_source = app_source.split("def _render_avatar_frame", 1)[1].split(
        "def _start_interaction_effect",
        1,
    )[0]

    assert "pyobjc-framework-Cocoa" in pyproject
    assert "class DesktopOverlayHost" in overlay_source
    assert "class AvatarLayer" in overlay_source
    assert "class BubbleLayer" in overlay_source
    assert "class FloatingCardLayer" in overlay_source
    assert "from jiume.desktop.overlay import" in app_source
    assert "self.overlay = DesktopOverlayHost" in app_source
    assert "self.overlay.apply_avatar_window(self.root" in app_source
    geometry_index = app_source.index("self.root.geometry(\n            _avatar_window_geometry")
    apply_index = app_source.index("self.overlay.apply_avatar_window(self.root")
    assert geometry_index < apply_index
    assert "apply_transparent_layer" in app_source
    assert "_draw_avatar_aura(" in render_source
    assert "_draw_avatar_status_badge(" not in render_source
    assert "_draw_active_skill_badge(" not in render_source
    assert "setStyleMask_(NSWindowStyleMaskBorderless)" in overlay_source
    assert "setBackgroundColor_(NSColor.clearColor())" in overlay_source
    assert "setWantsLayer_(True)" in overlay_source
    assert "layer.setBackgroundColor_(NSColor.clearColor().CGColor())" in overlay_source
    assert "layer.setOpaque_(False)" in overlay_source
    assert "layer.setContentsScale_(self.native_backing_scale())" in overlay_source
    assert "def is_image_layer_visible" in overlay_source
    assert '"visible": False' in overlay_source
    assert 'state["visible"] = True' in overlay_source
    assert 'state["visible"] = False' in overlay_source
    assert "def native_backing_scale" in overlay_source
    assert "def _retina_image" in overlay_source
    update_source = overlay_source.split("def update_avatar_image", 1)[1].split(
        "def show_image_layer",
        1,
    )[0]
    image_layer_source = overlay_source.split("class JiuMeImageLayerView", 1)[1].split(
        "image_view_class = JiuMeImageLayerView",
        1,
    )[0]
    assert "rgba.save(buffer, format=\"PNG\")" in update_source
    assert "self._retina_image(image, logical_width=size, logical_height=size)" in update_source
    assert "ns_image.setSize_(NSMakeSize(int(size), int(size)))" in update_source
    assert "self._avatar_view.setImage_(ns_image)" in update_source
    assert "self._avatar_window.orderFrontRegardless()" in update_source
    assert "logical_size: tuple[int, int] | None = None" in overlay_source
    assert "ns_image.setSize_(NSMakeSize(width, height))" in overlay_source
    assert "def acceptsFirstMouse_(self, event):" in image_layer_source


def test_native_avatar_callbacks_queue_without_touching_tk_from_appkit_event() -> None:
    scheduled: list[tuple[int, Any]] = []
    calls: list[tuple[str, tuple[object, ...]]] = []

    class FakeRoot:
        def after(self, delay: int, callback: Any) -> str:
            scheduled.append((delay, callback))
            return "after#1"

    host = DesktopOverlayHost(FakeRoot(), transparent_bg="systemTransparent")  # type: ignore[arg-type]
    host.set_avatar_callbacks(
        enter=lambda *args: calls.append(("enter", args)),
        left_click=lambda *args: calls.append(("left_click", args)),
    )

    assert len(scheduled) == 1
    assert scheduled[0][0] == 16
    poll_avatar_events = scheduled.pop(0)[1]

    host._invoke_avatar_callback("enter")
    host._invoke_avatar_callback("left_click", False)

    assert calls == []
    assert scheduled == []
    poll_avatar_events()
    assert calls == [("enter", ()), ("left_click", (False,))]
    assert len(scheduled) == 1
    assert scheduled[0][0] == 16

    overlay_source = Path("jiume/desktop/overlay.py").read_text(encoding="utf-8")
    apply_source = overlay_source.split("def _apply_appkit_window", 1)[1].split(
        "def _ensure_native_avatar_window",
        1,
    )[0]
    sync_source = overlay_source.split("def _sync_tk_from_native_frame", 1)[1].split(
        "def _invoke_avatar_callback",
        1,
    )[0]
    callback_source = overlay_source.split("def _invoke_avatar_callback", 1)[1].split(
        "def _queue_avatar_event",
        1,
    )[0]
    assert "window.update_idletasks()" in apply_source
    assert "NSApplication.sharedApplication().windows()" in apply_source
    assert "def _drain_avatar_events" in overlay_source
    assert "def _queue_avatar_event" in overlay_source
    assert "_queue_avatar_event" in callback_source
    assert "self.root.after" not in sync_source
    assert "self.root." not in sync_source
    assert "self.root.after" not in callback_source
    assert "window.update_idletasks()" not in callback_source
    assert "NSApplication.sharedApplication().windows()" not in callback_source


def test_desktop_background_callbacks_use_ui_queue_instead_of_thread_tk_after() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    watch_source = app_source.split("def _watch_state_file", 1)[1].split(
        "def _apply_external_state",
        1,
    )[0]
    gateway_post_source = app_source.split("def _post_gateway_event", 1)[1].split(
        "def _handle_gateway_event",
        1,
    )[0]
    approval_post_source = app_source.split("def _post_approval_result", 1)[1].split(
        "def _handle_approval_result",
        1,
    )[0]

    assert "def _post_to_ui" in app_source
    assert "def _drain_ui_events" in app_source
    assert "self._post_to_ui(self._reload_active_if_changed)" in watch_source
    assert "self._post_to_ui(lambda s=state, m=message, t=twin_id:" in watch_source
    assert "self._post_to_ui(lambda: self._handle_gateway_event(message, event))" in gateway_post_source
    assert "self._post_to_ui(lambda: self._handle_approval_result(label, event))" in approval_post_source
    assert "self.root.after" not in watch_source
    assert "self.root.after" not in gateway_post_source
    assert "self.root.after" not in approval_post_source


def test_hover_prompt_layer_is_disabled_instead_of_opening_legacy_dialogue() -> None:
    assert hasattr(desktop_app, "_hover_prompt_chip_specs")
    chips = desktop_app._hover_prompt_chip_specs()
    assert chips == []

    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    hover_enter_source = app_source.split("def _on_avatar_enter", 1)[1].split(
        "def set_state",
        1,
    )[0]
    show_hover_source = app_source.split("def _show_hover_menu", 1)[1].split(
        "def _position_hover_menu",
        1,
    )[0]

    assert 'self._show_hover_menu(mode="prompt")' not in hover_enter_source
    assert "show_bubble(" not in hover_enter_source
    assert "if _legacy_dialogue_layers_disabled():" in show_hover_source
    assert show_hover_source.index("if _legacy_dialogue_layers_disabled():") < show_hover_source.index(
        "self._draw_hover_menu()"
    )


def test_single_dialogue_hover_is_read_only_status_without_buttons() -> None:
    assert desktop_app._hover_prompt_chip_specs() == []

    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._hover_mode = "prompt"
    avatar._state = "working"
    avatar._activity_items = [{"kind": "processing", "title": "整理报告", "detail": "提取行动项"}]
    avatar._pending_approval = None
    avatar._active_skill_context = None

    image, zones = desktop_app.JiuMeDesktopAvatar._native_hover_menu_image(avatar)

    assert image.mode == "RGBA"
    assert zones == []


def test_right_click_cards_are_state_aware_and_limited_to_four() -> None:
    assert hasattr(desktop_app, "_floating_card_action_specs")

    default = desktop_app._floating_card_action_specs(
        state="idle",
        has_pending_approval=False,
        active_skill=None,
        latest_activity=None,
    )
    approval = desktop_app._floating_card_action_specs(
        state="waiting_approval",
        has_pending_approval=True,
        active_skill=None,
        latest_activity={"kind": "approval", "title": "需要确认"},
    )
    active_task = desktop_app._floating_card_action_specs(
        state="working",
        has_pending_approval=False,
        active_skill={"id": "meeting-minutes", "displayName": "会议纪要"},
        latest_activity={"kind": "processing", "title": "正在整理"},
    )

    shell_ids = ["settings", "quit"]
    assert [item["id"] for item in default] == shell_ids
    assert [item["id"] for item in approval] == shell_ids
    assert [item["id"] for item in active_task] == shell_ids

    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    open_menu_source = app_source.split("def _open_menu", 1)[1].split(
        "def _redirect_first_run_to_setup",
        1,
    )[0]
    cards_source = app_source.split("def _draw_floating_cards", 1)[1].split(
        "def _show_hover_menu",
        1,
    )[0]

    assert "_show_shell_menu" in open_menu_source
    assert 'mode="cards"' not in open_menu_source
    assert "show_bubble(" not in open_menu_source
    assert "_floating_card_action_specs(" in cards_source
    assert "floating_card_" in cards_source
    assert "for index, spec in enumerate(specs[:4])" in cards_source


def test_right_click_menu_is_shell_only_not_task_control() -> None:
    specs = _avatar_context_action_specs()
    ids = [item["id"] for item in specs]

    assert ids == ["settings", "quit"]
    assert not {"talk", "skills", "progress", "approval_accept", "approval_reject"} & set(ids)

    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    open_menu_source = app_source.split("def _open_menu", 1)[1].split(
        "def _redirect_first_run_to_setup",
        1,
    )[0]

    assert "_show_shell_menu" in open_menu_source
    assert 'mode="cards"' not in open_menu_source
    assert "_run_floating_card_action" not in open_menu_source


def test_avatar_shell_menu_has_only_settings_and_quit() -> None:
    specs = _avatar_context_action_specs()
    ids = [item["id"] for item in specs]
    labels = [item["label"] for item in specs]

    assert ids == ["settings", "quit"]
    assert labels == ["设置", "退出 JiuMe"]
    assert not {"tuck", "reset_opacity", "bottom_right", "progress", "skills", "approval_accept"} & set(ids)

    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    context_source = app_source.split("def _run_avatar_context_action", 1)[1].split("def _start_drag", 1)[0]
    assert 'if action == "settings":' in context_source
    assert 'if action == "quit":' in context_source
    assert 'if action == "tuck":' not in context_source
    assert 'if action == "reset_opacity":' not in context_source
    assert 'if action == "bottom_right":' not in context_source


def test_settings_remains_the_advanced_entry_after_daily_simplification(monkeypatch: pytest.MonkeyPatch) -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    calls: list[str] = []
    avatar.open_settings = lambda: calls.append("settings")  # type: ignore[method-assign]
    avatar.root = type("Root", (), {"destroy": lambda self: calls.append("quit")})()

    JiuMeDesktopAvatar._run_avatar_context_action(avatar, "settings")

    assert calls == ["settings"]
    assert {"skills", "artifacts", "history"}.issubset({section["id"] for section in SETTINGS_CENTER_SECTIONS})


def test_jiume_docs_describe_one_line_daily_surface() -> None:
    zh = Path("docs/zh/JiuMe.md").read_text(encoding="utf-8")
    en = Path("docs/en/JiuMe.md").read_text(encoding="utf-8")

    assert "单击头像，输入一句话" in zh
    assert "one-line" in en.lower()
    assert "掷骰子" not in zh
    assert "draw lot" not in en.lower()


def test_left_click_daily_surface_defaults_to_one_line_composer_only() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    open_direct_source = app_source.split("def open_direct_chat", 1)[1].split(
        "def _open_native_direct_surface",
        1,
    )[0]
    show_bubble_source = app_source.split("def show_bubble", 1)[1].split(
        "def _position_bubble",
        1,
    )[0]

    assert "_focus_direct_feature_layer()" not in open_direct_source
    assert "_rebuild_direct_chat_rows()" not in open_direct_source
    assert "ONE_LINE_INPUT_HINT" in open_direct_source
    assert "chat.title(" not in open_direct_source
    assert "close_button =" not in open_direct_source
    assert "DIRECT_CHAT_CHROME_HEIGHT" not in open_direct_source
    assert "_direct_chat_suppresses_speech(self._native_direct_chat_visible, state)" in show_bubble_source


def test_daily_entry_points_do_not_expose_legacy_action_labels() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    open_direct_source = app_source.split("def open_direct_chat", 1)[1].split(
        "def _open_native_direct_surface",
        1,
    )[0]
    native_chat_source = app_source.split("def _native_direct_chat_image", 1)[1].split(
        "def _native_direct_feature_image",
        1,
    )[0]
    forbidden_labels = (
        "看屏幕",
        "贴材料",
        "选文件",
        "打开技能货架",
        "看任务进度",
        "打开产物列表",
        "猜拳",
        "掷骰子",
        "抽签",
    )

    for label in forbidden_labels:
        assert label not in open_direct_source
        assert label not in native_chat_source


def test_native_daily_chat_has_one_send_control() -> None:
    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._chat_items = [
        {"role": "user", "text": "帮我整理报告"},
        {"role": "assistant", "text": "收到，我开始处理。"},
    ]
    avatar._active_twin = lambda: {"displayName": "JiuMe"}  # type: ignore[method-assign]
    avatar._has_active_work_context = lambda: False  # type: ignore[method-assign]

    idle_image, idle_zones, idle_input = desktop_app.JiuMeDesktopAvatar._native_direct_chat_image(
        avatar,
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=desktop_app.DIRECT_CHAT_MIN_HEIGHT,
    )

    assert [zone[4] for zone in idle_zones] == ["send"]
    assert idle_input["action_label"] == "发送"
    assert idle_input["placeholder"] == ONE_LINE_INPUT_HINT
    button_rgb = tuple(int(desktop_app.DIRECT_ACTION_BG[index : index + 2], 16) for index in (1, 3, 5))
    idle_x, idle_y, *_ = idle_zones[0]
    assert idle_image.getpixel((idle_x + 8, idle_y + 18))[:3] == button_rgb


def test_native_direct_chat_scroll_moves_between_history_windows() -> None:
    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._chat_items = [
        {"role": "user", "text": f"message {index}"}
        for index in range(6)
    ]
    avatar._direct_chat_scroll_offset = 0
    avatar._native_direct_surface = "chat"
    calls: list[str] = []
    avatar._position_direct_chat = lambda: calls.append("position")  # type: ignore[method-assign]

    assert [item["text"] for item in _conversation_preview_items(avatar._chat_items)] == [
        "message 3",
        "message 4",
        "message 5",
    ]

    desktop_app.JiuMeDesktopAvatar._handle_native_direct_scroll(avatar, 1.0)

    assert avatar._direct_chat_scroll_offset == 1
    assert calls == ["position"]
    assert [
        item["text"]
        for item in _conversation_preview_items(
            avatar._chat_items,
            offset=avatar._direct_chat_scroll_offset,
        )
    ] == ["message 2", "message 3", "message 4"]

    desktop_app.JiuMeDesktopAvatar._handle_native_direct_scroll(avatar, -1.0)

    assert avatar._direct_chat_scroll_offset == 0


def test_native_daily_chat_history_and_scroll_do_not_affect_composer_rendering() -> None:
    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._chat_items = []
    avatar._direct_chat_scroll_offset = 0
    empty_image, empty_zones, empty_input = desktop_app.JiuMeDesktopAvatar._native_direct_chat_image(
        avatar,
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=desktop_app.DIRECT_CHAT_MIN_HEIGHT,
    )

    avatar._chat_items = [
        {"role": "user", "text": f"history item {index}"}
        for index in range(12)
    ]
    avatar._direct_chat_scroll_offset = 7
    history_image, history_zones, history_input = desktop_app.JiuMeDesktopAvatar._native_direct_chat_image(
        avatar,
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=desktop_app.DIRECT_CHAT_MIN_HEIGHT,
    )

    assert empty_image.tobytes() == history_image.tobytes()
    assert empty_zones == history_zones
    assert empty_input["frame"] == history_input["frame"]
    assert history_input["action_label"] == "发送"


def test_native_direct_chat_keeps_entry_controls_clickable_without_double_placeholder() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    native_chat_source = app_source.split("def _native_direct_chat_image", 1)[1].split(
        "def _native_direct_feature_image",
        1,
    )[0]
    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._chat_items = [{"role": "assistant", "text": "我在。"}]
    avatar._active_twin = lambda: {"displayName": "JiuMe"}  # type: ignore[method-assign]
    avatar._has_active_work_context = lambda: False  # type: ignore[method-assign]

    image, zones, text_input = desktop_app.JiuMeDesktopAvatar._native_direct_chat_image(
        avatar,
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=desktop_app.DIRECT_CHAT_MIN_HEIGHT,
    )

    assert image.mode == "RGBA"
    assert [zone[4] for zone in zones] == ["send"]
    assert text_input["placeholder"] == ONE_LINE_INPUT_HINT
    assert text_input["action_label"] == "发送"
    assert text_input["font_size"] == 14
    assert text_input["text_color"] == desktop_app.INK
    hi_res_image, _, _ = desktop_app.JiuMeDesktopAvatar._native_direct_chat_image(
        avatar,
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=desktop_app.DIRECT_CHAT_MIN_HEIGHT,
        render_scale=2,
    )
    assert hi_res_image.size == (desktop_app.DIRECT_CHAT_WIDTH * 2, desktop_app.DIRECT_CHAT_MIN_HEIGHT * 2)
    assert desktop_app.DIRECT_ACTION_BG == "#071215"
    assert "_conversation_preview_items(" not in native_chat_source
    assert "_has_active_work_context" not in native_chat_source
    assert "run_submit" not in native_chat_source
    assert '"stop"' not in native_chat_source
    assert "nav_specs = (" not in native_chat_source
    assert '"skills"' not in native_chat_source
    assert '"progress"' not in native_chat_source
    assert "draw.line(" not in native_chat_source
    assert "DIRECT_CHAMPAGNE" not in native_chat_source
    assert "DIRECT_INPUT_BG" in native_chat_source
    assert "_chat_heading" not in native_chat_source
    assert "DIRECT_GLASS_MIST_ALPHA" not in native_chat_source
    assert 'draw.text((entry_x, entry_y + 2), "对分身说一句..."' not in native_chat_source


def test_native_daily_position_uses_fixed_one_line_height_without_history_scroll() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    native_position_source = app_source.split("def _position_native_direct_chat", 1)[1].split(
        "def _handle_native_direct_scroll",
        1,
    )[0]

    assert "natural_height = ONE_LINE_DIRECT_HEIGHT" in native_position_source
    assert "_conversation_preview_items(" not in native_position_source
    assert "_conversation_max_scroll_offset(" not in native_position_source
    assert "on_scroll=self._handle_native_direct_scroll" not in native_position_source


def test_native_direct_feature_surfaces_are_not_all_chat_dialogs() -> None:
    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._chat_items = [{"role": "assistant", "text": "我在。"}]
    avatar._active_twin = lambda: {  # type: ignore[method-assign]
        "displayName": "小九",
        "purpose": "写作搭档",
        "tone": "warm and concise",
        "permissions": {"defaultMode": "read_only"},
        "appearance": {"id": "mint", "label": "薄荷绿", "outfitColor": "#10B981"},
    }
    avatar._direct_skill_rows = lambda: [  # type: ignore[method-assign]
        {"id": "meeting-minutes", "displayName": "会议纪要精炼团队", "isEnabled": True},
        {"id": "data-analysis", "displayName": "数据分析团队", "isEnabled": False},
    ]
    avatar._active_skill_context = None
    avatar._activity_items = [{"kind": "processing", "title": "整理报告", "detail": "提取行动项"}]
    avatar._direct_settings_section = "identity"
    avatar._direct_skill_section = "recommended"
    avatar._native_direct_surface = "chat"
    avatar._has_active_work_context = lambda: False  # type: ignore[method-assign]

    chat_image, chat_zones, chat_input = desktop_app.JiuMeDesktopAvatar._native_direct_surface_image(
        avatar,
        surface="chat",
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=220,
    )
    settings_image, settings_zones, settings_input = desktop_app.JiuMeDesktopAvatar._native_direct_surface_image(
        avatar,
        surface="settings",
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=220,
    )
    skills_image, skills_zones, skills_input = desktop_app.JiuMeDesktopAvatar._native_direct_surface_image(
        avatar,
        surface="skills",
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=220,
    )
    progress_image, progress_zones, progress_input = desktop_app.JiuMeDesktopAvatar._native_direct_surface_image(
        avatar,
        surface="progress",
        width=desktop_app.DIRECT_CHAT_WIDTH,
        height=220,
    )

    assert [zone[4] for zone in chat_zones] == ["send"]
    assert chat_input["action_label"] == "发送"
    assert "settings:identity" in [zone[4] for zone in settings_zones]
    assert "skill:meeting-minutes" in [zone[4] for zone in skills_zones]
    assert "progress:detail" in [zone[4] for zone in progress_zones]
    assert settings_input["placeholder"] != chat_input["placeholder"]
    assert skills_input["placeholder"] != chat_input["placeholder"]
    assert progress_input["placeholder"] != chat_input["placeholder"]
    assert len({chat_image.tobytes(), settings_image.tobytes(), skills_image.tobytes(), progress_image.tobytes()}) == 4


def test_direct_skill_shortcuts_prioritize_avatar_ready_skills() -> None:
    rows = [
        {"id": "meeting-minutes", "displayName": "会议纪要精炼团队", "isEnabled": True, "risk": "low"},
        {
            "id": "knowledge-research",
            "displayName": "知识研究员",
            "isEnabled": False,
            "risk": "medium",
            "summary": "帮你把开放问题变成可执行的研究线索。",
        },
        {"id": "prd-review", "displayName": "PRD评审委员会", "isEnabled": False, "risk": "high"},
        {"id": "extra", "displayName": "Extra", "isEnabled": False, "risk": "low"},
    ]

    shortcuts = _direct_skill_shortcuts(rows)
    suggestions = _skill_picker_suggestions(rows)
    reply = _skill_picker_reply(suggestions)

    assert [item["id"] for item in shortcuts] == ["meeting-minutes", "knowledge-research", "prd-review"]
    assert shortcuts[0]["isEnabled"] is True
    assert len(shortcuts[0]["displayName"]) <= 18
    assert [item["id"] for item in suggestions] == ["meeting-minutes", "knowledge-research", "prd-review"]
    assert suggestions[0]["isEnabled"] is True
    assert "研究线索" in suggestions[1]["summary"]
    assert "头像旁" in reply["detail"]
    assert "展开 skill" in reply["detail"]
    assert "直接说任务" in reply["detail"]
    assert "更多" in reply["detail"]
    assert "完整技能货架" not in reply["detail"]
    assert "告诉我要处理什么" in _skill_picker_reply([])["detail"]
    assert _direct_skill_overflow_count(rows) == 1
    assert _direct_skill_overflow_count(rows[:3]) == 0
    assert [item["id"] for item in _active_skill_material_action_specs()] == ["screen", "clipboard", "file"]
    assert all(item["label"] for item in _active_skill_material_action_specs())
    assert [item["id"] for item in _direct_skill_section_specs()] == ["recommended", "current", "more"]
    assert [item["id"] for item in _direct_skill_section_specs(has_active_skill=True)] == [
        "recommended",
        "current",
        "materials",
        "more",
    ]
    assert _normalize_direct_skill_section("materials", has_active_skill=True) == "materials"
    assert _normalize_direct_skill_section("materials") == "recommended"
    assert _normalize_direct_skill_section("unknown", has_active_skill=True) == "recommended"
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    assert "打开完整技能货架" not in app_source
    assert "command=self.open_panel" not in app_source
    assert "avatar.root.after(500, avatar.open_panel)" not in app_source
    open_panel_source = app_source.split("def open_panel", 1)[1].split(
        "def _open_legacy_panel",
        1,
    )[0]
    legacy_panel_source = app_source.split("def _open_legacy_panel", 1)[1].split("def _append_chat", 1)[0]
    legacy_chat_source = app_source.split("def _rebuild_chat_rows", 1)[1].split(
        "def _rebuild_direct_chat_rows",
        1,
    )[0]
    legacy_position_source = app_source.split("def _position_panel", 1)[1].split(
        "def open_settings",
        1,
    )[0]
    assert "self.open_direct_chat()" in open_panel_source
    assert "return" in open_panel_source
    assert "panel = tk.Toplevel" not in open_panel_source
    assert "Legacy boxed control panel is retired" in legacy_panel_source
    assert "self.open_panel()" in legacy_panel_source
    assert "panel = tk.Toplevel" not in legacy_panel_source
    assert "Legacy boxed chat log is retired" in legacy_chat_source
    assert "tk.Label(" not in legacy_chat_source
    assert "tk.Frame(" not in legacy_chat_source
    assert "Legacy boxed control panel is retired" in legacy_position_source
    assert "geometry(" not in legacy_position_source
    assert "footer = tk.Frame(shell" not in app_source
    assert "self._direct_settings_frame = tk.Frame(content, bg=DIRECT_LAYER_SOFT" not in app_source
    assert "self._direct_companion_frame = tk.Frame(content, bg=DIRECT_LAYER_SOFT" not in app_source
    assert "self._direct_service_frame = tk.Frame(content, bg=DIRECT_LAYER_SOFT" not in app_source
    assert "self._direct_approval_frame = tk.Frame(content, bg=DIRECT_LAYER_SOFT" not in app_source
    assert 'bg="#F1FFF5", highlightthickness=1' not in app_source
    assert "row = tk.Frame(self._direct_skills_frame, bg=DIRECT_LAYER_BG, highlightthickness=1" not in app_source
    direct_approval_source = app_source.split("def _rebuild_direct_approval_card", 1)[1].split(
        "def _direct_quick_actions",
        1,
    )[0]
    assert 'text=prompt,\n            bg="#FFFFFF"' not in direct_approval_source
    assert "self._direct_artifact_frame = tk.Frame(content, bg=layer_bg" not in app_source
    assert 'panel.title("JiuMe Artifacts")' not in app_source
    assert 'panel.title("JiuMe Artifact")' not in app_source
    assert 'panel.title("JiuMe Image Artifact")' not in app_source
    assert "def _pack_direct_bubble_buttons" in app_source
    skill_source = app_source.split("def _rebuild_direct_skill_shortcuts", 1)[1].split(
        "def _run_active_skill_material_action",
        1,
    )[0]
    legacy_skill_source = app_source.split("def _rebuild_skill_rows", 1)[1].split(
        "def _install_local_skill_from_panel",
        1,
    )[0]
    open_skill_source = app_source.split("def _open_skill_shelf_from_direct", 1)[1].split(
        "def _set_active_skill_context",
        1,
    )[0]
    legacy_quick_source = app_source.split("def _rebuild_quick_action_rows", 1)[1].split(
        "def _run_quick_action",
        1,
    )[0]
    assert "_pack_direct_bubble_buttons" in skill_source
    assert "_pack_direct_speech_bubble" in skill_source
    assert "_pack_direct_value_bubbles" in skill_source
    assert 'self._direct_skill_section = "recommended"' in open_skill_source
    assert "self._direct_skills_picker_visible = False" in open_skill_source
    assert "self._direct_skills_detail_visible = False" in open_skill_source
    assert "self._direct_skills_picker_visible" in skill_source
    assert "self._direct_skills_detail_visible" in skill_source
    assert "skill 先不全部展开。你可以直接说任务，或只打开推荐、当前、更多这一层。" in skill_source
    assert "先选一个 skill 层，我再只展开那一层。" in skill_source
    assert "展开 skill" in skill_source
    assert 'self._focus_direct_feature_layer({"skills"})' in open_skill_source
    hover_action_source = app_source.split("def _run_hover_menu_action", 1)[1].split(
        "def _on_avatar_enter",
        1,
    )[0]
    assert 'self._focus_direct_feature_layer({"skills"})' in hover_action_source
    assert "self.open_settings()" in hover_action_source
    assert 'self._focus_direct_feature_layer({"settings"})' not in hover_action_source
    assert 'self._focus_direct_feature_layer({"activity", "approval", "artifacts"})' in hover_action_source
    assert "_open_direct_skill_detail_layer" in app_source
    assert "_hide_direct_skill_layer" in app_source
    assert "_focus_direct_entry_for_skill" in app_source
    open_skill_layer_source = app_source.split("def _open_direct_skill_detail_layer", 1)[1].split(
        "def _hide_direct_skill_layer",
        1,
    )[0]
    assert "self._direct_skills_picker_visible = True" in open_skill_layer_source
    assert "self._direct_skills_detail_visible = False" in open_skill_layer_source
    assert "if not self._direct_skills_detail_visible and not self._direct_skills_picker_visible" in skill_source
    assert "if self._direct_skills_picker_visible and not self._direct_skills_detail_visible" in skill_source
    assert "self._direct_skills_detail_visible = True" in app_source
    assert "我把 skill 入口放到头像旁边了。" in app_source
    assert "section_row = tk.Frame(self._direct_skills_frame" not in skill_source
    assert "material_row = tk.Frame" not in skill_source
    assert "row = tk.Frame(self._direct_skills_frame" not in skill_source
    assert "tk.Button(" not in skill_source
    assert "tk.Label(" not in skill_source
    assert "Legacy boxed skill shelf is retired" in legacy_skill_source
    assert "tk.Button(" not in legacy_skill_source
    assert "tk.Label(" not in legacy_skill_source
    assert "highlightthickness=1" not in legacy_skill_source
    assert "Legacy boxed quick actions are retired" in legacy_quick_source
    assert "tk.Button(" not in legacy_quick_source
    assert 'bg=ACCENT if active else "#EFE9DF"' not in skill_source


def test_direct_quick_actions_prioritize_avatar_ready_work_starts() -> None:
    shortcuts = _direct_quick_action_shortcuts(quick_actions())

    assert [item["id"] for item in shortcuts] == ["focus", "today", "skill_picker"]
    assert all(item["state"] == "thinking" for item in shortcuts)
    assert all(len(item["label"]) <= 10 for item in shortcuts)
    assert _direct_quick_action_shortcuts([{"id": "rest", "label": "休息", "kind": "local"}]) == []


def test_direct_help_actions_collapse_to_one_line_daily_entry() -> None:
    specs = _direct_help_action_specs()
    ids = [spec["id"] for spec in specs]

    assert ids == ["talk", "settings"]
    assert [spec["label"] for spec in specs] == ["说一句", "设置"]
    assert _direct_help_section_specs() == []
    assert _normalize_direct_help_section("unknown") == "overview"
    assert _normalize_direct_help_section("materials") == "overview"
    assert _normalize_direct_help_section("play") == "overview"
    assert _direct_help_action_specs("talk") == specs
    assert _direct_help_action_specs("play") == specs
    assert _direct_help_action_specs("skills") == specs
    assert _direct_help_action_specs("materials") == specs
    assert _direct_help_action_specs("progress") == specs
    assert _direct_help_action_specs("settings") == specs
    assert [item["id"] for item in _direct_play_action_specs()] == ["rps", "dice", "coin"]
    assert [item["id"] for item in _direct_play_action_specs({"coin"})] == ["rps", "dice"]
    assert all(spec["label"] for spec in specs)
    assert all(daily_label not in {spec["label"] for spec in specs} for daily_label in DAILY_FORBIDDEN_LABELS)


def test_hover_menu_entry_points_stay_disabled_and_right_click_stays_shell_only() -> None:
    specs = _hover_menu_action_specs()
    context_specs = _avatar_context_action_specs()

    assert specs == []
    assert [item["id"] for item in context_specs] == ["settings", "quit"]
    assert [item["label"] for item in context_specs] == ["设置", "退出 JiuMe"]
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    assert 'self.label.bind("<Enter>", self._on_avatar_enter)' in app_source
    assert "悬浮我先看四个入口；单击就直接说话。" not in app_source
    assert "右键也能装载技能" not in app_source
    open_menu_source = app_source.split("def _open_menu", 1)[1].split("def _redirect_first_run_to_setup", 1)[0]
    context_source = app_source.split("def _run_avatar_context_action", 1)[1].split("def _start_drag", 1)[0]
    hover_enter_source = app_source.split("def _on_avatar_enter", 1)[1].split("def set_state", 1)[0]
    show_hover_source = app_source.split("def _show_hover_menu", 1)[1].split("def _position_hover_menu", 1)[0]
    position_hover_source = app_source.split("def _position_hover_menu", 1)[1].split("def _hide_hover_menu", 1)[0]
    shell_menu_source = app_source.split("def _show_shell_menu", 1)[1].split("def _open_menu", 1)[0]
    assert "self._show_shell_menu(event)" in open_menu_source
    assert 'mode="cards"' not in open_menu_source
    assert "tk.Menu" in shell_menu_source
    assert "menu.add_command" in shell_menu_source
    assert "menu.tk_popup" in shell_menu_source
    assert 'self._show_hover_menu(mode="prompt")' not in hover_enter_source
    assert "show_bubble(" not in hover_enter_source
    assert show_hover_source.index("if _legacy_dialogue_layers_disabled():") < show_hover_source.index("tk.Toplevel")
    assert position_hover_source.index("if _legacy_dialogue_layers_disabled():") < position_hover_source.index(
        "_native_hover_menu_image"
    )
    init_source = app_source.split("def __init__", 1)[1].split("def _load_initial", 1)[0]
    assert "self.root.after(900, self._restore_work_hud_from_history)" not in init_source
    assert "_show_native_onboarding" not in init_source
    assert 'lambda: self.show_bubble("悬浮我先看四个入口；单击就直接说话。"' not in init_source
    assert "if self._idle_companion_enabled:\n            self._schedule_idle_companion()" in init_source
    assert 'if action == "settings":' in context_source
    assert 'if action == "quit":' in context_source
    assert 'if action == "tuck":' not in context_source
    assert 'if action == "reset_opacity":' not in context_source
    assert 'if action == "bottom_right":' not in context_source
    assert "tk_popup" not in open_menu_source
    assert "show_bubble(" not in open_menu_source


def test_unhandled_direct_actions_fall_back_to_avatar_conversation() -> None:
    help_reply = _direct_unhandled_action_reply("help")
    task_reply = _direct_unhandled_action_reply("activity")
    material_reply = _direct_unhandled_action_reply("skill_material")

    assert help_reply["label"] == "未知能力入口"
    assert task_reply["label"] == "未知任务入口"
    assert material_reply["label"] == "未知材料入口"
    assert help_reply["state"] == "speaking"
    assert "对话放到你旁边" in help_reply["line"]
    assert "直接说下一步" in help_reply["line"]
    assert "还没准备好" not in help_reply["line"]


def test_clipboard_material_payload_turns_text_and_paths_into_agent_messages(tmp_path: Path) -> None:
    text_payload = _clipboard_material_payload("  summarize this note\nwith constraints  ")

    assert text_payload is not None
    assert text_payload["kind"] == "text"
    assert text_payload["detail"] == "summarize this note"
    assert "请处理我从剪贴板交给你的材料" in text_payload["message"]

    preview, truncated = _clipboard_text_preview("abcdefghijk", limit=8)
    assert preview == "abcdefg…"
    assert truncated is True

    first = tmp_path / "brief.md"
    second = tmp_path / "space name.txt"
    first.write_text("brief", encoding="utf-8")
    second.write_text("space", encoding="utf-8")
    raw_paths = f"{first}\n{second.as_uri()}"

    targets = _clipboard_file_targets(raw_paths)
    file_payload = _clipboard_material_payload(raw_paths)

    assert targets == [str(first.resolve()), str(second.resolve())]
    assert file_payload is not None
    assert file_payload["kind"] == "files"
    assert "brief.md" in file_payload["detail"]
    assert str(second.resolve()) in file_payload["message"]
    assert _clipboard_material_payload("docs/readme.md")["kind"] == "text"


def test_file_material_payload_classifies_selected_files(tmp_path: Path) -> None:
    image = tmp_path / "screen.png"
    code = tmp_path / "main.py"
    table = tmp_path / "data.csv"
    missing = tmp_path / "missing.txt"
    image.write_bytes(b"png")
    code.write_text("print('hi')", encoding="utf-8")
    table.write_text("a,b\n1,2", encoding="utf-8")

    payload = _file_material_payload([image, code, table, missing])

    assert payload is not None
    assert payload["title"] == "文件材料：3 个文件"
    assert "screen.png" in payload["detail"]
    assert str(code.resolve()) in payload["message"]
    assert [item["category"] for item in payload["artifacts"]] == ["image", "code", "table"]
    assert _file_material_payload([missing]) is None


def test_direct_path_material_payload_accepts_pasted_local_paths(tmp_path: Path) -> None:
    note = tmp_path / "brief.md"
    image = tmp_path / "diagram.png"
    note.write_text("brief", encoding="utf-8")
    image.write_bytes(b"png")

    payload = _direct_path_material_payload(f'"{note}"\n{image.as_uri()}')

    assert payload is not None
    assert payload["kind"] == "files"
    assert payload["title"] == "路径材料：2 个文件"
    assert "brief.md" in payload["detail"]
    assert str(image.resolve()) in payload["message"]
    assert [item["category"] for item in payload["artifacts"]] == ["text", "image"]
    assert _direct_path_material_payload("帮我整理这段会议纪要") is None
    assert _direct_path_material_payload(str(tmp_path / "missing.txt")) is None


def test_screen_context_payload_is_agent_ready(tmp_path: Path) -> None:
    path = _screen_capture_path(tmp_path, timestamp="2026/05/22 10:24")
    payload = _screen_material_payload(path)

    assert path == tmp_path / "screen_context" / "screen-2026-05-22-10-24.png"
    assert payload["kind"] == "screen"
    assert payload["artifact"]["category"] == "image"
    assert payload["artifact"]["mime"] == "image/png"
    assert str(path) in payload["message"]


def test_direct_settings_snapshot_and_payload_are_avatar_ready() -> None:
    twin = {
        "displayName": "Ada",
        "purpose": "Help Ada stay focused.",
        "tone": "warm and concise",
        "appearance": {"id": "purple"},
        "permissions": {"defaultMode": "draft"},
    }

    snapshot = _direct_settings_snapshot(twin)
    payload = _direct_settings_payload(
        "direct and action-oriented",
        "autonomous",
        display_name="Ada JiuMe",
        purpose="Draft and review with me.",
        appearance="sun",
    )

    assert snapshot["displayName"] == "Ada"
    assert snapshot["purpose"] == "Help Ada stay focused."
    assert snapshot["appearanceLabel"] == "葡萄紫"
    assert snapshot["defaultMode"] == "draft"
    assert snapshot["defaultModeLabel"] == "先起草"
    assert payload == {
        "displayName": "Ada JiuMe",
        "purpose": "Draft and review with me.",
        "tone": "direct and action-oriented",
        "appearance": normalize_twin_appearance("sun"),
        "permissions": {"defaultMode": "autonomous"},
    }
    assert _direct_settings_payload("", "", display_name="  ")["displayName"] == "JiuMe"
    assert _permission_mode_label("not-real") == "行动前确认"
    assert [item["id"] for item in _direct_settings_section_specs()] == [
        "identity",
        "tone",
        "permission",
        "appearance",
        "size",
    ]
    assert _normalize_direct_settings_section("tone") == "tone"
    assert _normalize_direct_settings_section("not-real") == "identity"
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    assert "完整设置" not in app_source
    open_settings_source = app_source.split("def open_settings", 1)[1].split(
        "def _open_legacy_settings_panel",
        1,
    )[0]
    legacy_settings_source = app_source.split("def _open_legacy_settings_panel", 1)[1].split(
        "def _close_settings",
        1,
    )[0]
    close_settings_source = app_source.split("def _close_settings", 1)[1].split(
        "def _record_activity",
        1,
    )[0]
    assert "self._settings_panel" not in app_source
    assert "_settings_panel: tk.Toplevel" not in app_source
    assert "_settings_vars" not in app_source
    assert "def _position_settings" not in app_source
    assert "self._settings_center.open()" in open_settings_source
    assert "self.open_direct_chat()" not in open_settings_source
    assert "_focus_direct_feature_layer" not in open_settings_source
    assert "_rebuild_direct_settings_card" not in open_settings_source
    assert 'panel.title("JiuMe Settings")' not in open_settings_source
    assert "self.open_settings()" in legacy_settings_source
    assert 'panel.title("JiuMe Settings")' not in legacy_settings_source
    assert "self._direct_settings_visible = False" in close_settings_source
    assert "destroy()" not in close_settings_source
    settings_source = app_source.split("def _rebuild_direct_settings_card", 1)[1].split(
        "def _refresh_mock_avatar_assets",
        1,
    )[0]
    assert "_pack_direct_bubble_buttons" in settings_source
    assert "_pack_direct_speech_bubble" in app_source
    assert "_pack_direct_speech_bubble(" in settings_source
    assert "_pack_direct_value_bubbles" in app_source
    assert "_pack_direct_value_bubbles" in settings_source
    value_bubble_source = app_source.split("def _pack_direct_value_bubbles", 1)[1].split(
        "def _pack_direct_text_preview_bubble",
        1,
    )[0]
    assert "for index, item in enumerate(items):" in value_bubble_source
    assert "from_user_side = index % 2 == 1" in value_bubble_source
    assert "bubble.pack(anchor=anchor_side" in value_bubble_source
    assert "direct_value_tail" not in value_bubble_source
    assert "create_polygon" not in value_bubble_source
    assert "bubble_width = _direct_value_bubble_width(label, value)" in value_bubble_source
    assert "width=bubble_width" in value_bubble_source
    assert "width=294" not in value_bubble_source
    assert "width=270" not in value_bubble_source
    assert "width=224" not in value_bubble_source
    assert 'bubble.pack(fill="x"' not in value_bubble_source
    text_preview_source = app_source.split("def _pack_direct_text_preview_bubble", 1)[1].split(
        "def _pack_direct_bubble_entry",
        1,
    )[0]
    assert "width_hint = _direct_text_preview_bubble_width(safe_title, safe_text)" in text_preview_source
    assert "width=width_hint" in text_preview_source
    assert 'bubble.pack(anchor="w"' in text_preview_source
    assert 'bubble.pack(fill="x"' not in text_preview_source
    button_bubble_source = app_source.split("def _pack_direct_bubble_buttons", 1)[1].split(
        "def _show_direct_help_card",
        1,
    )[0]
    assert "spread = max(1, min(3, int(columns or 1)))" in button_bubble_source
    assert "from_user_side = index % 2 == 1" in button_bubble_source
    assert "bubble.pack(\n                anchor=anchor_side" in button_bubble_source
    assert "direct_bubble_button_tail" not in button_bubble_source
    assert "create_polygon" not in button_bubble_source
    assert "row = tk.Frame(shell" not in button_bubble_source
    assert 'bubble.pack(side="left"' not in button_bubble_source
    assert "self._direct_settings_picker_visible" in settings_source
    assert "self._direct_settings_detail_visible" in settings_source
    assert "设置先不全部展开。你可以直接说一句，或只打开一个设置层。" in settings_source
    assert "展开设置" in settings_source
    assert "_open_direct_settings_detail_layer" in app_source
    assert "_hide_direct_settings_layer" in app_source
    open_settings_layer_source = app_source.split("def _open_direct_settings_detail_layer", 1)[1].split(
        "def _hide_direct_settings_layer",
        1,
    )[0]
    assert "self._direct_settings_detail_visible = False" in open_settings_layer_source
    assert "先选一个设置层，我再只展开那一层。" in settings_source
    assert "if not self._direct_settings_detail_visible:\n                self._pack_direct_bubble_buttons" in settings_source
    assert "and not self._direct_settings_detail_visible" in settings_source
    assert "if not self._native_onboarding_pending and self._direct_settings_picker_visible" in settings_source
    assert "换一层" in settings_source
    assert "收起分区" not in settings_source
    assert "_toggle_direct_settings_picker" in app_source
    assert "直接说给我" in settings_source
    assert "以后叫你小九" in settings_source
    assert "_focus_direct_entry_for_settings" in app_source
    assert "sections = tk.Frame(self._direct_settings_frame" not in settings_source
    assert "tk.Label(" not in settings_source
    assert "tk.Entry(" not in settings_source
    assert "tk.Radiobutton(" not in settings_source
    assert "现在的名字" in settings_source
    assert 'bg=ACCENT if active else "#EFE9DF"' not in settings_source
    assert "记住这一层" in settings_source


def test_open_settings_routes_to_settings_center_not_direct_chat_layer() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    open_settings_source = app_source.split("def open_settings", 1)[1].split(
        "def _open_legacy_settings_panel",
        1,
    )[0]

    assert "SettingsCenterWindow" in app_source
    assert "self._settings_center" in app_source
    assert "self._settings_center.open()" in open_settings_source
    assert "self.open_direct_chat()" not in open_settings_source
    assert "_focus_direct_feature_layer" not in open_settings_source
    assert "_rebuild_direct_settings_card" not in open_settings_source
    assert "设置就在头像旁边" not in open_settings_source


def test_user_visible_settings_routes_open_settings_center() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    hover_source = app_source.split("def _run_hover_menu_action", 1)[1].split(
        "def _on_avatar_enter",
        1,
    )[0]
    control_source = app_source.split("def _run_native_control_command", 1)[1].split(
        "def _request_task_interrupt_from_menu",
        1,
    )[0]
    settings_summary_source = app_source.split("def _reply_with_settings_summary", 1)[1].split(
        "def _reply_with_active_skill_summary",
        1,
    )[0]
    native_onboarding_source = app_source.split("def _show_native_onboarding", 1)[1].split(
        "def _toggle_direct_settings",
        1,
    )[0]

    assert "    def _local_reply" not in app_source
    for source in (hover_source, control_source):
        assert "self.open_settings()" in source
        assert '_open_native_direct_surface("settings")' not in source
        assert "_rebuild_direct_settings_card()" not in source
    assert "self.open_settings()" not in settings_summary_source
    assert "_rebuild_direct_settings_card()" not in settings_summary_source
    assert "self.open_settings()" in native_onboarding_source
    assert "_rebuild_direct_settings_card()" not in native_onboarding_source


def test_settings_center_desktop_save_is_defensive_and_live_size_ready() -> None:
    settings_source = Path("jiume/desktop/settings_center.py").read_text(encoding="utf-8")
    save_desktop_source = settings_source.split("def _save_desktop", 1)[1].split(
        "def _save_agent_config",
        1,
    )[0]
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    saved_callback_source = app_source.split("def _after_settings_center_saved", 1)[1].split(
        "def _open_legacy_settings_panel",
        1,
    )[0]

    assert "tk.StringVar(master=self.root" in settings_source
    assert "头像大小请输入数字" in save_desktop_source
    assert "int(self.size_var.get()" not in save_desktop_source
    assert 'state.get("x") or 0' not in save_desktop_source
    assert '_widget_int(self.root, "winfo_x", 0)' in save_desktop_source
    assert "_set_avatar_size(" in saved_callback_source


def test_settings_center_sections_cover_full_configuration() -> None:
    assert [section["id"] for section in SETTINGS_CENTER_SECTIONS] == [
        "profile",
        "desktop",
        "image_model",
        "skills",
        "artifacts",
        "history",
        "diagnostics",
    ]
    assert [section["label"] for section in SETTINGS_CENTER_SECTIONS] == [
        "分身",
        "桌面",
        "图片模型",
        "技能",
        "产物",
        "历史",
        "诊断",
    ]


def test_settings_center_window_class_is_setup_style_not_transcript() -> None:
    source = Path("jiume/desktop/settings_center.py").read_text(encoding="utf-8")

    assert "class SettingsCenterWindow" in source
    assert 'self.window.title("JiuMe 设置")' in source
    assert "PREMIUM_SETUP_COLORS" in source
    assert "SETTINGS_CENTER_SECTIONS" in source
    assert "_render_image_model_section" in source
    assert "_render_diagnostics_section" in source
    assert "_render_profile_section" in source
    assert "_render_desktop_section" in source
    assert "_render_maintenance_section" not in source
    assert "_chat_items" not in source
    assert "_pack_direct_speech_bubble" not in source
    assert "_direct_settings_frame" not in source


def test_settings_center_agent_snapshot_keeps_diagnostics_out_of_daily_chat() -> None:
    snapshot = build_agent_settings_snapshot(
        service={
            "services": {
                "agent": {"status": "exited", "mode": "managed", "restart_count": 2},
                "setup": {"status": "running"},
            },
            "note": "agent restarted",
        },
        gateway_url="ws://127.0.0.1:19092/ws",
        agent_mode="auto_harness",
    )

    assert snapshot["connectionLabel"] == "Agent 已退出"
    assert snapshot["gatewayUrl"] == "ws://127.0.0.1:19092/ws"
    assert snapshot["agentMode"] == "auto_harness"
    assert snapshot["primaryAction"] == "打开 JiuwenSwarm 配置"
    assert snapshot["secondaryAction"] == "重新检测"
    assert "agent restarted" in snapshot["detail"]


def test_settings_center_never_edits_jiuwenswarm_runtime_model_fields() -> None:
    source = Path("jiume/desktop/settings_center.py").read_text(encoding="utf-8")
    diagnostics_source = source.split("def _render_diagnostics_section", 1)[1].split(
        "def _button_row",
        1,
    )[0]

    assert "_save_agent_config" not in source
    assert "保存 Agent 设置" not in source
    assert 'self._field(body, "API Key"' not in diagnostics_source
    assert 'self._field(body, "Base URL"' not in diagnostics_source
    assert 'self._field(body, "模型"' not in diagnostics_source
    assert "打开 JiuwenSwarm 配置" in diagnostics_source
    assert "重新检测" in diagnostics_source


def test_settings_center_desktop_snapshot_reads_avatar_state() -> None:
    snapshot = build_desktop_settings_snapshot(
        window_state={"x": 120, "y": 240, "size": 168, "opacity": 0.72},
        current_size=144,
        gateway_url="ws://127.0.0.1:19092/ws",
    )

    assert snapshot["size"] == "168"
    assert snapshot["placement"] == "120,240"
    assert snapshot["opacity"] == "72%"
    assert snapshot["gatewayUrl"] == "ws://127.0.0.1:19092/ws"


def test_direct_help_layer_collapses_to_one_line_help_not_button_map() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    help_source = app_source.split("def _show_direct_help_card", 1)[1].split(
        "def _run_direct_help_action",
        1,
    )[0]

    assert "_pack_direct_bubble_buttons" in help_source
    assert "_pack_direct_speech_bubble" in help_source
    assert "单击头像，输入一句话" in help_source
    for label in DAILY_FORBIDDEN_LABELS:
        assert label not in help_source
    assert "section_shell = tk.Frame" not in help_source
    assert "button_shell = tk.Frame" not in help_source
    assert "tk.Button(" not in help_source
    assert "tk.Label(" not in help_source
    assert "direct_help_close" in help_source
    assert "direct_bubble_button_text" in app_source


def test_native_onboarding_prompt_keeps_first_run_inside_avatar_ui() -> None:
    prompt = _native_onboarding_prompt({"displayName": "小九"})
    fallback = _native_onboarding_prompt(None)
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")

    assert prompt["label"] == "先完成原生配置窗口"
    assert "小九" in prompt["detail"]
    assert "上传照片" in prompt["detail"]
    assert "启用" in prompt["detail"]
    assert "桌面只保留头像" in prompt["detail"]
    assert "聊天、设置、技能、进度四个入口" not in prompt["detail"]
    assert "JiuMe" in fallback["detail"]
    assert "def _redirect_first_run_to_setup" in app_source
    assert "先完成原生配置窗口" in app_source
    assert 'action_id in {"talk", "settings", "skills", "progress"}' in app_source
    assert 'key in {"direct_chat", "settings", "skills", "progress", "status"}' in app_source
    first_run_source = app_source.split("def _redirect_first_run_to_setup", 1)[1].split(
        "def _run_avatar_context_action",
        1,
    )[0]
    assert "webbrowser.open(self.setup_url)" not in first_run_source
    assert "self._close_direct_chat()" in first_run_source
    assert "self._hide_hover_menu()" in first_run_source


def test_direct_activity_summary_keeps_latest_task_and_artifacts() -> None:
    summary = _direct_activity_summary(
        [
            {
                "kind": "final",
                "title": "任务完成",
                "detail": "整理好了会议纪要和行动项",
                "time": "10:24",
                "artifacts": [
                    {"label": "report.md", "target": "/tmp/report.md", "kind": "file"},
                    {"label": "notes.json", "target": "/tmp/notes.json", "kind": "file"},
                    {"label": "extra.txt", "target": "/tmp/extra.txt", "kind": "file"},
                ],
            }
        ]
    )

    assert summary is not None
    assert summary["title"] == "任务完成"
    assert summary["stage"] == "收尾完成"
    assert summary["detail"] == "整理好了会议纪要和行动项"
    assert len(summary["artifacts"]) == 2
    assert _direct_activity_summary([]) is None
    still_task = _direct_activity_summary(
        [
            {"kind": "interaction", "title": "打气", "detail": "第 7 次桌面互动"},
            {"kind": "processing", "title": "正在整理", "detail": "提取行动项"},
        ]
    )
    assert still_task is not None
    assert still_task["kind"] == "processing"
    interaction_only = _direct_activity_summary([{"kind": "interaction", "title": "挥手"}])
    assert interaction_only is not None
    assert interaction_only["kind"] == "interaction"


def test_task_progress_reply_reads_like_jiume_reporting_status() -> None:
    active = _task_progress_reply(
        {
            "kind": "processing",
            "stage": "拆步骤",
            "title": "整理会议纪要",
            "detail": "提取行动项",
            "artifacts": [],
        }
    )
    complete = _task_progress_reply(
        {
            "kind": "final",
            "stage": "收尾完成",
            "title": "任务完成",
            "detail": "整理好了会议纪要和行动项",
            "artifacts": [
                {"label": "report.md", "target": "/tmp/report.md", "kind": "file"},
                {"label": "notes.json", "target": "/tmp/notes.json", "kind": "file"},
            ],
        },
        has_artifact_tray=True,
    )
    empty = _task_progress_reply(None)

    assert active["state"] == "thinking"
    assert "我正在「拆步骤」" in active["detail"]
    assert "整理会议纪要" in active["detail"]
    assert "刚刚这一步是：提取行动项" in active["detail"]
    assert "补一句、进度、更多" in active["detail"]
    assert complete["state"] == "success"
    assert "我刚刚「收尾完成」" in complete["detail"]
    assert "report.md、notes.json" in complete["detail"]
    assert "产物列表、继续聊" in complete["detail"]
    assert empty["state"] == "speaking"
    assert "没有正在接手的任务" in empty["detail"]


def test_direct_activity_actions_keep_task_control_beside_avatar() -> None:
    active = _direct_activity_action_specs({"kind": "processing", "artifacts": []})
    active_expanded = _direct_activity_action_specs({"kind": "processing", "artifacts": []}, expanded=True)
    waiting = _direct_activity_action_specs({"kind": "approval", "artifacts": []})
    waiting_expanded = _direct_activity_action_specs({"kind": "approval", "artifacts": []}, expanded=True)
    complete = _direct_activity_action_specs(
        {
            "kind": "final",
            "artifacts": [{"label": "report.md", "kind": "file", "target": "/tmp/report.md"}],
        },
        has_artifact_tray=True,
    )
    failed = _direct_activity_action_specs({"kind": "error", "artifacts": []})

    assert [item["id"] for item in active] == ["chat", "progress", "more"]
    assert [item["id"] for item in active_expanded] == [
        "chat",
        "progress",
        "nudge",
        "quiet",
        "cancel",
        "cheer",
        "less",
    ]
    assert [item["id"] for item in waiting] == ["approval_accept", "approval_reject", "chat", "more"]
    assert [item["id"] for item in waiting_expanded] == [
        "approval_accept",
        "approval_reject",
        "chat",
        "cheer",
        "less",
    ]
    assert waiting[0]["label"] == "同意"
    assert [item["id"] for item in complete] == ["artifacts", "chat"]
    assert [item["id"] for item in failed] == ["progress", "retry", "chat"]
    for specs in (active, active_expanded, waiting, waiting_expanded, complete, failed):
        labels = {item["label"] for item in specs}
        assert labels.isdisjoint(DAILY_FORBIDDEN_LABELS)
    assert _direct_activity_action_specs(None) == []


def test_task_result_and_approval_layers_use_bubble_buttons() -> None:
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    companion_source = app_source.split("def _rebuild_direct_companion_card", 1)[1].split(
        "def _run_direct_companion_suggestion",
        1,
    )[0]
    service_source = app_source.split("def _rebuild_direct_service_card", 1)[1].split(
        "def _set_idle_companion_enabled",
        1,
    )[0]
    show_service_source = app_source.split("def _show_service_status", 1)[1].split(
        "def _run_login_item_command",
        1,
    )[0]
    activity_source = app_source.split("def _rebuild_direct_activity_card", 1)[1].split(
        "def _run_direct_activity_action",
        1,
    )[0]
    legacy_activity_source = app_source.split("def _rebuild_activity_rows", 1)[1].split(
        "def _artifact_type_label",
        1,
    )[0]
    run_activity_source = app_source.split("def _run_direct_activity_action", 1)[1].split(
        "def _rebuild_direct_approval_card",
        1,
    )[0]
    approval_source = app_source.split("def _rebuild_direct_approval_card", 1)[1].split(
        "def _direct_quick_actions",
        1,
    )[0]
    legacy_approval_source = app_source.split("def _rebuild_approval_card", 1)[1].split(
        "def _send_approval_answer",
        1,
    )[0]
    quick_source = app_source.split("def _rebuild_direct_quick_actions", 1)[1].split(
        "def _direct_skill_rows",
        1,
    )[0]
    artifact_preview_source = app_source.split("def _show_direct_artifact_preview", 1)[1].split(
        "def _preview_activity_artifact",
        1,
    )[0]
    artifact_tray_source = app_source.split("def _rebuild_direct_artifact_tray", 1)[1].split(
        "def _show_artifact_tray",
        1,
    )[0]
    work_hud_source = app_source.split("def _rebuild_work_hud_actions", 1)[1].split(
        "def _apply_work_hud_style",
        1,
    )[0]

    for source in (
        companion_source,
        service_source,
        activity_source,
        quick_source,
        artifact_preview_source,
        artifact_tray_source,
        work_hud_source,
    ):
        assert "_pack_direct_bubble_buttons" in source

    for source in (
        companion_source,
        service_source,
        activity_source,
        quick_source,
    ):
        assert "_pack_direct_speech_bubble" in source

    assert "tk.Label(" not in companion_source
    assert "tk.Label(" not in service_source
    assert "tk.Label(" not in activity_source
    assert "tk.Label(" not in approval_source
    assert "tk.Label(" not in quick_source
    button_bubble_source = app_source.split("def _pack_direct_bubble_buttons", 1)[1].split(
        "def _show_direct_help_card",
        1,
    )[0]
    assert "direct_bubble_button_tail" not in button_bubble_source
    assert "create_polygon" not in button_bubble_source
    assert "bubble.pack(side=\"left\"" not in button_bubble_source
    assert "suggestion_row = tk.Frame" not in companion_source
    assert "play_row = tk.Frame" not in companion_source
    assert "_pack_direct_value_bubbles" in companion_source
    value_bubble_source = app_source.split("def _pack_direct_value_bubbles", 1)[1].split(
        "def _pack_direct_text_preview_bubble",
        1,
    )[0]
    assert "direct_value_tail" not in value_bubble_source
    assert "create_polygon" not in value_bubble_source
    assert "from_user_side = index % 2 == 1" in value_bubble_source
    assert "bubble_width = _direct_value_bubble_width(label, value)" in value_bubble_source
    assert "width=bubble_width" in value_bubble_source
    assert "width=270" not in value_bubble_source
    assert "我建议下一步" in companion_source
    assert "轻互动" in companion_source
    assert "self._direct_companion_more_visible" in companion_source
    assert 'if self._direct_companion_more_visible:' in companion_source
    assert '"id": "companion_more", "label": "更多陪伴"' in companion_source
    assert '"id": "companion_less", "label": "收起陪伴"' in companion_source
    assert 'for action_id in DIRECT_COMPANION_ACTION_IDS:' in companion_source
    assert "next_row = tk.Frame" not in activity_source
    assert "actions = tk.Frame(self._direct_activity_frame" not in activity_source
    assert "Legacy boxed activity log is retired" in legacy_activity_source
    assert "tk.Label(" not in legacy_activity_source
    assert "tk.Button(" not in legacy_activity_source
    assert "highlightthickness=1" not in legacy_activity_source
    assert "detail_parts: list[str]" in activity_source
    assert "self._direct_activity_more_visible" in activity_source
    assert "self._direct_activity_empty_visible" in activity_source
    assert "self._direct_activity_detail_visible" in activity_source
    assert "if not self._direct_activity_detail_visible:" in activity_source
    assert "先收成一条进度" in activity_source
    assert "需要细节时再展开；我不会把任务控制一次性铺满。" in activity_source
    assert '"id": "progress", "label": "展开进度"' in activity_source
    assert "现在没有任务进度" in activity_source
    assert "你可以直接说一句，我会接住下一件事" in activity_source
    assert '"id": "materials", "label": "交材料"' not in activity_source
    assert '"id": "close_progress", "label": "收起"' in activity_source
    assert 'if action == "more"' in run_activity_source
    assert 'if action == "less"' in run_activity_source
    assert 'if action == "progress":\n            self._direct_activity_detail_visible = True' in run_activity_source
    assert 'self._direct_activity_detail_visible = True' in run_activity_source
    assert 'if action == "close_progress"' in run_activity_source
    for label in DAILY_FORBIDDEN_LABELS:
        assert label not in activity_source
        assert label not in work_hud_source
    assert "buttons = tk.Frame(self._direct_approval_frame" not in approval_source
    assert "Legacy boxed approval card is retired" in legacy_approval_source
    assert "tk.Label(" not in legacy_approval_source
    assert "tk.Button(" not in legacy_approval_source
    assert "tk.Entry(" not in legacy_approval_source
    assert "self._direct_approval_feedback_visible" in approval_source
    assert "_pack_direct_bubble_buttons" not in approval_source
    assert "_pack_direct_speech_bubble" not in approval_source
    assert "_pack_direct_bubble_entry" not in approval_source
    assert "pack_forget()" in approval_source
    assert "_run_direct_approval_action" in app_source
    assert "tk.Entry(" not in approval_source
    assert "row = tk.Frame(self._direct_quick_frame" not in quick_source
    assert "row = tk.Frame(self._direct_artifact_frame" not in artifact_preview_source
    assert "top = tk.Frame(self._direct_artifact_frame" not in artifact_preview_source
    assert "tk.Label(" not in artifact_preview_source
    assert "_pack_direct_speech_bubble" in artifact_preview_source
    assert "_pack_direct_text_preview_bubble" in artifact_preview_source
    assert "image_canvas = tk.Canvas(" in artifact_preview_source
    assert "tk.Button(" not in artifact_preview_source
    assert "_pack_direct_header_button" not in artifact_preview_source
    assert "buttons = tk.Frame(row" not in artifact_tray_source
    assert "row = tk.Frame(self._direct_artifact_frame" not in artifact_tray_source
    assert "header = tk.Frame(row" not in artifact_tray_source
    assert "tk.Label(" not in artifact_tray_source
    assert "_pack_direct_speech_bubble" in artifact_tray_source
    assert "_pack_direct_value_bubbles" in artifact_tray_source
    assert "tk.Button(" not in artifact_tray_source
    assert "_pack_direct_header_button" not in artifact_tray_source
    assert "tk.Button(" not in work_hud_source
    assert "self.open_direct_chat()" in show_service_source
    assert "self._rebuild_direct_service_card()" in show_service_source


def test_direct_companion_suggestions_adapt_to_person_context() -> None:
    waiting = _direct_companion_suggestion_specs(
        presence={"mood": "waiting_approval"},
        activity_summary={"kind": "processing"},
    )
    working = _direct_companion_suggestion_specs(
        presence={"mood": "working"},
        activity_summary={"kind": "tool"},
    )
    finished = _direct_companion_suggestion_specs(
        presence={"mood": "success"},
        activity_summary={"kind": "final"},
        has_artifact_tray=True,
    )
    skilled = _direct_companion_suggestion_specs(
        presence={"mood": "ready"},
        active_skill={"id": "meeting-minutes", "displayName": "会议纪要精炼团队"},
    )
    idle = _direct_companion_suggestion_specs(presence={"mood": "idle"})

    assert [item["id"] for item in waiting] == ["approval_accept", "approval_reject", "chat"]
    assert waiting[0]["label"] == "同意继续"
    assert [item["id"] for item in working] == ["chat", "quiet"]
    assert [item["id"] for item in finished] == ["artifacts", "chat"]
    assert [item["id"] for item in skilled] == ["chat", "settings"]
    assert [item["id"] for item in _direct_companion_suggestion_specs(presence={"mood": "error"})] == [
        "chat",
        "retry",
    ]
    assert [item["id"] for item in _direct_companion_suggestion_specs(presence={"mood": "sleep"})] == [
        "wake",
        "settings",
    ]
    assert [item["id"] for item in idle] == ["chat", "settings"]
    assert [item["label"] for item in idle] == ["说一句", "设置"]
    suggestion_copy = " ".join(
        str(item.get("label") or "")
        for group in (waiting, working, finished, skilled, idle)
        for item in group
    )
    for label in DAILY_FORBIDDEN_LABELS:
        assert label not in suggestion_copy
    assert waiting[0]["style"] == "primary"


def test_artifact_preview_actions_keep_results_native() -> None:
    inline_actions = JiuMeDesktopAvatar._artifact_preview_action_specs(
        {"kind": "inline", "target": "inline:0"},
        can_copy=True,
    )
    file_actions = JiuMeDesktopAvatar._artifact_preview_action_specs(
        {"kind": "file", "target": "/tmp/report.md"},
        can_copy=True,
    )
    empty_actions = JiuMeDesktopAvatar._artifact_preview_action_specs(
        {"kind": "file", "target": ""},
        can_copy=False,
    )
    image_actions = JiuMeDesktopAvatar._artifact_preview_action_specs(
        {"kind": "file", "category": "image", "target": "/tmp/screen.png"},
        can_copy=False,
    )
    url_actions = JiuMeDesktopAvatar._artifact_preview_action_specs(
        {"kind": "file", "category": "link", "target": "https://example.com/report"},
        can_copy=False,
    )

    assert [item["id"] for item in inline_actions] == ["copy"]
    assert [item["id"] for item in file_actions] == ["copy", "open"]
    assert [item["id"] for item in image_actions] == ["copy", "open"]
    assert [item["id"] for item in url_actions] == ["copy", "open"]
    assert JiuMeDesktopAvatar._artifact_copy_target({"kind": "file", "target": "file:///tmp/report.md"}) == "/tmp/report.md"
    assert JiuMeDesktopAvatar._artifact_copy_target({"kind": "inline", "target": "inline:0"}) == ""
    assert empty_actions == []


def test_companion_status_tracks_playful_presence() -> None:
    fresh = _companion_status(0, 0)
    warmed = _companion_status(3, 2)
    quiet = _companion_status(3, 2, enabled=False)

    assert fresh["level"] == 1
    assert fresh["label"] == "刚刚在一起"
    assert warmed["level"] >= 3
    assert "3 次互动" in warmed["detail"]
    assert quiet["label"] == "安静守候"
    assert quiet["enabled"] is False


def test_desktop_companion_state_roundtrip_and_defaults() -> None:
    assert read_companion_state() == {
        "interaction_count": 0,
        "idle_companion_index": 0,
        "idle_companion_enabled": False,
    }

    written = write_companion_state(
        interaction_count=4,
        idle_companion_index=2,
        idle_companion_enabled=False,
        twin_id="twin_1",
    )
    loaded = read_companion_state()

    assert loaded["interaction_count"] == 4
    assert loaded["idle_companion_index"] == 2
    assert loaded["idle_companion_enabled"] is False
    assert loaded["twin_id"] == "twin_1"
    assert loaded["updated_at"] == written["updated_at"]

    get_companion_state_path().write_text(
        '{"interaction_count": -8, "idle_companion_index": "oops", "idle_companion_enabled": "false"}',
        encoding="utf-8",
    )

    repaired = read_companion_state()

    assert repaired["interaction_count"] == 0
    assert repaired["idle_companion_index"] == 0
    assert repaired["idle_companion_enabled"] is False


def test_desktop_window_state_roundtrip_and_geometry() -> None:
    assert read_window_state() == {}
    assert _avatar_window_geometry(size=128, screen_width=1440, screen_height=900, saved={}) == "128x128+1276+676"
    assert _window_position_geometry(-180, 64) == "+-180+64"
    assert _avatar_size_from_state(128, {"size": 168}) == 168
    assert _avatar_size_from_state(144, {"size": 96}) == 144
    assert _avatar_size_from_state(128, {"size": 999}) == 220
    assert _avatar_size_label(96) == "小"
    assert _avatar_size_label(128) == "标准"
    assert _avatar_size_label(168) == "大"

    written = write_window_state(
        x=-180,
        y=64,
        size=128,
        screen_width=1440,
        screen_height=900,
        opacity=0.62,
        twin_id="twin_1",
    )
    loaded = read_window_state()

    assert loaded["x"] == -180
    assert loaded["y"] == 64
    assert loaded["size"] == 128
    assert loaded["opacity"] == 0.62
    assert loaded["twin_id"] == "twin_1"
    assert loaded["updated_at"] == written["updated_at"]
    assert _avatar_window_geometry(size=128, screen_width=1440, screen_height=900, saved=loaded) == "128x128+-180+64"

    get_window_state_path().write_text('{"x": "bad", "y": 20, "size": -1}', encoding="utf-8")

    assert read_window_state() == {}
    assert _avatar_window_geometry(
        size=128,
        screen_width=1440,
        screen_height=900,
        saved={"x": 99999, "y": -99999},
    ) == "128x128+2728+-876"


def test_desktop_conversation_state_keeps_recent_context() -> None:
    assert read_conversation_state() == {"chat": [], "activity": []}

    chat_items = [
        {"role": "user", "text": f"message {index}"}
        for index in range(10)
    ]
    activity_items = [
        {
            "kind": "final",
            "title": "任务完成",
            "detail": "整理好了文件",
            "time": "10:24",
            "artifacts": [
                {"label": "report.md", "target": "/tmp/report.md", "kind": "file", "category": "text"},
                {"label": "extra.txt", "target": "/tmp/extra.txt", "kind": "file", "category": "text"},
                {"label": "third.csv", "target": "/tmp/third.csv", "kind": "file", "category": "table"},
                {"label": "ignored.csv", "target": "/tmp/ignored.csv", "kind": "file", "category": "table"},
            ],
        }
    ]

    written = write_conversation_state(
        chat_items=chat_items,
        activity_items=activity_items,
        active_skill={
            "id": "meeting-minutes",
            "displayName": "会议纪要精炼团队",
            "summary": "整理会议",
            "category": "办公",
            "risk": "low",
            "whyJiume": "贴近桌面助理",
        },
        twin_id="twin_1",
    )
    loaded = read_conversation_state()

    assert [item["text"] for item in loaded["chat"]] == [f"message {index}" for index in range(10)]
    assert loaded["activity"][0]["title"] == "任务完成"
    assert len(loaded["activity"][0]["artifacts"]) == 3
    assert loaded["activeSkill"]["id"] == "meeting-minutes"
    assert loaded["activeSkill"]["displayName"] == "会议纪要精炼团队"
    assert loaded["activeSkill"]["risk"] == "low"
    assert loaded["twin_id"] == "twin_1"
    assert loaded["updated_at"] == written["updated_at"]

    get_conversation_state_path().write_text(
        '{"chat": [{"role": "system", "text": "hi"}, {"role": "user", "text": ""}], "activity": "bad"}',
        encoding="utf-8",
    )

    repaired = read_conversation_state()

    assert repaired == {"chat": [{"role": "assistant", "text": "hi"}], "activity": []}


def test_desktop_chat_thread_keeps_more_than_recent_bubbles() -> None:
    avatar = object.__new__(JiuMeDesktopAvatar)
    avatar._chat_items = []
    avatar._stream_chat_index = None
    avatar._native_direct_chat_visible = False
    avatar._direct_chat_frame = None
    avatar._direct_chat_scroll_offset = 3
    avatar._persist_desktop_history = lambda: None  # type: ignore[method-assign]
    avatar._rebuild_chat_rows = lambda: None  # type: ignore[method-assign]
    avatar._rebuild_direct_chat_rows = lambda: None  # type: ignore[method-assign]

    for index in range(12):
        JiuMeDesktopAvatar._append_chat(avatar, "user", f"message {index}")

    assert [item["text"] for item in avatar._chat_items] == [f"message {index}" for index in range(12)]
    assert avatar._direct_chat_scroll_offset == 0


def test_desktop_quick_actions_are_agent_ready() -> None:
    actions = quick_actions()
    ids = {str(action["id"]) for action in actions}
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    run_quick_source = app_source.split("def _run_quick_action", 1)[1].split(
        "def _finish_quick_action_fallback",
        1,
    )[0]

    assert {"focus", "today", "skill_picker", "rest"}.issubset(ids)
    assert quick_action_by_id("focus")["title"] == "陪我专注"
    assert "JiuMe desktop focus session" in quick_action_prompt("focus")
    assert quick_action_by_id("rest")["kind"] == "local"
    assert quick_action_prompt("missing") == ""
    assert "_reply_with_skill_picker" not in run_quick_source


def test_desktop_interactions_cover_idle_and_encouragement() -> None:
    actions = interaction_actions()
    ids = {str(action["id"]) for action in actions}

    assert {"wave", "pat", "cheer", "nod", "stretch", "breathe", "peek", "dance", "heart", "companion"}.issubset(ids)
    assert interaction_by_id("cheer")["state"] == "success"
    assert interaction_by_id("cheer")["effect"] == "cheer"
    assert all(action.get("effect") for action in actions)
    assert interaction_by_id("nod")["effect"] == "nod"
    assert interaction_by_id("pat")["effect"] == "pat"
    assert interaction_by_id("heart")["effect"] == "heart"
    assert "宠物" not in interaction_by_id("pat")["line"]
    assert interaction_by_id("breathe")["line"].startswith("吸气")
    assert "桌面上陪着你" in interaction_by_id("companion")["line"]
    assert interaction_by_id("missing") is None


def test_desktop_app_menu_labels_cover_core_entry_points() -> None:
    labels = app_menu_labels()
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    non_shell_label_helpers = [
        play_menu_labels(),
        material_menu_labels(),
        skill_menu_labels(),
        task_menu_labels(),
        companion_menu_labels(),
        state_menu_labels(),
    ]

    assert labels == ["设置", "退出 JiuMe"]
    assert "只留头像" not in labels
    assert "恢复不透明" not in labels
    assert "回到右下角" not in labels
    assert app_source.count("app_menu.add_cascade") == 1
    assert 'app_menu.add_cascade(label="JiuMe", menu=jiume_menu)' in app_source
    for menu_label in ("互动", "快捷动作", "交材料", "当前 skill", "任务 / 产物", "陪伴", "状态"):
        assert f'app_menu.add_cascade(label="{menu_label}"' not in app_source
    assert "配置入口" not in labels
    assert "退出 JiuMe" in labels
    assert non_shell_label_helpers == [[], [], [], [], [], []]


def test_desktop_work_hud_tracks_task_lifecycle() -> None:
    assert _work_hud_state_for_activity("user") == "thinking"
    assert _work_hud_state_for_activity("tool") == "working"
    assert _work_hud_state_for_activity("approval") == "waiting_approval"
    assert _work_hud_state_for_activity("final") == "success"
    assert _work_hud_state_for_activity("interaction") is None
    assert _activity_stage_label("tool") == "使用工具"
    assert _activity_stage_label("interrupt") == "请求停止"
    assert _activity_stage_label("final") == "收尾完成"
    assert _activity_stage_label("missing") == ""
    assert _activity_effect_for_kind("tool") == "peek"
    assert _activity_effect_for_kind("interrupt") == "nod"
    assert _activity_effect_for_kind("final") == "cheer"
    assert _activity_effect_for_kind("error") == ""
    assert _work_hud_auto_hide_ms("final") == 3200
    assert _work_hud_auto_hide_ms("tool") is None
    assert _work_hud_phase_label("thinking", 2).endswith("..")
    assert _work_hud_phase_label("thinking", 1, "processing") == "JiuMe 正在拆步骤."
    assert _work_hud_phase_label("working", 2, "tool") == "JiuMe 正在用工具.."
    assert _work_hud_phase_label("success", 1, "final") == "JiuMe 收尾完成"
    assert _work_hud_phase_label("focus", 1) == "JiuMe 陪你专注."
    assert _work_hud_phase_label("waiting_approval", 1) == "JiuMe 等你确认"
    assert _work_hud_bubble_line("整理会议纪要", "提取行动项", state="working", kind="tool") == (
        "JiuMe 正在用工具｜整理会议纪要：提取行动项"
    )
    assert [item["id"] for item in _work_hud_action_specs("working")] == ["chat", "progress", "nudge", "cheer", "quiet", "cancel"]
    assert [item["id"] for item in _work_hud_action_specs("focus")] == ["finish_focus", "focus_status", "cheer", "chat"]
    assert [item["id"] for item in _work_hud_action_specs("waiting_approval")] == [
        "approval_accept",
        "approval_reject",
        "chat",
        "cheer",
    ]
    assert _work_hud_action_specs("waiting_approval")[0]["label"] == "同意"
    assert "cheer" in [item["id"] for item in _work_hud_action_specs("waiting_approval")]
    assert _work_hud_action_specs("success")[0]["label"] == "查看"
    assert _work_hud_action_specs("error")[0]["label"] == "查看"
    assert "retry" in [item["id"] for item in _work_hud_action_specs("error")]
    for state in ("success", "error", "working", "waiting_approval", "focus"):
        labels = {item["label"] for item in _work_hud_action_specs(state)}
        assert labels.isdisjoint(DAILY_FORBIDDEN_LABELS)
    assert _work_hud_resume_activity(
        [
            {"kind": "final", "title": "任务完成", "detail": "done"},
            {"kind": "approval", "title": "等待确认", "detail": "需要你点头"},
        ]
    ) is None
    assert _work_hud_resume_activity([{"kind": "final", "title": "任务完成"}]) is None
    app_source = Path("jiume/desktop/app.py").read_text(encoding="utf-8")
    show_work_hud_source = app_source.split("def _show_work_hud", 1)[1].split("def _build_work_hud", 1)[0]
    build_work_hud_source = app_source.split("def _build_work_hud", 1)[1].split("def _work_hud_command", 1)[0]
    assert "self._build_work_hud()" not in show_work_hud_source
    assert "self.show_bubble(line" in show_work_hud_source
    assert "Legacy boxed HUD is retired" in build_work_hud_source
    assert "tk.Toplevel" not in build_work_hud_source


def test_idle_companion_only_runs_when_jiume_is_truly_idle() -> None:
    moments = idle_companion_moments()
    skill_moment = _idle_companion_moment_for_context(
        0,
        {"id": "meeting-minutes", "displayName": "会议纪要精炼团队"},
    )
    next_skill_moment = _idle_companion_moment_for_context(
        1,
        {"id": "meeting-minutes", "displayName": "会议纪要精炼团队"},
    )

    assert moments[0]["id"] == "check_in"
    assert moments[0]["effect"] == "nod"
    assert "tiny_lot" in {str(moment["id"]) for moment in moments}
    tiny_lot = next(moment for moment in moments if moment["id"] == "tiny_lot")
    assert tiny_lot["effect"] == "cheer"
    assert "小签" in tiny_lot["line"]
    assert idle_companion_moment(len(moments))["id"] == "check_in"
    assert _idle_companion_moment_for_context(0)["id"] == "check_in"
    assert skill_moment["id"] == "skill_ready"
    assert skill_moment["effect"] == "peek"
    assert "会议纪要精炼团队" in skill_moment["line"]
    assert "剪贴板" in skill_moment["line"]
    assert next_skill_moment["id"] == "skill_waiting_material"
    assert should_run_idle_companion(
        state="idle",
        idle_seconds=IDLE_COMPANION_SECONDS,
        has_visible_surface=False,
        enabled=True,
    )
    assert not should_run_idle_companion(
        state="idle",
        idle_seconds=IDLE_COMPANION_SECONDS,
        has_visible_surface=False,
    )
    assert not should_run_idle_companion(
        state="working",
        idle_seconds=IDLE_COMPANION_SECONDS + 1,
        has_visible_surface=False,
    )
    assert not should_run_idle_companion(
        state="idle",
        idle_seconds=IDLE_COMPANION_SECONDS + 1,
        has_visible_surface=True,
    )
    assert not should_run_idle_companion(
        state="idle",
        idle_seconds=IDLE_COMPANION_SECONDS - 1,
        has_visible_surface=False,
    )


def test_jiume_launcher_reuses_running_services_or_starts_missing_ones() -> None:
    assert _gateway_endpoint("ws://localhost:19000/ws") == ("localhost", 19000)
    assert _gateway_endpoint("wss://assistant.example/ws") == ("assistant.example", 443)
    assert _should_open_desktop_avatar(first_run=True, open_setup=False, no_setup=False) is False
    assert _should_open_desktop_avatar(first_run=True, open_setup=False, no_setup=True) is True
    assert _should_open_desktop_avatar(first_run=False, open_setup=False, no_setup=False) is True
    launcher_source = Path("jiume/launcher.py").read_text(encoding="utf-8")
    assert "native setup is the primary surface" in launcher_source
    assert "waiting for first twin" in launcher_source

    plan = _build_launch_plan(
        python_executable="/python",
        first_run=True,
        open_setup=True,
        no_setup=False,
        agent="auto",
        gateway_url="ws://127.0.0.1:19000/ws",
        gateway_running=False,
        web_running=False,
        web_host="localhost",
        web_port=5173,
    )

    assert plan.setup_command == ["/python", "-m", "jiume.setup.server"]
    assert plan.agent_command == ["/python", "-m", "jiuwenswarm.app"]
    assert plan.web_command == ["/python", "-m", "jiuwenswarm.channels.web.app_web", "--host", "localhost", "--port", "5173"]
    assert plan.runtime_config_url == "http://localhost:5173/?panel=config"
    assert plan.wait_for_gateway is True

    reuse = _build_launch_plan(
        python_executable="/python",
        first_run=False,
        open_setup=False,
        no_setup=False,
        agent="auto",
        gateway_url="ws://127.0.0.1:19000/ws",
        gateway_running=True,
        web_running=True,
        web_host="localhost",
        web_port=5173,
    )

    assert reuse.setup_command is None
    assert reuse.agent_command is None
    assert reuse.web_command is None
    assert reuse.wait_for_gateway is False


def test_open_setup_is_setup_exclusive_even_with_active_twin() -> None:
    assert not _should_open_desktop_avatar(
        first_run=False,
        open_setup=True,
        no_setup=False,
    )


def test_open_setup_does_not_wait_for_first_twin_before_desktop() -> None:
    assert hasattr(jiume_launcher, "_should_wait_for_first_twin_before_desktop")
    assert not jiume_launcher._should_wait_for_first_twin_before_desktop(
        first_run=False,
        open_setup=True,
        no_setup=False,
    )
    assert jiume_launcher._should_wait_for_first_twin_before_desktop(
        first_run=True,
        open_setup=False,
        no_setup=False,
    )
    assert not jiume_launcher._should_wait_for_first_twin_before_desktop(
        first_run=True,
        open_setup=False,
        no_setup=True,
    )
    main_source = Path("jiume/launcher.py").read_text(encoding="utf-8").split("def main()", 1)[1]
    assert "_should_wait_for_first_twin_before_desktop(" in main_source


def test_open_setup_continues_to_desktop_after_setup_enables_twin() -> None:
    main_source = Path("jiume/launcher.py").read_text(encoding="utf-8").split("def main()", 1)[1]
    open_setup_block = main_source.split("if args.open_setup and not args.no_setup:", 1)[1].split(
        "if _should_wait_for_first_twin_before_desktop(",
        1,
    )[0]

    assert "setup requested: native setup is the primary surface" in open_setup_block
    assert "store.get_active_twin_id()" in open_setup_block
    assert "setup completed; opening desktop twin" in open_setup_block


def test_native_setup_enable_closes_window_so_launcher_can_open_avatar(tmp_path: Path) -> None:
    class FakeStatus:
        def __init__(self) -> None:
            self.value = ""

        def set(self, value: str) -> None:
            self.value = value

    class FakeButton:
        def __init__(self) -> None:
            self.config: dict[str, Any] = {}

        def configure(self, **kwargs: Any) -> None:
            self.config.update(kwargs)

    class FakeRoot:
        def __init__(self) -> None:
            self.after_delay: int | None = None
            self.after_callback: Callable[[], None] | None = None
            self.destroyed = False

        def after(self, delay: int, callback: Callable[[], None]) -> None:
            self.after_delay = delay
            self.after_callback = callback

        def destroy(self) -> None:
            self.destroyed = True

    store = TwinStore(root=tmp_path / "twins")
    twin = store.create_twin({"displayName": "Ada", "activate": False})
    ready = store.update_twin(twin["id"], {"status": "ready"})
    root = FakeRoot()
    window = object.__new__(NativeSetupWindow)
    window.controller = NativeSetupController(store=store, avatars=AvatarService(store))
    window.created_twin_id = ready["id"]
    window.status = FakeStatus()
    window.primary_button = FakeButton()
    window.root = root

    NativeSetupWindow._enable_created_twin(window)

    assert store.get_active_twin_id() == ready["id"]
    assert window.status.value.startswith("已启用")
    assert root.after_delay == 300
    assert root.after_callback is not None
    root.after_callback()
    assert root.destroyed is True


def test_jiume_launcher_runtime_config_deep_link_targets_config_panel() -> None:
    assert hasattr(jiume_launcher, "_runtime_config_url")
    assert jiume_launcher._runtime_config_url(host="localhost", port=5173) == "http://localhost:5173/?panel=config"
    assert jiume_launcher._runtime_config_url(host="127.0.0.1", port=6180) == "http://127.0.0.1:6180/?panel=config"

    app_source = Path("jiuwenswarm/channels/web/frontend/src/App.tsx").read_text(encoding="utf-8")
    assert "initialNavFromLocation" in app_source
    assert "URLSearchParams(window.location.search)" in app_source
    assert "panel=config" in app_source
    assert "setConfigInitialExpandGroup('model_default')" in app_source


def test_jiume_launcher_single_instance_lock_reports_existing_process(tmp_path: Path) -> None:
    lock_path = tmp_path / "launcher.pid"

    assert _claim_launcher_lock(lock_path, pid=200, pid_is_running=lambda _pid: False) is None
    assert _read_launcher_pid(lock_path) == 200

    assert _claim_launcher_lock(lock_path, pid=201, pid_is_running=lambda pid: pid == 200) == 200
    assert _read_launcher_pid(lock_path) == 200

    _release_launcher_lock(lock_path, pid=201)
    assert _read_launcher_pid(lock_path) == 200
    _release_launcher_lock(lock_path, pid=200)
    assert _read_launcher_pid(lock_path) is None


def test_jiume_launcher_native_setup_does_not_probe_or_reuse_http_ports() -> None:
    launcher_source = Path("jiume/launcher.py").read_text(encoding="utf-8")

    assert "_setup_server_ready" not in launcher_source
    assert "_resolve_setup_endpoint" not in launcher_source
    assert "urllib.request" not in launcher_source
    assert "webbrowser.open(plan.setup_url)" not in launcher_source


def test_macos_avatar_drag_uses_global_screen_coordinates_without_snapback() -> None:
    source = Path("jiume/desktop/overlay.py").read_text(encoding="utf-8")
    avatar_view_source = source.split("class _JiuMeAvatarImageView", 1)[1].split("rect = NSMakeRect", 1)[0]
    mouse_down = avatar_view_source.split("def mouseDown_", 1)[1].split("def mouseDragged_", 1)[0]
    mouse_dragged = avatar_view_source.split("def mouseDragged_", 1)[1].split("def mouseUp_", 1)[0]
    mouse_up = avatar_view_source.split("def mouseUp_", 1)[1].split("def rightMouseDown_", 1)[0]

    assert "event.locationInWindow()" not in mouse_down
    assert "event.locationInWindow()" not in mouse_dragged
    assert "NSEvent.mouseLocation()" in mouse_down
    assert "NSEvent.mouseLocation()" in mouse_dragged
    assert "_sync_tk_from_native_frame(frame, final=False)" in mouse_dragged
    assert "_sync_tk_from_native_frame(frame, final=True)" in mouse_up


def test_macos_avatar_click_jitter_does_not_sync_native_frame_as_drag() -> None:
    source = Path("jiume/desktop/overlay.py").read_text(encoding="utf-8")
    avatar_view_source = source.split("class _JiuMeAvatarImageView", 1)[1].split("rect = NSMakeRect", 1)[0]
    mouse_dragged = avatar_view_source.split("def mouseDragged_", 1)[1].split("def mouseUp_", 1)[0]
    mouse_up = avatar_view_source.split("def mouseUp_", 1)[1].split("def rightMouseDown_", 1)[0]

    assert "AVATAR_DRAG_THRESHOLD_PX = 3" in source
    assert (
        "if not host._avatar_dragged and abs(dx) <= AVATAR_DRAG_THRESHOLD_PX and abs(dy) <= AVATAR_DRAG_THRESHOLD_PX:"
        in mouse_dragged
    )
    assert mouse_dragged.index("return") < mouse_dragged.index("frame = self.window().frame()")
    assert "if dragged:" in mouse_up
    assert mouse_up.index("if dragged:") < mouse_up.index("_sync_tk_from_native_frame(frame, final=True)")


def test_macos_image_layer_forwards_scroll_wheel_events() -> None:
    source = Path("jiume/desktop/overlay.py").read_text(encoding="utf-8")
    image_view_source = source.split("class JiuMeImageLayerView", 1)[1].split(
        "image_view_class = JiuMeImageLayerView",
        1,
    )[0]
    show_image_source = source.split("def show_image_layer", 1)[1].split("def hide_image_layer", 1)[0]

    assert "on_scroll: Callable[[float], None] | None = None" in source
    assert "self.scrollCallback = None" in image_view_source
    assert "def scrollWheel_" in image_view_source
    assert "event.scrollingDeltaY()" in image_view_source
    assert "host._queue_layer_callback" in image_view_source
    assert "view.scrollCallback = on_scroll" in show_image_source


def test_macos_overlay_image_layer_send_and_run_submit_clicks_submit_text_field() -> None:
    source = Path("jiume/desktop/overlay.py").read_text(encoding="utf-8")
    image_view_source = source.split("class JiuMeImageLayerView", 1)[1].split(
        "image_view_class = JiuMeImageLayerView",
        1,
    )[0]
    mouse_down_source = image_view_source.split("def mouseDown_", 1)[1].split(
        "def rightMouseDown_",
        1,
    )[0]

    assert 'action in {"run_submit", "send"}' in mouse_down_source
    assert "self.textField.stringValue()" in mouse_down_source
    assert "self.textField.setStringValue_(\"\")" in mouse_down_source
    assert "cb(text)" in mouse_down_source
    assert mouse_down_source.index('action in {"run_submit", "send"}') < mouse_down_source.index(
        "callback = self.clickCallback"
    )


def test_jiume_launcher_login_item_payload_is_self_contained(tmp_path: Path) -> None:
    args = SimpleNamespace(
        size=144,
        setup_host="127.0.0.1",
        setup_port=8765,
        open_setup=False,
        no_setup=False,
        agent="auto",
        gateway_url="ws://127.0.0.1:19000/ws",
        agent_mode="auto_harness",
        wait_agent_seconds=12.5,
        health_check_seconds=3.0,
        no_service_restart=False,
    )

    launcher_args = _launcher_args_for_login(args)
    direct_args = _login_item_command_args(
        "install",
        size=144,
        gateway_url=args.gateway_url,
        agent_mode=args.agent_mode,
    )
    payload = _launch_agent_payload(
        python_executable="/venv/bin/python",
        launcher_args=launcher_args,
        working_directory=tmp_path / "repo",
        log_dir=tmp_path / "logs",
        data_dir=str(tmp_path / "data"),
    )

    assert payload["Label"] == LAUNCH_AGENT_LABEL
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"Crashed": True}
    assert payload["ProgramArguments"] == ["/venv/bin/python", "-m", "jiume.launcher", *launcher_args]
    assert payload["WorkingDirectory"] == str(tmp_path / "repo")
    assert payload["EnvironmentVariables"] == {
        "PYTHONPATH": str(tmp_path / "repo"),
        "JIUWENSWARM_DATA_DIR": str(tmp_path / "data"),
    }
    assert "--health-check-seconds" in payload["ProgramArguments"]
    assert "--install-login-item" not in payload["ProgramArguments"]
    assert "--no-service-restart" not in payload["ProgramArguments"]
    assert direct_args[1:4] == ["-m", "jiume.launcher", "--install-login-item"]
    assert "--setup-host" not in direct_args
    assert "--setup-port" not in direct_args
    assert "--gateway-url" in direct_args
    assert _login_item_command_args("status", size=144)[-1] == "--login-item-status"
    assert _login_item_command_args("missing", size=144) == []

    args.no_service_restart = True
    assert "--no-service-restart" in _launcher_args_for_login(args)


def test_desktop_service_status_roundtrip_and_formatting() -> None:
    assert "后台状态还没有写入" in _format_service_status({})
    assert _direct_service_status_summary({})["state"] == "unknown"

    written = set_service_status(
        source="jiume-launch",
        note="agent restarted",
        restart_enabled=True,
        services={
            "setup": {"mode": "managed", "status": "running", "pid": 123, "restart_count": 0},
            "agent": {"mode": "managed", "status": "running", "pid": 456, "restart_count": 2},
        },
    )

    assert read_service_status()["services"] == written["services"]
    text = _format_service_status(read_service_status())
    assert "配置窗口：运行中（pid 123）" in text
    assert "Agent/Gateway：运行中（pid 456，已恢复 2 次）" in text
    assert "agent restarted" in text
    summary = _direct_service_status_summary(read_service_status())
    assert summary["state"] == "online"
    assert summary["label"] == "Agent 在线"
    assert "已恢复 2 次" in summary["detail"]

    offline = _direct_service_status_summary(
        {"services": {"setup": {"status": "running"}, "agent": {"status": "exited"}}}
    )
    assert offline["state"] == "offline"
    assert offline["label"] == "Agent 已退出"


def test_desktop_gateway_defaults_to_normal_agent_chat_mode() -> None:
    assert desktop_app.DEFAULT_AGENT_MODE == "agent.plan"


def test_gateway_client_reuses_persisted_desktop_session_id() -> None:
    first = JiuMeGatewayChatClient()
    second = JiuMeGatewayChatClient()

    assert first.session_id.startswith("jiume_")
    assert second.session_id == first.session_id


def test_gateway_frames_map_to_desktop_avatar_states() -> None:
    response = normalize_gateway_frame(
        {"type": "res", "id": "req-1", "ok": True, "payload": {"accepted": True}}
    )
    assert response == GatewayEvent(kind="response", request_id="req-1", ok=True, payload={"accepted": True})

    delta = normalize_gateway_frame(
        {"type": "event", "event": "chat.delta", "payload": {"content": "hello"}}
    )
    assert delta is not None
    assert desktop_state_for_gateway_event(delta) == "speaking"
    assert gateway_event_text(delta) == "hello"

    tool_call = normalize_gateway_frame(
        {"type": "event", "event": "chat.tool_call", "payload": {"name": "read_file"}}
    )
    assert tool_call is not None
    assert desktop_state_for_gateway_event(tool_call) == "working"
    assert "read_file" in gateway_event_text(tool_call)

    ask = normalize_gateway_frame(
        {"type": "event", "event": "chat.ask_user_question", "payload": {"question": "继续吗？"}}
    )
    assert ask is not None
    assert desktop_state_for_gateway_event(ask) == "waiting_approval"
    assert gateway_event_text(ask) == "继续吗？"

    subtask = normalize_gateway_frame(
        {
            "type": "event",
            "event": "chat.subtask_update",
            "payload": {"description": "并行执行两个任务", "status": "running", "index": 1, "total": 2},
        }
    )
    assert subtask is not None
    assert desktop_state_for_gateway_event(subtask) == "working"
    assert gateway_event_text(subtask) == "1/2 并行执行两个任务 · running"

    final = normalize_gateway_frame(
        {
            "type": "event",
            "event": "chat.final",
            "payload": {
                "content": "done",
                "artifacts": [{"name": "report.md", "path": "/tmp/report.md"}],
            },
        }
    )
    assert final is not None
    assert gateway_event_artifacts(final) == [
        {"label": "report.md", "target": "/tmp/report.md", "kind": "file", "category": "text"}
    ]

    inline = normalize_gateway_frame(
        {
            "type": "event",
            "event": "chat.file",
            "payload": {"files": [{"name": "summary.md", "content": "# Summary"}]},
        }
    )
    assert inline is not None
    assert gateway_event_artifacts(inline) == [
        {"label": "summary.md", "target": "inline:0", "kind": "inline", "category": "text", "preview": "# Summary"}
    ]

    media = normalize_gateway_frame(
        {
            "type": "event",
            "event": "chat.media",
            "payload": {"files": [{"name": "chart.png", "path": "/tmp/chart.png", "mime": "image/png"}]},
        }
    )
    assert media is not None
    assert gateway_event_artifacts(media) == [
        {"label": "chart.png", "target": "/tmp/chart.png", "kind": "file", "category": "image", "mime": "image/png"}
    ]

    interrupt = normalize_gateway_frame(
        {
            "type": "event",
            "event": "chat.interrupt_result",
            "payload": {"success": True, "message": "任务已取消"},
        }
    )
    assert interrupt is not None
    assert desktop_state_for_gateway_event(interrupt) == "success"
    assert gateway_event_text(interrupt) == "任务已取消"


def test_empty_gateway_final_closes_without_fake_completion_reply() -> None:
    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._gateway_reply = ""
    avatar._stream_chat_index = None
    avatar._last_action = None
    avatar.set_state = lambda _state: None  # type: ignore[method-assign]
    recorded: list[tuple[str, str, str]] = []
    finished: list[str] = []
    bubbles: list[str] = []
    avatar._record_activity = lambda kind, title, detail="", artifacts=None: recorded.append((kind, title, detail))  # type: ignore[method-assign]
    avatar._finish_assistant_stream = lambda text="", state="": finished.append(text)  # type: ignore[method-assign]
    avatar.show_bubble = lambda text, state="", duration=None: bubbles.append(text)  # type: ignore[method-assign]
    avatar.root = SimpleNamespace(after=lambda _delay, callback: None)

    event = GatewayEvent(
        kind="event",
        event="chat.final",
        payload={"event_type": "chat.final", "content": "", "is_complete": True},
    )

    desktop_app.JiuMeDesktopAvatar._handle_gateway_event(avatar, "帮我整理报告", event)

    assert finished == []
    assert recorded == [("final", "任务完成", "")]
    assert "完成。" not in bubbles


def test_processing_idle_without_final_closes_active_direct_task() -> None:
    avatar = object.__new__(desktop_app.JiuMeDesktopAvatar)
    avatar._gateway_reply = ""
    avatar._stream_chat_index = 1
    avatar._last_action = None
    avatar._activity_items = [
        {"kind": "accepted", "title": "已接收", "detail": "我在等它回复。"},
        {"kind": "user", "title": "发起任务", "detail": "帮我整理报告"},
    ]
    states: list[str] = []
    finished: list[str] = []
    bubbles: list[str] = []

    def record(kind: str, title: str, detail: str = "", artifacts: Any = None) -> None:
        avatar._activity_items.insert(0, {"kind": kind, "title": title, "detail": detail})

    avatar.set_state = states.append  # type: ignore[method-assign]
    avatar._record_activity = record  # type: ignore[method-assign]
    avatar._finish_assistant_stream = lambda text="", state="": finished.append(text)  # type: ignore[method-assign]
    avatar.show_bubble = lambda text, state="", duration=None: bubbles.append(text)  # type: ignore[method-assign]
    avatar.root = SimpleNamespace(after=lambda _delay, callback: None)

    event = GatewayEvent(
        kind="event",
        event="chat.processing_status",
        payload={"event_type": "chat.processing_status", "is_processing": False, "is_complete": True},
    )

    desktop_app.JiuMeDesktopAvatar._handle_gateway_event(avatar, "帮我整理报告", event)

    assert states == ["idle"]
    assert avatar._stream_chat_index is None
    assert avatar._activity_items[0] == {"kind": "final", "title": "任务已结束", "detail": ""}
    assert _work_hud_resume_activity(avatar._activity_items) is None
    assert finished == []
    assert bubbles == []


def test_gateway_approval_answer_payloads_match_web_contract() -> None:
    payload = {
        "request_id": "ask-1",
        "source": "permission_interrupt",
        "questions": [
            {
                "question": "允许写文件吗？",
                "options": [{"label": "同意"}, {"label": "拒绝"}],
            }
        ],
    }
    answers = answers_for_decision(payload, "reject", feedback="只允许读，不要写。")

    assert answers == [
        {
            "selected_options": ["拒绝"],
            "question": "允许写文件吗？",
            "custom_input": "只允许读，不要写。",
        }
    ]

    method, params = build_user_answer_request(
        session_id="sess-1",
        request_id="ask-1",
        source="permission_interrupt",
        answers=answers,
        feedback="只允许读，不要写。",
    )

    assert method == "chat.send"
    assert params["session_id"] == "sess-1"
    assert params["request_id"] == "ask-1"
    assert params["answers"] == answers
    assert params["source"] == "permission_interrupt"

    method, params = build_user_answer_request(
        session_id="sess-1",
        request_id="ask-2",
        source="ask_user_interrupt",
        answers=[{"selected_options": ["继续"], "question": "下一步？"}],
    )

    assert method == "chat.send"
    assert params["session_id"] == "sess-1"
    assert params["request_id"] == "ask-2"
    assert params["answers"] == [{"selected_options": ["继续"], "question": "下一步？"}]
    assert params["source"] == "ask_user_interrupt"

    method, params = build_interrupt_request(
        session_id="jiume-session",
        intent="cancel",
        mode="auto_harness",
    )
    assert method == "chat.interrupt"
    assert params == {
        "session_id": "jiume-session",
        "intent": "cancel",
        "mode": "auto_harness",
    }

    method, params = build_user_answer_request(
        session_id="sess-1",
        request_id="activate-1",
        source="activate_confirm",
        answers=[{"selected_options": ["拒绝"]}],
        feedback="先解释风险。",
    )

    assert method == "chat.send"
    assert params["activate_response"] == {
        "interaction_id": "activate-1",
        "action": "reject",
        "feedback": "先解释风险。",
    }
