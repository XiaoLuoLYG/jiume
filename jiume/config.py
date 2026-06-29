"""Local configuration for JiuMe providers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv, set_key

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
        load_dotenv(path, override=override)
    return path


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


def write_image_provider_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> Path:
    path = get_config_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Local JiuMe image provider config.\n"
            "# This file is loaded by jiume-setup and the JiuMe desktop avatar. Do not commit it.\n",
            encoding="utf-8",
        )
    values = {key: str(value) for key, value in dotenv_values(path).items() if value is not None}
    if api_key is not None:
        stripped = api_key.strip()
        if stripped:
            values["JIUME_OPENAI_API_KEY"] = stripped
    if base_url is not None:
        values["JIUME_OPENAI_BASE_URL"] = base_url.strip()
    if model is not None:
        values["JIUME_IMAGE_MODEL"] = model.strip() or "gpt-image-2"

    ordered_keys = ("JIUME_OPENAI_API_KEY", "JIUME_OPENAI_BASE_URL", "JIUME_IMAGE_MODEL")
    for key in ordered_keys:
        if key in values:
            set_key(str(path), key, values[key])
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
