"""Native settings center for JiuMe desktop twins."""

from __future__ import annotations

import tkinter as tk
import threading
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable

from jiume.desktop.state import read_conversation_state, read_service_status, read_window_state, write_window_state
from jiume.runtime.health import RuntimeHealth, RuntimeHealthCode, check_gateway_health
from jiume.runtime.status import runtime_config_url, runtime_diagnostic_from_health, runtime_diagnostic_from_service
from jiume.setup.server import PREMIUM_SETUP_COLORS
from jiume.twins.store import TwinStore

SETTINGS_FONT = "PingFang SC"
SETTINGS_DISPLAY_FONT = "PingFang SC"

SETTINGS_CENTER_DEFAULT_AVATAR_SIZE = 128
SETTINGS_CENTER_MIN_AVATAR_SIZE = 80
SETTINGS_CENTER_MAX_AVATAR_SIZE = 220

SETTINGS_CENTER_SECTIONS: tuple[dict[str, str], ...] = (
    {"id": "profile", "label": "分身"},
    {"id": "desktop", "label": "桌面"},
    {"id": "skills", "label": "技能"},
    {"id": "artifacts", "label": "产物"},
    {"id": "history", "label": "历史"},
    {"id": "diagnostics", "label": "诊断"},
)


def profile_settings_snapshot(twin: dict[str, Any] | None) -> dict[str, str]:
    twin = twin if isinstance(twin, dict) else {}
    permissions = twin.get("permissions") if isinstance(twin.get("permissions"), dict) else {}
    appearance = twin.get("appearance") if isinstance(twin.get("appearance"), dict) else {}
    appearance_id = appearance.get("id") if appearance else twin.get("appearance")
    if isinstance(appearance_id, dict):
        appearance_id = None
    return {
        "displayName": str(twin.get("displayName") or "JiuMe"),
        "purpose": str(twin.get("purpose") or "桌面个人分身助手"),
        "tone": str(twin.get("tone") or "warm, concise, and action-oriented"),
        "defaultMode": str(permissions.get("defaultMode") or twin.get("defaultMode") or "confirm_before_act"),
        "appearanceId": str(appearance_id or "blue"),
    }


def profile_settings_payload(
    *,
    display_name: str,
    purpose: str,
    tone: str,
    default_mode: str,
    appearance_id: str,
) -> dict[str, Any]:
    return {
        "displayName": " ".join(str(display_name or "JiuMe").split()) or "JiuMe",
        "purpose": " ".join(str(purpose or "桌面个人分身助手").split()) or "桌面个人分身助手",
        "tone": " ".join(str(tone or "warm, concise, and action-oriented").split()),
        "permissions": {"defaultMode": str(default_mode or "confirm_before_act")},
        "appearance": {"id": str(appearance_id or "blue")},
    }


def _comma_label(items: list[str], *, empty: str = "无") -> str:
    return "、".join(items) if items else empty


def _skill_ids_from_text(value: str) -> list[str]:
    raw = str(value or "")
    for delimiter in ("，", "、", ";", "\n", "\t"):
        raw = raw.replace(delimiter, ",")
    ids: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        skill_id = item.strip()
        if not skill_id:
            continue
        key = skill_id.casefold()
        if key in seen:
            continue
        seen.add(key)
        ids.append(skill_id)
    return ids


def skill_settings_payload(allowed_skill_ids: str) -> dict[str, Any]:
    return {"permissions": {"allowedSkillIds": _skill_ids_from_text(allowed_skill_ids)}}


def build_skill_settings_snapshot(
    *,
    twin: dict[str, Any] | None,
    conversation: dict[str, Any] | None = None,
) -> dict[str, str]:
    twin = twin if isinstance(twin, dict) else {}
    conversation = conversation if isinstance(conversation, dict) else {}
    permissions = twin.get("permissions") if isinstance(twin.get("permissions"), dict) else {}
    allowed = [str(item).strip() for item in permissions.get("allowedSkillIds", []) if str(item).strip()] if isinstance(permissions.get("allowedSkillIds"), list) else []
    active = conversation.get("activeSkill") if isinstance(conversation.get("activeSkill"), dict) else None
    active_label = str(active.get("displayName") or active.get("id") or "未固定") if active else "未固定"
    return {
        "allowedCsv": ", ".join(allowed),
        "allowedLabel": _comma_label(allowed),
        "allowedCount": str(len(allowed)),
        "activeLabel": active_label,
        "detail": f"允许 {len(allowed)} 个 skill；当前接手：{active_label}。",
    }


def _conversation_artifacts(conversation: dict[str, Any] | None) -> list[dict[str, str]]:
    conversation = conversation if isinstance(conversation, dict) else {}
    activity = conversation.get("activity") if isinstance(conversation.get("activity"), list) else []
    artifacts: list[dict[str, str]] = []
    for item in activity:
        if not isinstance(item, dict):
            continue
        for artifact in item.get("artifacts", []) if isinstance(item.get("artifacts"), list) else []:
            if not isinstance(artifact, dict):
                continue
            label = str(artifact.get("label") or artifact.get("target") or "产物").strip()
            target = str(artifact.get("target") or "").strip()
            if label or target:
                artifacts.append({"label": label or "产物", "target": target})
    return artifacts


def build_artifacts_settings_snapshot(conversation: dict[str, Any] | None = None) -> dict[str, str]:
    artifacts = _conversation_artifacts(conversation)
    labels = [artifact["label"] for artifact in artifacts[:3]]
    return {
        "artifactCount": str(len(artifacts)),
        "latestLabel": labels[0] if labels else "暂无产物",
        "detail": f"最近 {len(artifacts)} 个产物：{_comma_label(labels, empty='暂无产物')}。",
    }


def build_history_settings_snapshot(conversation: dict[str, Any] | None = None) -> dict[str, str]:
    conversation = conversation if isinstance(conversation, dict) else {}
    chat = conversation.get("chat") if isinstance(conversation.get("chat"), list) else []
    activity = conversation.get("activity") if isinstance(conversation.get("activity"), list) else []
    latest = next((item for item in activity if isinstance(item, dict)), {})
    latest_title = str(latest.get("title") or "暂无任务") if isinstance(latest, dict) else "暂无任务"
    return {
        "chatCount": str(len(chat)),
        "activityCount": str(len(activity)),
        "latestTask": latest_title,
        "detail": f"最近对话 {len(chat)} 条；任务记录 {len(activity)} 条；最新任务：{latest_title}。",
    }


def settings_service_status_summary(payload: dict[str, Any]) -> dict[str, str]:
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, dict):
        return {"state": "unknown", "label": "后台状态未知", "detail": "设置页会在这里显示连接诊断。"}
    agent = services.get("agent")
    setup = services.get("setup")
    agent_status = str(agent.get("status") or "") if isinstance(agent, dict) else ""
    gateway_ready = agent.get("gateway_ready") if isinstance(agent, dict) else None
    setup_status = str(setup.get("status") or "") if isinstance(setup, dict) else ""
    if agent_status in {"running", "reused"} and gateway_ready is False:
        label = "Gateway 检测中"
        state = "unknown"
    elif agent_status in {"running", "reused"}:
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
        detail_parts.append(f"配置窗口 {setup_status}")
    if isinstance(agent, dict):
        mode = str(agent.get("mode") or "")
        if mode:
            detail_parts.append(f"模式 {mode}")
        restart_count = agent.get("restart_count")
        if isinstance(restart_count, int) and restart_count > 0:
            detail_parts.append(f"已恢复 {restart_count} 次")
    return {"state": state, "label": label, "detail": " · ".join(detail_parts) or "后台状态已写入。"}


def avatar_size_label(size: int) -> str:
    if size <= 120:
        return "紧凑"
    if size >= 168:
        return "大"
    return "标准"


def _percent_label(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 1.0
    number = min(max(number, 0.35), 1.0)
    return f"{round(number * 100):.0f}%"


def _avatar_size_value(*candidates: Any) -> int:
    for candidate in candidates:
        try:
            size = int(candidate)
        except (TypeError, ValueError):
            continue
        return min(max(size, SETTINGS_CENTER_MIN_AVATAR_SIZE), SETTINGS_CENTER_MAX_AVATAR_SIZE)
    return SETTINGS_CENTER_DEFAULT_AVATAR_SIZE


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _widget_int(widget: tk.Misc, method_name: str, default: int) -> int:
    try:
        return int(getattr(widget, method_name)())
    except (AttributeError, tk.TclError, TypeError, ValueError):
        return default


def _ui_font(size: int, *, bold: bool = False) -> tuple[str, int] | tuple[str, int, str]:
    return (SETTINGS_FONT, int(size), "bold") if bold else (SETTINGS_FONT, int(size))


def _display_font(size: int, *, bold: bool = True) -> tuple[str, int] | tuple[str, int, str]:
    return (SETTINGS_DISPLAY_FONT, int(size), "bold") if bold else (SETTINGS_DISPLAY_FONT, int(size))


def build_agent_settings_snapshot(
    *,
    service: dict[str, Any],
    gateway_url: str,
    agent_mode: str,
    health: RuntimeHealth | None = None,
) -> dict[str, str]:
    summary = settings_service_status_summary(service)
    diagnostic = runtime_diagnostic_from_health(health, service) if health is not None else runtime_diagnostic_from_service(service)
    if health is not None:
        summary = {
            "label": diagnostic.label,
            "state": "online" if diagnostic.ready else "offline",
            "detail": diagnostic.detail,
        }
    detail = str(summary.get("detail") or "")
    note = str(service.get("note") or "") if isinstance(service, dict) else ""
    if note and note not in detail:
        detail = f"{detail} · {note}" if detail else note
    if diagnostic.detail and diagnostic.detail not in detail:
        detail = f"{diagnostic.detail} · {detail}" if detail else diagnostic.detail
    return {
        "connectionLabel": str(summary.get("label") or "后台状态未知"),
        "connectionState": str(summary.get("state") or "unknown"),
        "detail": detail,
        "gatewayUrl": str(gateway_url or ""),
        "agentMode": str(agent_mode or ""),
        "diagnosticCode": diagnostic.code,
        "primaryAction": diagnostic.primary_action,
        "secondaryAction": diagnostic.secondary_action,
        "configUrl": runtime_config_url(),
    }


def build_desktop_settings_snapshot(
    *,
    window_state: dict[str, Any],
    current_size: int,
    gateway_url: str,
) -> dict[str, str]:
    size = _avatar_size_value(window_state.get("size"), current_size, SETTINGS_CENTER_DEFAULT_AVATAR_SIZE)
    x = window_state.get("x")
    y = window_state.get("y")
    placement = f"{x},{y}" if isinstance(x, int) and isinstance(y, int) else "当前位置"
    return {
        "size": str(size),
        "sizeLabel": avatar_size_label(size),
        "placement": placement,
        "opacity": _percent_label(window_state.get("opacity")),
        "gatewayUrl": str(gateway_url or ""),
    }


@dataclass
class SettingsCenterCallbacks:
    on_saved: Callable[[], None]
    on_quit: Callable[[], None]


class SettingsCenterWindow:
    def __init__(
        self,
        *,
        root: tk.Misc,
        store: TwinStore,
        active_twin_id: str,
        current_size: int,
        gateway_url: str,
        agent_mode: str,
        callbacks: SettingsCenterCallbacks,
    ) -> None:
        self.root = root
        self.store = store
        self.active_twin_id = active_twin_id
        self.current_size = current_size
        self.gateway_url = gateway_url
        self.agent_mode = agent_mode
        self.callbacks = callbacks
        self.window: tk.Toplevel | None = None
        self.section = "profile"
        self.body: tk.Frame | None = None
        self.nav_buttons: dict[str, tk.Label] = {}
        self.name_var = tk.StringVar(master=self.root, value="")
        self.purpose_var = tk.StringVar(master=self.root, value="")
        self.tone_var = tk.StringVar(master=self.root, value="")
        self.mode_var = tk.StringVar(master=self.root, value="confirm_before_act")
        self.skill_ids_var = tk.StringVar(master=self.root, value="")
        self.size_var = tk.StringVar(
            master=self.root,
            value=str(_avatar_size_value(current_size, SETTINGS_CENTER_DEFAULT_AVATAR_SIZE)),
        )
        self.status_var = tk.StringVar(master=self.root, value="")
        self._runtime_health: RuntimeHealth | None = None
        self._runtime_health_refreshing = False

    def open(self) -> None:
        if self.window and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            self._reload()
            return
        c = PREMIUM_SETUP_COLORS
        self.window = tk.Toplevel(self.root)
        self.window.title("JiuMe 设置")
        self.window.geometry("1000x680")
        self.window.resizable(False, False)
        self.window.configure(bg=c["bg"])
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        shell = tk.Frame(self.window, bg=c["bg"], padx=32, pady=28)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=c["bg"])
        header.pack(fill="x")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="JiuMe 设置",
            bg=c["bg"],
            fg=c["text"],
            font=_display_font(28),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="编辑分身、桌面表现、技能、产物和历史。Agent runtime 只在这里做诊断和跳转。",
            bg=c["bg"],
            fg=c["muted"],
            font=_ui_font(13),
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))
        tk.Label(
            header,
            text="日常界面保持窄，只把重配置放在这里",
            bg=c["surface_high"],
            fg=c["accent"],
            padx=12,
            pady=7,
            font=_ui_font(11, bold=True),
        ).grid(row=0, column=1, rowspan=2, sticky="ne")
        content = tk.Frame(shell, bg=c["bg"])
        content.pack(fill="both", expand=True, pady=(22, 0))
        nav_shell = tk.Frame(content, bg=c["surface_shell"], padx=1, pady=1)
        nav_shell.pack(side="left", fill="y", padx=(0, 18))
        nav = tk.Frame(nav_shell, bg=c["surface_high"], padx=10, pady=10, width=166)
        nav.pack(side="left", fill="y", padx=(0, 16))
        nav.pack_propagate(False)
        body_shell = tk.Frame(content, bg=c["surface_shell"], padx=2, pady=2)
        body_shell.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(body_shell, bg=c["surface"], padx=28, pady=22)
        self.body.pack(fill="both", expand=True)
        for section in SETTINGS_CENTER_SECTIONS:
            button = tk.Label(
                nav,
                text=section["label"],
                anchor="w",
                padx=14,
                pady=10,
                bg=c["surface_high"],
                fg=c["muted"],
                font=_ui_font(12, bold=True),
                cursor="hand2",
            )
            button.pack(fill="x", pady=4)
            button.bind("<Button-1>", lambda _event, value=section["id"]: self._set_section(value))
            button.bind(
                "<Enter>",
                lambda _event, widget=button: widget.configure(bg=c["ghost_hover"]) if widget.cget("fg") != c["button_text"] else None,
            )
            button.bind(
                "<Leave>",
                lambda _event, widget=button, value=section["id"]: self._style_nav_button(value),
            )
            self.nav_buttons[section["id"]] = button
        self._reload()

    def close(self) -> None:
        if self.window and self.window.winfo_exists():
            self.window.withdraw()

    def _reload(self) -> None:
        twin = self.store.get_twin(self.active_twin_id) if self.active_twin_id else None
        snapshot = profile_settings_snapshot(twin)
        self.name_var.set(snapshot["displayName"])
        self.purpose_var.set(snapshot["purpose"])
        self.tone_var.set(snapshot["tone"])
        self.mode_var.set(snapshot["defaultMode"])
        self.skill_ids_var.set(
            build_skill_settings_snapshot(twin=twin, conversation=read_conversation_state())["allowedCsv"]
        )
        window_state = read_window_state()
        self.size_var.set(str(window_state.get("size") or self.current_size or SETTINGS_CENTER_DEFAULT_AVATAR_SIZE))
        self._render()

    def _set_section(self, section: str) -> None:
        ids = {item["id"] for item in SETTINGS_CENTER_SECTIONS}
        self.section = section if section in ids else "profile"
        self._render()

    def _clear_body(self) -> tk.Frame:
        if self.body is None:
            raise RuntimeError("settings center body is not built")
        for child in self.body.winfo_children():
            child.destroy()
        for section_id in self.nav_buttons:
            self._style_nav_button(section_id)
        return self.body

    def _style_nav_button(self, section_id: str) -> None:
        button = self.nav_buttons.get(section_id)
        if button is None:
            return
        c = PREMIUM_SETUP_COLORS
        active = section_id == self.section
        button.configure(
            bg=c["accent"] if active else c["surface_high"],
            fg=c["button_text"] if active else c["muted"],
            padx=16 if active else 14,
        )

    def _render(self) -> None:
        if self.section == "desktop":
            self._render_desktop_section()
        elif self.section == "skills":
            self._render_skills_section()
        elif self.section == "artifacts":
            self._render_artifacts_section()
        elif self.section == "history":
            self._render_history_section()
        elif self.section == "diagnostics":
            self._render_diagnostics_section()
        else:
            self._render_profile_section()

    def _section_title(self, parent: tk.Frame, title: str, detail: str) -> None:
        c = PREMIUM_SETUP_COLORS
        tk.Label(parent, text=title, bg=c["surface"], fg=c["text"], font=_display_font(22)).pack(anchor="w")
        tk.Label(
            parent,
            text=detail,
            bg=c["surface"],
            fg=c["muted"],
            font=_ui_font(12),
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(5, 16))

    def _field(self, parent: tk.Frame, label: str, variable: tk.StringVar, *, show: str = "") -> None:
        c = PREMIUM_SETUP_COLORS
        block = tk.Frame(parent, bg=c["surface"])
        block.pack(fill="x", pady=5)
        tk.Label(block, text=label, bg=c["surface"], fg=c["muted"], anchor="w", font=_ui_font(11, bold=True)).pack(
            anchor="w",
            pady=(0, 5),
        )
        input_shell = tk.Frame(block, bg=c["line_soft"], padx=1, pady=1)
        input_shell.pack(fill="x")
        entry = tk.Entry(
            input_shell,
            textvariable=variable,
            show=show,
            bg=c["field"],
            fg=c["text"],
            insertbackground=c["accent"],
            relief="flat",
            highlightthickness=0,
            font=_ui_font(12),
        )
        entry.pack(fill="x", expand=True, ipady=7, padx=10, pady=5)

    def _render_profile_section(self) -> None:
        body = self._clear_body()
        self._section_title(body, "分身", "编辑名字、定位、语气和权限模式。")
        self._field(body, "名字", self.name_var)
        self._field(body, "定位", self.purpose_var)
        self._field(body, "语气", self.tone_var)
        self._field(body, "权限", self.mode_var)
        self._button_row(body, [("保存分身", self._save_profile)])

    def _render_desktop_section(self) -> None:
        body = self._clear_body()
        snapshot = build_desktop_settings_snapshot(
            window_state=read_window_state(),
            current_size=self.current_size,
            gateway_url=self.gateway_url,
        )
        self._section_title(body, "桌面", f"当前大小 {snapshot['sizeLabel']}，位置 {snapshot['placement']}。")
        self._field(body, "头像大小", self.size_var)
        self._button_row(body, [("保存桌面", self._save_desktop)])

    def _render_skills_section(self) -> None:
        body = self._clear_body()
        snapshot = build_skill_settings_snapshot(
            twin=self.store.get_twin(self.active_twin_id) if self.active_twin_id else None,
            conversation=read_conversation_state(),
        )
        self._section_title(body, "技能", snapshot["detail"])
        self._field(body, "允许 Skill IDs", self.skill_ids_var)
        tk.Label(
            body,
            text=f"当前接手：{snapshot['activeLabel']}。用逗号分隔多个 skill id；保存后会写入当前分身权限。",
            bg=PREMIUM_SETUP_COLORS["surface"],
            fg=PREMIUM_SETUP_COLORS["muted"],
            wraplength=620,
            justify="left",
            font=_ui_font(12),
        ).pack(anchor="w", pady=(8, 12))
        self._button_row(body, [("保存技能", self._save_skills), ("重新加载", self._reload)])

    def _render_artifacts_section(self) -> None:
        body = self._clear_body()
        snapshot = build_artifacts_settings_snapshot(read_conversation_state())
        self._section_title(body, "产物", snapshot["detail"])
        tk.Label(
            body,
            text=(
                f"最新产物：{snapshot['latestLabel']}。这里承接从日常头像旁收起的产物入口；"
                "日常面只显示短结果，完整产物记录留在高级设置里查看。"
            ),
            bg=PREMIUM_SETUP_COLORS["surface"],
            fg=PREMIUM_SETUP_COLORS["muted"],
            wraplength=620,
            justify="left",
            font=_ui_font(12),
        ).pack(anchor="w", pady=(0, 12))
        self._button_row(body, [("重新加载", self._reload)])

    def _render_history_section(self) -> None:
        body = self._clear_body()
        snapshot = build_history_settings_snapshot(read_conversation_state())
        self._section_title(body, "历史", snapshot["detail"])
        tk.Label(
            body,
            text=(
                f"最近对话：{snapshot['chatCount']} 条；任务记录：{snapshot['activityCount']} 条。"
                "日常面不会展开完整历史，需要复盘时从这里进入。"
            ),
            bg=PREMIUM_SETUP_COLORS["surface"],
            fg=PREMIUM_SETUP_COLORS["muted"],
            wraplength=620,
            justify="left",
            font=_ui_font(12),
        ).pack(anchor="w", pady=(0, 12))
        self._button_row(body, [("重新加载", self._reload)])

    def _render_diagnostics_section(self) -> None:
        body = self._clear_body()
        snapshot = build_agent_settings_snapshot(
            service=read_service_status(),
            gateway_url=self.gateway_url,
            agent_mode=self.agent_mode,
            health=self._runtime_health,
        )
        self._section_title(body, "诊断", f"{snapshot['connectionLabel']} · {snapshot['gatewayUrl'] or '未设置 Gateway'}")
        tk.Label(
            body,
            text=snapshot["detail"],
            bg=PREMIUM_SETUP_COLORS["surface"],
            fg=PREMIUM_SETUP_COLORS["muted"],
            wraplength=620,
            justify="left",
            font=_ui_font(12),
        ).pack(anchor="w", pady=(0, 12))
        tk.Label(
            body,
            text=f"Agent 模式：{snapshot['agentMode'] or 'auto'}。runtime 的 API Key、Base URL、模型都请在 JiuwenSwarm 配置页维护。",
            bg=PREMIUM_SETUP_COLORS["surface"],
            fg=PREMIUM_SETUP_COLORS["muted"],
            wraplength=620,
            justify="left",
            font=_ui_font(12),
        ).pack(anchor="w", pady=(0, 12))
        tk.Label(
            body,
            textvariable=self.status_var,
            bg=PREMIUM_SETUP_COLORS["surface"],
            fg=PREMIUM_SETUP_COLORS["muted"],
            wraplength=620,
            justify="left",
            font=_ui_font(12),
        ).pack(anchor="w", pady=(0, 12))
        self._button_row(
            body,
            [
                ("打开 JiuwenSwarm 配置", self._open_runtime_config),
                ("重新检测", self._refresh_diagnostics_section),
                ("退出 JiuMe", self.callbacks.on_quit),
            ],
        )

    def _button_row(self, parent: tk.Frame, buttons: list[tuple[str, Callable[[], None]]]) -> None:
        c = PREMIUM_SETUP_COLORS
        row = tk.Frame(parent, bg=c["surface"])
        row.pack(fill="x", pady=(14, 0))
        for index, (label, command) in enumerate(buttons):
            primary = index == 0
            bg = c["button"] if primary else c["ghost"]
            fg = c["button_text"] if primary else c["text"]
            hover = c["accent_high"] if primary else c["ghost_hover"]
            button = tk.Label(
                row,
                text=label,
                bg=bg,
                fg=fg,
                padx=18,
                pady=9,
                font=_ui_font(12, bold=True),
                cursor="hand2",
            )
            button.pack(side="left", padx=(0, 10))
            button.bind("<Button-1>", lambda _event, action=command: action())
            button.bind("<ButtonPress-1>", lambda _event, widget=button, color=hover: widget.configure(bg=color, pady=10))
            button.bind("<ButtonRelease-1>", lambda _event, widget=button, color=hover: widget.configure(bg=color, pady=9))
            button.bind("<Enter>", lambda _event, widget=button, color=hover: widget.configure(bg=color))
            button.bind("<Leave>", lambda _event, widget=button, color=bg: widget.configure(bg=color, pady=9))

    def _save_profile(self) -> None:
        twin = self.store.get_twin(self.active_twin_id)
        if not twin:
            self.status_var.set("还没有可用分身。")
            return
        self.store.update_twin(
            self.active_twin_id,
            profile_settings_payload(
                tone=self.tone_var.get(),
                default_mode=self.mode_var.get(),
                display_name=self.name_var.get(),
                purpose=self.purpose_var.get(),
                appearance_id=(
                    (twin.get("appearance") or {}).get("id")
                    if isinstance(twin.get("appearance"), dict)
                    else str(twin.get("appearance") or "blue")
                ),
            ),
        )
        self.status_var.set("分身设置已保存。")
        self.callbacks.on_saved()

    def _save_desktop(self) -> None:
        state = read_window_state()
        raw_size = str(self.size_var.get() or "").strip()
        if raw_size and _optional_int(raw_size) is None:
            self.status_var.set("头像大小请输入数字。")
            return
        size = _avatar_size_value(raw_size, self.current_size, state.get("size"), SETTINGS_CENTER_DEFAULT_AVATAR_SIZE)
        self.size_var.set(str(size))
        x = _optional_int(state.get("x"))
        y = _optional_int(state.get("y"))
        screen_width = _optional_int(state.get("screen_width"))
        screen_height = _optional_int(state.get("screen_height"))
        write_window_state(
            x=x if x is not None else _widget_int(self.root, "winfo_x", 0),
            y=y if y is not None else _widget_int(self.root, "winfo_y", 0),
            size=size,
            screen_width=screen_width if screen_width is not None else _widget_int(self.root, "winfo_screenwidth", size),
            screen_height=screen_height if screen_height is not None else _widget_int(self.root, "winfo_screenheight", size),
            opacity=state.get("opacity"),
            twin_id=self.active_twin_id,
        )
        self.status_var.set("桌面设置已保存。")
        self.callbacks.on_saved()

    def _save_skills(self) -> None:
        twin = self.store.get_twin(self.active_twin_id)
        if not twin:
            self.status_var.set("还没有可用分身。")
            return
        payload = skill_settings_payload(self.skill_ids_var.get())
        self.store.update_twin(self.active_twin_id, payload)
        snapshot = build_skill_settings_snapshot(
            twin=self.store.get_twin(self.active_twin_id),
            conversation=read_conversation_state(),
        )
        self.skill_ids_var.set(snapshot["allowedCsv"])
        self.status_var.set("Skill 设置已保存。")
        self.callbacks.on_saved()
        self._render_skills_section()

    def _open_runtime_config(self) -> None:
        webbrowser.open(runtime_config_url())
        self.status_var.set("已打开 JiuwenSwarm 配置页。保存 runtime 模型后回到这里重新检测。")

    def _refresh_diagnostics_section(self) -> None:
        if self._runtime_health_refreshing:
            self.status_var.set("正在检测 Gateway。")
            return
        self._runtime_health_refreshing = True
        self.status_var.set("正在检测 Gateway。")
        self._render_diagnostics_section()

        def probe() -> None:
            health = check_gateway_health(self.gateway_url)

            def apply_result() -> None:
                self._runtime_health = health
                self._runtime_health_refreshing = False
                self.status_var.set("已重新检测 Gateway。")
                if self.section == "diagnostics":
                    self._render_diagnostics_section()

            try:
                self.root.after(0, apply_result)
            except tk.TclError:
                self._runtime_health_refreshing = False

        threading.Thread(target=probe, daemon=True).start()
