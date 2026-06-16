"""Static asset path resolution for avatar files."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from jiume.paths import get_twin_root
from jiume.twins.store import ensure_safe_twin_id


def resolve_asset_path(twin_id: str, asset_name: str) -> tuple[Path, str]:
    safe_id = ensure_safe_twin_id(twin_id)
    asset = str(asset_name or "").replace("\\", "/").lstrip("/")
    if not asset or ".." in asset.split("/"):
        raise ValueError("invalid asset path")
    base = (get_twin_root(safe_id) / "avatar").resolve()
    target = (base / asset).resolve()
    target.relative_to(base)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(asset)
    mime, _ = mimetypes.guess_type(target.name)
    return target, mime or "application/octet-stream"
