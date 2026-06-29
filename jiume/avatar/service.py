"""Codex pet package import and manifest management for JiuMe avatars."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from jiume.audit.logger import append_audit_event
from jiume.paths import get_twin_root
from jiume.twins.appearance import normalize_twin_appearance
from jiume.twins.store import TwinStore, ensure_safe_twin_id

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
CODEX_PET_STATE_PURPOSES = {
    "idle": "calm resting, breathing, and blinking loop",
    "running-right": "rightward drag movement loop",
    "running-left": "leftward drag movement loop",
    "waving": "greeting or attention gesture",
    "jumping": "hover or playful jump",
    "failed": "blocked, failed, or cancelled reaction",
    "waiting": "waiting for approval, help, or user input",
    "running": "active task work or processing",
    "review": "ready or completed output review",
}
CODEX_PET_STATE_ALIASES = {
    "thinking": "running",
    "speaking": "waving",
    "working": "running",
    "waiting_approval": "waiting",
    "success": "review",
    "error": "failed",
    "sleep": "idle",
}

DESKTOP_STATES = tuple(CODEX_PET_FRAME_COUNTS.keys())
CODEX_CELL = (192, 208)
CODEX_GRID = (8, 9)
ANIMATION_FRAMES_PER_STATE = CODEX_PET_FRAME_COUNTS["idle"]
AVATAR_VIEW_NAMES = ("front", "left", "right", "back")
AVATAR_PACK_FILENAME = "avatar_pack.json"
COMPAT_SPRITE_PACK_FILENAME = "pet.json"
MAX_PET_ZIP_BYTES = 64 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _avatar_dir(twin_id: str) -> Path:
    path = get_twin_root(ensure_safe_twin_id(twin_id)) / "avatar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _codex_pets_root() -> Path:
    return Path(os.getenv("CODEX_HOME") or Path.home() / ".codex") / "pets"


def _safe_pet_id(pet_id: str) -> str:
    value = str(pet_id or "").strip()
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError("petId must be a direct folder name under CODEX_HOME/pets")
    return value


def _read_pet_json(package_dir: Path) -> dict[str, Any]:
    manifest_path = package_dir / COMPAT_SPRITE_PACK_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing {COMPAT_SPRITE_PACK_FILENAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("pet.json must be an object")
    pet_id = str(manifest.get("id") or package_dir.name).strip()
    display_name = str(manifest.get("displayName") or pet_id or "Codex Pet").strip()
    description = str(manifest.get("description") or "Codex pet avatar.").strip()
    spritesheet_path = str(manifest.get("spritesheetPath") or "spritesheet.webp").strip()
    if not pet_id or not display_name or not spritesheet_path:
        raise ValueError("pet.json requires id, displayName, and spritesheetPath")
    if Path(spritesheet_path).is_absolute() or ".." in Path(spritesheet_path).parts:
        raise ValueError("spritesheetPath must stay inside the pet package")
    return {
        "id": pet_id,
        "displayName": display_name,
        "description": description,
        "spritesheetPath": spritesheet_path,
    }


def _validate_atlas(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"missing spritesheet: {path.name}")
    atlas = Image.open(path).convert("RGBA")
    expected_size = (CODEX_CELL[0] * CODEX_GRID[0], CODEX_CELL[1] * CODEX_GRID[1])
    if atlas.size != expected_size:
        raise ValueError(f"spritesheet must be {expected_size[0]}x{expected_size[1]}")
    for pixel in atlas.getdata():
        if pixel[3] == 0 and any(pixel[:3]):
            raise ValueError("transparent spritesheet pixels must not retain hidden color")
    for row, (state, frame_count) in enumerate(CODEX_PET_FRAME_COUNTS.items()):
        for column in range(CODEX_GRID[0]):
            cell = atlas.crop(
                (
                    column * CODEX_CELL[0],
                    row * CODEX_CELL[1],
                    (column + 1) * CODEX_CELL[0],
                    (row + 1) * CODEX_CELL[1],
                )
            )
            has_pixels = cell.getchannel("A").getbbox() is not None
            if column < frame_count and not has_pixels:
                raise ValueError(f"{state} column {column} is empty")
            if column >= frame_count and has_pixels:
                raise ValueError(f"{state} unused column {column} must be transparent")


def _find_package_dir(root: Path) -> Path:
    if (root / COMPAT_SPRITE_PACK_FILENAME).exists():
        return root
    candidates = sorted(path.parent for path in root.rglob(COMPAT_SPRITE_PACK_FILENAME))
    if not candidates:
        raise FileNotFoundError("missing pet.json")
    if len(candidates) > 1:
        raise ValueError("pet package archive must contain exactly one pet.json")
    return candidates[0]


def _extract_zip_safely(zip_path: Path, target_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        total = 0
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise ValueError("pet ZIP contains an unsafe path")
            total += info.file_size
            if total > MAX_PET_ZIP_BYTES:
                raise ValueError("pet ZIP is larger than 64MB")
        archive.extractall(target_dir)
    return _find_package_dir(target_dir)


def _resolve_package_path(source_path: str | Path) -> Path:
    path = Path(str(source_path or "")).expanduser()
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.is_dir():
        return _find_package_dir(path)
    raise ValueError("sourcePath must be a pet directory or ZIP file")


def _load_package(package_dir: Path) -> tuple[dict[str, Any], Path]:
    pet = _read_pet_json(package_dir)
    spritesheet = (package_dir / pet["spritesheetPath"]).resolve()
    spritesheet.relative_to(package_dir.resolve())
    _validate_atlas(spritesheet)
    return pet, spritesheet


def _sprite_animations() -> dict[str, dict[str, Any]]:
    return {
        state: {
            "frames": [row * CODEX_GRID[0] + column for column in range(frame_count)],
            "fps": 6,
            "loop": True,
        }
        for row, (state, frame_count) in enumerate(CODEX_PET_FRAME_COUNTS.items())
    }


def _sprite_pack(pet: dict[str, Any], avatar_dir: Path) -> dict[str, Any]:
    return {
        "id": pet["id"],
        "displayName": pet["displayName"],
        "description": pet["description"],
        "spritesheet": "spritesheet.webp",
        "cell": {"width": CODEX_CELL[0], "height": CODEX_CELL[1]},
        "grid": {"columns": CODEX_GRID[0], "rows": CODEX_GRID[1]},
        "rows": [
            {
                "state": state,
                "row": row,
                "frames": frame_count,
                "purpose": CODEX_PET_STATE_PURPOSES[state],
            }
            for row, (state, frame_count) in enumerate(CODEX_PET_FRAME_COUNTS.items())
        ],
        "animations": _sprite_animations(),
        "manifest": str(avatar_dir / AVATAR_PACK_FILENAME),
        "compatFile": str(avatar_dir / COMPAT_SPRITE_PACK_FILENAME),
        "spritesheetPath": str(avatar_dir / "spritesheet.webp"),
        "pet": pet,
        "format": "codex-pet-atlas",
    }


def _manifest_has_desktop_assets(manifest: dict[str, Any], avatar_dir: Path) -> bool:
    sprite_pack = manifest.get("spritePack")
    if isinstance(sprite_pack, dict):
        spritesheet = sprite_pack.get("spritesheet")
        path = Path(str(spritesheet)) if spritesheet else avatar_dir / "spritesheet.webp"
        if path.exists():
            try:
                _validate_atlas(path)
            except Exception:
                return False
            return True
    states = manifest.get("states")
    if not isinstance(states, dict):
        return False
    for state in DESKTOP_STATES:
        item = states.get(state)
        if not isinstance(item, dict):
            return False
        frames = item.get("frames")
        if isinstance(frames, list) and frames:
            target = frames[0].get("file") if isinstance(frames[0], dict) else None
        else:
            target = item.get("file")
        if not target or not Path(str(target)).exists():
            return False
    return True


class AvatarService:
    def __init__(self, store: TwinStore | None = None) -> None:
        self.store = store or TwinStore()

    def list_pets(self) -> list[dict[str, Any]]:
        root = _codex_pets_root()
        if not root.exists():
            return []
        pets: list[dict[str, Any]] = []
        for package_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            try:
                pet = _read_pet_json(package_dir)
                spritesheet = package_dir / pet["spritesheetPath"]
                if not spritesheet.exists():
                    continue
            except Exception:
                continue
            pets.append({**pet, "petId": package_dir.name, "packagePath": str(package_dir)})
        return pets

    def import_pet(
        self,
        twin_id: str,
        *,
        pet_id: str | None = None,
        source_path: str | Path | None = None,
    ) -> dict[str, Any]:
        if bool(pet_id) == bool(source_path):
            raise ValueError("provide exactly one of petId or sourcePath")
        if pet_id:
            package_dir = _codex_pets_root() / _safe_pet_id(pet_id)
            return self.import_pet_package(twin_id, package_dir)
        source = Path(str(source_path or "")).expanduser()
        if source.suffix.lower() == ".zip":
            with tempfile.TemporaryDirectory(prefix="jiume-pet-") as temp_dir:
                package_dir = _extract_zip_safely(source, Path(temp_dir))
                return self.import_pet_package(twin_id, package_dir)
        return self.import_pet_package(twin_id, _resolve_package_path(source))

    def import_pet_package(self, twin_id: str, package_dir: Path) -> dict[str, Any]:
        twin = self.store.get_twin(twin_id)
        pet, spritesheet = _load_package(package_dir)
        avatar_dir = _avatar_dir(twin["id"])
        shutil.copyfile(spritesheet, avatar_dir / "spritesheet.webp")
        pet_json = {**pet, "spritesheetPath": "spritesheet.webp"}
        (avatar_dir / COMPAT_SPRITE_PACK_FILENAME).write_text(
            json.dumps(pet_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sprite_pack = _sprite_pack(pet_json, avatar_dir)
        (avatar_dir / AVATAR_PACK_FILENAME).write_text(
            json.dumps(sprite_pack, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest = self._write_manifest(twin, avatar_dir, pet_json, sprite_pack)
        return self._write_job(avatar_dir, twin["id"], manifest)

    def _write_manifest(
        self,
        twin: dict[str, Any],
        avatar_dir: Path,
        pet: dict[str, Any],
        sprite_pack: dict[str, Any],
    ) -> dict[str, Any]:
        states = {
            state: {
                "row": row,
                "frames": frame_count,
                "fps": 6,
                "loop": True,
                "cell": {"width": CODEX_CELL[0], "height": CODEX_CELL[1]},
                "purpose": CODEX_PET_STATE_PURPOSES[state],
            }
            for row, (state, frame_count) in enumerate(CODEX_PET_FRAME_COUNTS.items())
        }
        manifest = {
            "version": "2.0",
            "style": "codex-pet",
            "appearance": normalize_twin_appearance(twin.get("appearance")),
            "identity": {
                "form": "codex-pet",
                "role": "personal desktop twin",
                "agentEntryPoint": True,
            },
            "provider": "codex-pet-import",
            "states": states,
            "views": {},
            "desktop": {
                "defaultState": "idle",
                "size": 128,
                "alwaysOnTop": True,
                "dragAcrossScreens": True,
            },
            "spritePack": {
                "manifest": str(avatar_dir / AVATAR_PACK_FILENAME),
                "compatFile": str(avatar_dir / COMPAT_SPRITE_PACK_FILENAME),
                "spritesheet": str(avatar_dir / "spritesheet.webp"),
                "cell": sprite_pack["cell"],
                "grid": sprite_pack["grid"],
                "frameCounts": dict(CODEX_PET_FRAME_COUNTS),
                "animations": sprite_pack["animations"],
                "pet": pet,
            },
            "generated_at": _utc_now(),
        }
        manifest_path = avatar_dir / "avatar_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.store.update_twin(twin["id"], {"avatarManifestPath": f"twins/{twin['id']}/avatar/avatar_manifest.json"})
        append_audit_event(twin["id"], "avatar.pet_imported", {"pet_id": pet["id"]})
        return manifest

    def _write_job(self, avatar_dir: Path, twin_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        job = {
            "id": f"avatar_job_{secrets.token_hex(4)}",
            "twin_id": twin_id,
            "status": "completed",
            "provider": "codex-pet-import",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "manifest": manifest,
        }
        jobs_dir = avatar_dir / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{job['id']}.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        return job

    def get_manifest(self, twin_id: str) -> dict[str, Any]:
        twin = self.store.get_twin(twin_id)
        avatar_dir = _avatar_dir(twin["id"])
        path = avatar_dir / "avatar_manifest.json"
        if not path.exists():
            raise FileNotFoundError("avatar manifest is missing; import a Codex pet package first")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not _manifest_has_desktop_assets(manifest, avatar_dir):
            raise FileNotFoundError("avatar assets are invalid; import a Codex pet package again")
        return manifest

    def get_job(self, twin_id: str, job_id: str) -> dict[str, Any]:
        avatar_dir = _avatar_dir(twin_id)
        safe_job = Path(str(job_id or "")).name
        if not safe_job:
            raise ValueError("job_id is required")
        path = avatar_dir / "jobs" / f"{safe_job}.json"
        if not path.exists():
            raise FileNotFoundError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))
