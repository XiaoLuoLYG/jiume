"""Datamodels for JiuMe personal distillation jobs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DistillationLayer(str, Enum):
    PROFILE = "profile"
    STYLE = "style"
    PROCEDURAL = "procedural"
    PERSONAL_SKILL = "personal_skill"


class DistillationStatus(str, Enum):
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    INSTALLED = "installed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


SAFE_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def safe_slug(value: str, *, fallback: str = "jiume-distilled-skill", limit: int = 64) -> str:
    slug = SAFE_SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return (slug[:limit].strip("-") or fallback)[:limit]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass(frozen=True)
class DistillationSource:
    id: str
    kind: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "content": self.content,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DistillationSource":
        return cls(
            id=str(payload.get("id") or "").strip(),
            kind=str(payload.get("kind") or "note").strip() or "note",
            title=str(payload.get("title") or "").strip(),
            content=str(payload.get("content") or "").strip(),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class DistilledArtifact:
    id: str
    layer: DistillationLayer
    title: str
    content: str
    confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer.value,
            "title": self.title,
            "content": self.content,
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DistilledArtifact":
        layer_value = str(payload.get("layer") or "").strip()
        try:
            layer = DistillationLayer(layer_value)
        except ValueError as exc:
            raise ValueError(f"invalid distillation layer: {layer_value}") from exc
        confidence_raw = payload.get("confidence")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        return cls(
            id=str(payload.get("id") or "").strip(),
            layer=layer,
            title=str(payload.get("title") or "").strip(),
            content=str(payload.get("content") or "").strip(),
            confidence=max(0.0, min(1.0, confidence)),
            evidence_ids=_string_list(payload.get("evidence_ids") or payload.get("evidenceIds")),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class DistillationJob:
    id: str
    twin_id: str
    mode: str
    status: DistillationStatus
    goal: str
    sources: list[DistillationSource]
    artifacts: list[DistilledArtifact]
    generated_skill: dict[str, Any]
    created_at: str
    updated_at: str
    test: dict[str, Any] = field(default_factory=dict)
    installed_path: str = ""
    review: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "twin_id": self.twin_id,
            "mode": self.mode,
            "source_type": self.mode,
            "status": self.status.value,
            "goal": self.goal,
            "sources": [source.to_dict() for source in self.sources],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "generated_skill": dict(self.generated_skill),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.test:
            payload["test"] = dict(self.test)
        if self.installed_path:
            payload["installed_path"] = self.installed_path
        if self.review:
            payload["review"] = dict(self.review)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DistillationJob":
        status_value = str(payload.get("status") or "").strip()
        try:
            status = DistillationStatus(status_value)
        except ValueError as exc:
            raise ValueError(f"invalid distillation status: {status_value}") from exc
        sources = [
            DistillationSource.from_dict(item)
            for item in payload.get("sources", [])
            if isinstance(item, dict)
        ]
        artifacts = [
            DistilledArtifact.from_dict(item)
            for item in payload.get("artifacts", [])
            if isinstance(item, dict)
        ]
        return cls(
            id=str(payload.get("id") or "").strip(),
            twin_id=str(payload.get("twin_id") or payload.get("twinId") or "").strip(),
            mode=str(
                payload.get("mode")
                or payload.get("source_type")
                or payload.get("sourceType")
                or "offline_bootstrap"
            ).strip()
            or "offline_bootstrap",
            status=status,
            goal=str(payload.get("goal") or "").strip(),
            sources=sources,
            artifacts=artifacts,
            generated_skill=dict(payload.get("generated_skill") or payload.get("generatedSkill") or {}),
            created_at=str(payload.get("created_at") or payload.get("createdAt") or "").strip(),
            updated_at=str(payload.get("updated_at") or payload.get("updatedAt") or "").strip(),
            test=dict(payload.get("test") or {}),
            installed_path=str(payload.get("installed_path") or payload.get("installedPath") or "").strip(),
            review=dict(payload.get("review") or {}),
        )
