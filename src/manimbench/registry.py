"""The model list, the routes, and the judge panel."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from manimbench.paths import JUDGES_PATH, MODELS_PATH, ROUTES_PATH
from manimbench.providers.base import Route, RouteDisabledError
from manimbench.providers.claude_cli import ClaudeCliRoute
from manimbench.providers.openrouter import OpenRouterRoute

ROUTE_NAMES = ["openrouter", "claude-cli"]


@dataclass(frozen=True)
class ModelEntry:
    id: str
    name: str
    vendor: str
    reasoning_effort: str | None
    max_output_tokens: int | None
    routes: dict[str, dict[str, Any]]

    def target(self, route: str) -> dict[str, Any]:
        if route not in self.routes:
            available = ", ".join(sorted(self.routes)) or "none"
            raise KeyError(f"Model {self.id} has no {route} route (it has: {available})")
        return dict(self.routes[route])


@dataclass(frozen=True)
class JudgePanel:
    route: str
    judges: list[str]
    max_frames: int
    max_output_tokens: int | None


IGNORE_LOCAL_ENV = "MANIMBENCH_IGNORE_LOCAL_CONFIG"


def local_override(path: Path) -> Path:
    """``routes.local.yaml`` next to ``routes.yaml``, and so on.

    A local file replaces the shipped one on this machine and is ignored by git.
    That is how a route is turned on without changing what the repository ships.
    """
    return path.with_name(path.stem + ".local" + path.suffix)


def _load(path: Path) -> dict[str, Any]:
    override = local_override(path)
    if override.exists() and not os.environ.get(IGNORE_LOCAL_ENV):
        path = override
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping in {path}")
    return data


def load_models(path: Path = MODELS_PATH) -> dict[str, ModelEntry]:
    models: dict[str, ModelEntry] = {}
    for item in _load(path).get("models", []):
        model_id = str(item["id"])
        if model_id in models:
            raise ValueError(f"{path}: duplicate model id {model_id}")
        routes = {str(name): dict(target) for name, target in (item.get("routes") or {}).items()}
        for name, target in routes.items():
            if name not in ROUTE_NAMES:
                raise ValueError(f"{path}: model {model_id} names an unknown route {name!r}")
            if not target.get("model"):
                raise ValueError(f"{path}: model {model_id} route {name} needs a model")
        effort = item.get("reasoning_effort")
        limit = item.get("max_output_tokens")
        models[model_id] = ModelEntry(
            id=model_id,
            name=str(item.get("name", model_id)),
            vendor=str(item.get("vendor", "")),
            reasoning_effort=str(effort) if effort else None,
            max_output_tokens=int(limit) if limit else None,
            routes=routes,
        )
    return models


def load_model(model_id: str, path: Path = MODELS_PATH) -> ModelEntry:
    models = load_models(path)
    if model_id not in models:
        raise KeyError(f"Unknown model id: {model_id}. Known: {', '.join(sorted(models))}")
    return models[model_id]


def load_routes(path: Path = ROUTES_PATH) -> dict[str, Any]:
    data = _load(path)
    routes = data.get("routes") or {}
    for name in routes:
        if name not in ROUTE_NAMES:
            raise ValueError(f"{path}: unknown route {name!r}")
    return {"default_route": str(data.get("default_route", "openrouter")), "routes": routes}


def load_judges(path: Path = JUDGES_PATH) -> JudgePanel:
    data = _load(path)
    judges = [str(item) for item in data.get("judges", [])]
    if len(judges) != len(set(judges)):
        raise ValueError(f"{path}: the same judge is listed twice")
    limit = data.get("max_output_tokens")
    return JudgePanel(
        route=str(data.get("route", "openrouter")),
        judges=judges,
        max_frames=int(data.get("max_frames", 12)),
        max_output_tokens=int(limit) if limit else None,
    )


def make_route(name: str, path: Path = ROUTES_PATH) -> Route:
    """Build a live route. Refuses unless the route is enabled in routes.yaml."""
    config = load_routes(path)["routes"].get(name)
    if config is None:
        raise KeyError(f"Unknown route: {name}")
    if not config.get("enabled", False):
        raise RouteDisabledError(
            f"The {name} route is switched off. To allow live calls, copy {path.name} to "
            f"{local_override(path).name} in the same folder and set enabled: true for it there."
        )
    if name == "openrouter":
        return OpenRouterRoute(
            base_url=str(config.get("base_url", "https://openrouter.ai/api/v1")),
            api_key_env=str(config.get("api_key_env", "OPENROUTER_API_KEY")),
            timeout_seconds=float(config.get("timeout_seconds", 900)),
        )
    return ClaudeCliRoute(
        command=str(config.get("command", "claude")),
        timeout_seconds=float(config.get("timeout_seconds", 1800)),
    )
