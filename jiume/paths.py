"""Filesystem paths for local JiuMe data."""

from __future__ import annotations

from pathlib import Path

from jiuwenswarm.common.utils import get_user_workspace_dir


def get_jiume_root() -> Path:
    root = get_user_workspace_dir() / "jiume"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_twins_root() -> Path:
    root = get_jiume_root() / "twins"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_twin_root(twin_id: str) -> Path:
    root = get_twins_root() / twin_id
    root.mkdir(parents=True, exist_ok=True)
    return root
