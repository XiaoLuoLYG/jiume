"""Local configuration for JiuMe providers."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from jiume.paths import get_jiume_root


@dataclass(frozen=True)
class ImageProviderConfig:
    api_key: str
    api_key_source: str | None
    base_url: str
    base_url_source: str | None
    model: str
    model_source: str | None
    config_path: Path

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


def get_config_env_path() -> Path:
    return get_jiume_root() / "config.env"


def load_jiume_env(*, override: bool = False) -> Path:
    path = get_config_env_path()
    if path.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(path, override=override)
        except Exception:
            _load_simple_env(path, override=override)
    return path


def _load_simple_env(path: Path, *, override: bool) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or (not override and key in os.environ):
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _first_env(keys: tuple[str, ...], default: str = "") -> tuple[str, str | None]:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value.strip(), key
    return default, None


def get_image_provider_config() -> ImageProviderConfig:
    load_jiume_env(override=False)
    api_key, api_key_source = _first_env(("JIUME_OPENAI_API_KEY", "OPENAI_API_KEY"))
    base_url, base_url_source = _first_env(
        ("JIUME_OPENAI_BASE_URL", "OPENAI_BASE_URL", "API_BASE"),
    )
    model, model_source = _first_env(("JIUME_IMAGE_MODEL", "OPENAI_IMAGE_MODEL"), "gpt-image-2")
    return ImageProviderConfig(
        api_key=api_key,
        api_key_source=api_key_source,
        base_url=base_url,
        base_url_source=base_url_source,
        model=model,
        model_source=model_source,
        config_path=get_config_env_path(),
    )


def _read_config_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_image_provider_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> Path:
    path = get_config_env_path()
    values = _read_config_values(path)
    if api_key is not None:
        stripped = api_key.strip()
        if stripped:
            values["JIUME_OPENAI_API_KEY"] = stripped
    if base_url is not None:
        values["JIUME_OPENAI_BASE_URL"] = base_url.strip()
    if model is not None:
        values["JIUME_IMAGE_MODEL"] = model.strip() or "gpt-image-2"

    ordered_keys = ("JIUME_OPENAI_API_KEY", "JIUME_OPENAI_BASE_URL", "JIUME_IMAGE_MODEL")
    lines = [
        "# Local JiuMe image provider config.",
        "# This file is loaded by jiume-setup and the JiuMe desktop avatar. Do not commit it.",
    ]
    for key in ordered_keys:
        if key in values:
            lines.append(f"{key}={shlex.quote(values[key])}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_jiume_env(override=True)
    return path


def public_config_payload() -> dict[str, object]:
    config = get_image_provider_config()
    return {
        "configPath": str(config.config_path),
        "hasApiKey": config.has_api_key,
        "apiKeySource": config.api_key_source,
        "baseUrl": config.base_url,
        "baseUrlSource": config.base_url_source,
        "model": config.model,
        "modelSource": config.model_source,
        "envKeys": {
            "apiKey": "JIUME_OPENAI_API_KEY or OPENAI_API_KEY",
            "baseUrl": "JIUME_OPENAI_BASE_URL or OPENAI_BASE_URL",
            "model": "JIUME_IMAGE_MODEL",
        },
    }
