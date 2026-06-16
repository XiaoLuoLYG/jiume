"""File-backed storage for personal distillation jobs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from jiume.personal_distillation.models import DistillationJob
from jiume.twins.store import ensure_safe_twin_id

SAFE_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def ensure_safe_job_id(job_id: str) -> str:
    value = str(job_id or "").strip()
    if not value or not SAFE_JOB_ID_RE.match(value):
        raise ValueError("invalid distillation job id")
    return value


class PersonalDistillationStore:
    def __init__(self, twins_root: Path) -> None:
        self.twins_root = Path(twins_root)
        self.twins_root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, twin_id: str, job_id: str, *, create: bool = False) -> Path:
        root = self.twins_root / ensure_safe_twin_id(twin_id) / "distill" / "jobs" / ensure_safe_job_id(job_id)
        if create:
            root.mkdir(parents=True, exist_ok=True)
        return root

    def write_job(self, job: DistillationJob) -> None:
        root = self.job_dir(job.twin_id, job.id, create=True)
        (root / "job.json").write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_job(self, twin_id: str, job_id: str) -> DistillationJob:
        path = self.job_dir(twin_id, job_id) / "job.json"
        if not path.exists():
            raise FileNotFoundError("distill job not found")
        return DistillationJob.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_jobs(self, twin_id: str) -> list[DistillationJob]:
        root = self.twins_root / ensure_safe_twin_id(twin_id) / "distill" / "jobs"
        if not root.exists():
            return []
        jobs: list[DistillationJob] = []
        for path in sorted(root.glob("*/job.json"), reverse=True):
            try:
                jobs.append(DistillationJob.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
        return jobs
