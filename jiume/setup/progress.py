"""Import progress and error classification for JiuMe setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GenerationStage = Literal["pet", "enable"]
GenerationFailureCode = Literal["invalid_pet", "unknown"]

GENERATION_PHASE_LABELS: dict[GenerationStage, str] = {
    "pet": "正在导入 Codex pet",
    "enable": "分身已导入，等待启用",
}

GENERATION_PHASE_DETAILS: dict[GenerationStage, str] = {
    "pet": "正在校验 pet.json 和 spritesheet.webp。",
    "enable": "导入完成，启用后才会出现在桌面。",
}

GENERATION_PHASE_PERCENT: dict[GenerationStage, float] = {
    "pet": 0.6,
    "enable": 1.0,
}


@dataclass(frozen=True)
class GenerationProgress:
    stage: GenerationStage
    title: str
    detail: str
    percent: float

    def as_dict(self) -> dict[str, str | float]:
        return {
            "stage": self.stage,
            "title": self.title,
            "detail": self.detail,
            "percent": self.percent,
        }


@dataclass(frozen=True)
class GenerationFailure:
    code: GenerationFailureCode
    title: str
    detail: str


def generation_progress(stage: str) -> GenerationProgress:
    safe_stage: GenerationStage = stage if stage in GENERATION_PHASE_LABELS else "pet"  # type: ignore[assignment]
    return GenerationProgress(
        stage=safe_stage,
        title=GENERATION_PHASE_LABELS[safe_stage],
        detail=GENERATION_PHASE_DETAILS[safe_stage],
        percent=GENERATION_PHASE_PERCENT[safe_stage],
    )


def classify_generation_error(error: BaseException | str) -> GenerationFailure:
    message = str(error or "").strip() or error.__class__.__name__
    lower = message.lower()
    if "pet" in lower or "spritesheet" in lower or "atlas" in lower or "zip" in lower:
        return GenerationFailure(
            code="invalid_pet",
            title="Codex pet 包无效",
            detail=message,
        )
    return GenerationFailure(
        code="unknown",
        title="生成失败",
        detail=message,
    )
