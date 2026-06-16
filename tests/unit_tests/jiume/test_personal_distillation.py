from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jiume.distill.service import DistillService
from jiume.api.web_handlers import register_jiume_handlers
from jiume.personal_distillation.engine import PersonalDistillationEngine
from jiume.personal_distillation.models import (
    DistillationJob,
    DistillationLayer,
    DistillationSource,
    DistillationStatus,
    DistilledArtifact,
    safe_slug,
)
from jiume.personal_distillation.store import PersonalDistillationStore, ensure_safe_job_id
from jiume.runtime.context import enrich_gateway_message
from jiume.twins.store import TwinStore


class _FakeJiumeChannel:
    def __init__(self) -> None:
        self.methods: dict[str, object] = {}
        self.responses: list[dict] = []

    def register_method(self, name: str, handler: object) -> None:
        self.methods[name] = handler

    async def send_response(
        self,
        ws: object,
        req_id: str,
        *,
        ok: bool,
        payload: dict | None = None,
        error: str | None = None,
        code: str | None = None,
    ) -> None:
        self.responses.append(
            {
                "id": req_id,
                "ok": ok,
                "payload": payload,
                "error": error,
                "code": code,
            }
        )


def _isolate_jiume_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    twins_root = tmp_path / "twins"
    monkeypatch.setattr("jiume.paths.get_twins_root", lambda: twins_root)
    monkeypatch.setattr("jiume.twins.store.get_twins_root", lambda: twins_root)
    monkeypatch.setattr("jiume.personal_distillation.engine.get_twins_root", lambda: twins_root)
    monkeypatch.setattr("jiume.personal_distillation.engine.get_agent_skills_dir", lambda: tmp_path / "agent-skills")
    return twins_root


def _sample_job(
    *,
    twin_id: str = "twin_safe",
    status: DistillationStatus = DistillationStatus.NEEDS_REVIEW,
) -> DistillationJob:
    source = DistillationSource(
        id="src_1",
        kind="chat",
        title="Chat sample",
        content="User prefers decisions, owners, and risks.",
    )
    artifacts = [
        DistilledArtifact(
            id="art_profile_1",
            layer=DistillationLayer.PROFILE,
            title="Working memory",
            content="Remember that decisions and owners matter.",
            confidence=0.8,
            evidence_ids=[source.id],
        )
    ]
    return DistillationJob(
        id="distill_20260616000000_meeting",
        twin_id=twin_id,
        mode="offline_bootstrap",
        status=status,
        goal="Meeting minutes",
        sources=[source],
        artifacts=artifacts,
        generated_skill={"name": "meeting-minutes", "folder": "/tmp/meeting-minutes"},
        created_at="2026-06-16T00:00:00+00:00",
        updated_at="2026-06-16T00:00:00+00:00",
    )


def test_safe_slug_keeps_short_ascii_identifier() -> None:
    assert safe_slug("  Meeting: Notes! ") == "meeting-notes"
    assert safe_slug("???", fallback="fallback-skill") == "fallback-skill"
    assert len(safe_slug("x" * 100, limit=12)) == 12


def test_distillation_job_round_trips_json() -> None:
    job = _sample_job()
    restored = DistillationJob.from_dict(job.to_dict())

    assert restored.to_dict() == job.to_dict()
    assert restored.status == DistillationStatus.NEEDS_REVIEW
    assert restored.artifacts[0].layer == DistillationLayer.PROFILE
    assert restored.to_dict()["source_type"] == "offline_bootstrap"


def test_distillation_job_rejects_unknown_status() -> None:
    payload = _sample_job().to_dict()
    payload["status"] = "unknown"

    with pytest.raises(ValueError, match="invalid distillation status"):
        DistillationJob.from_dict(payload)


def test_distillation_store_persists_and_lists_jobs(tmp_path: Path) -> None:
    store = PersonalDistillationStore(tmp_path / "twins")
    job = _sample_job()

    store.write_job(job)

    assert store.get_job(job.twin_id, job.id).to_dict() == job.to_dict()
    assert [item.id for item in store.list_jobs(job.twin_id)] == [job.id]


def test_distillation_store_rejects_unsafe_job_id(tmp_path: Path) -> None:
    store = PersonalDistillationStore(tmp_path / "twins")

    with pytest.raises(ValueError, match="invalid distillation job id"):
        ensure_safe_job_id("../escape")
    with pytest.raises(ValueError, match="invalid distillation job id"):
        store.get_job("twin_safe", "../escape")


def test_engine_creates_layered_review_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_alpha", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=tmp_path / "skills")

    job = engine.create_job(
        twin["id"],
        {
            "mode": "offline_bootstrap",
            "goal": "Meeting minutes",
            "sources": [
                {
                    "kind": "chat",
                    "title": "Chat export",
                    "content": "I prefer summaries with decisions, owners, and risks.",
                }
            ],
        },
    )

    assert job.status == DistillationStatus.NEEDS_REVIEW
    assert job.mode == "offline_bootstrap"
    assert {artifact.layer for artifact in job.artifacts} == set(DistillationLayer)
    assert job.sources[0].kind == "chat"
    skill_md = Path(str(job.generated_skill["skill_md"]))
    assert skill_md.exists()
    assert "requires_approval:" in skill_md.read_text(encoding="utf-8")


def test_engine_tests_install_and_mounts_personal_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    skills_dir = tmp_path / "skills"
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_install", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=skills_dir)
    job = engine.create_job(
        twin["id"],
        {"goal": "Meeting minutes", "recipe": "Summarize decisions, risks, and owners."},
    )

    approved = engine.test_job(twin["id"], job.id)
    installed = engine.install_job(twin["id"], job.id)

    skill_name = str(installed.generated_skill["name"])
    assert approved.status == DistillationStatus.APPROVED
    assert approved.test["passed"] is True
    assert installed.status == DistillationStatus.INSTALLED
    assert (skills_dir / skill_name / "SKILL.md").exists()
    assert skill_name in store.get_twin(twin["id"])["permissions"]["allowedSkillIds"]


def test_context_block_includes_approved_distilled_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_context", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=tmp_path / "skills")
    job = engine.create_job(
        twin["id"],
        {"goal": "Meeting minutes", "recipe": "Summarize decisions, risks, and owners."},
    )
    engine.install_job(twin["id"], job.id)
    message = SimpleNamespace(
        params={"content": "Help with today's notes.", "twin_id": twin["id"]},
        metadata={"method": "chat.send"},
        session_id="sess-1",
    )

    enriched = enrich_gateway_message(message)

    content = enriched.params["content"]
    assert "[JiuMe Distilled Context]" in content
    assert "Profile memory" in content
    assert "Procedural memory" in content
    assert "Meeting minutes" in content
    assert content.endswith("Help with today's notes.")


def test_distill_service_reject_records_feedback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    skills_dir = tmp_path / "agent" / "workspace" / "skills"
    monkeypatch.setattr("jiume.distill.service.get_agent_skills_dir", lambda: skills_dir)
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_reject", "displayName": "Ada", "selectedSkillIds": []})
    service = DistillService(store)
    job = service.create_job(twin["id"], {"goal": "Email triage", "recipe": "Sort and draft replies."})

    rejected = service.reject_job(twin["id"], job["id"], feedback="Too broad; keep only VIP senders.")

    assert rejected["status"] == "rejected"
    assert rejected["review"]["feedback"] == "Too broad; keep only VIP senders."


def test_engine_imports_chat_history_tasks_and_redacts_sensitive_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    history_path = import_dir / "history.json"
    history_path.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "I like owner-first weekly reviews."},
                    {"role": "assistant", "content": "Here is a summary."},
                    {"role": "user", "content": "My api_key is fake-secret-key. Do not show it."},
                ],
                "tasks": [
                    {
                        "title": "Weekly review",
                        "summary": "Extract decisions, risks, and owners from the week.",
                    }
                ],
                "corrections": ["Never send calendar invites without asking."],
                "artifacts": [{"name": "weekly.md", "preview": "Decision table with owner column."}],
                "approvals": [{"action": "save-personal-workflow", "approved": True}],
                "notes": ["Keep the workflow local-first and review-gated."],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_import", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=tmp_path / "skills")

    job = engine.create_job(
        twin["id"],
        {
            "mode": "offline_bootstrap",
            "goal": "Weekly review",
            "source_base_dir": str(import_dir),
            "source_files": [str(history_path)],
        },
    )
    installed = engine.install_job(twin["id"], job.id)
    context_text = engine.active_context_text(twin["id"], query="weekly review")

    source_kinds = {source.kind for source in job.sources}
    assert {"chat", "task_trace", "correction", "artifact", "approval", "manual_note"}.issubset(source_kinds)
    assert installed.review["sensitive"]["requires_explicit_approval"] is True
    assert "fake-secret-key" not in json.dumps(job.to_dict(), ensure_ascii=False)
    assert "fake-secret-key" not in context_text
    assert "owner-first weekly reviews" in context_text


def test_online_increment_marks_conflicts_and_keeps_review_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_conflict", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=tmp_path / "skills")

    job = engine.create_job(
        twin["id"],
        {
            "mode": "online_increment",
            "goal": "Review writing style",
            "messages": [
                {"role": "user", "content": "Prefer concise bullet summaries."},
                {"role": "user", "content": "Actually prefer detailed narrative summaries for reviews."},
            ],
            "corrections": ["Prefer detailed narrative summaries for reviews."],
        },
    )

    assert job.mode == "online_increment"
    assert job.status == DistillationStatus.NEEDS_REVIEW
    assert job.review["conflicts"]
    assert job.review["queue"] == "needs_review"


def test_install_job_preserves_skill_evolution_file_and_supersedes_prior_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    skills_dir = tmp_path / "skills"
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_evolve", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=skills_dir)
    first = engine.create_job(
        twin["id"],
        {"goal": "Weekly review", "recipe": "Summarize decisions, risks, and owners."},
    )
    first_installed = engine.install_job(twin["id"], first.id)
    skill_name = str(first_installed.generated_skill["name"])
    evolution_path = skills_dir / skill_name / "evolutions.json"
    evolution_path.write_text('{"owner":"jiuwen-skill-evolution"}\n', encoding="utf-8")
    second = engine.create_job(
        twin["id"],
        {
            "goal": "Weekly review",
            "skill_name": skill_name,
            "recipe": "Summarize decisions, risks, owners, and next actions.",
        },
    )

    second_installed = engine.install_job(twin["id"], second.id)
    refreshed_first = engine.get_job(twin["id"], first.id)

    assert second_installed.status == DistillationStatus.INSTALLED
    assert refreshed_first.status == DistillationStatus.SUPERSEDED
    assert evolution_path.read_text(encoding="utf-8") == '{"owner":"jiuwen-skill-evolution"}\n'


def test_runtime_context_uses_query_relevant_procedural_memory_without_sensitive_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_relevance", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=tmp_path / "skills")
    weekly = engine.create_job(
        twin["id"],
        {"goal": "Weekly review", "recipe": "Summarize decisions, risks, and owners."},
    )
    email = engine.create_job(
        twin["id"],
        {
            "goal": "Email triage",
            "recipe": "Prioritize VIP senders and draft direct replies. api_key fake-hidden-key should never leak.",
        },
    )
    engine.install_job(twin["id"], weekly.id)
    engine.install_job(twin["id"], email.id)
    monkeypatch.setattr("jiume.runtime.context.PersonalDistillationEngine", lambda: engine)
    message = SimpleNamespace(
        params={"content": "Help me triage email from VIP senders.", "twin_id": twin["id"]},
        metadata={"method": "chat.send"},
        session_id="sess-relevance",
    )

    enriched = enrich_gateway_message(message)

    content = enriched.params["content"]
    assert "Email triage" in content
    assert "Weekly review" not in content
    assert "fake-hidden-key" not in content
    assert content.endswith("Help me triage email from VIP senders.")


def test_source_file_import_rejects_paths_outside_base_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    import_dir = tmp_path / "imports"
    import_dir.mkdir()
    outside_path = tmp_path / "outside.json"
    outside_path.write_text('{"messages": [{"content": "escape"}]}', encoding="utf-8")
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_safe_import", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=tmp_path / "skills")

    with pytest.raises(ValueError, match="outside source_base_dir"):
        engine.create_job(
            twin["id"],
            {
                "mode": "offline_bootstrap",
                "goal": "Unsafe import",
                "source_base_dir": str(import_dir),
                "source_files": [str(outside_path)],
            },
        )


def test_external_action_sources_require_explicit_review_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_sensitive_action", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=tmp_path / "skills")

    job = engine.create_job(
        twin["id"],
        {
            "mode": "online_increment",
            "goal": "Appointment follow-up",
            "messages": [
                {
                    "role": "user",
                    "content": "After appointments, send a message to my assistant and create a calendar invite.",
                }
            ],
        },
    )

    assert job.review["sensitive"]["requires_explicit_approval"] is True
    assert set(job.review["sensitive"]["risk_actions"]) >= {"send_external_message", "modify_calendar"}


def test_generated_skill_package_declares_provenance_and_leaves_evolutions_to_jiuwen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    store = TwinStore(root=twins_root)
    twin = store.create_twin({"id": "twin_provenance", "displayName": "Ada", "selectedSkillIds": []})
    engine = PersonalDistillationEngine(store=store, twins_root=twins_root, skills_dir=tmp_path / "skills")

    job = engine.create_job(
        twin["id"],
        {"goal": "Launch review", "recipe": "Summarize launch decisions, risks, and next actions."},
    )
    tested = engine.test_job(twin["id"], job.id)
    skill_dir = Path(str(job.generated_skill["folder"]))
    manifest = json.loads((skill_dir / "manifest.json").read_text(encoding="utf-8"))

    assert tested.test["checks"]["has_provenance"] is True
    assert tested.test["checks"]["does_not_ship_evolutions_json"] is True
    assert manifest["skill_evolution_owner"] == "jiuwen"
    assert manifest["provenance"]["job_id"] == job.id
    assert manifest["provenance"]["source_ids"] == [source.id for source in job.sources]
    assert manifest["provenance"]["artifact_layers"] == [layer.value for layer in DistillationLayer]
    assert "provenance" in job.generated_skill
    assert not (skill_dir / "evolutions.json").exists()


def test_rpc_reject_handler_passes_feedback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twins_root = _isolate_jiume_paths(monkeypatch, tmp_path)
    monkeypatch.setattr("jiume.api.web_handlers.TwinStore", lambda: TwinStore(root=twins_root))
    monkeypatch.setattr("jiume.distill.service.get_agent_skills_dir", lambda: tmp_path / "skills")
    channel = _FakeJiumeChannel()
    register_jiume_handlers(channel)
    twin = channel.methods["twin.create"]

    async def run_flow() -> None:
        await twin(object(), "create-1", {"id": "twin_rpc", "displayName": "Ada"}, "sess-rpc")
        await channel.methods["twin.distill.create"](
            object(),
            "distill-1",
            {"twin_id": "twin_rpc", "goal": "Email review", "recipe": "Review drafts."},
            "sess-rpc",
        )
        job_id = channel.responses[-1]["payload"]["job"]["id"]
        await channel.methods["twin.distill.reject"](
            object(),
            "reject-1",
            {"twin_id": "twin_rpc", "job_id": job_id, "feedback": "Keep this as memory, not a skill."},
            "sess-rpc",
        )

    asyncio.run(run_flow())

    assert channel.responses[-1]["ok"] is True
    assert channel.responses[-1]["payload"]["job"]["status"] == "rejected"
    assert channel.responses[-1]["payload"]["job"]["review"]["feedback"] == "Keep this as memory, not a skill."
