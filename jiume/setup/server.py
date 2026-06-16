"""Native setup window for JiuMe desktop twins."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import secrets
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from queue import Empty, SimpleQueue
from tkinter import filedialog, messagebox
from typing import Any, Callable

from PIL import Image, ImageTk

from jiume.avatar.service import AvatarService
from jiume.config import (
    get_image_provider_config,
    load_jiume_env,
    public_config_payload,
    write_image_provider_config,
)
from jiume.desktop.gateway_client import DEFAULT_GATEWAY_URL
from jiume.desktop.state import read_service_status, set_desktop_state
from jiume.runtime.health import check_gateway_health
from jiume.runtime.status import runtime_config_url, runtime_diagnostic_from_health
from jiume.setup.progress import classify_generation_error, generation_progress
from jiume.twins.store import TwinStore

load_jiume_env()

SETUP_WIZARD_STEPS = ("photo", "model", "runtime", "generate", "enable")
SETUP_PROGRESS_STAGES = (
    ("photo", "照片"),
    ("model", "模型"),
    ("runtime", "Agent"),
    ("states", "生成"),
    ("enable", "启用"),
)
SETUP_STEP_TO_STAGE = {
    "photo": "photo",
    "model": "model",
    "runtime": "runtime",
    "generate": "runtime",
    "enable": "enable",
}
SETUP_FONT = "PingFang SC"
SETUP_DISPLAY_FONT = "PingFang SC"
PREMIUM_SETUP_COLORS = {
    "bg": "#081013",
    "bg_lift": "#0d171b",
    "surface": "#121b20",
    "surface_high": "#1a252b",
    "surface_shell": "#25343b",
    "field": "#0b1418",
    "field_high": "#142126",
    "line": "#344a52",
    "line_soft": "#22323a",
    "text": "#f1f8f5",
    "muted": "#9fb5b9",
    "subtle": "#6f858b",
    "accent": "#8dd8cf",
    "accent_high": "#b9eee6",
    "accent_soft": "#173a3a",
    "good": "#94dfb8",
    "danger": "#f0a09b",
    "button": "#8dd8cf",
    "button_text": "#061315",
    "ghost": "#1d2b31",
    "ghost_hover": "#263a42",
    "shadow": "#05090b",
}


def _public_manifest(manifest: dict[str, Any], twin_id: str) -> dict[str, Any]:
    clone = json.loads(json.dumps(manifest, ensure_ascii=False))
    version = str(clone.get("generated_at") or "")
    suffix = f"?v={version}" if version else ""
    states = clone.get("states")
    if isinstance(states, dict):
        for state in states.values():
            if isinstance(state, dict):
                file_path = state.get("file")
                if isinstance(file_path, str) and file_path:
                    state["src"] = f"/assets/{twin_id}/{Path(file_path).name}{suffix}"
                frames = state.get("frames")
                if isinstance(frames, list):
                    for frame in frames:
                        if not isinstance(frame, dict):
                            continue
                        frame_file = frame.get("file")
                        if isinstance(frame_file, str) and frame_file:
                            frame["src"] = f"/assets/{twin_id}/{Path(frame_file).name}{suffix}"
                        frame.pop("file", None)
                state.pop("file", None)
    views = clone.get("views")
    if isinstance(views, dict):
        for view in views.values():
            if isinstance(view, dict):
                file_path = view.get("file")
                if isinstance(file_path, str) and file_path:
                    view["src"] = f"/assets/{twin_id}/{Path(file_path).name}{suffix}"
                view.pop("file", None)
    sprite_pack = clone.get("spritePack")
    if isinstance(sprite_pack, dict):
        sprite_pack["manifest"] = f"/assets/{twin_id}/avatar_pack.json{suffix}"
        sprite_pack["compatFile"] = f"/assets/{twin_id}/pet.json{suffix}"
        sprite_pack["spritesheet"] = f"/assets/{twin_id}/spritesheet.webp{suffix}"
    source_image = clone.get("sourceImage")
    if isinstance(source_image, dict):
        file_path = source_image.get("file")
        if isinstance(file_path, str) and file_path:
            source_image["src"] = f"/assets/{twin_id}/{Path(file_path).name}{suffix}"
        source_image.pop("file", None)
    legacy_pack = clone.get("codexPet")
    if isinstance(legacy_pack, dict):
        legacy_pack["petJson"] = f"/assets/{twin_id}/pet.json{suffix}"
        legacy_pack["spritesheet"] = f"/assets/{twin_id}/spritesheet.webp{suffix}"
    clone.pop("base", None)
    return clone


def _source_image_from_path(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or ""
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("请选择 PNG、JPG 或 WebP 照片")
    return {
        "contentBase64": base64.b64encode(path.read_bytes()).decode("ascii"),
        "mimeType": mime,
        "consent": True,
    }


def _ui_font(size: int, *, bold: bool = False) -> tuple[str, int] | tuple[str, int, str]:
    return (SETUP_FONT, int(size), "bold") if bold else (SETUP_FONT, int(size))


def _display_font(size: int, *, bold: bool = True) -> tuple[str, int] | tuple[str, int, str]:
    return (SETUP_DISPLAY_FONT, int(size), "bold") if bold else (SETUP_DISPLAY_FONT, int(size))


class NativeSetupController:
    """Strict first-run twin creation orchestration for the native setup UI."""

    def __init__(self, *, store: TwinStore | None = None, avatars: AvatarService | None = None) -> None:
        self.store = store or TwinStore()
        self.avatars = avatars or AvatarService(self.store)

    def provider_config(self) -> dict[str, object]:
        return public_config_payload()

    def save_provider_config(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> Path:
        return write_image_provider_config(api_key=api_key, base_url=base_url, model=model)

    def create_twin_from_photo(
        self,
        *,
        display_name: str,
        source_image: dict[str, Any],
        progress: Callable[[str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        def report(stage: str) -> None:
            if is_cancelled and is_cancelled():
                raise RuntimeError("generation cancelled")
            if progress:
                progress(stage)

        config = get_image_provider_config()
        if not config.has_api_key:
            raise ValueError(f"image model API key is required before creating a twin. Configure it in {config.config_path}")

        twin_id: str | None = None
        name = " ".join(str(display_name or "").split()) or "JiuMe"
        try:
            twin = self.store.create_twin(
                {
                    "displayName": name,
                    "purpose": "桌面个人分身助手",
                    "tone": "warm, concise, and action-oriented",
                    "defaultMode": "confirm_before_act",
                    "selectedSkillIds": [],
                    "activate": False,
                }
            )
            twin_id = twin["id"]
            self.avatars.upload_source(twin_id, source_image)
            report("photo")
            report("model")
            job = self.avatars.generate_model_avatar(twin_id)
            report("states")
            if is_cancelled and is_cancelled():
                self.store.delete_twin(twin_id)
                raise RuntimeError("generation cancelled")
            twin = self.store.update_twin(twin_id, {"status": "ready"})
            manifest = _public_manifest(job["manifest"], twin_id)
            public_job = {**job, "manifest": manifest}
            report("enable")
            return {"twin": twin, "manifest": manifest, "job": public_job}
        except Exception as exc:  # noqa: BLE001
            if twin_id:
                try:
                    self.store.update_twin(twin_id, {"status": "error"})
                except Exception:
                    pass
                if is_cancelled and is_cancelled():
                    try:
                        self.store.delete_twin(twin_id)
                    except Exception:
                        pass
            raise

    def enable_twin(self, twin_id: str) -> dict[str, Any]:
        twin = self.store.activate_twin(twin_id)
        set_desktop_state("success", twin_id=twin["id"], message="我已经换成你的桌面分身", source="setup")
        return twin


class NativeSetupWindow:
    """Step-by-step native setup for first-run avatar creation."""

    def __init__(self, controller: NativeSetupController | None = None) -> None:
        self.controller = controller or NativeSetupController()
        self.created_twin_id = ""
        self.current_step = "photo"
        self.progress_stage = "photo"
        self.is_generating = False
        self.generation_attempt_id = ""
        self.generation_cancelled = False
        self.generation_started_at = 0.0
        self.generation_timer_after: str | None = None
        self._ui_events: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._ui_event_polling = False

        self.root = tk.Tk()
        self.root.title("JiuMe 配置")
        self.root.geometry("1040x690")
        self.root.resizable(False, False)
        self.root.configure(bg=PREMIUM_SETUP_COLORS["bg"])
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        config = self.controller.provider_config()
        self.display_name = tk.StringVar(value="JiuMe")
        self.photo_path = tk.StringVar(value="")
        self.api_key = tk.StringVar(value="")
        self.base_url = tk.StringVar(value=str(config.get("baseUrl") or ""))
        self.model = tk.StringVar(value=str(config.get("model") or "gpt-image-2"))
        self.status = tk.StringVar(value="先选一张照片。生成成功前，桌面不会出现临时分身。")
        self.runtime_status = tk.StringVar(value="Agent runtime 尚未检测。")
        self.runtime_detail = tk.StringVar(value="JiuMe 会打开 JiuwenSwarm 配置页；runtime 配好后才能启用分身。")
        self.generation_detail = tk.StringVar(value="等待开始生成。")
        self.generation_failure = tk.StringVar(value="")
        self.generation_elapsed = tk.StringVar(value="")
        self.advanced_visible = tk.BooleanVar(value=False)

        self.photo_preview_image: ImageTk.PhotoImage | None = None
        self.generated_preview_image: ImageTk.PhotoImage | None = None
        self.photo_preview_label: tk.Label | None = None
        self.generated_preview_label: tk.Label | None = None
        self.progress_labels: dict[str, tk.Label] = {}
        self.stage_status_label: tk.Label | None = None
        self.progress_canvas: tk.Canvas | None = None
        self.stage_canvas: tk.Canvas | None = None

        self._ensure_ui_event_polling()
        self._build_shell()
        self._set_step("photo")

    def _build_shell(self) -> None:
        c = PREMIUM_SETUP_COLORS
        shell = tk.Frame(self.root, bg=c["bg"], padx=34, pady=30)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(3, weight=1)

        header = tk.Frame(shell, bg=c["bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        tk.Label(
            header,
            text="创建你的 JiuMe 分身",
            bg=c["bg"],
            fg=c["text"],
            font=_display_font(28),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="上传照片，连接图片模型，确认 Agent runtime，然后启用桌面上的 ready twin。",
            bg=c["bg"],
            fg=c["muted"],
            font=_ui_font(13),
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        tk.Label(
            header,
            text="首次配置是硬门槛",
            bg=c["surface_high"],
            fg=c["accent"],
            padx=12,
            pady=7,
            font=_ui_font(11, bold=True),
        ).grid(row=0, column=1, rowspan=2, sticky="ne")

        self.progress_frame = tk.Frame(shell, bg=c["bg"], height=76)
        self.progress_frame.grid(row=2, column=0, sticky="ew")
        self.progress_frame.grid_propagate(False)
        self.progress_frame.grid_columnconfigure(0, weight=1)
        self.progress_canvas = tk.Canvas(self.progress_frame, height=76, bg=c["bg"], highlightthickness=0)
        self.progress_canvas.grid(row=0, column=0, sticky="ew")
        self.progress_canvas.bind("<Configure>", lambda _event: self._draw_progress_track())

        content_shell = tk.Frame(
            shell,
            bg=c["surface_shell"],
            padx=2,
            pady=2,
            width=968,
            height=414,
        )
        content_shell.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        content_shell.grid_propagate(False)
        content_shell.grid_columnconfigure(0, weight=1)
        content_shell.grid_rowconfigure(0, weight=1)
        self.content_frame = tk.Frame(
            content_shell,
            bg=c["surface"],
            padx=24,
            pady=22,
            width=964,
            height=410,
        )
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        self.content_frame.grid_propagate(False)
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(1, weight=2)
        self.content_frame.grid_rowconfigure(0, weight=1)

        self.footer_frame = tk.Frame(shell, bg=c["bg"], height=78)
        self.footer_frame.grid(row=4, column=0, sticky="sew", pady=(18, 0))
        self.footer_frame.grid_propagate(False)
        self.footer_frame.grid_columnconfigure(0, weight=1)

        self.status_label = tk.Label(
            self.footer_frame,
            textvariable=self.status,
            bg=c["bg"],
            fg=c["muted"],
            justify="left",
            wraplength=600,
            font=_ui_font(12),
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=(0, 18))

        self.back_button = self._make_button(
            self.footer_frame,
            text="上一步",
            command=self._go_back,
            variant="ghost",
        )
        self.back_button.grid(row=0, column=1, sticky="e", padx=(0, 10))

        self.primary_button = self._make_button(
            self.footer_frame,
            text="继续",
            command=self._go_next,
            variant="primary",
        )
        self.primary_button.grid(row=0, column=2, sticky="e")

    def _set_step(self, step: str) -> None:
        if step not in SETUP_WIZARD_STEPS:
            raise ValueError(f"unknown setup step: {step}")
        self._sync_progress_stage_for_step(step)
        self.current_step = step
        self._render_progress()
        self._render_step()
        self._sync_footer()

    def _sync_progress_stage_for_step(self, step: str) -> None:
        target = SETUP_STEP_TO_STAGE.get(step, "photo")
        if step == "generate":
            if self._stage_index(self.progress_stage) < self._stage_index(target):
                self.progress_stage = target
            return
        self.progress_stage = target

    def _set_progress_stage(self, stage: str) -> None:
        if stage not in {item[0] for item in SETUP_PROGRESS_STAGES}:
            return
        progress = generation_progress(stage)
        self.progress_stage = stage
        if self.is_generating or stage in {"photo", "model", "states", "enable"}:
            self.generation_detail.set(progress.detail)
        self._render_progress()
        self._draw_generation_track()
        if self.stage_status_label:
            self.stage_status_label.configure(text=progress.title)

    def _render_progress(self) -> None:
        self._draw_progress_track()

    def _draw_progress_track(self) -> None:
        if not self.progress_canvas:
            return
        c = PREMIUM_SETUP_COLORS
        canvas = self.progress_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 900)
        start_x = 24
        end_x = width - 24
        y = 29
        stages = list(SETUP_PROGRESS_STAGES)
        active_index = self._stage_index(self.progress_stage)
        step_width = (end_x - start_x) / max(len(stages) - 1, 1)
        active_x = start_x + step_width * active_index
        canvas.create_line(start_x, y, end_x, y, fill=c["line_soft"], width=4)
        canvas.create_line(start_x, y, active_x, y, fill=c["accent"], width=4)
        for index, (stage, label) in enumerate(stages):
            x = start_x + step_width * index
            is_active = index == active_index
            is_done = index < active_index
            radius = 10 if is_active else 7
            fill = c["accent"] if is_active or is_done else c["surface_high"]
            outline = c["accent"] if is_active else c["line"]
            if is_active:
                canvas.create_oval(x - 17, y - 17, x + 17, y + 17, fill=c["accent_soft"], outline="")
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=fill, outline=outline, width=1)
            canvas.create_text(
                x,
                y + 30,
                text=label,
                fill=c["text"] if is_active else c["muted"],
                font=_ui_font(12, bold=is_active),
            )

    def _draw_generation_track(self) -> None:
        if not self.stage_canvas:
            return
        c = PREMIUM_SETUP_COLORS
        canvas = self.stage_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 280)
        active_index = self._stage_index(self.progress_stage)
        start_x = 8
        end_x = width - 8
        y = 16
        stages = list(SETUP_PROGRESS_STAGES)
        step_width = (end_x - start_x) / max(len(stages) - 1, 1)
        active_x = start_x + step_width * active_index
        canvas.create_line(start_x, y, end_x, y, fill=c["line_soft"], width=5)
        canvas.create_line(start_x, y, active_x, y, fill=c["accent"], width=5)
        pulse = 10 if self.is_generating else 7
        canvas.create_oval(
            active_x - pulse - 6,
            y - pulse - 6,
            active_x + pulse + 6,
            y + pulse + 6,
            fill=c["accent_soft"],
            outline="",
        )
        canvas.create_oval(
            active_x - pulse,
            y - pulse,
            active_x + pulse,
            y + pulse,
            fill=c["accent"],
            outline=c["accent_soft"],
            width=3,
        )

    def _render_step(self) -> None:
        for child in self.content_frame.winfo_children():
            child.destroy()
        self.stage_canvas = None
        if self.current_step == "photo":
            self._render_photo_step()
        elif self.current_step == "model":
            self._render_model_step()
        elif self.current_step == "runtime":
            self._render_runtime_step()
        elif self.current_step == "generate":
            self._render_generate_step()
        elif self.current_step == "enable":
            self._render_enable_step()

    def _render_photo_step(self) -> None:
        c = PREMIUM_SETUP_COLORS
        preview = self._preview_panel(self.content_frame, "照片预览", 0, 0)
        self.photo_preview_label = tk.Label(
            preview,
            text="选择照片后会先在这里预览",
            bg=c["field"],
            fg=c["muted"],
            width=28,
            height=12,
            justify="center",
        )
        self.photo_preview_label.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        if self.photo_path.get():
            self._load_photo_preview(Path(self.photo_path.get()).expanduser())

        form = self._form_panel(self.content_frame, row=0, column=1)
        form.grid(row=0, column=1, sticky="nsew", padx=(22, 0))
        form.grid_columnconfigure(0, weight=1)

        self._section_title(form, "照片", "选一张能代表你的照片", row=0)
        self._field_label(form, "显示名", row=2)
        self._entry(form, textvariable=self.display_name).grid(row=3, column=0, sticky="ew", ipady=8)
        self._field_label(form, "照片", row=4)
        path_row = tk.Frame(form, bg=c["surface_high"])
        path_row.grid(row=5, column=0, sticky="ew")
        path_row.grid_columnconfigure(0, weight=1)
        self._entry(path_row, textvariable=self.photo_path).grid(row=0, column=0, sticky="ew", ipady=8)
        self._make_button(
            path_row,
            text="选择",
            command=self._choose_photo,
            variant="ghost",
        ).grid(row=0, column=1, padx=(8, 0), ipady=5)
        tk.Label(
            form,
            text="支持 PNG、JPG、WebP。透明图会保留主体，普通照片会交给图片模型生成多状态分身。",
            bg=c["surface_high"],
            fg=c["muted"],
            justify="left",
            wraplength=320,
            font=_ui_font(11),
        ).grid(row=6, column=0, sticky="w", pady=(14, 0))

    def _render_model_step(self) -> None:
        c = PREMIUM_SETUP_COLORS
        preview = self._preview_panel(self.content_frame, "当前照片", 0, 0)
        self.photo_preview_label = tk.Label(preview, bg=c["field"], fg=c["muted"], width=28, height=12)
        self.photo_preview_label.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        if self.photo_path.get():
            self._load_photo_preview(Path(self.photo_path.get()).expanduser())

        form = self._form_panel(self.content_frame, row=0, column=1)
        form.grid(row=0, column=1, sticky="nsew", padx=(22, 0))
        form.grid_columnconfigure(0, weight=1)
        self._section_title(form, "图片模型", "连接照片生成模型", row=0)
        self._field_label(form, "API Key", row=2)
        self._entry(form, textvariable=self.api_key, show="•").grid(row=3, column=0, sticky="ew", ipady=8)

        config = get_image_provider_config()
        key_hint = "已检测到本机保存的 API Key，可以直接生成。" if config.has_api_key else "API Key 是必填项；Base URL 和模型是可选项。"
        tk.Label(form, text=key_hint, bg=c["surface_high"], fg=c["muted"], justify="left", wraplength=360, font=_ui_font(11)).grid(
            row=4,
            column=0,
            sticky="w",
            pady=(10, 12),
        )
        self._make_button(
            form,
            text="Base URL / 模型（可选）",
            command=self._toggle_advanced_options,
            variant="ghost",
        ).grid(row=5, column=0, sticky="w")

        if self.advanced_visible.get():
            self._field_label(form, "Base URL", row=6)
            self._entry(form, textvariable=self.base_url).grid(row=7, column=0, sticky="ew", ipady=8)
            self._field_label(form, "模型", row=8)
            self._entry(form, textvariable=self.model).grid(row=9, column=0, sticky="ew", ipady=8)
            tk.Label(
                form,
                text="不填 Base URL 会使用默认服务；模型不填会使用 gpt-image-2。",
                bg=c["surface_high"],
                fg=c["muted"],
                justify="left",
                wraplength=320,
                font=_ui_font(11),
            ).grid(row=10, column=0, sticky="w", pady=(10, 0))

    def _render_runtime_step(self) -> None:
        self._refresh_runtime_status(silent=True)
        c = PREMIUM_SETUP_COLORS
        preview = self._preview_panel(self.content_frame, "当前照片", 0, 0)
        self.photo_preview_label = tk.Label(preview, bg=c["field"], fg=c["muted"], width=28, height=12)
        self.photo_preview_label.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        if self.photo_path.get():
            self._load_photo_preview(Path(self.photo_path.get()).expanduser())

        panel = self._form_panel(self.content_frame, row=0, column=1)
        panel.grid(row=0, column=1, sticky="nsew", padx=(22, 0))
        panel.grid_columnconfigure(0, weight=1)
        self._section_title(panel, "Agent runtime", "确认 JiuwenSwarm 已经可用", row=0)
        tk.Label(
            panel,
            textvariable=self.runtime_status,
            bg=c["surface_high"],
            fg=c["text"],
            font=_display_font(16),
            justify="left",
            wraplength=320,
        ).grid(row=2, column=0, sticky="w", pady=(6, 8))
        tk.Label(
            panel,
            textvariable=self.runtime_detail,
            bg=c["surface_high"],
            fg=c["muted"],
            justify="left",
            wraplength=320,
            font=_ui_font(11),
        ).grid(row=3, column=0, sticky="w", pady=(0, 16))
        action_row = tk.Frame(panel, bg=c["surface_high"])
        action_row.grid(row=4, column=0, sticky="w")
        self._make_button(
            action_row,
            text="打开 JiuwenSwarm 配置",
            command=self._open_runtime_config,
            variant="ghost",
        ).grid(row=0, column=0, sticky="w")
        self._make_button(
            action_row,
            text="重新检测",
            command=self._refresh_runtime_status,
            variant="ghost",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(
            panel,
            text="runtime 的 API Key、Base URL 和模型都在 JiuwenSwarm 配置页维护；JiuMe 不复制这套表单。",
            bg=c["surface_high"],
            fg=c["muted"],
            justify="left",
            wraplength=320,
            font=_ui_font(11),
        ).grid(row=5, column=0, sticky="w", pady=(18, 0))

    def _render_generate_step(self) -> None:
        c = PREMIUM_SETUP_COLORS
        left = self._preview_panel(self.content_frame, "生成中", 0, 0)
        self.photo_preview_label = tk.Label(left, bg=c["field"], fg=c["muted"], width=28, height=12)
        self.photo_preview_label.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        if self.photo_path.get():
            self._load_photo_preview(Path(self.photo_path.get()).expanduser())

        panel = self._form_panel(self.content_frame, row=0, column=1)
        panel.grid(row=0, column=1, sticky="nsew", padx=(22, 0))
        panel.grid_columnconfigure(0, weight=1)
        self._section_title(panel, "生成", "正在生成你的桌面分身", row=0)
        self.stage_status_label = tk.Label(
            panel,
            text=self._progress_label(self.progress_stage),
            bg=c["surface_high"],
            fg=c["text"],
            font=_display_font(16),
            justify="left",
            wraplength=320,
        )
        self.stage_status_label.grid(row=2, column=0, sticky="w", pady=(6, 12))
        self.stage_canvas = tk.Canvas(panel, height=42, bg=c["surface_high"], highlightthickness=0)
        self.stage_canvas.grid(row=3, column=0, sticky="ew")
        self.stage_canvas.bind("<Configure>", lambda _event: self._draw_generation_track())
        self._draw_generation_track()
        tk.Label(
            panel,
            textvariable=self.generation_detail,
            bg=c["surface_high"],
            fg=c["muted"],
            justify="left",
            wraplength=320,
            font=_ui_font(11),
        ).grid(row=4, column=0, sticky="w", pady=(16, 0))
        tk.Label(
            panel,
            textvariable=self.generation_elapsed,
            bg=c["surface_high"],
            fg=c["subtle"],
            justify="left",
            wraplength=320,
            font=_ui_font(11),
        ).grid(row=5, column=0, sticky="w", pady=(8, 0))
        tk.Label(
            panel,
            textvariable=self.generation_failure,
            bg=c["surface_high"],
            fg=c["danger"],
            justify="left",
            wraplength=320,
            font=_ui_font(11),
        ).grid(row=6, column=0, sticky="w", pady=(8, 0))
        action_row = tk.Frame(panel, bg=c["surface_high"])
        action_row.grid(row=7, column=0, sticky="w", pady=(16, 0))
        self._make_button(
            action_row,
            text="取消",
            command=self._cancel_generation,
            variant="ghost",
        ).grid(row=0, column=0, sticky="w")
        self._make_button(
            action_row,
            text="重试",
            command=self._retry_generation,
            variant="ghost",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

    def _render_enable_step(self) -> None:
        c = PREMIUM_SETUP_COLORS
        preview = self._preview_panel(self.content_frame, "生成预览", 0, 0)
        self.generated_preview_label = tk.Label(
            preview,
            text="分身预览加载中",
            bg=c["field"],
            fg=c["muted"],
            width=28,
            height=12,
            justify="center",
        )
        self.generated_preview_label.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        if self.created_twin_id:
            self._load_generated_preview(self.created_twin_id)

        panel = self._form_panel(self.content_frame, row=0, column=1)
        panel.grid(row=0, column=1, sticky="nsew", padx=(22, 0))
        panel.grid_columnconfigure(0, weight=1)
        self._section_title(panel, "启用", "启用这个分身", row=0)
        tk.Label(
            panel,
            text="现在它只是 ready。点启用后，它才会成为桌面上的 active twin，并刷新正在运行的 avatar。",
            bg=c["surface_high"],
            fg=c["muted"],
            justify="left",
            wraplength=320,
            font=_ui_font(11),
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

    def _sync_footer(self) -> None:
        c = PREMIUM_SETUP_COLORS
        self.back_button.configure(state="normal", bg=c["ghost"], fg=c["text"])
        self.primary_button.configure(state="normal", bg=c["button"], fg=c["button_text"])
        if self.current_step == "photo":
            self.back_button.configure(state="disabled")
            self.primary_button.configure(text="下一步")
        elif self.current_step == "model":
            self.primary_button.configure(text="连接 Agent")
        elif self.current_step == "runtime":
            self.primary_button.configure(text="生成预览")
        elif self.current_step == "generate":
            if self.is_generating:
                self.back_button.configure(state="disabled")
            self.primary_button.configure(text="生成中", state="disabled", bg=c["line"], fg=c["muted"])
        elif self.current_step == "enable":
            self.primary_button.configure(text="启用这个分身")

    def _make_button(self, parent: tk.Widget, *, text: str, command: Callable[[], None], variant: str) -> tk.Label:
        c = PREMIUM_SETUP_COLORS
        if variant == "primary":
            bg = c["button"]
            fg = c["button_text"]
            active_bg = c["accent_high"]
            active_fg = c["button_text"]
            padx = 24
        else:
            bg = c["ghost"]
            fg = c["text"]
            active_bg = c["ghost_hover"]
            active_fg = c["text"]
            padx = 18
        button = tk.Label(
            parent,
            text=text,
            anchor="center",
            relief="solid",
            borderwidth=0,
            highlightthickness=0,
            padx=padx,
            pady=10,
            bg=bg,
            fg=fg,
            disabledforeground=c["muted"],
            font=_ui_font(12, bold=True),
            cursor="hand2",
            takefocus=True,
        )

        def is_enabled() -> bool:
            return str(button.cget("state")) != "disabled"

        def invoke(_event: tk.Event[tk.Misc] | None = None) -> None:
            if is_enabled():
                command()

        def on_enter(_event: tk.Event[tk.Misc] | None = None) -> None:
            if is_enabled():
                button.configure(bg=active_bg, fg=active_fg)

        def on_leave(_event: tk.Event[tk.Misc] | None = None) -> None:
            if is_enabled():
                button.configure(bg=bg, fg=fg)

        def on_press(_event: tk.Event[tk.Misc] | None = None) -> None:
            if is_enabled():
                button.configure(bg=active_bg, fg=active_fg, pady=11)

        def on_release(_event: tk.Event[tk.Misc] | None = None) -> None:
            if is_enabled():
                button.configure(bg=active_bg, fg=active_fg, pady=10)

        button.bind("<Button-1>", invoke)
        button.bind("<ButtonPress-1>", on_press)
        button.bind("<ButtonRelease-1>", on_release)
        button.bind("<Return>", invoke)
        button.bind("<space>", invoke)
        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)
        return button

    def _entry(self, parent: tk.Widget, *, textvariable: tk.StringVar, show: str | None = None) -> tk.Entry:
        c = PREMIUM_SETUP_COLORS
        return tk.Entry(
            parent,
            textvariable=textvariable,
            show=show,
            relief="flat",
            bg=c["field"],
            fg=c["text"],
            insertbackground=c["accent"],
            highlightthickness=1,
            highlightbackground=c["line"],
            highlightcolor=c["accent"],
            font=_ui_font(13),
        )

    @staticmethod
    def _section_title(parent: tk.Widget, kicker: str, title: str, *, row: int) -> None:
        c = PREMIUM_SETUP_COLORS
        tk.Label(
            parent,
            text=kicker,
            bg=c["surface_high"],
            fg=c["accent"],
            font=_ui_font(11, bold=True),
            padx=0,
        ).grid(
            row=row,
            column=0,
            sticky="w",
        )
        tk.Label(parent, text=title, bg=c["surface_high"], fg=c["text"], font=_display_font(20)).grid(
            row=row + 1,
            column=0,
            sticky="w",
            pady=(3, 12),
        )

    @staticmethod
    def _field_label(parent: tk.Widget, text: str, *, row: int) -> None:
        c = PREMIUM_SETUP_COLORS
        tk.Label(parent, text=text, bg=c["surface_high"], fg=c["muted"], font=_ui_font(11, bold=True)).grid(
            row=row,
            column=0,
            sticky="w",
            pady=(10, 5),
        )

    @staticmethod
    def _form_panel(parent: tk.Widget, *, row: int, column: int) -> tk.Frame:
        c = PREMIUM_SETUP_COLORS
        return tk.Frame(parent, bg=c["surface_high"], padx=22, pady=20)

    @staticmethod
    def _preview_panel(parent: tk.Widget, title: str, row: int, column: int) -> tk.Frame:
        c = PREMIUM_SETUP_COLORS
        outer = tk.Frame(parent, bg=c["surface_shell"], padx=1, pady=1)
        outer.grid(row=row, column=column, sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        panel = tk.Frame(outer, bg=c["surface_high"], padx=18, pady=17)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)
        tk.Label(panel, text=title, bg=c["surface_high"], fg=c["muted"], font=_ui_font(11, bold=True)).grid(
            row=0,
            column=0,
            sticky="w",
        )
        return panel

    def _progress_label(self, stage: str) -> str:
        labels = dict(SETUP_PROGRESS_STAGES)
        return labels.get(stage, "准备生成")

    def _stage_index(self, stage: str) -> int:
        stages = [item[0] for item in SETUP_PROGRESS_STAGES]
        try:
            return stages.index(stage)
        except ValueError:
            return 0

    def _choose_photo(self) -> None:
        path = filedialog.askopenfilename(
            title="选择你的照片",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if path:
            self.photo_path.set(path)
            self._load_photo_preview(Path(path).expanduser())
            self.status.set("照片已载入。下一步连接图片模型生成多状态分身。")

    def _load_photo_preview(self, path: Path) -> None:
        if not self.photo_preview_label:
            return
        try:
            image = Image.open(path)
            image.thumbnail((270, 270), Image.Resampling.LANCZOS)
            self.photo_preview_image = ImageTk.PhotoImage(image)
        except Exception as exc:  # noqa: BLE001
            self.photo_preview_image = None
            self.photo_preview_label.configure(image="", text=f"预览失败：{exc}")
            return
        self.photo_preview_label.configure(image=self.photo_preview_image, text="", width=270, height=270)

    def _load_generated_preview(self, twin_id: str) -> None:
        if not self.generated_preview_label:
            return
        try:
            manifest = self.controller.avatars.get_manifest(twin_id)
            states = manifest.get("states") if isinstance(manifest, dict) else {}
            state = states.get("idle") if isinstance(states, dict) else {}
            if not isinstance(state, dict) or not state.get("file"):
                state = next((item for item in states.values() if isinstance(item, dict) and item.get("file")), {})
            file_path = Path(str(state.get("file") or ""))
            image = Image.open(file_path)
            image.thumbnail((270, 270), Image.Resampling.LANCZOS)
            self.generated_preview_image = ImageTk.PhotoImage(image)
        except Exception as exc:  # noqa: BLE001
            self.generated_preview_image = None
            self.generated_preview_label.configure(image="", text=f"预览加载失败：{exc}")
            return
        self.generated_preview_label.configure(image=self.generated_preview_image, text="", width=270, height=270)

    def _toggle_advanced_options(self) -> None:
        self.advanced_visible.set(not self.advanced_visible.get())
        self._render_step()

    def _go_next(self) -> None:
        if self.current_step == "photo":
            path = Path(self.photo_path.get()).expanduser()
            if not path.exists():
                messagebox.showerror("JiuMe", "请先选择一张照片。")
                return
            try:
                _source_image_from_path(path)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("JiuMe", str(exc))
                return
            self._set_progress_stage("photo")
            self._set_step("model")
            return
        if self.current_step == "model":
            config = get_image_provider_config()
            if not self.api_key.get().strip() and not config.has_api_key:
                messagebox.showerror("JiuMe", "请填写图片模型 API Key。Base URL 和模型可以留空。")
                return
            self.controller.save_provider_config(
                api_key=self.api_key.get(),
                base_url=self.base_url.get(),
                model=self.model.get(),
            )
            self._set_progress_stage("runtime")
            self._set_step("runtime")
            return
        if self.current_step == "runtime":
            if not self._runtime_ready():
                messagebox.showerror("JiuMe", "请先完成 JiuwenSwarm Agent runtime 配置并重新检测。")
                return
            self._start_generation()
            return
        if self.current_step == "enable":
            self._enable_created_twin()

    def _go_back(self) -> None:
        if self.current_step == "model":
            self._set_step("photo")
        elif self.current_step == "runtime":
            self._set_step("model")
        elif self.current_step == "generate" and not self.is_generating:
            self._set_step("model")
        elif self.current_step == "enable":
            self._set_step("runtime")

    def _runtime_ready(self) -> bool:
        return self._runtime_diagnostic().ready

    def _runtime_diagnostic(self):
        health = check_gateway_health(DEFAULT_GATEWAY_URL, timeout_seconds=1.5)
        return runtime_diagnostic_from_health(health, service_payload=read_service_status())

    def _refresh_runtime_status(self, silent: bool = False) -> None:
        diagnostic = self._runtime_diagnostic()
        self.runtime_status.set(diagnostic.label)
        self.runtime_detail.set(diagnostic.detail)
        if not silent:
            self.status.set(diagnostic.detail)

    def _open_runtime_config(self) -> None:
        webbrowser.open(runtime_config_url())
        self.status.set("已打开 JiuwenSwarm 配置页。保存 runtime 模型后回到这里重新检测。")

    def _start_generation(self) -> None:
        path = Path(self.photo_path.get()).expanduser()
        if not path.exists():
            messagebox.showerror("JiuMe", "请先选择一张照片。")
            self._set_step("photo")
            return
        self.created_twin_id = ""
        self.generation_attempt_id = secrets.token_hex(8)
        self.generation_cancelled = False
        self.generation_started_at = time.monotonic()
        self.generation_failure.set("")
        self.generation_elapsed.set("已等待 0 秒")
        self.is_generating = True
        self.status.set("正在调用图片模型生成分身...")
        self._set_progress_stage("model")
        self._set_step("generate")
        self._tick_generation_timer(self.generation_attempt_id)
        threading.Thread(target=self._generate_worker, args=(path, self.generation_attempt_id), daemon=True).start()

    def _generate_worker(self, path: Path, attempt_id: str) -> None:
        try:
            result = self.controller.create_twin_from_photo(
                display_name=self.display_name.get(),
                source_image=_source_image_from_path(path),
                progress=lambda stage: self._post_to_ui(
                    lambda s=stage, a=attempt_id: self._handle_generation_progress(a, s),
                ),
                is_cancelled=lambda a=attempt_id: a != self.generation_attempt_id or self.generation_cancelled,
            )
        except Exception as exc:  # noqa: BLE001
            self._post_to_ui(lambda e=exc, a=attempt_id: self._generation_failed(a, e))
            return
        self._post_to_ui(lambda r=result, a=attempt_id: self._generation_succeeded(a, r))

    def _handle_generation_progress(self, attempt_id: str, stage: str) -> None:
        if attempt_id != self.generation_attempt_id or self.generation_cancelled:
            return
        self._set_progress_stage(stage)

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

    def _cancel_generation_timer(self) -> None:
        if not self.generation_timer_after:
            return
        try:
            self.root.after_cancel(self.generation_timer_after)
        except tk.TclError:
            pass
        self.generation_timer_after = None

    def _tick_generation_timer(self, attempt_id: str) -> None:
        if attempt_id != self.generation_attempt_id or not self.is_generating:
            return
        elapsed = max(0, int(time.monotonic() - self.generation_started_at))
        self.generation_elapsed.set(f"已等待 {elapsed} 秒")
        self.generation_timer_after = self.root.after(1000, lambda a=attempt_id: self._tick_generation_timer(a))

    def _cancel_generation(self) -> None:
        self.generation_cancelled = True
        self.is_generating = False
        self._cancel_generation_timer()
        self.generation_detail.set("已取消。本次图片模型返回会被忽略。")
        self.generation_failure.set("")
        self.status.set("已取消生成。你可以重试或返回修改图片模型配置。")
        self._draw_generation_track()

    def _retry_generation(self) -> None:
        self._start_generation()

    def _discard_generation_result(self, result: dict[str, Any]) -> None:
        twin = result.get("twin") if isinstance(result.get("twin"), dict) else {}
        twin_id = str(twin.get("id") or "")
        if not twin_id:
            return
        try:
            self.controller.store.delete_twin(twin_id)
        except Exception:
            pass

    def _generation_failed(self, attempt_id: str, error: BaseException | str) -> None:
        if attempt_id != self.generation_attempt_id or self.generation_cancelled:
            return
        failure = classify_generation_error(error)
        self.is_generating = False
        self._cancel_generation_timer()
        self.status.set(f"{failure.title}：{failure.detail}")
        self.generation_failure.set(f"{failure.title}：{failure.detail}")
        self._draw_generation_track()
        self._set_step("generate")

    def _generation_succeeded(self, attempt_id: str, result: dict[str, Any]) -> None:
        if attempt_id != self.generation_attempt_id or self.generation_cancelled:
            self._discard_generation_result(result)
            return
        twin = result.get("twin") if isinstance(result.get("twin"), dict) else {}
        self.created_twin_id = str(twin.get("id") or "")
        self.is_generating = False
        self._cancel_generation_timer()
        self.status.set("分身已经生成。点“启用这个分身”后它才会出现在桌面。")
        self._set_progress_stage("enable")
        self._set_step("enable")

    def _enable_created_twin(self) -> None:
        if not self.created_twin_id:
            return
        try:
            twin = self.controller.enable_twin(self.created_twin_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("JiuMe", str(exc))
            return
        self.status.set(f"已启用：{twin.get('displayName') or 'JiuMe'}。正在打开桌面分身。")
        self.primary_button.configure(
            text="已启用",
            state="disabled",
            bg=PREMIUM_SETUP_COLORS["line"],
            fg=PREMIUM_SETUP_COLORS["muted"],
        )
        self.root.after(300, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the native JiuMe setup window.")
    parser.add_argument("--display-name", default="JiuMe")
    parser.add_argument("--photo", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--enable", action="store_true", help="Enable the generated twin after CLI generation.")
    parser.add_argument("--host", default="", help=argparse.SUPPRESS)
    parser.add_argument("--port", default="", help=argparse.SUPPRESS)
    parser.add_argument("--open", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    controller = NativeSetupController()
    if args.api_key or args.base_url or args.model:
        controller.save_provider_config(api_key=args.api_key, base_url=args.base_url, model=args.model)
    if args.photo:
        result = controller.create_twin_from_photo(
            display_name=args.display_name,
            source_image=_source_image_from_path(Path(args.photo).expanduser()),
        )
        if args.enable:
            result["twin"] = controller.enable_twin(str(result["twin"]["id"]))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    NativeSetupWindow(controller).run()


if __name__ == "__main__":
    main()
