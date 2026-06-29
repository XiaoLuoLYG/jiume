"""Native setup window for JiuMe desktop twins."""

from __future__ import annotations

import argparse
import json
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

from PIL import Image, ImageTk

from jiume.avatar.service import AvatarService
from jiume.desktop.gateway_client import DEFAULT_GATEWAY_URL
from jiume.desktop.state import read_service_status, set_desktop_state
from jiume.runtime.health import check_gateway_health
from jiume.runtime.status import runtime_config_url, runtime_diagnostic_from_health
from jiume.twins.store import TwinStore

SETUP_WIZARD_STEPS = ("pet", "enable")
SETUP_PROGRESS_STAGES = (
    ("pet", "Pet"),
    ("enable", "启用"),
)
SETUP_STEP_TO_STAGE = {
    "pet": "pet",
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


def _ui_font(size: int, *, bold: bool = False) -> tuple[str, int] | tuple[str, int, str]:
    return (SETUP_FONT, int(size), "bold") if bold else (SETUP_FONT, int(size))


def _display_font(size: int, *, bold: bool = True) -> tuple[str, int] | tuple[str, int, str]:
    return (SETUP_DISPLAY_FONT, int(size), "bold") if bold else (SETUP_DISPLAY_FONT, int(size))


class NativeSetupController:
    """First-run twin creation from an existing Codex pet package."""

    def __init__(self, *, store: TwinStore | None = None, avatars: AvatarService | None = None) -> None:
        self.store = store or TwinStore()
        self.avatars = avatars or AvatarService(self.store)

    def create_twin_from_pet(
        self,
        *,
        display_name: str,
        pet_id: str | None = None,
        source_path: str | Path | None = None,
    ) -> dict[str, Any]:
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
            job = self.avatars.import_pet(twin_id, pet_id=pet_id, source_path=source_path)
            twin = self.store.update_twin(twin_id, {"status": "ready"})
            manifest = _public_manifest(job["manifest"], twin_id)
            public_job = {**job, "manifest": manifest}
            return {"twin": twin, "manifest": manifest, "job": public_job}
        except Exception as exc:  # noqa: BLE001
            if twin_id:
                try:
                    self.store.delete_twin(twin_id)
                except Exception:
                    try:
                        self.store.update_twin(twin_id, {"status": "error"})
                    except Exception:
                        pass
            raise

    def enable_twin(self, twin_id: str) -> dict[str, Any]:
        twin = self.store.activate_twin(twin_id)
        set_desktop_state("success", twin_id=twin["id"], message="我已经换成你的桌面分身", source="setup")
        return twin


class NativeSetupWindow:
    """Small setup window that imports an existing Codex pet package."""

    def __init__(self, controller: NativeSetupController | None = None) -> None:
        self.controller = controller or NativeSetupController()
        self.created_twin_id = ""
        self.current_step = "pet"
        self.progress_stage = "pet"

        self.root = tk.Tk()
        self.root.title("JiuMe 配置")
        self.root.geometry("980x620")
        self.root.resizable(False, False)
        self.root.configure(bg=PREMIUM_SETUP_COLORS["bg"])
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.display_name = tk.StringVar(value="JiuMe")
        self.pet_path = tk.StringVar(value="")
        self.status = tk.StringVar(value="选择一个 Codex pet 包。JiuMe 只负责导入和启用。")
        self.preview_image: ImageTk.PhotoImage | None = None
        self.preview_label: tk.Label | None = None
        self.progress_canvas: tk.Canvas | None = None

        self._build_shell()
        self._set_step("pet")

    def _build_shell(self) -> None:
        c = PREMIUM_SETUP_COLORS
        shell = tk.Frame(self.root, bg=c["bg"], padx=34, pady=30)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(3, weight=1)

        header = tk.Frame(shell, bg=c["bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="创建你的 JiuMe 分身", bg=c["bg"], fg=c["text"], font=_display_font(28)).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="导入 hatch-pet 或现有 Codex pet 项目产出的 pet.json + spritesheet.webp。",
            bg=c["bg"],
            fg=c["muted"],
            font=_ui_font(13),
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))
        tk.Label(
            header,
            text="Codex pet 包",
            bg=c["surface_high"],
            fg=c["accent"],
            padx=12,
            pady=7,
            font=_ui_font(11, bold=True),
        ).grid(row=0, column=1, rowspan=2, sticky="ne")

        self.progress_canvas = tk.Canvas(shell, height=76, bg=c["bg"], highlightthickness=0)
        self.progress_canvas.grid(row=2, column=0, sticky="ew")
        self.progress_canvas.bind("<Configure>", lambda _event: self._draw_progress_track())

        content_shell = tk.Frame(shell, bg=c["surface_shell"], padx=2, pady=2, width=908, height=350)
        content_shell.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        content_shell.grid_propagate(False)
        content_shell.grid_columnconfigure(0, weight=1)
        content_shell.grid_rowconfigure(0, weight=1)
        self.content_frame = tk.Frame(content_shell, bg=c["surface"], padx=24, pady=22, width=904, height=346)
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        self.content_frame.grid_propagate(False)
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(1, weight=2)
        self.content_frame.grid_rowconfigure(0, weight=1)

        footer = tk.Frame(shell, bg=c["bg"], height=78)
        footer.grid(row=4, column=0, sticky="sew", pady=(18, 0))
        footer.grid_propagate(False)
        footer.grid_columnconfigure(0, weight=1)
        tk.Label(footer, textvariable=self.status, bg=c["bg"], fg=c["muted"], justify="left", wraplength=560, font=_ui_font(12)).grid(row=0, column=0, sticky="w", padx=(0, 18))
        self.back_button = self._make_button(footer, text="上一步", command=self._go_back, variant="ghost")
        self.back_button.grid(row=0, column=1, sticky="e", padx=(0, 10))
        self.primary_button = self._make_button(footer, text="继续", command=self._go_next, variant="primary")
        self.primary_button.grid(row=0, column=2, sticky="e")

    def _set_step(self, step: str) -> None:
        if step not in SETUP_WIZARD_STEPS:
            raise ValueError(f"unknown setup step: {step}")
        self.current_step = step
        self.progress_stage = SETUP_STEP_TO_STAGE.get(step, "pet")
        self._draw_progress_track()
        self._render_step()
        self._sync_footer()

    def _draw_progress_track(self) -> None:
        if not self.progress_canvas:
            return
        c = PREMIUM_SETUP_COLORS
        canvas = self.progress_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 760)
        start_x = 40
        end_x = width - 40
        y = 29
        stages = list(SETUP_PROGRESS_STAGES)
        active_index = self._stage_index(self.progress_stage)
        step_width = (end_x - start_x) / max(len(stages) - 1, 1)
        active_x = start_x + step_width * active_index
        canvas.create_line(start_x, y, end_x, y, fill=c["line_soft"], width=4)
        canvas.create_line(start_x, y, active_x, y, fill=c["accent"], width=4)
        for index, (_stage, label) in enumerate(stages):
            x = start_x + step_width * index
            is_active = index == active_index
            is_done = index < active_index
            fill = c["accent"] if is_active or is_done else c["surface_high"]
            outline = c["accent"] if is_active else c["line"]
            canvas.create_oval(x - 9, y - 9, x + 9, y + 9, fill=fill, outline=outline, width=1)
            canvas.create_text(x, y + 30, text=label, fill=c["text"] if is_active else c["muted"], font=_ui_font(12, bold=is_active))

    def _render_step(self) -> None:
        for child in self.content_frame.winfo_children():
            child.destroy()
        if self.current_step == "enable":
            self._render_enable_step()
        else:
            self._render_pet_step()

    def _render_pet_step(self) -> None:
        c = PREMIUM_SETUP_COLORS
        preview = self._preview_panel(self.content_frame, "Pet 预览", 0, 0)
        self.preview_label = tk.Label(preview, text="选择 pet 包后会显示 idle 首帧", bg=c["field"], fg=c["muted"], width=28, height=12, justify="center")
        self.preview_label.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        if self.pet_path.get():
            self._load_pet_preview(Path(self.pet_path.get()).expanduser())

        form = self._form_panel(self.content_frame, row=0, column=1)
        form.grid(row=0, column=1, sticky="nsew", padx=(22, 0))
        form.grid_columnconfigure(0, weight=1)
        self._section_title(form, "Codex pet", "选择本地 pet 包", row=0)
        self._field_label(form, "显示名", row=2)
        self._entry(form, textvariable=self.display_name).grid(row=3, column=0, sticky="ew", ipady=8)
        self._field_label(form, "pet 包目录、ZIP，或 CODEX_HOME/pets 下的 petId", row=4)
        path_row = tk.Frame(form, bg=c["surface_high"])
        path_row.grid(row=5, column=0, sticky="ew")
        path_row.grid_columnconfigure(0, weight=1)
        self._entry(path_row, textvariable=self.pet_path).grid(row=0, column=0, sticky="ew", ipady=8)
        self._make_button(path_row, text="目录", command=self._choose_pet_dir, variant="ghost").grid(row=0, column=1, padx=(8, 0), ipady=5)
        self._make_button(path_row, text="ZIP", command=self._choose_pet_zip, variant="ghost").grid(row=0, column=2, padx=(8, 0), ipady=5)
        tk.Label(
            form,
            text="包里只需要 pet.json 和 spritesheet.webp。生成请交给 hatch-pet 或现有 Codex pet 项目。",
            bg=c["surface_high"],
            fg=c["muted"],
            justify="left",
            wraplength=340,
            font=_ui_font(11),
        ).grid(row=6, column=0, sticky="w", pady=(14, 0))

    def _render_enable_step(self) -> None:
        c = PREMIUM_SETUP_COLORS
        preview = self._preview_panel(self.content_frame, "导入预览", 0, 0)
        self.preview_label = tk.Label(preview, text="分身预览加载中", bg=c["field"], fg=c["muted"], width=28, height=12, justify="center")
        self.preview_label.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
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
            wraplength=340,
            font=_ui_font(11),
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

    def _sync_footer(self) -> None:
        c = PREMIUM_SETUP_COLORS
        self.back_button.configure(state="normal", bg=c["ghost"], fg=c["text"])
        self.primary_button.configure(state="normal", bg=c["button"], fg=c["button_text"])
        if self.current_step == "pet":
            self.back_button.configure(state="disabled")
            self.primary_button.configure(text="导入预览")
        else:
            self.primary_button.configure(text="启用这个分身")

    @staticmethod
    def _stage_index(stage: str) -> int:
        stages = [item[0] for item in SETUP_PROGRESS_STAGES]
        try:
            return stages.index(stage)
        except ValueError:
            return 0

    @staticmethod
    def _preview_panel(parent: tk.Widget, title: str, row: int, column: int) -> tk.Frame:
        c = PREMIUM_SETUP_COLORS
        panel = tk.Frame(parent, bg=c["surface_high"], padx=18, pady=18)
        panel.grid(row=row, column=column, sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        tk.Label(panel, text=title, bg=c["surface_high"], fg=c["muted"], font=_ui_font(11, bold=True)).grid(row=0, column=0, sticky="w")
        return panel

    @staticmethod
    def _form_panel(parent: tk.Widget, *, row: int, column: int) -> tk.Frame:
        c = PREMIUM_SETUP_COLORS
        return tk.Frame(parent, bg=c["surface_high"], padx=20, pady=18)

    def _make_button(self, parent: tk.Widget, *, text: str, command: Any, variant: str) -> tk.Label:
        c = PREMIUM_SETUP_COLORS
        primary = variant == "primary"
        button = tk.Label(
            parent,
            text=text,
            bg=c["button"] if primary else c["ghost"],
            fg=c["button_text"] if primary else c["text"],
            padx=18,
            pady=10,
            font=_ui_font(12, bold=True),
            cursor="hand2",
        )
        button.bind("<Button-1>", lambda _event: command() if str(button.cget("state")) != "disabled" else None)
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
        tk.Label(parent, text=kicker, bg=c["surface_high"], fg=c["accent"], font=_ui_font(11, bold=True)).grid(row=row, column=0, sticky="w")
        tk.Label(parent, text=title, bg=c["surface_high"], fg=c["text"], font=_display_font(20)).grid(row=row + 1, column=0, sticky="w", pady=(3, 12))

    @staticmethod
    def _field_label(parent: tk.Widget, text: str, *, row: int) -> None:
        c = PREMIUM_SETUP_COLORS
        tk.Label(parent, text=text, bg=c["surface_high"], fg=c["muted"], font=_ui_font(11, bold=True)).grid(row=row, column=0, sticky="w", pady=(10, 5))

    def _choose_pet_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 Codex pet 包目录")
        if path:
            self.pet_path.set(path)
            self._load_pet_preview(Path(path).expanduser())
            self.status.set("pet 包目录已载入。")

    def _choose_pet_zip(self) -> None:
        path = filedialog.askopenfilename(title="选择 Codex pet ZIP", filetypes=[("ZIP", "*.zip"), ("All files", "*.*")])
        if path:
            self.pet_path.set(path)
            self.status.set("pet ZIP 已载入，导入时会校验 spritesheet。")

    def _load_pet_preview(self, path: Path) -> None:
        if not self.preview_label or not path.exists() or not path.is_dir():
            return
        try:
            pet = json.loads((path / "pet.json").read_text(encoding="utf-8"))
            sheet = Image.open(path / str(pet.get("spritesheetPath") or "spritesheet.webp")).convert("RGBA")
            image = sheet.crop((0, 0, 192, 208))
            image.thumbnail((270, 270), Image.Resampling.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(image)
        except Exception as exc:  # noqa: BLE001
            self.preview_image = None
            self.preview_label.configure(image="", text=f"预览失败：{exc}")
            return
        self.preview_label.configure(image=self.preview_image, text="", width=270, height=270)

    def _load_generated_preview(self, twin_id: str) -> None:
        if not self.preview_label:
            return
        try:
            manifest = self.controller.avatars.get_manifest(twin_id)
            pack = manifest.get("spritePack") if isinstance(manifest.get("spritePack"), dict) else {}
            image = Image.open(str(pack.get("spritesheet") or "")).convert("RGBA").crop((0, 0, 192, 208))
            image.thumbnail((270, 270), Image.Resampling.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(image)
        except Exception as exc:  # noqa: BLE001
            self.preview_image = None
            self.preview_label.configure(image="", text=f"预览加载失败：{exc}")
            return
        self.preview_label.configure(image=self.preview_image, text="", width=270, height=270)

    def _go_next(self) -> None:
        if self.current_step == "enable":
            self._enable_created_twin()
            return
        source = self.pet_path.get().strip()
        if not source:
            messagebox.showerror("JiuMe", "请先选择 pet 包目录、ZIP，或填写 CODEX_HOME/pets 下的 petId。")
            return
        try:
            result = self.controller.create_twin_from_pet(
                display_name=self.display_name.get(),
                source_path=source if Path(source).expanduser().exists() else None,
                pet_id=None if Path(source).expanduser().exists() else source,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("JiuMe", str(exc))
            self.status.set(str(exc))
            return
        self.created_twin_id = str(result.get("twin", {}).get("id") or "")
        self.status.set("pet 包已经导入。点启用后它才会出现在桌面。")
        self._set_step("enable")

    def _go_back(self) -> None:
        if self.current_step == "enable":
            self._set_step("pet")

    def _enable_created_twin(self) -> None:
        if not self.created_twin_id:
            return
        try:
            twin = self.controller.enable_twin(self.created_twin_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("JiuMe", str(exc))
            return
        self.status.set(f"已启用：{twin.get('displayName') or 'JiuMe'}。正在打开桌面分身。")
        self.primary_button.configure(text="已启用", state="disabled", bg=PREMIUM_SETUP_COLORS["line"], fg=PREMIUM_SETUP_COLORS["muted"])
        self.root.after(300, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the native JiuMe setup window.")
    parser.add_argument("--display-name", default="JiuMe")
    parser.add_argument("--pet", default="", help="Codex pet package directory, ZIP, or petId under CODEX_HOME/pets.")
    parser.add_argument("--enable", action="store_true", help="Enable the imported twin.")
    parser.add_argument("--photo", default="", help=argparse.SUPPRESS)
    parser.add_argument("--api-key", default="", help=argparse.SUPPRESS)
    parser.add_argument("--base-url", default="", help=argparse.SUPPRESS)
    parser.add_argument("--model", default="", help=argparse.SUPPRESS)
    parser.add_argument("--host", default="", help=argparse.SUPPRESS)
    parser.add_argument("--port", default="", help=argparse.SUPPRESS)
    parser.add_argument("--open", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    controller = NativeSetupController()
    if args.photo or args.api_key or args.base_url or args.model:
        raise SystemExit("JiuMe no longer generates avatars from photos. Use --pet with a Codex pet package.")
    if args.pet:
        pet = Path(args.pet).expanduser()
        result = controller.create_twin_from_pet(
            display_name=args.display_name,
            source_path=str(pet) if pet.exists() else None,
            pet_id=None if pet.exists() else args.pet,
        )
        if args.enable:
            result["twin"] = controller.enable_twin(str(result["twin"]["id"]))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    NativeSetupWindow(controller).run()


if __name__ == "__main__":
    main()
