"""Local JSON store for JiuMe twins."""

from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jiume.audit.logger import append_audit_event
from jiume.paths import get_twins_root
from jiume.security.permissions import (
    DEFAULT_DENIED_TOOL_CATEGORIES,
    DEFAULT_SKILLS,
    normalize_permission_mode,
    normalize_skill_ids,
)
from jiume.twins.appearance import normalize_twin_appearance

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_TWIN_MEMORIES = 12
TWIN_MEMORY_CHAR_LIMIT = 120
TWIN_STATUSES = {"creating", "ready", "active", "error"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_safe_twin_id(twin_id: str) -> str:
    value = str(twin_id or "").strip()
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError("invalid twin_id")
    return value


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_twin_memories(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    memories: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = " ".join(str(item or "").split())
        if not text:
            continue
        text = text[:TWIN_MEMORY_CHAR_LIMIT]
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        memories.append(text)
        if len(memories) >= MAX_TWIN_MEMORIES:
            break
    return memories


class TwinStore:
    """Small local file-backed store for product MVP state."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_twins_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.active_path = self.root / "active.json"

    def _twin_root(self, twin_id: str, *, create: bool = False) -> Path:
        root = self.root / ensure_safe_twin_id(twin_id)
        if create:
            root.mkdir(parents=True, exist_ok=True)
        return root

    def list_twins(self) -> list[dict[str, Any]]:
        index = _read_json(self.index_path, {"twins": []})
        ids = index.get("twins") if isinstance(index, dict) else []
        twins = []
        for twin_id in ids if isinstance(ids, list) else []:
            try:
                twins.append(self.get_twin(str(twin_id)))
            except FileNotFoundError:
                continue
        return twins

    def get_active_twin_id(self) -> str | None:
        active = _read_json(self.active_path, {})
        twin_id = active.get("twin_id") if isinstance(active, dict) else None
        if isinstance(twin_id, str) and twin_id:
            try:
                twin = self.get_twin(twin_id)
            except FileNotFoundError:
                return None
            return twin["id"] if twin.get("status") == "active" else None
        if self.active_path.exists():
            return None
        twins = self.list_twins()
        active_twins = [twin for twin in twins if twin.get("status") == "active"]
        return active_twins[0]["id"] if active_twins else None

    def set_active_twin(self, twin_id: str) -> dict[str, Any]:
        twin = self.get_twin(twin_id)
        if twin.get("status") != "active":
            raise ValueError("twin is not active")
        _write_json(self.active_path, {"twin_id": twin["id"], "updated_at": utc_now()})
        append_audit_event(twin["id"], "twin.active_set", {})
        return twin

    def activate_twin(self, twin_id: str) -> dict[str, Any]:
        twin = self.get_twin(twin_id)
        if twin.get("status") not in {"ready", "active"}:
            raise ValueError("twin is not ready")
        twin = self.update_twin(twin["id"], {"status": "active"})
        _write_json(self.active_path, {"twin_id": twin["id"], "updated_at": utc_now()})
        append_audit_event(twin["id"], "twin.active_set", {"reason": "enable"})
        return twin

    def get_twin(self, twin_id: str) -> dict[str, Any]:
        safe_id = ensure_safe_twin_id(twin_id)
        path = self._twin_root(safe_id) / "profile.json"
        if not path.exists():
            raise FileNotFoundError(f"twin not found: {safe_id}")
        profile = _read_json(path, {})
        if not isinstance(profile, dict):
            raise FileNotFoundError(f"twin profile invalid: {safe_id}")
        return self._normalize_profile(profile)

    def create_twin(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        now = utc_now()
        activate = bool(payload.get("activate", True))
        twin_id = str(payload.get("id") or f"twin_{secrets.token_hex(4)}")
        twin_id = ensure_safe_twin_id(twin_id)
        twin_root = self._twin_root(twin_id, create=True)
        profile_path = twin_root / "profile.json"
        if profile_path.exists():
            raise FileExistsError(f"twin already exists: {twin_id}")

        explicit_skills = False
        if "selectedSkillIds" in payload:
            explicit_skills = True
            selected_skills = normalize_skill_ids(payload.get("selectedSkillIds"))
        elif "selected_skill_ids" in payload:
            explicit_skills = True
            selected_skills = normalize_skill_ids(payload.get("selected_skill_ids"))
        else:
            selected_skills = []
        if not explicit_skills and not selected_skills:
            selected_skills = list(DEFAULT_SKILLS)

        profile = {
            "id": twin_id,
            "displayName": str(payload.get("displayName") or payload.get("display_name") or "JiuMe").strip() or "JiuMe",
            "baseType": str(payload.get("baseType") or payload.get("base_type") or "self"),
            "status": "active" if activate else "creating",
            "tone": str(payload.get("tone") or "clear, helpful, and work-focused"),
            "purpose": str(payload.get("purpose") or "Represent the user for low-risk work tasks."),
            "appearance": normalize_twin_appearance(payload.get("appearance")),
            "memories": normalize_twin_memories(payload.get("memories")),
            "permissions": {
                "defaultMode": normalize_permission_mode(
                    payload.get("defaultMode") or payload.get("default_mode")
                ),
                "allowedSkillIds": selected_skills,
                "deniedToolCategories": list(DEFAULT_DENIED_TOOL_CATEGORIES),
            },
            "avatarManifestPath": f"twins/{twin_id}/avatar/avatar_manifest.json",
            "createdAt": now,
            "updatedAt": now,
        }
        _write_json(profile_path, profile)
        self._add_to_index(twin_id)
        append_audit_event(twin_id, "twin.created", {"displayName": profile["displayName"]})
        if activate:
            _write_json(self.active_path, {"twin_id": twin_id, "updated_at": now})
            append_audit_event(twin_id, "twin.active_set", {"reason": "create"})
        elif not self.active_path.exists():
            _write_json(self.active_path, {"twin_id": None, "pending_twin_id": twin_id, "updated_at": now})
        return profile

    def update_twin(self, twin_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        profile = self.get_twin(twin_id)
        for key in ("displayName", "baseType", "status", "tone", "purpose"):
            if key in updates:
                value = str(updates[key] or "").strip()
                if key == "status":
                    value = value if value in TWIN_STATUSES else profile.get("status") or "creating"
                profile[key] = value
        if "memories" in updates:
            profile["memories"] = normalize_twin_memories(updates.get("memories"))
        if "appearance" in updates:
            profile["appearance"] = normalize_twin_appearance(updates.get("appearance"))
        if "avatarManifestPath" in updates:
            profile["avatarManifestPath"] = str(updates["avatarManifestPath"] or "").strip()
        if "permissions" in updates and isinstance(updates["permissions"], dict):
            permissions = dict(profile.get("permissions") or {})
            incoming = updates["permissions"]
            if "defaultMode" in incoming:
                permissions["defaultMode"] = normalize_permission_mode(incoming.get("defaultMode"))
            if "allowedSkillIds" in incoming:
                permissions["allowedSkillIds"] = normalize_skill_ids(incoming.get("allowedSkillIds"))
            if "deniedToolCategories" in incoming and isinstance(incoming["deniedToolCategories"], list):
                permissions["deniedToolCategories"] = [
                    str(item).strip() for item in incoming["deniedToolCategories"] if str(item).strip()
                ]
            profile["permissions"] = permissions
        profile["updatedAt"] = utc_now()
        _write_json(self._twin_root(profile["id"], create=True) / "profile.json", self._normalize_profile(profile))
        append_audit_event(profile["id"], "twin.updated", {"fields": sorted(updates.keys())})
        return profile

    def delete_twin(self, twin_id: str) -> None:
        safe_id = ensure_safe_twin_id(twin_id)
        root = self._twin_root(safe_id)
        if root.exists():
            shutil.rmtree(root)
        index = _read_json(self.index_path, {"twins": []})
        twins = index.get("twins") if isinstance(index, dict) else []
        twins = [item for item in twins if item != safe_id] if isinstance(twins, list) else []
        _write_json(self.index_path, {"twins": twins, "updated_at": utc_now()})
        if self.get_active_twin_id() == safe_id:
            next_id = None
            for candidate in twins:
                try:
                    if self.get_twin(str(candidate)).get("status") == "active":
                        next_id = candidate
                        break
                except FileNotFoundError:
                    continue
            _write_json(self.active_path, {"twin_id": next_id, "updated_at": utc_now()})

    def enable_skill(self, twin_id: str, skill_id: str) -> dict[str, Any]:
        profile = self.get_twin(twin_id)
        skill = str(skill_id or "").strip()
        if not skill:
            raise ValueError("skill_id is required")
        permissions = dict(profile.get("permissions") or {})
        allowed = normalize_skill_ids(permissions.get("allowedSkillIds"))
        if skill not in allowed:
            allowed.append(skill)
        permissions["allowedSkillIds"] = allowed
        profile["permissions"] = permissions
        profile["updatedAt"] = utc_now()
        _write_json(self._twin_root(profile["id"], create=True) / "profile.json", profile)
        append_audit_event(profile["id"], "skill.enabled", {"skill_id": skill})
        return profile

    def disable_skill(self, twin_id: str, skill_id: str) -> dict[str, Any]:
        profile = self.get_twin(twin_id)
        skill = str(skill_id or "").strip()
        permissions = dict(profile.get("permissions") or {})
        permissions["allowedSkillIds"] = [
            item for item in normalize_skill_ids(permissions.get("allowedSkillIds")) if item != skill
        ]
        profile["permissions"] = permissions
        profile["updatedAt"] = utc_now()
        _write_json(self._twin_root(profile["id"], create=True) / "profile.json", profile)
        append_audit_event(profile["id"], "skill.disabled", {"skill_id": skill})
        return profile

    def _add_to_index(self, twin_id: str) -> None:
        index = _read_json(self.index_path, {"twins": []})
        twins = index.get("twins") if isinstance(index, dict) else []
        if not isinstance(twins, list):
            twins = []
        if twin_id not in twins:
            twins.append(twin_id)
        _write_json(self.index_path, {"twins": twins, "updated_at": utc_now()})

    @staticmethod
    def _normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
        permissions = dict(profile.get("permissions") or {})
        permissions["defaultMode"] = normalize_permission_mode(permissions.get("defaultMode"))
        permissions["allowedSkillIds"] = normalize_skill_ids(permissions.get("allowedSkillIds"))
        denied = permissions.get("deniedToolCategories")
        permissions["deniedToolCategories"] = (
            [str(item).strip() for item in denied if str(item).strip()]
            if isinstance(denied, list)
            else list(DEFAULT_DENIED_TOOL_CATEGORIES)
        )
        profile["permissions"] = permissions
        profile.setdefault("baseType", "self")
        status = str(profile.get("status") or "active").strip()
        profile["status"] = status if status in TWIN_STATUSES else "active"
        profile.setdefault("tone", "")
        profile.setdefault("purpose", "")
        profile["appearance"] = normalize_twin_appearance(profile.get("appearance"))
        profile["memories"] = normalize_twin_memories(profile.get("memories"))
        profile.setdefault("createdAt", utc_now())
        profile.setdefault("updatedAt", profile["createdAt"])
        return profile
