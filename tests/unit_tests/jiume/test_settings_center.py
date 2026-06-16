from __future__ import annotations

import ast
from pathlib import Path

import jiume.desktop.settings_center as settings_center
from jiume.desktop.settings_center import (
    SETTINGS_CENTER_SECTIONS,
    build_agent_settings_snapshot,
    build_artifacts_settings_snapshot,
    build_desktop_settings_snapshot,
    build_history_settings_snapshot,
    build_skill_settings_snapshot,
    profile_settings_snapshot,
    skill_settings_payload,
)


def test_settings_center_imports_without_desktop_app_dependency() -> None:
    source = Path("jiume/desktop/settings_center.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert "jiume.desktop.app" not in imported_modules
    assert "jiume.runtime.health" in imported_modules
    assert "jiume.runtime.status" in imported_modules
    assert "jiume.setup.server" in imported_modules


def test_settings_center_headless_snapshot_helpers_work_standalone() -> None:
    assert hasattr(settings_center, "build_image_model_settings_snapshot")
    image_model = settings_center.build_image_model_settings_snapshot(
        provider={"hasApiKey": True, "model": "gpt-image-2", "baseUrl": ""},
    )
    diagnostics = build_agent_settings_snapshot(
        service={"services": {"agent": {"status": "running"}}},
        gateway_url="ws://127.0.0.1:19092/ws",
        agent_mode="manual",
    )
    desktop = build_desktop_settings_snapshot(
        window_state={"size": 120, "opacity": 1.2},
        current_size=144,
        gateway_url="ws://127.0.0.1:19092/ws",
    )

    assert SETTINGS_CENTER_SECTIONS[0] == {"id": "profile", "label": "分身"}
    assert [section["id"] for section in SETTINGS_CENTER_SECTIONS] == [
        "profile",
        "desktop",
        "image_model",
        "skills",
        "artifacts",
        "history",
        "diagnostics",
    ]
    assert image_model["apiKeyLabel"] == "已配置"
    assert image_model["modelLabel"] == "gpt-image-2"
    assert diagnostics["connectionLabel"] == "Agent 在线"
    assert diagnostics["primaryAction"] == "打开 JiuwenSwarm 配置"
    assert desktop["sizeLabel"] == "紧凑"
    assert desktop["opacity"] == "100%"


def test_settings_center_agent_snapshot_prefers_live_health() -> None:
    diagnostics = build_agent_settings_snapshot(
        service={"services": {"agent": {"status": "exited", "exit_code": 1}}},
        gateway_url="ws://127.0.0.1:19092/ws",
        agent_mode="manual",
        health=settings_center.RuntimeHealth(
            code=settings_center.RuntimeHealthCode.READY,
            detail="Gateway acknowledged connection.",
            checked_url="ws://127.0.0.1:19092/ws",
        ),
    )

    assert diagnostics["connectionLabel"] == "Agent runtime 已连接"
    assert diagnostics["connectionState"] == "online"
    assert diagnostics["diagnosticCode"] == "ready"
    assert "Gateway acknowledged connection." in diagnostics["detail"]


def test_settings_center_exposes_advanced_skill_artifact_history_sections() -> None:
    conversation = {
        "activeSkill": {"id": "meeting-notes", "displayName": "会议纪要"},
        "chat": [{"role": "user", "text": "整理会议"}],
        "activity": [
            {
                "kind": "final",
                "title": "任务完成",
                "detail": "整理好了",
                "artifacts": [{"label": "report.md", "target": "/tmp/report.md", "kind": "file"}],
            }
        ],
    }
    skills = build_skill_settings_snapshot(
        twin={"permissions": {"allowedSkillIds": ["meeting-notes", "code-review"]}},
        conversation=conversation,
    )
    artifacts = build_artifacts_settings_snapshot(conversation)
    history = build_history_settings_snapshot(conversation)

    assert skills["allowedCount"] == "2"
    assert skills["activeLabel"] == "会议纪要"
    assert skill_settings_payload(" meeting-notes, code-review，meeting-notes ") == {
        "permissions": {"allowedSkillIds": ["meeting-notes", "code-review"]}
    }
    assert artifacts["artifactCount"] == "1"
    assert artifacts["latestLabel"] == "report.md"
    assert history["chatCount"] == "1"
    assert history["activityCount"] == "1"
    assert history["latestTask"] == "任务完成"


def test_settings_center_render_dispatch_has_advanced_sections() -> None:
    source = Path("jiume/desktop/settings_center.py").read_text(encoding="utf-8")
    render_source = source.split("def _render(self)", 1)[1].split("def _section_title", 1)[0]

    assert 'elif self.section == "skills":' in render_source
    assert 'elif self.section == "artifacts":' in render_source
    assert 'elif self.section == "history":' in render_source
    assert "def _render_skills_section" in source
    assert "def _render_artifacts_section" in source
    assert "def _render_history_section" in source


def test_settings_center_diagnostics_render_does_not_probe_gateway_inline() -> None:
    source = Path("jiume/desktop/settings_center.py").read_text(encoding="utf-8")
    diagnostics_source = source.split("def _render_diagnostics_section", 1)[1].split(
        "    def _button_row",
        1,
    )[0]

    assert "check_gateway_health(" not in diagnostics_source


def test_desktop_snapshot_normalizes_malformed_size() -> None:
    default_snapshot = build_desktop_settings_snapshot(
        window_state={"size": "not-a-size"},
        current_size="also-bad",  # type: ignore[arg-type]
        gateway_url="",
    )
    current_size_snapshot = build_desktop_settings_snapshot(
        window_state={"size": "not-a-size"},
        current_size="168",  # type: ignore[arg-type]
        gateway_url="",
    )

    assert default_snapshot["size"] == "128"
    assert current_size_snapshot["size"] == "168"


def test_profile_snapshot_uses_blue_when_appearance_dict_has_no_id() -> None:
    snapshot = profile_settings_snapshot({"appearance": {"label": "Sun"}})

    assert snapshot["appearanceId"] == "blue"
