from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from manimbench.paths import PROJECT_ROOT


PUBLIC_MODELS_PATH = PROJECT_ROOT / "models" / "public.yaml"
OPENROUTER_MODELS_PATH = PROJECT_ROOT / "models" / "openrouter.yaml"
PROVIDERS_PATH = PROJECT_ROOT / "models" / "providers.yaml"


@dataclass(frozen=True)
class RegistryModel:
    id: str
    display_name: str
    default_enabled: bool
    provider_family: str
    tokenizer: str | None
    pricing: dict[str, Any]
    openrouter_slug: str | None
    raw: dict[str, Any]


def load_models(public_only: bool = True) -> list[RegistryModel]:
    data = _load_yaml(PUBLIC_MODELS_PATH)
    routes = _openrouter_routes()
    models = []
    for item in data.get("models", []):
        if public_only and _is_private_model(item):
            continue
        model_id = str(item["id"])
        models.append(
            RegistryModel(
                id=model_id,
                display_name=str(item.get("display_name", model_id)),
                default_enabled=bool(item.get("default_enabled", False)),
                provider_family=str(item.get("provider_family", "openrouter")),
                tokenizer=str(item["tokenizer"]) if item.get("tokenizer") else None,
                pricing=dict(item.get("pricing", {})),
                openrouter_slug=routes.get(model_id),
                raw=dict(item),
            )
        )
    return models


def load_model(model_id: str) -> RegistryModel:
    for model in load_models(public_only=False):
        if model.id == model_id:
            return model
    raise KeyError(f"Unknown model id: {model_id}")


def model_map(public_only: bool = True) -> dict[str, RegistryModel]:
    return {model.id: model for model in load_models(public_only=public_only)}


def provider_config(provider: str) -> dict[str, Any]:
    data = _load_yaml(PROVIDERS_PATH)
    providers = data.get("providers", {})
    if provider not in providers:
        raise KeyError(f"Unknown provider: {provider}")
    return dict(providers[provider])


def default_provider_for_model(model_id: str) -> str:
    data = _load_yaml(PROVIDERS_PATH)
    overrides = data.get("model_overrides", {})
    if isinstance(overrides, dict) and model_id in overrides:
        return str(overrides[model_id])
    return str(data.get("default_provider", "openrouter"))


def openrouter_slug(model_id: str) -> str:
    routes = _openrouter_routes()
    if model_id not in routes:
        raise KeyError(f"No OpenRouter slug configured for model id: {model_id}")
    return str(routes[model_id])


def public_model_rows(public_only: bool = True) -> list[dict[str, Any]]:
    rows = []
    for model in load_models(public_only=public_only):
        rows.append(
            {
                "id": model.id,
                "display_name": model.display_name,
                "default_enabled": model.default_enabled,
                "provider_family": model.provider_family,
                "default_provider": default_provider_for_model(model.id),
                "openrouter_slug": model.openrouter_slug,
            }
        )
    return rows


def _openrouter_routes() -> dict[str, str]:
    data = _load_yaml(OPENROUTER_MODELS_PATH)
    routes = data.get("models", {})
    if not isinstance(routes, dict):
        raise ValueError(f"Expected models mapping in {OPENROUTER_MODELS_PATH}")
    return {str(key): str(value) for key, value in routes.items()}


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def _is_private_model(item: dict[str, Any]) -> bool:
    if bool(item.get("catalog_hidden")):
        return True
    tier = str(item.get("tier", "")).lower()
    access = str(item.get("access", "")).lower()
    return tier in {"pro", "enterprise"} or access in {"pro", "enterprise", "private"}
