"""Compatibility service for JiuMe personal distillation RPCs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jiuwenswarm.common.utils import get_agent_skills_dir

from jiume.personal_distillation.engine import PersonalDistillationEngine
from jiume.twins.store import TwinStore


class DistillService:
    def __init__(
        self,
        store: TwinStore | None = None,
        *,
        skills_dir: Path | None = None,
    ) -> None:
        self.store = store or TwinStore()
        self.engine = PersonalDistillationEngine(
            store=self.store,
            twins_root=getattr(self.store, "root", None),
            skills_dir=skills_dir or get_agent_skills_dir(),
        )

    def create_job(self, twin_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.engine.create_job(twin_id, payload).to_dict()

    def list_jobs(self, twin_id: str) -> list[dict[str, Any]]:
        return [job.to_dict() for job in self.engine.list_jobs(twin_id)]

    def get_job(self, twin_id: str, job_id: str) -> dict[str, Any]:
        return self.engine.get_job(twin_id, job_id).to_dict()

    def test_job(self, twin_id: str, job_id: str) -> dict[str, Any]:
        return self.engine.test_job(twin_id, job_id).to_dict()

    def install_job(self, twin_id: str, job_id: str) -> dict[str, Any]:
        return self.engine.install_job(twin_id, job_id).to_dict()

    def reject_job(self, twin_id: str, job_id: str, feedback: str = "") -> dict[str, Any]:
        return self.engine.reject_job(twin_id, job_id, feedback=feedback).to_dict()
