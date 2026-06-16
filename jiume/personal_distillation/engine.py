"""Local-first continuous personal distillation engine."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jiuwenswarm.common.utils import get_agent_skills_dir

from jiume.audit.logger import append_audit_event
from jiume.paths import get_twins_root
from jiume.personal_distillation.models import (
    DistillationJob,
    DistillationLayer,
    DistillationSource,
    DistillationStatus,
    DistilledArtifact,
    safe_slug,
)
from jiume.personal_distillation.store import PersonalDistillationStore
from jiume.twins.store import TwinStore

SENSITIVE_REPLACEMENTS = [
    (re.compile(r"sk-[a-zA-Z0-9_-]+"), "[redacted-api-key]"),
    (re.compile(r"(?i)\b(api[_ -]?key|token|secret|password)\s*(?:is|=|:)?\s*([a-zA-Z0-9._-]+)"), r"\1 [redacted]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[redacted-number]"),
]
RISK_ACTION_RULES = [
    ("identity_profile", re.compile(r"(?i)\b(identity|passport|legal name|id card|social security)\b")),
    ("contact_data", re.compile(r"(?i)\b(contact|phone number|address book|recipient)\b")),
    ("send_external_message", re.compile(r"(?i)\b(send|reply|text|dm|message|email|slack|wechat|mail)\b")),
    ("modify_calendar", re.compile(r"(?i)\b(calendar|invite|appointment|schedule|reschedule)\b")),
    ("payment", re.compile(r"(?i)\b(payment|pay|purchase|transfer|refund|invoice)\b")),
    ("irreversible_change", re.compile(r"(?i)\b(delete|remove forever|irreversible|publish|submit|sign)\b")),
]
WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: str, limit: int = 280) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rstrip() + "..."


def _redact_sensitive(value: str) -> tuple[str, bool]:
    redacted = str(value or "")
    changed = False
    for pattern, replacement in SENSITIVE_REPLACEMENTS:
        redacted, count = pattern.subn(replacement, redacted)
        changed = changed or count > 0
    return redacted, changed


def _tokens(value: str) -> set[str]:
    return {item.casefold() for item in WORD_RE.findall(str(value or ""))}


def _relevance_score(query: str, haystack: str) -> int:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0
    return len(query_tokens & _tokens(haystack))


class PersonalDistillationEngine:
    def __init__(
        self,
        *,
        store: TwinStore | None = None,
        twins_root: Path | None = None,
        skills_dir: Path | None = None,
    ) -> None:
        self.store = store or TwinStore()
        self.twins_root = twins_root or getattr(self.store, "root", None) or get_twins_root()
        self.skills_dir = skills_dir or get_agent_skills_dir()
        self.job_store = PersonalDistillationStore(self.twins_root)

    def create_job(self, twin_id: str, payload: dict[str, Any]) -> DistillationJob:
        twin = self.store.get_twin(twin_id)
        goal = str(payload.get("goal") or payload.get("recipe") or "Reusable personal workflow").strip()
        mode = str(payload.get("mode") or payload.get("source_type") or payload.get("sourceType") or "manual_recipe").strip()
        if mode == "manual_recipe":
            mode = "online_increment"
        skill_name = safe_slug(str(payload.get("skill_name") or payload.get("skillName") or goal))
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        job_id = self._next_job_id(twin["id"], timestamp=timestamp, skill_name=skill_name)
        sources = self._normalize_sources(payload, goal=goal)
        review = self._review_metadata(sources)
        artifacts = self._distill_artifacts(goal=goal, skill_name=skill_name, sources=sources)
        skill_dir = self.job_store.job_dir(twin["id"], job_id, create=True) / skill_name
        generated_skill = self._render_skill_package(
            skill_dir=skill_dir,
            job_id=job_id,
            mode=mode,
            skill_name=skill_name,
            author=str(twin.get("displayName") or "JiuMe"),
            goal=goal,
            artifacts=artifacts,
            sources=sources,
        )
        now = utc_now()
        job = DistillationJob(
            id=job_id,
            twin_id=twin["id"],
            mode=mode,
            status=DistillationStatus.NEEDS_REVIEW,
            goal=goal,
            sources=sources,
            artifacts=artifacts,
            generated_skill=generated_skill,
            created_at=now,
            updated_at=now,
            review=review,
        )
        self.job_store.write_job(job)
        append_audit_event(twin["id"], "distill.created", {"job_id": job.id, "skill": skill_name, "mode": mode})
        return job

    def _next_job_id(self, twin_id: str, *, timestamp: str, skill_name: str) -> str:
        base = f"distill_{timestamp}_{skill_name[:24]}"
        candidate = base
        suffix = 2
        while self.job_store.job_dir(twin_id, candidate).exists():
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def list_jobs(self, twin_id: str) -> list[DistillationJob]:
        self.store.get_twin(twin_id)
        return self.job_store.list_jobs(twin_id)

    def get_job(self, twin_id: str, job_id: str) -> DistillationJob:
        self.store.get_twin(twin_id)
        return self.job_store.get_job(twin_id, job_id)

    def test_job(self, twin_id: str, job_id: str) -> DistillationJob:
        job = self.get_job(twin_id, job_id)
        skill_md = Path(str(job.generated_skill.get("skill_md") or ""))
        folder = Path(str(job.generated_skill.get("folder") or ""))
        manifest_path = folder / "manifest.json"
        content = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                parsed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = parsed_manifest if isinstance(parsed_manifest, dict) else {}
            except json.JSONDecodeError:
                manifest = {}
        provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
        layers = {artifact.layer for artifact in job.artifacts}
        checks = {
            "has_frontmatter": content.startswith("---\n") and "\n---\n" in content[4:],
            "declares_allowed_tools": "allowed_tools:" in content,
            "declares_approval": "requires_approval:" in content,
            "has_layered_artifacts": {
                DistillationLayer.PROFILE,
                DistillationLayer.STYLE,
                DistillationLayer.PROCEDURAL,
                DistillationLayer.PERSONAL_SKILL,
            }.issubset(layers),
            "has_examples": (folder / "examples" / "input.md").exists(),
            "has_evals": (folder / "evals" / "evals.json").exists(),
            "has_provenance": (
                manifest.get("source") == "jiume_personal_distillation"
                and provenance.get("job_id") == job.id
                and provenance.get("source_ids") == [source.id for source in job.sources]
            ),
            "declares_skill_evolution_owner": manifest.get("skill_evolution_owner") == "jiuwen",
            "does_not_ship_evolutions_json": not (folder / "evolutions.json").exists(),
        }
        passed = all(checks.values())
        updated = DistillationJob(
            **{
                **job.__dict__,
                "status": DistillationStatus.APPROVED if passed else DistillationStatus.NEEDS_REVIEW,
                "test": {"passed": passed, "checks": checks, "tested_at": utc_now()},
                "updated_at": utc_now(),
            }
        )
        self.job_store.write_job(updated)
        append_audit_event(twin_id, "distill.tested", {"job_id": job_id, "passed": passed})
        return updated

    def install_job(self, twin_id: str, job_id: str) -> DistillationJob:
        job = self.test_job(twin_id, job_id)
        if not job.test.get("passed"):
            raise ValueError("distilled skill did not pass validation")
        skill_name = str(job.generated_skill.get("name") or "").strip()
        source = Path(str(job.generated_skill.get("folder") or ""))
        target = self.skills_dir / skill_name
        evolution_bytes = b""
        evolution_path = target / "evolutions.json"
        if evolution_path.exists():
            evolution_bytes = evolution_path.read_bytes()
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        if evolution_bytes:
            (target / "evolutions.json").write_bytes(evolution_bytes)
        self.store.enable_skill(twin_id, skill_name)
        self._supersede_prior_jobs(twin_id, current_job_id=job.id, skill_name=skill_name)
        updated = DistillationJob(
            **{
                **job.__dict__,
                "status": DistillationStatus.INSTALLED,
                "installed_path": str(target),
                "updated_at": utc_now(),
            }
        )
        self.job_store.write_job(updated)
        append_audit_event(twin_id, "distill.installed", {"job_id": job_id, "skill": skill_name})
        return updated

    def reject_job(self, twin_id: str, job_id: str, feedback: str = "") -> DistillationJob:
        job = self.get_job(twin_id, job_id)
        updated = DistillationJob(
            **{
                **job.__dict__,
                "status": DistillationStatus.REJECTED,
                "review": {"feedback": str(feedback or "").strip(), "reviewed_at": utc_now()},
                "updated_at": utc_now(),
            }
        )
        self.job_store.write_job(updated)
        append_audit_event(twin_id, "distill.rejected", {"job_id": job_id, "feedback": feedback})
        return updated

    def active_context(self, twin_id: str, *, query: str = "", limit_per_layer: int = 3) -> dict[str, list[dict[str, Any]]]:
        jobs = [
            job
            for job in self.list_jobs(twin_id)
            if job.status in {DistillationStatus.APPROVED, DistillationStatus.INSTALLED}
        ]
        query_text = str(query or "").casefold()
        by_layer: dict[str, list[dict[str, Any]]] = {layer.value: [] for layer in DistillationLayer}
        for job in jobs:
            for artifact in job.artifacts:
                haystack = f"{artifact.title} {artifact.content}".casefold()
                score = _relevance_score(query_text, haystack) if query_text else 0
                row = {**artifact.to_dict(), "job_id": job.id, "score": score}
                by_layer[artifact.layer.value].append(row)
        for layer, rows in by_layer.items():
            if query_text and any(int(item.get("score") or 0) > 0 for item in rows):
                rows = [item for item in rows if int(item.get("score") or 0) > 0]
            rows.sort(
                key=lambda item: (
                    int(item.get("score") or 0),
                    float(item.get("confidence") or 0.0),
                ),
                reverse=True,
            )
            by_layer[layer] = rows[:limit_per_layer]
        return by_layer

    def active_context_text(self, twin_id: str, *, query: str = "", limit_per_layer: int = 2) -> str:
        context = self.active_context(twin_id, query=query, limit_per_layer=limit_per_layer)
        labels = {
            DistillationLayer.PROFILE.value: "Profile memory",
            DistillationLayer.STYLE.value: "Style memory",
            DistillationLayer.PROCEDURAL.value: "Procedural memory",
            DistillationLayer.PERSONAL_SKILL.value: "Promoted personal skills",
        }
        lines = ["[JiuMe Distilled Context]"]
        any_rows = False
        for layer in (
            DistillationLayer.PROFILE.value,
            DistillationLayer.STYLE.value,
            DistillationLayer.PROCEDURAL.value,
            DistillationLayer.PERSONAL_SKILL.value,
        ):
            rows = context.get(layer) or []
            lines.append(f"{labels[layer]}:")
            if rows:
                any_rows = True
                for row in rows:
                    lines.append(f"- {row.get('title')}: {row.get('content')}")
            else:
                lines.append("- none")
        lines.append("[/JiuMe Distilled Context]")
        return "\n".join(lines) if any_rows else ""

    def _normalize_sources(self, payload: dict[str, Any], *, goal: str) -> list[DistillationSource]:
        sources: list[DistillationSource] = []
        self._append_source_files(payload, sources)
        self._append_structured_sources(payload, sources)
        raw_sources = payload.get("sources")
        if isinstance(raw_sources, list):
            for item in raw_sources:
                if isinstance(item, dict):
                    content = str(item.get("content") or item.get("text") or item.get("body") or "").strip()
                    if content:
                        self._add_source(
                            sources,
                            kind=str(item.get("kind") or item.get("type") or "note").strip() or "note",
                            title=str(item.get("title") or f"Source {len(sources) + 1}").strip(),
                            content=content,
                            metadata=dict(item.get("metadata") or {}),
                        )
        recipe = str(payload.get("recipe") or payload.get("content") or "").strip()
        if recipe:
            self._add_source(sources, kind="manual_recipe", title=goal, content=recipe)
        if not sources:
            self._add_source(sources, kind="manual_recipe", title=goal, content=goal)
        return sources

    def _add_source(
        self,
        sources: list[DistillationSource],
        *,
        kind: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        clean_content, sensitive = _redact_sensitive(content)
        clean_title, title_sensitive = _redact_sensitive(title)
        item_metadata = dict(metadata or {})
        if sensitive or title_sensitive:
            item_metadata["sensitive"] = True
            item_metadata["redacted"] = True
        sources.append(
            DistillationSource(
                id=f"src_{len(sources) + 1}",
                kind=str(kind or "note").strip() or "note",
                title=clean_title.strip() or f"Source {len(sources) + 1}",
                content=clean_content.strip(),
                metadata=item_metadata,
            )
        )

    def _append_source_files(self, payload: dict[str, Any], sources: list[DistillationSource]) -> None:
        raw_files = payload.get("source_files") or payload.get("sourceFiles")
        if not isinstance(raw_files, list):
            return
        base_raw = payload.get("source_base_dir") or payload.get("sourceBaseDir")
        base_dir = Path(str(base_raw)).expanduser().resolve() if base_raw else None
        for item in raw_files:
            path = Path(str(item)).expanduser().resolve()
            if base_dir and not path.is_relative_to(base_dir):
                raise ValueError("source file is outside source_base_dir")
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"source file not found: {path}")
            text = path.read_text(encoding="utf-8")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                self._add_source(
                    sources,
                    kind="file",
                    title=path.name,
                    content=text,
                    metadata={"path": str(path)},
                )
                continue
            if isinstance(parsed, dict):
                self._append_structured_sources(parsed, sources, metadata={"path": str(path)})
            elif isinstance(parsed, list):
                self._append_structured_sources({"messages": parsed}, sources, metadata={"path": str(path)})

    def _append_structured_sources(
        self,
        payload: dict[str, Any],
        sources: list[DistillationSource],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        base_metadata = dict(metadata or {})
        for message in self._iter_items(
            payload,
            "messages",
            "chat_messages",
            "chatMessages",
            "chat_history",
            "chatHistory",
            "history",
        ):
            if isinstance(message, dict):
                role = str(message.get("role") or "message").strip()
                content = str(message.get("content") or message.get("text") or "").strip()
            else:
                role = "message"
                content = str(message or "").strip()
            if content:
                self._add_source(
                    sources,
                    kind="chat",
                    title=f"Chat {len(sources) + 1} ({role})",
                    content=content,
                    metadata={**base_metadata, "role": role},
                )
        for task in self._iter_items(payload, "tasks", "task_traces", "taskTraces"):
            if isinstance(task, dict):
                title = str(task.get("title") or task.get("name") or "Task trace").strip()
                content = str(
                    task.get("summary")
                    or task.get("content")
                    or task.get("description")
                    or task.get("result")
                    or title
                ).strip()
            else:
                title = "Task trace"
                content = str(task or "").strip()
            if content:
                self._add_source(sources, kind="task_trace", title=title, content=content, metadata=base_metadata)
        for correction in self._iter_items(payload, "corrections", "user_corrections", "userCorrections"):
            title = "Correction"
            content = str(correction or "").strip()
            if isinstance(correction, dict):
                title = str(correction.get("title") or title).strip()
                content = str(correction.get("content") or correction.get("text") or "").strip()
            if content:
                self._add_source(sources, kind="correction", title=title, content=content, metadata=base_metadata)
        for artifact in self._iter_items(payload, "artifacts", "outputs"):
            if isinstance(artifact, dict):
                title = str(artifact.get("name") or artifact.get("label") or "Artifact").strip()
                content = str(
                    artifact.get("preview")
                    or artifact.get("summary")
                    or artifact.get("content")
                    or artifact.get("path")
                    or title
                ).strip()
            else:
                title = "Artifact"
                content = str(artifact or "").strip()
            if content:
                self._add_source(sources, kind="artifact", title=title, content=content, metadata=base_metadata)
        for approval in self._iter_items(payload, "approvals", "approval_events", "approvalEvents"):
            if isinstance(approval, dict):
                title = str(approval.get("action") or approval.get("title") or "Approval").strip()
                approved = approval.get("approved")
                content = f"{title}: {'approved' if approved else 'not approved'}"
                note = str(approval.get("note") or approval.get("reason") or "").strip()
                if note:
                    content = f"{content}. {note}"
            else:
                title = "Approval"
                content = str(approval or "").strip()
            if content:
                self._add_source(sources, kind="approval", title=title, content=content, metadata=base_metadata)
        for note in self._iter_items(payload, "notes", "manual_notes", "manualNotes"):
            title = "Manual note"
            content = str(note or "").strip()
            if isinstance(note, dict):
                title = str(note.get("title") or title).strip()
                content = str(note.get("content") or note.get("text") or "").strip()
            if content:
                self._add_source(sources, kind="manual_note", title=title, content=content, metadata=base_metadata)

    @staticmethod
    def _iter_items(payload: dict[str, Any], *keys: str) -> list[Any]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []

    def _review_metadata(self, sources: list[DistillationSource]) -> dict[str, Any]:
        sensitive_ids = [source.id for source in sources if source.metadata.get("sensitive")]
        conflicts = self._detect_conflicts(sources)
        risk_actions = self._risk_actions(sources)
        return {
            "queue": "needs_review",
            "conflicts": conflicts,
            "sensitive": {
                "requires_explicit_approval": bool(sensitive_ids or risk_actions),
                "redacted_source_ids": sensitive_ids,
                "risk_actions": risk_actions,
            },
        }

    def _risk_actions(self, sources: list[DistillationSource]) -> list[str]:
        actions: set[str] = set()
        for source in sources:
            text = f"{source.title}\n{source.content}"
            for action, pattern in RISK_ACTION_RULES:
                if pattern.search(text):
                    actions.add(action)
        return sorted(actions)

    def _detect_conflicts(self, sources: list[DistillationSource]) -> list[dict[str, Any]]:
        combined = "\n".join(source.content.casefold() for source in sources)
        conflicts: list[dict[str, Any]] = []
        if "prefer concise" in combined and "prefer detailed" in combined:
            conflicts.append(
                {
                    "type": "preference_conflict",
                    "topic": "response_detail",
                    "evidence": [source.id for source in sources if "prefer" in source.content.casefold()],
                }
            )
        if "do not send calendar" in combined and "send calendar" in combined:
            conflicts.append(
                {
                    "type": "permission_conflict",
                    "topic": "calendar_actions",
                    "evidence": [source.id for source in sources if "calendar" in source.content.casefold()],
                }
            )
        return conflicts

    def _supersede_prior_jobs(self, twin_id: str, *, current_job_id: str, skill_name: str) -> None:
        for previous in self.list_jobs(twin_id):
            if previous.id == current_job_id:
                continue
            if str(previous.generated_skill.get("name") or "") != skill_name:
                continue
            if previous.status not in {
                DistillationStatus.NEEDS_REVIEW,
                DistillationStatus.APPROVED,
                DistillationStatus.INSTALLED,
            }:
                continue
            updated = DistillationJob(
                **{
                    **previous.__dict__,
                    "status": DistillationStatus.SUPERSEDED,
                    "updated_at": utc_now(),
                    "review": {
                        **dict(previous.review or {}),
                        "superseded_by": current_job_id,
                    },
                }
            )
            self.job_store.write_job(updated)

    def _distill_artifacts(
        self,
        *,
        goal: str,
        skill_name: str,
        sources: list[DistillationSource],
    ) -> list[DistilledArtifact]:
        combined = " ".join(source.content for source in sources)
        evidence_ids = [source.id for source in sources]
        return [
            DistilledArtifact(
                id="art_profile_1",
                layer=DistillationLayer.PROFILE,
                title=f"{goal} personal context",
                content=_clip(f"Use this when representing the user's recurring need: {goal}. Evidence: {combined}"),
                confidence=0.72,
                evidence_ids=evidence_ids,
            ),
            DistilledArtifact(
                id="art_style_1",
                layer=DistillationLayer.STYLE,
                title=f"{goal} response style",
                content=_clip(
                    "Prefer concise, explicit, reviewable outputs. "
                    "Preserve user corrections as higher-priority instructions."
                ),
                confidence=0.68,
                evidence_ids=evidence_ids,
            ),
            DistilledArtifact(
                id="art_procedural_1",
                layer=DistillationLayer.PROCEDURAL,
                title=f"{goal} procedure",
                content=_clip(f"For {goal}, ask for missing material, summarize decisions, identify risks, and list next actions."),
                confidence=0.76,
                evidence_ids=evidence_ids,
            ),
            DistilledArtifact(
                id="art_skill_1",
                layer=DistillationLayer.PERSONAL_SKILL,
                title=skill_name,
                content=_clip(f"Promote this workflow to a personal skill named {skill_name}."),
                confidence=0.64,
                evidence_ids=evidence_ids,
            ),
        ]

    def _render_skill_package(
        self,
        *,
        skill_dir: Path,
        job_id: str,
        mode: str,
        skill_name: str,
        author: str,
        goal: str,
        artifacts: list[DistilledArtifact],
        sources: list[DistillationSource],
    ) -> dict[str, Any]:
        skill_dir.mkdir(parents=True, exist_ok=True)
        procedural = [artifact for artifact in artifacts if artifact.layer == DistillationLayer.PROCEDURAL]
        procedure_lines = "\n".join(f"- {artifact.content}" for artifact in procedural) or f"- {goal}"
        evidence_lines = "\n".join(f"- {source.title}: {_clip(source.content, 160)}" for source in sources)
        skill_md = (
            "---\n"
            f"name: {skill_name}\n"
            "version: 0.1.0\n"
            f"author: {author}\n"
            f"description: Personal distilled workflow for {goal}\n"
            "tags: [jiume, personal-skill, distilled]\n"
            "allowed_tools: [read_memory, write_file]\n"
            "risk_level: medium\n"
            "requires_approval: [send_external_message, modify_calendar, payment, irreversible_change]\n"
            "---\n\n"
            f"# {skill_name}\n\n"
            "Use this skill when the user asks for the recurring personal workflow below.\n\n"
            "## Workflow\n\n"
            f"{procedure_lines}\n\n"
            "## Evidence\n\n"
            f"{evidence_lines}\n\n"
            "## Expected output\n\n"
            "- Concise result summary.\n"
            "- Decisions, risks, and next actions when applicable.\n"
            "- Assumptions and follow-up questions when source material is incomplete.\n"
        )
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        (skill_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "name": skill_name,
                    "source": "jiume_personal_distillation",
                    "goal": goal,
                    "allowed_tools": ["read_memory", "write_file"],
                    "skill_evolution_owner": "jiuwen",
                    "provenance": {
                        "job_id": job_id,
                        "mode": mode,
                        "source_ids": [source.id for source in sources],
                        "source_kinds": sorted({source.kind for source in sources}),
                        "artifact_layers": [
                            layer.value for layer in DistillationLayer if any(artifact.layer == layer for artifact in artifacts)
                        ],
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        examples_dir = skill_dir / "examples"
        examples_dir.mkdir(exist_ok=True)
        (examples_dir / "input.md").write_text(goal + "\n", encoding="utf-8")
        (examples_dir / "expected_output.md").write_text(
            "- Concise result summary\n- Decisions\n- Risks\n- Next actions\n",
            encoding="utf-8",
        )
        evals_dir = skill_dir / "evals"
        evals_dir.mkdir(exist_ok=True)
        (evals_dir / "evals.json").write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "name": "basic",
                            "input": "Run this personal workflow",
                            "must_include": ["summary"],
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "name": skill_name,
            "folder": str(skill_dir),
            "skill_md": str(skill_dir / "SKILL.md"),
            "allowed_tools": ["read_memory", "write_file"],
            "provenance": {
                "job_id": job_id,
                "source": "jiume_personal_distillation",
                "skill_evolution_owner": "jiuwen",
            },
        }
