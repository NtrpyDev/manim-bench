from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from manimbench.model_registry import OPENROUTER_MODELS_PATH, PUBLIC_MODELS_PATH
from manimbench.paths import PROJECT_ROOT
from manimbench.providers.openrouter import OpenRouterProvider


DEFAULT_MODEL_CHECK_STATE_PATH = PROJECT_ROOT / ".manimbench" / "model-check.json"


@dataclass(frozen=True)
class ModelCandidate:
    id: str
    display_name: str
    provider_family: str
    openrouter_slug: str
    tokenizer: str
    pricing: dict[str, Any]
    context_length: int | None = None
    max_completion_tokens: int | None = None
    supported_parameters: list[str] = field(default_factory=list)
    created: int | None = None


@dataclass(frozen=True)
class ModelCheckResult:
    checked_at: str
    skipped: bool
    state_path: Path
    new_models: list[ModelCandidate]
    all_models: list[ModelCandidate] = field(default_factory=list)
    unregistered_models: list[ModelCandidate] = field(default_factory=list)
    applied: bool = False
    error: str | None = None


def check_openrouter_models(
    *,
    force: bool = False,
    apply_updates: bool = False,
    interval_hours: int = 24,
    catalog: dict[str, Any] | None = None,
    api_key: str | None = None,
    client: Any | None = None,
    state_path: Path = DEFAULT_MODEL_CHECK_STATE_PATH,
    openrouter_path: Path = OPENROUTER_MODELS_PATH,
    public_path: Path = PUBLIC_MODELS_PATH,
    include_unregistered: bool = False,
) -> ModelCheckResult:
    state = _load_state(state_path)
    cached = _cached_result(state, state_path=state_path, include_unregistered=include_unregistered)
    cache_has_requested_sections = not include_unregistered or ("unregistered_models" in state and "catalog_models" in state)
    if not force and cache_has_requested_sections and _state_is_fresh(state, interval_hours):
        if apply_updates and cached.new_models:
            apply_model_candidates(cached.new_models, openrouter_path=openrouter_path, public_path=public_path)
            _write_state(state_path, {**state, "applied_at": _now_iso(), "applied_model_ids": [model.id for model in cached.new_models]})
            return ModelCheckResult(
                checked_at=cached.checked_at,
                skipped=True,
                state_path=state_path,
                new_models=cached.new_models,
                all_models=cached.all_models,
                unregistered_models=cached.unregistered_models,
                applied=True,
            )
        return cached

    try:
        payload = catalog or OpenRouterProvider.fetch_model_metadata(api_key=api_key, client=client)
        live_items = _catalog_items(payload)
        live_slugs = {str(item.get("id")) for item in live_items if item.get("id")}
        known_slugs = set(state.get("known_openrouter_slugs", [])) if isinstance(state.get("known_openrouter_slugs"), list) else set()
        configured_slugs = _configured_openrouter_slugs(openrouter_path)
        all_models = _candidates_from_items(
            live_items,
            openrouter_path=openrouter_path,
            public_path=public_path,
        )
        new_slugs = live_slugs - known_slugs if known_slugs else live_slugs - configured_slugs if force else set()
        candidates = _candidates_from_items(
            [item for item in live_items if str(item.get("id")) in new_slugs],
            openrouter_path=openrouter_path,
            public_path=public_path,
        )
        visible_slugs = _visible_openrouter_slugs(openrouter_path, public_path)
        unregistered = (
            _candidates_from_items(
                [item for item in live_items if str(item.get("id")) not in visible_slugs],
                openrouter_path=openrouter_path,
                public_path=public_path,
            )
            if include_unregistered
            else []
        )
        if apply_updates and candidates:
            apply_model_candidates(candidates, openrouter_path=openrouter_path, public_path=public_path)
        checked_at = _now_iso()
        _write_state(
            state_path,
            {
                "checked_at": checked_at,
                "known_openrouter_slugs": sorted(live_slugs),
                "new_models": [asdict(candidate) for candidate in candidates],
                "catalog_models": [asdict(candidate) for candidate in all_models],
                "unregistered_models": [asdict(candidate) for candidate in unregistered],
                "applied_at": checked_at if apply_updates and candidates else state.get("applied_at"),
                "applied_model_ids": [candidate.id for candidate in candidates] if apply_updates and candidates else state.get("applied_model_ids", []),
            },
        )
        return ModelCheckResult(
            checked_at=checked_at,
            skipped=False,
            state_path=state_path,
            new_models=candidates,
            all_models=all_models,
            unregistered_models=unregistered,
            applied=bool(apply_updates and candidates),
        )
    except Exception as error:
        checked_at = _now_iso()
        _write_state(state_path, {**state, "checked_at": checked_at, "error": str(error)})
        return ModelCheckResult(checked_at=checked_at, skipped=False, state_path=state_path, new_models=[], error=str(error))


def apply_model_candidates(
    candidates: list[ModelCandidate],
    *,
    openrouter_path: Path = OPENROUTER_MODELS_PATH,
    public_path: Path = PUBLIC_MODELS_PATH,
    hidden: bool = False,
) -> None:
    if not candidates:
        return
    route_data = _load_yaml(openrouter_path)
    routes = dict(route_data.get("models", {}))
    for candidate in reversed(candidates):
        routes.pop(candidate.id, None)
        routes = {candidate.id: candidate.openrouter_slug, **routes}
    route_data["models"] = routes
    _write_yaml(openrouter_path, route_data)

    public_data = _load_yaml(public_path)
    rows = list(public_data.get("models", []))
    rows_by_id = {str(row.get("id")): row for row in rows if isinstance(row, dict) and row.get("id")}
    additions = []
    changed = False
    for candidate in candidates:
        existing = rows_by_id.get(candidate.id)
        if existing is not None:
            if not hidden and existing.get("catalog_hidden"):
                existing.pop("catalog_hidden", None)
                changed = True
            continue
        additions.append(_public_row(candidate, hidden=hidden))
    if additions:
        public_data["models"] = additions + rows
        _write_yaml(public_path, public_data)
    elif changed:
        _write_yaml(public_path, public_data)


def _cached_result(state: dict[str, Any], *, state_path: Path, include_unregistered: bool) -> ModelCheckResult:
    return ModelCheckResult(
        checked_at=str(state.get("checked_at") or ""),
        skipped=True,
        state_path=state_path,
        new_models=[_candidate_from_dict(item) for item in state.get("new_models", []) if isinstance(item, dict)],
        all_models=[_candidate_from_dict(item) for item in state.get("catalog_models", []) if isinstance(item, dict)],
        unregistered_models=[
            _candidate_from_dict(item) for item in state.get("unregistered_models", []) if isinstance(item, dict)
        ]
        if include_unregistered
        else [],
        applied=False,
        error=state.get("error") if isinstance(state.get("error"), str) else None,
    )


def _state_is_fresh(state: dict[str, Any], interval_hours: int) -> bool:
    checked = _parse_iso(str(state.get("checked_at") or ""))
    if checked is None:
        return False
    return datetime.now(timezone.utc) - checked < timedelta(hours=max(1, interval_hours))


def _catalog_items(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    data = catalog.get("data", [])
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and _is_text_output_model(item)]


def _candidates_from_items(
    items: list[dict[str, Any]],
    *,
    openrouter_path: Path,
    public_path: Path,
) -> list[ModelCandidate]:
    existing_ids = _configured_model_ids(openrouter_path, public_path)
    existing_id_by_slug = _configured_openrouter_ids_by_slug(openrouter_path)
    used_ids = set(existing_ids)
    candidates = []
    for item in sorted(items, key=lambda value: int(value.get("created") or 0), reverse=True):
        slug = str(item.get("id") or "").strip()
        if not slug:
            continue
        model_id = existing_id_by_slug.get(slug) or _local_model_id(slug, used_ids)
        used_ids.add(model_id)
        candidates.append(
            ModelCandidate(
                id=model_id,
                display_name=_display_name(item),
                provider_family=_provider_family(slug),
                openrouter_slug=slug,
                tokenizer=_tokenizer_for_slug(slug),
                pricing=_pricing(item),
                context_length=_optional_int(item.get("context_length")),
                max_completion_tokens=_optional_int((item.get("top_provider") or {}).get("max_completion_tokens"))
                if isinstance(item.get("top_provider"), dict)
                else None,
                supported_parameters=[str(value) for value in item.get("supported_parameters", []) if value],
                created=_optional_int(item.get("created")),
            )
        )
    return candidates


def _public_row(candidate: ModelCandidate, *, hidden: bool = False) -> dict[str, Any]:
    row = {
        "id": candidate.id,
        "display_name": candidate.display_name,
        "provider_family": candidate.provider_family,
        "tokenizer": candidate.tokenizer,
        "pricing": candidate.pricing,
    }
    if hidden:
        row["catalog_hidden"] = True
    return row


def _configured_openrouter_slugs(path: Path) -> set[str]:
    data = _load_yaml(path)
    routes = data.get("models", {})
    if not isinstance(routes, dict):
        return set()
    return {str(value) for value in routes.values()}


def _configured_openrouter_ids_by_slug(path: Path) -> dict[str, str]:
    data = _load_yaml(path)
    routes = data.get("models", {})
    if not isinstance(routes, dict):
        return {}
    return {str(value): str(key) for key, value in routes.items()}


def _visible_openrouter_slugs(openrouter_path: Path, public_path: Path) -> set[str]:
    routes = _load_yaml(openrouter_path).get("models", {})
    if not isinstance(routes, dict):
        return set()
    public_rows = _load_yaml(public_path).get("models", [])
    visible_ids = {
        str(row.get("id"))
        for row in public_rows
        if isinstance(row, dict) and row.get("id") and not bool(row.get("catalog_hidden"))
    }
    return {str(slug) for model_id, slug in routes.items() if str(model_id) in visible_ids}


def _configured_model_ids(openrouter_path: Path, public_path: Path) -> set[str]:
    ids = set()
    routes = _load_yaml(openrouter_path).get("models", {})
    if isinstance(routes, dict):
        ids.update(str(key) for key in routes)
    rows = _load_yaml(public_path).get("models", [])
    if isinstance(rows, list):
        ids.update(str(row.get("id")) for row in rows if isinstance(row, dict) and row.get("id"))
    return ids


def _is_text_output_model(item: dict[str, Any]) -> bool:
    architecture = item.get("architecture", {})
    if not isinstance(architecture, dict):
        return True
    output_modalities = architecture.get("output_modalities")
    if isinstance(output_modalities, list):
        return "text" in {str(value).lower() for value in output_modalities}
    modality = str(architecture.get("modality") or "").lower()
    return not modality or "->text" in modality or modality.endswith("text")


def _local_model_id(slug: str, existing_ids: set[str]) -> str:
    provider, _, name = slug.partition("/")
    base = _slug_to_id(name or provider)
    if base and base not in existing_ids:
        return base
    provider_base = _slug_to_id(f"{provider}-{name}") if name else base
    if provider_base not in existing_ids:
        return provider_base
    index = 2
    while f"{provider_base}-{index}" in existing_ids:
        index += 1
    return f"{provider_base}-{index}"


def _slug_to_id(value: str) -> str:
    clean = value.lower().replace(".", "-").replace("_", "-").replace("/", "-")
    return "-".join(part for part in clean.split("-") if part)


def _display_name(item: dict[str, Any]) -> str:
    name = str(item.get("name") or item.get("id") or "").strip()
    if ":" in name:
        name = name.split(":", 1)[1].strip()
    return name or str(item.get("id"))


def _provider_family(slug: str) -> str:
    provider = slug.split("/", 1)[0].lower()
    return {
        "anthropic": "anthropic",
        "openai": "openai",
        "google": "google",
        "x-ai": "xai",
    }.get(provider, "openrouter")


def _tokenizer_for_slug(slug: str) -> str:
    family = _provider_family(slug)
    return {
        "anthropic": "anthropic_estimate_v1",
        "openai": "openai_estimate_v1",
        "google": "gemini_estimate_v1",
        "xai": "xai_estimate_v1",
    }.get(family, "manimbench_regex_estimator_v1")


def _pricing(item: dict[str, Any]) -> dict[str, Any]:
    pricing = item.get("pricing", {})
    if not isinstance(pricing, dict):
        pricing = {}
    row: dict[str, Any] = {"method": "configured_benchmark_estimate_rate"}
    input_rate = _per_million(pricing.get("prompt"))
    output_rate = _per_million(pricing.get("completion"))
    if input_rate is not None:
        row["input_usd_per_1m_tokens"] = input_rate
    if output_rate is not None:
        row["output_usd_per_1m_tokens"] = output_rate
    return row


def _per_million(value: Any) -> float | None:
    if value is None:
        return None
    try:
        rate = Decimal(str(value)) * Decimal("1000000")
    except (InvalidOperation, ValueError):
        return None
    return float(rate)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _candidate_from_dict(value: dict[str, Any]) -> ModelCandidate:
    return ModelCandidate(
        id=str(value.get("id") or ""),
        display_name=str(value.get("display_name") or value.get("id") or ""),
        provider_family=str(value.get("provider_family") or "openrouter"),
        openrouter_slug=str(value.get("openrouter_slug") or ""),
        tokenizer=str(value.get("tokenizer") or "manimbench_regex_estimator_v1"),
        pricing=dict(value.get("pricing") or {}),
        context_length=_optional_int(value.get("context_length")),
        max_completion_tokens=_optional_int(value.get("max_completion_tokens")),
        supported_parameters=[str(item) for item in value.get("supported_parameters", [])],
        created=_optional_int(value.get("created")),
    )


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
