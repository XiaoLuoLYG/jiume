"""Generation progress and error classification for JiuMe setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GenerationStage = Literal["photo", "model", "states", "enable"]
GenerationFailureCode = Literal["config_missing", "timeout", "network", "unknown"]

GENERATION_PHASE_LABELS: dict[GenerationStage, str] = {
    "photo": "照片已读取",
    "model": "正在调用图片模型",
    "states": "正在生成分身动作",
    "enable": "分身已生成，等待启用",
}

GENERATION_PHASE_DETAILS: dict[GenerationStage, str] = {
    "photo": "照片已经准备好，正在整理素材。",
    "model": "图片模型正在生成角色基底。",
    "states": "正在生成 idle、waving、running 等 Codex pet 动作。",
    "enable": "生成完成，启用后才会出现在桌面。",
}

GENERATION_PHASE_PERCENT: dict[GenerationStage, float] = {
    "photo": 0.18,
    "model": 0.45,
    "states": 0.78,
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
    safe_stage: GenerationStage = stage if stage in GENERATION_PHASE_LABELS else "model"  # type: ignore[assignment]
    return GenerationProgress(
        stage=safe_stage,
        title=GENERATION_PHASE_LABELS[safe_stage],
        detail=GENERATION_PHASE_DETAILS[safe_stage],
        percent=GENERATION_PHASE_PERCENT[safe_stage],
    )


def classify_generation_error(error: BaseException | str) -> GenerationFailure:
    message = str(error or "").strip() or error.__class__.__name__
    lower = message.lower()
    if "api key" in lower or "apikey" in lower or "config" in lower:
        return GenerationFailure(
            code="config_missing",
            title="图片模型 API Key 缺失",
            detail=message,
        )
    if isinstance(error, TimeoutError) or "timeout" in lower or "timed out" in lower or "超时" in message:
        return GenerationFailure(
            code="timeout",
            title="图片模型请求超时",
            detail=message,
        )
    if isinstance(error, (ConnectionError, OSError)) or "connection" in lower or "network" in lower:
        return GenerationFailure(
            code="network",
            title="图片模型网络连接失败",
            detail=message,
        )
    return GenerationFailure(
        code="unknown",
        title="生成失败",
        detail=message,
    )
