from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from manimbench.model_registry import load_models, provider_config
from manimbench.paths import DEFAULT_OUTPUTS_DIR, DEFAULT_RUNS_DIR, DEFAULT_SITE_REPO
from manimbench.reasoning import stored_reasoning_effort


def user_config_dir() -> Path:
    root = os.getenv("XDG_CONFIG_HOME")
    if root:
        return Path(root).expanduser() / "manimbench"
    return Path.home() / ".config" / "manimbench"


def state_path() -> Path:
    return user_config_dir() / "dashboard.json"


def legacy_state_path() -> Path:
    return user_config_dir() / "tui-state.json"


@dataclass
class UIState:
    schema_version: str = "0.5b"
    selected_models: list[str] = field(default_factory=list)
    provider_filter: str = "all"
    model_scope: str = "curated"
    model_sort: str = "provider"
    status_filter: str = "all"
    context_filter: str = "all"
    price_filter: str = "all"
    search: str = ""
    last_run_id: str | None = None
    default_parallel: int = 1
    output_dir: str = str(DEFAULT_OUTPUTS_DIR)
    runs_dir: str = str(DEFAULT_RUNS_DIR)
    site_repo: str = str(DEFAULT_SITE_REPO)
    spend_warning_usd: float = 25.0
    env_var_names: dict[str, str] = field(default_factory=dict)
    github_token_env: str = "GITHUB_TOKEN"
    github_repo: str = "Ntrpydev/manim-bench"
    draft_branch: str = "draft"
    live_branch: str = "main"
    cloudflare_deploy_hook_env: str = "CLOUDFLARE_DEPLOY_HOOK"
    docker_image: str = "manimbench-manimce:latest"
    skip_complete: bool = True
    force_rerun: bool = False
    openrouter_catalog_enabled: bool = True
    reasoning_effort: str = "default"

    @classmethod
    def defaults(cls) -> "UIState":
        selected = [model.id for model in load_models(public_only=True) if model.default_enabled]
        env_names = {}
        for provider in ["openrouter", "cursor", "openai", "anthropic", "google", "xai"]:
            try:
                env_names[provider] = str(provider_config(provider).get("env_key", ""))
            except KeyError:
                continue
        return cls(selected_models=selected, env_var_names=env_names)

    @classmethod
    def load(cls, path: Path | None = None) -> "UIState":
        target = path or state_path()
        base = cls.defaults()
        if path is None and not target.exists() and legacy_state_path().exists():
            target = legacy_state_path()
        if not target.exists():
            return base
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return base
        if not isinstance(data, dict):
            return base
        clean: dict[str, Any] = {}
        for key in asdict(base):
            if key in data:
                clean[key] = data[key]
        state = cls(**{**asdict(base), **clean})
        state.env_var_names = _scrub_env_names(state.env_var_names, base.env_var_names)
        state.github_token_env = _scrub_env_name(state.github_token_env, base.github_token_env)
        state.cloudflare_deploy_hook_env = _scrub_env_name(state.cloudflare_deploy_hook_env, base.cloudflare_deploy_hook_env)
        try:
            state.default_parallel = max(1, int(state.default_parallel or 1))
        except (TypeError, ValueError):
            state.default_parallel = base.default_parallel
        state.skip_complete = bool(state.skip_complete)
        state.force_rerun = bool(state.force_rerun)
        state.reasoning_effort = stored_reasoning_effort(state.reasoning_effort)
        return state

    def save(self, path: Path | None = None) -> Path:
        target = path or state_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["env_var_names"] = _scrub_env_names(self.env_var_names, UIState.defaults().env_var_names)
        data["github_token_env"] = _scrub_env_name(self.github_token_env, UIState.defaults().github_token_env)
        data["cloudflare_deploy_hook_env"] = _scrub_env_name(
            self.cloudflare_deploy_hook_env,
            UIState.defaults().cloudflare_deploy_hook_env,
        )
        data["reasoning_effort"] = stored_reasoning_effort(self.reasoning_effort)
        target.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return target

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir).expanduser()

    @property
    def runs_path(self) -> Path:
        return Path(self.runs_dir).expanduser()

    @property
    def site_repo_path(self) -> Path:
        return Path(self.site_repo).expanduser()


def _scrub_env_names(value: dict[str, str], fallback: dict[str, str]) -> dict[str, str]:
    clean = {}
    for provider, env_name in {**fallback, **(value or {})}.items():
        name = _scrub_env_name(str(env_name), fallback.get(provider, ""))
        if not name:
            continue
        clean[str(provider)] = name
    return clean


def _scrub_env_name(value: str, fallback: str) -> str:
    name = str(value or "").strip()
    if not name:
        return str(fallback or "").strip()
    upper = name.upper()
    if any(secret_marker in upper for secret_marker in ["KEY=", "TOKEN=", "SECRET=", "BEARER ", "SK-"]):
        return str(fallback or "").strip()
    return name
