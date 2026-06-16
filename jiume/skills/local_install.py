"""Install local skills into the JiuwenSwarm Agent skills directory for JiuMe."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from jiuwenswarm.common.utils import get_agent_skills_dir

from jiume.audit.logger import append_audit_event
from jiume.twins.store import TwinStore

_SAFE_SKILL_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _slugify_skill_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    return slug[:64] or "jiume-local-skill"


def _frontmatter_name(skill_md: Path) -> str:
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not content.startswith("---"):
        return ""
    for line in content.splitlines()[1:80]:
        if line.strip() == "---":
            break
        if line.lower().startswith("name:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def resolve_local_skill_source(source: str | Path) -> tuple[Path, Path, str]:
    raw = str(source or "").strip()
    if not raw:
        raise ValueError("skill path is required")
    path = Path(raw).expanduser()
    if not path.exists():
        raise FileNotFoundError(raw)
    if path.is_file():
        if path.name != "SKILL.md":
            raise ValueError("local skill file must be named SKILL.md")
        skill_dir = path.parent
        skill_md = path
    else:
        skill_dir = path
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            raise FileNotFoundError(str(skill_md))
    name = _frontmatter_name(skill_md) or skill_dir.name
    skill_name = _slugify_skill_name(name)
    if not _SAFE_SKILL_RE.match(skill_name):
        raise ValueError("invalid skill name")
    return skill_dir.resolve(), skill_md.resolve(), skill_name


def install_local_skill(
    *,
    store: TwinStore,
    twin_id: str,
    source: str | Path,
    skills_dir: Path | None = None,
) -> dict[str, Any]:
    twin = store.get_twin(twin_id)
    source_dir, skill_md, skill_name = resolve_local_skill_source(source)
    target_root = skills_dir or get_agent_skills_dir()
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / skill_name
    if target.exists() and target.resolve() != source_dir:
        shutil.rmtree(target)
    if not target.exists():
        shutil.copytree(
            source_dir,
            target,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
        )
    copied_skill_md = target / "SKILL.md"
    if not copied_skill_md.exists():
        raise FileNotFoundError(str(copied_skill_md))
    store.enable_skill(twin["id"], skill_name)
    record = {
        "id": skill_name,
        "name": skill_name,
        "source": str(source_dir),
        "sourceSkillMd": str(skill_md),
        "installedPath": str(target),
        "skillMd": str(copied_skill_md),
        "twinId": twin["id"],
    }
    append_audit_event(twin["id"], "skill.local_installed", record)
    return record
