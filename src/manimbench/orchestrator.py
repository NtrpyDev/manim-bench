from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from manimbench.model_registry import default_provider_for_model, load_model, load_models, model_map, openrouter_slug, provider_config, public_model_rows
from manimbench.models import ModelOutput
from manimbench.paths import (
    DEFAULT_ENGINE_STATE_DIR,
    DEFAULT_OUTPUTS_DIR,
    DEFAULT_PROMPT_PATH,
    DEFAULT_REPORTS_DIR,
    DEFAULT_RUNS_DIR,
    DEFAULT_SITE_REPO,
    DEFAULT_SUITE_PATH,
)
from manimbench.prompting import build_task_prompt, load_master_prompt
from manimbench.providers.anthropic import AnthropicProvider
from manimbench.providers.common import GenerationValidationError, HttpJsonClient, ProviderError, cleanup_generated_source, validate_main_scene
from manimbench.providers.cursor import CursorProvider
from manimbench.providers.file_provider import FileProvider
from manimbench.providers.google import GoogleProvider
from manimbench.providers.openai import OpenAIProvider
from manimbench.providers.openrouter import OpenRouterProvider
from manimbench.providers.xai import XAIProvider
from manimbench.reasoning import normalize_reasoning_effort
from manimbench.reporting import write_report
from manimbench.runtime import ManimCERuntime
from manimbench.sandbox import ContainerSandbox, LocalSandbox
from manimbench.scoring import SCORING_VERSION, result_payload, score_task, source_metadata_with_hash
from manimbench.tasks import filter_tasks, load_suite, suite_hashes
from manimbench.usage import count_tokens, estimate_cost as estimate_token_cost


ProviderFactory = Callable[[str], Any]
EventCallback = Callable[["PipelineEvent"], None]
_CANCEL_EVENT = threading.Event()


@dataclass(frozen=True)
class PipelineEvent:
    type: str
    message: str
    model: str | None = None
    task_id: str | None = None
    status: str | None = None
    progress: float | None = None
    cost_usd: float | None = None
    path: Path | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BalanceResult:
    provider: str = "openrouter"
    available: bool = False
    total_credits: float | None = None
    total_usage: float | None = None
    balance: float | None = None
    error: str | None = None
    checked_at: str = field(default_factory=lambda: _now_iso())


@dataclass(frozen=True)
class ModelCostEstimate:
    model: str
    display_name: str
    task_count: int
    input_tokens: int
    output_tokens: int
    estimated_usd: float
    pricing: dict[str, Any]


@dataclass(frozen=True)
class CostEstimate:
    currency: str
    task_count: int
    model_count: int
    input_tokens: int
    output_tokens: int
    estimated_usd: float
    unavailable_models: list[str] = field(default_factory=list)
    models: list[ModelCostEstimate] = field(default_factory=list)


@dataclass(frozen=True)
class DashboardModelRow:
    id: str
    display_name: str
    selected: bool
    default_provider: str
    provider_family: str
    openrouter_slug: str | None
    tokenizer: str | None
    pricing: dict[str, Any]
    context_window: int | None
    output_statuses: dict[str, str]
    status: str


@dataclass(frozen=True)
class ModelTaskDetail:
    task_id: str
    output_status: str
    render_status: str
    score: float | int | str | None
    cost_usd: float | None
    source_path: Path
    video_path: Path | None = None
    result_path: Path | None = None


@dataclass(frozen=True)
class ModelDetailState:
    model_id: str
    display_name: str
    default_provider: str
    openrouter_slug: str | None
    usage_path: Path | None
    tasks: list[ModelTaskDetail]


@dataclass(frozen=True)
class VideoPreviewRow:
    model: str
    task_id: str
    score: float | int | str | None
    duration: str | None
    video_path: Path
    result_path: Path | None = None


@dataclass(frozen=True)
class VideoPreviewState:
    run_id: str | None
    run_dir: Path | None
    rows: list[VideoPreviewRow]


@dataclass(frozen=True)
class PublishSummary:
    run_id: str | None
    run_dir: Path | None
    status: str
    suite_id: str | None = None
    suite_version: str | None = None
    suite_title: str | None = None
    task_count: int = 0
    model_count: int = 0
    models: list[str] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    missing: int = 0
    cost_usd: float | None = None
    estimated_usd: float | None = None
    docker_digest: str | None = None

    @property
    def complete(self) -> bool:
        return self.status == "complete" and self.missing == 0 and self.failed == 0

    @property
    def partial(self) -> bool:
        return bool(self.failed or self.missing or self.status in {"failed", "missing", "pending", "generated"})


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    run_dir: Path | None
    state_path: Path | None
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    models: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    missing: int = 0
    cost_usd: float | None = None


@dataclass(frozen=True)
class DashboardState:
    suite_id: str
    suite_version: str
    suite_title: str
    task_ids: list[str]
    models: list[DashboardModelRow]
    selected_models: list[str]
    filters: dict[str, str]
    search: str
    balance: BalanceResult
    estimate: CostEstimate
    spent_usd: float | None
    current_run: RunSummary | None
    output_dir: Path
    runs_dir: Path
    site_repo: Path


@dataclass(frozen=True)
class PipelineRequest:
    models: list[str]
    mode: str = "full"
    suite_path: Path = DEFAULT_SUITE_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    task_ids: list[str] | None = None
    output_dir: Path = DEFAULT_OUTPUTS_DIR
    provider: str = "auto"
    force: bool = False
    resume: bool = True
    parallel: int = 1
    runs_dir: Path = DEFAULT_RUNS_DIR
    run_id: str | None = None
    sandbox: str = "container"
    timeout_seconds: int = 180
    container_image: str = "manimbench-manimce:latest"
    manim_executable: str = "python"
    allow_stale: bool = False
    report_output_dir: Path | None = None
    reasoning_effort: str | None = None
    provider_factory: ProviderFactory | None = None
    event_callback: EventCallback | None = None


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    mode: str
    generation: "GenerateResult | None" = None
    render: "RenderMatrixResult | None" = None
    report: "ReportResult | None" = None
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        if self.cancelled:
            return False
        return all(result is None or result.ok for result in [self.generation, self.render])


@dataclass(frozen=True)
class RetryFailedRequest:
    previous_run_dir: Path
    models: list[str] | None = None
    suite_path: Path = DEFAULT_SUITE_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    output_dir: Path = DEFAULT_OUTPUTS_DIR
    runs_dir: Path = DEFAULT_RUNS_DIR
    run_id: str | None = None
    sandbox: str = "container"
    timeout_seconds: int = 180
    container_image: str = "manimbench-manimce:latest"
    manim_executable: str = "python"
    allow_stale: bool = False
    parallel: int = 1
    event_callback: EventCallback | None = None


@dataclass(frozen=True)
class GenerateRequest:
    model: str
    suite_path: Path = DEFAULT_SUITE_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    task_ids: list[str] | None = None
    output_dir: Path = DEFAULT_OUTPUTS_DIR
    provider: str = "auto"
    force: bool = False
    smoke: bool = False
    parallel: int = 1
    run_id: str | None = None
    reasoning_effort: str | None = None
    provider_factory: ProviderFactory | None = None
    event_callback: EventCallback | None = None
    clear_cancel: bool = True


@dataclass(frozen=True)
class GenerateBatchRequest:
    models: list[str]
    suite_path: Path = DEFAULT_SUITE_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    task_ids: list[str] | None = None
    output_dir: Path = DEFAULT_OUTPUTS_DIR
    provider: str = "auto"
    force: bool = False
    smoke: bool = False
    dry_run: bool = False
    parallel: int = 1
    run_id: str | None = None
    reasoning_effort: str | None = None
    provider_factory: ProviderFactory | None = None
    event_callback: EventCallback | None = None
    clear_cancel: bool = True


@dataclass(frozen=True)
class RenderInput:
    model: str
    outputs_dir: Path


@dataclass(frozen=True)
class RenderMatrixRequest:
    model_outputs: list[RenderInput]
    suite_path: Path = DEFAULT_SUITE_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    task_ids: list[str] | None = None
    sandbox: str = "container"
    runs_dir: Path = DEFAULT_RUNS_DIR
    run_id: str | None = None
    timeout_seconds: int = 180
    container_image: str = "manimbench-manimce:latest"
    manim_executable: str = "python"
    allow_stale: bool = False
    force: bool = False
    resume: bool = False
    parallel: int = 1
    provider_route: str = "file"
    model_task_ids: dict[str, list[str]] | None = None
    event_callback: EventCallback | None = None
    clear_cancel: bool = True


@dataclass(frozen=True)
class ReportRequest:
    run_dir: Path
    output_dir: Path | None = None


@dataclass(frozen=True)
class PublishRequest:
    run_dir: Path
    target: str
    site_repo: Path = DEFAULT_SITE_REPO
    allow_partial: bool = False
    draft_branch: str = "draft"
    live_branch: str = "main"


@dataclass
class GenerateResult:
    run_id: str
    state_path: Path
    api_log_path: Path
    output_dir: Path
    generated: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    dry_run: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


@dataclass
class RenderMatrixResult:
    run_id: str
    run_dir: Path
    failures: int
    result_paths: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failures == 0


@dataclass(frozen=True)
class ReportResult:
    index_path: Path
    output_dir: Path


@dataclass(frozen=True)
class PublishResult:
    target: str
    branch: str
    site_repo: Path
    commit: str | None
    pushed: bool
    bundle_files: list[Path]


def list_models(public: bool = True) -> list[dict[str, Any]]:
    return public_model_rows(public_only=public)


def fetch_openrouter_catalog(*, api_key: str | None = None, client: Any | None = None) -> dict[str, Any]:
    return OpenRouterProvider.fetch_model_metadata(api_key=api_key, client=client)


def fetch_balance(
    *,
    api_key: str | None = None,
    client: Any | None = None,
    base_url: str | None = None,
    timeout_seconds: int = 30,
) -> BalanceResult:
    """Fetch OpenRouter credit status without letting UI callers crash on setup/network issues."""

    try:
        config = provider_config("openrouter")
        env_key = str(config.get("env_key", "OPENROUTER_API_KEY"))
        key = api_key if api_key is not None else os.getenv(env_key)
        if not key:
            return BalanceResult(error=f"{env_key} is not set")
        key = key.strip()
        if key.startswith("crsr_"):
            return BalanceResult(error=f"{env_key} looks like a Cursor key, not an OpenRouter key")
        http = client or HttpJsonClient()
        base = (base_url or str(config.get("base_url", "https://openrouter.ai/api/v1"))).rstrip("/")
        headers = {"Authorization": f"Bearer {key}"}
        endpoint = f"{base}/key"
        payload = http.get_json(endpoint, headers=headers, timeout=timeout_seconds)
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise ProviderError("OpenRouter key response did not include an object")
        usage = _optional_float(data.get("usage"))
        balance = _optional_float(data.get("limit_remaining"))
        limit = _optional_float(data.get("limit"))
        total_credits = limit
        if total_credits is None:
            total_credits = _optional_float(data.get("total_credits"))
        total_usage = usage if usage is not None else _optional_float(data.get("total_usage"))
        if balance is None and total_credits is not None and total_usage is not None:
            balance = round(total_credits - total_usage, 8)
        if balance is None:
            try:
                account = _parse_openrouter_credits_payload(http.get_json(f"{base}/credits", headers=headers, timeout=timeout_seconds))
                if account:
                    total_credits = account.get("total_credits") if account.get("total_credits") is not None else total_credits
                    total_usage = account.get("total_usage") if account.get("total_usage") is not None else total_usage
                    balance = account.get("balance") if account.get("balance") is not None else balance
            except Exception:
                pass
        return BalanceResult(
            available=True,
            total_credits=total_credits,
            total_usage=total_usage,
            balance=balance,
        )
    except Exception as error:
        return BalanceResult(error=str(error))


def estimate_cost(
    selected_models: list[str],
    suite_path: Path = DEFAULT_SUITE_PATH,
    output_token_estimate_per_task: int = 2000,
    *,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    task_ids: list[str] | None = None,
) -> CostEstimate:
    suite = load_suite(suite_path)
    master_prompt = load_master_prompt(prompt_path)
    tasks = filter_tasks(suite, task_ids)
    task_prompts = [build_task_prompt(master_prompt, task) for task in tasks]
    output_tokens = max(0, int(output_token_estimate_per_task)) * len(tasks)

    rows: list[ModelCostEstimate] = []
    unavailable: list[str] = []
    total_input = 0
    total_output = 0
    total_cost = 0.0
    models_by_id = model_map(public_only=False)
    prompt_tokens_by_tokenizer: dict[str | None, int] = {}
    for model_id in selected_models:
        try:
            model = models_by_id[model_id]
            if model.tokenizer not in prompt_tokens_by_tokenizer:
                prompt_tokens_by_tokenizer[model.tokenizer] = sum(count_tokens(prompt, model.tokenizer) for prompt in task_prompts)
            prompt_tokens = prompt_tokens_by_tokenizer[model.tokenizer]
            cost = estimate_token_cost(prompt_tokens, output_tokens, model.pricing)
            estimated_usd = float(cost["estimated_usd"])
            rows.append(
                ModelCostEstimate(
                    model=model.id,
                    display_name=model.display_name,
                    task_count=len(tasks),
                    input_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    estimated_usd=estimated_usd,
                    pricing=model.pricing,
                )
            )
            total_input += prompt_tokens
            total_output += output_tokens
            total_cost += estimated_usd
        except Exception:
            unavailable.append(model_id)

    return CostEstimate(
        currency="USD",
        task_count=len(tasks),
        model_count=len(selected_models),
        input_tokens=total_input,
        output_tokens=total_output,
        estimated_usd=round(total_cost, 6),
        unavailable_models=unavailable,
        models=rows,
    )


def get_dashboard_state(
    *,
    selected_models: list[str] | None = None,
    suite_path: Path = DEFAULT_SUITE_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    output_dir: Path = DEFAULT_OUTPUTS_DIR,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    site_repo: Path = DEFAULT_SITE_REPO,
    provider_filter: str = "all",
    status_filter: str = "all",
    context_filter: str = "all",
    price_filter: str = "all",
    search: str = "",
    last_run_id: str | None = None,
    include_balance: bool = True,
    balance: BalanceResult | None = None,
    catalog: dict[str, Any] | None = None,
) -> DashboardState:
    suite = load_suite(suite_path)
    selected = selected_models if selected_models is not None else [model.id for model in load_models(public_only=True) if model.default_enabled]
    selected_set = set(selected)
    balance_result = balance if balance is not None else fetch_balance() if include_balance else BalanceResult(error="not requested")
    estimate = estimate_cost(selected, suite_path=suite_path, prompt_path=prompt_path)
    rows: list[DashboardModelRow] = []
    search_lc = search.strip().lower()
    catalog_by_slug = _catalog_by_slug(catalog)
    master_prompt = load_master_prompt(prompt_path)
    task_prompts = [(task.id, build_task_prompt(master_prompt, task)) for task in suite.tasks]
    visible_models = load_models(public_only=True)
    for model in visible_models:
        default_provider = default_provider_for_model(model.id)
        catalog_item = catalog_by_slug.get(model.openrouter_slug or "")
        pricing = _pricing_from_catalog_item(catalog_item) or model.pricing
        context_window = _context_window_from_catalog_item(catalog_item) or _context_window(model.raw)
        statuses = _get_output_status_for_prompts(model.id, task_prompts, output_dir=output_dir)
        status = _summarize_output_status(statuses)
        if provider_filter not in {"", "all"} and provider_filter != default_provider and provider_filter != model.provider_family:
            continue
        if status_filter not in {"", "all"} and status_filter != status:
            continue
        if not _matches_context_filter(context_window, context_filter):
            continue
        if not _matches_price_filter(pricing, price_filter):
            continue
        haystack = " ".join([model.id, model.display_name, default_provider, model.provider_family, model.openrouter_slug or ""]).lower()
        if search_lc and search_lc not in haystack:
            continue
        rows.append(
            DashboardModelRow(
                id=model.id,
                display_name=model.display_name,
                selected=model.id in selected_set,
                default_provider=default_provider,
                provider_family=model.provider_family,
                openrouter_slug=model.openrouter_slug,
                tokenizer=model.tokenizer,
                pricing=pricing,
                context_window=context_window,
                output_statuses=statuses,
                status=status,
            )
        )
    current_run = get_run_summary(last_run_id, runs_dir=runs_dir) if last_run_id else _latest_run_summary(runs_dir)
    return DashboardState(
        suite_id=suite.id,
        suite_version=suite.version,
        suite_title=suite.title,
        task_ids=[task.id for task in suite.tasks],
        models=rows,
        selected_models=selected,
        filters={"provider": provider_filter, "status": status_filter, "context": context_filter, "price": price_filter},
        search=search,
        balance=balance_result,
        estimate=estimate,
        spent_usd=_spent_from_selected_outputs(selected, output_dir),
        current_run=current_run,
        output_dir=output_dir,
        runs_dir=runs_dir,
        site_repo=site_repo,
    )


def get_output_status(
    model: str,
    *,
    suite_path: Path = DEFAULT_SUITE_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    output_dir: Path = DEFAULT_OUTPUTS_DIR,
    state_path: Path | None = None,
) -> dict[str, str]:
    suite = load_suite(suite_path)
    master_prompt = load_master_prompt(prompt_path)
    state = {}
    if state_path and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    return _get_output_status_for_prompts(
        model,
        [(task.id, build_task_prompt(master_prompt, task)) for task in suite.tasks],
        output_dir=output_dir,
        state=state,
    )


def _get_output_status_for_prompts(
    model: str,
    task_prompts: list[tuple[str, str]],
    *,
    output_dir: Path,
    state: dict[str, Any] | None = None,
) -> dict[str, str]:
    state = state or {}
    return {
        task_id: generation_status(output_dir / model / f"{task_id}.py", prompt, state, model, task_id)
        for task_id, prompt in task_prompts
    }


def run_smoke(request: GenerateBatchRequest) -> GenerateResult:
    return generate_batch(replace(request, smoke=True))


def run_batch(request: GenerateBatchRequest) -> GenerateResult:
    return generate_batch(request)


def generate(request: GenerateRequest) -> GenerateResult:
    batch = GenerateBatchRequest(
        models=[request.model],
        suite_path=request.suite_path,
        prompt_path=request.prompt_path,
        task_ids=request.task_ids,
        output_dir=request.output_dir,
        provider=request.provider,
        force=request.force,
        smoke=request.smoke,
        dry_run=False,
        parallel=request.parallel,
        run_id=request.run_id,
        reasoning_effort=request.reasoning_effort,
        provider_factory=request.provider_factory,
        event_callback=request.event_callback,
        clear_cancel=request.clear_cancel,
    )
    return generate_batch(batch)


def generate_batch(request: GenerateBatchRequest) -> GenerateResult:
    if request.clear_cancel:
        _CANCEL_EVENT.clear()
    _emit_event(request.event_callback, PipelineEvent("generation_started", "Generation started", data={"models": request.models}))
    suite = load_suite(request.suite_path)
    master_prompt = load_master_prompt(request.prompt_path)
    tasks = filter_tasks(suite, request.task_ids)
    run_id = request.run_id or _new_run_id("generation")
    state_dir = DEFAULT_ENGINE_STATE_DIR / run_id
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "state.json"
    api_log_path = state_dir / "generation.log"
    state = _load_state(state_path, run_id, request)
    result = GenerateResult(run_id=run_id, state_path=state_path, api_log_path=api_log_path, output_dir=request.output_dir)

    work: list[tuple[str, Any, str, Path, str]] = []
    for model in request.models:
        provider_name = _resolve_provider_name(request.provider, model)
        for task in tasks:
            prompt = build_task_prompt(master_prompt, task)
            output_path = request.output_dir / model / f"{task.id}.py"
            status = generation_status(output_path, prompt, state, model, task.id)
            if request.dry_run:
                result.dry_run.append(
                    {
                        "model": model,
                        "task_id": task.id,
                        "status": status,
                        "path": str(output_path),
                        "provider": provider_name,
                    }
                )
                continue
            if status == "complete" and not request.force:
                result.skipped.append(output_path)
                _record_generation_state(state, model, task.id, status="complete", output_path=output_path, prompt=prompt)
                _emit_event(
                    request.event_callback,
                    PipelineEvent(
                        "status",
                        f"Skipped complete output {model}/{task.id}",
                        model=model,
                        task_id=task.id,
                        status="skipped",
                        path=output_path,
                    ),
                )
                continue
            work.append((model, task, prompt, output_path, provider_name))

    if request.dry_run:
        _write_state(state_path, state)
        _emit_event(request.event_callback, PipelineEvent("generation_finished", "Generation dry run finished", data={"dry_run": result.dry_run}))
        return result

    if request.smoke and work:
        model, task, prompt, output_path, provider_name = work[0]
        smoke_outcome = _generate_one(
            model=model,
            task=task,
            prompt=prompt,
            output_path=output_path,
            provider_name=provider_name,
            provider_factory=request.provider_factory,
            force=True,
            smoke=True,
            reasoning_effort=request.reasoning_effort,
            event_callback=request.event_callback,
        )
        state["smoke"] = smoke_outcome.state_entry
        _append_api_log(api_log_path, smoke_outcome.api_log)
        if smoke_outcome.error:
            result.failed.append(smoke_outcome.error)
            _write_state(state_path, state)
            return result
        _record_state_entry(state, smoke_outcome.state_entry)
        if smoke_outcome.output_path:
            result.generated.append(smoke_outcome.output_path)
        work = []

    max_workers = max(1, int(request.parallel))
    total = len(work)
    completed = 0
    model_totals: dict[str, int] = {}
    for model, _task, _prompt, _output_path, _provider_name in work:
        model_totals[model] = model_totals.get(model, 0) + 1
    model_completed: dict[str, int] = {model: 0 for model in model_totals}
    work_iter = iter(work)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        def submit_next() -> None:
            if _CANCEL_EVENT.is_set():
                return
            try:
                model, task, prompt, output_path, provider_name = next(work_iter)
            except StopIteration:
                return
            futures[
                executor.submit(
                    _generate_one,
                    model=model,
                    task=task,
                    prompt=prompt,
                    output_path=output_path,
                    provider_name=provider_name,
                    provider_factory=request.provider_factory,
                    force=request.force,
                    smoke=False,
                    reasoning_effort=request.reasoning_effort,
                    event_callback=request.event_callback,
                )
            ] = (model, task.id)

        for _ in range(max_workers):
            submit_next()

        while futures:
            future = next(as_completed(list(futures)))
            model, _task_id = futures.pop(future, (None, None))
            outcome = future.result()
            completed += 1
            _record_state_entry(state, outcome.state_entry)
            _append_api_log(api_log_path, outcome.api_log)
            if model:
                model_completed[model] = model_completed.get(model, 0) + 1
                _emit_event(
                    request.event_callback,
                    PipelineEvent(
                        "model_progress",
                        f"{model}: generated {model_completed[model]}/{model_totals.get(model, 0)}",
                        model=model,
                        data={"completed": model_completed[model], "total": model_totals.get(model, 0)},
                    ),
                )
            if outcome.error:
                result.failed.append(outcome.error)
            elif outcome.output_path:
                result.generated.append(outcome.output_path)
            _emit_event(
                request.event_callback,
                PipelineEvent(
                    "progress",
                    f"Generated {completed}/{total}",
                    progress=(completed / total) if total else 1.0,
                    data={"completed": completed, "total": total},
                ),
            )
            submit_next()

    _write_state(state_path, state)
    _write_generation_usage(request.output_dir, state)
    if _CANCEL_EVENT.is_set():
        _emit_event(
            request.event_callback,
            PipelineEvent(
                "generation_cancelled",
                "Generation cancelled at a safe boundary",
                status="cancelled",
                progress=(completed / total) if total else 1.0,
                data={"completed": completed, "total": total},
            ),
        )
    _emit_event(
        request.event_callback,
        PipelineEvent(
            "generation_finished",
            "Generation cancelled" if _CANCEL_EVENT.is_set() else "Generation finished" if result.ok else "Generation finished with failures",
            status="cancelled" if _CANCEL_EVENT.is_set() else "complete" if result.ok else "failed",
            data={"generated": [str(path) for path in result.generated], "failed": result.failed, "skipped": [str(path) for path in result.skipped]},
        ),
    )
    return result


def generation_status(output_path: Path, prompt: str, state: dict[str, Any], model: str, task_id: str) -> str:
    if not output_path.exists():
        return "-"
    source = output_path.read_text(encoding="utf-8", errors="replace")
    try:
        validate_main_scene(source)
    except GenerationValidationError:
        return "partial"
    entry = state.get("generations", {}).get(model, {}).get(task_id, {})
    if not entry:
        return "complete"
    if (
        entry.get("status") == "complete"
        and entry.get("prompt_sha256") == _sha256_text(prompt)
        and entry.get("source_sha256") == _sha256_text(source)
    ):
        return "complete"
    return "stale"


def list_run_history(
    *,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    engine_state_dir: Path = DEFAULT_ENGINE_STATE_DIR,
    limit: int = 50,
) -> list[RunSummary]:
    summaries: dict[str, RunSummary] = {}
    if runs_dir.exists():
        for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True):
            summary = _summarize_run_dir(run_dir)
            summaries[summary.run_id] = summary
    if engine_state_dir.exists():
        for state_path in sorted(engine_state_dir.glob("*/state.json"), key=lambda path: path.stat().st_mtime, reverse=True):
            summary = _summarize_generation_state(state_path)
            if summary.run_id in summaries:
                existing = summaries[summary.run_id]
                summaries[summary.run_id] = RunSummary(
                    run_id=existing.run_id,
                    run_dir=existing.run_dir,
                    state_path=state_path,
                    status=existing.status if existing.status != "missing" else summary.status,
                    created_at=existing.created_at or summary.created_at,
                    updated_at=max(filter(None, [existing.updated_at, summary.updated_at]), default=None),
                    models=existing.models or summary.models,
                    task_ids=existing.task_ids or summary.task_ids,
                    passed=existing.passed,
                    failed=existing.failed or summary.failed,
                    missing=existing.missing,
                    cost_usd=existing.cost_usd if existing.cost_usd is not None else summary.cost_usd,
                )
            else:
                summaries[summary.run_id] = summary
    return sorted(summaries.values(), key=lambda item: item.updated_at or item.created_at or "", reverse=True)[:limit]


def get_run_summary(
    run_id_or_path: str | Path,
    *,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    engine_state_dir: Path = DEFAULT_ENGINE_STATE_DIR,
) -> RunSummary | None:
    value = Path(run_id_or_path)
    if value.exists() and value.is_dir():
        return _summarize_run_dir(value)
    run_id = str(run_id_or_path)
    run_dir = runs_dir / run_id
    state_path = engine_state_dir / run_id / "state.json"
    if run_dir.exists():
        summary = _summarize_run_dir(run_dir)
        if state_path.exists():
            state_summary = _summarize_generation_state(state_path)
            return RunSummary(
                run_id=summary.run_id,
                run_dir=summary.run_dir,
                state_path=state_path,
                status=summary.status,
                created_at=summary.created_at or state_summary.created_at,
                updated_at=max(filter(None, [summary.updated_at, state_summary.updated_at]), default=None),
                models=summary.models or state_summary.models,
                task_ids=summary.task_ids or state_summary.task_ids,
                passed=summary.passed,
                failed=summary.failed or state_summary.failed,
                missing=summary.missing,
                cost_usd=summary.cost_usd if summary.cost_usd is not None else state_summary.cost_usd,
            )
        return summary
    if state_path.exists():
        return _summarize_generation_state(state_path)
    return None


def get_model_detail_state(
    model_id: str,
    *,
    run_id: str | None = None,
    suite_path: Path = DEFAULT_SUITE_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    output_dir: Path = DEFAULT_OUTPUTS_DIR,
    runs_dir: Path = DEFAULT_RUNS_DIR,
) -> ModelDetailState:
    try:
        model = load_model(model_id)
        display_name = model.display_name
        slug = model.openrouter_slug
    except KeyError:
        display_name = model_id
        slug = None
    suite = load_suite(suite_path)
    statuses = get_output_status(model_id, suite_path=suite_path, prompt_path=prompt_path, output_dir=output_dir)
    result_by_task: dict[str, tuple[Path, dict[str, Any]]] = {}
    if run_id:
        run_dir = runs_dir / run_id
        for result_path in sorted(run_dir.glob(f"{model_id}/*/result.json")):
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            task_id = str(payload.get("task", {}).get("id", ""))
            if task_id:
                result_by_task[task_id] = (result_path, payload)
    tasks: list[ModelTaskDetail] = []
    for task in suite.tasks:
        result_path, payload = result_by_task.get(task.id, (None, {}))  # type: ignore[assignment]
        score = payload.get("score", {}) if isinstance(payload.get("score"), dict) else {}
        metadata = payload.get("source_metadata", {}) if isinstance(payload.get("source_metadata"), dict) else {}
        if score:
            render_status = "pass" if score.get("passed") else "fail"
            score_value: float | int | str | None = score.get("automated_score")
        else:
            render_status = "-"
            score_value = "-"
        tasks.append(
            ModelTaskDetail(
                task_id=task.id,
                output_status=statuses.get(task.id, "-"),
                render_status=render_status,
                score=score_value,
                cost_usd=_optional_float(metadata.get("cost_usd")),
                source_path=output_dir / model_id / f"{task.id}.py",
                video_path=_media_path_from_result_payload(payload),
                result_path=result_path,
            )
        )
    usage_path = output_dir / model_id / "usage.json"
    return ModelDetailState(
        model_id=model_id,
        display_name=display_name,
        default_provider=_resolve_provider_name("auto", model_id),
        openrouter_slug=slug,
        usage_path=usage_path if usage_path.exists() else None,
        tasks=tasks,
    )


def get_video_preview_state(
    run_id: str | None,
    *,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    model_id: str | None = None,
) -> VideoPreviewState:
    if not run_id:
        return VideoPreviewState(run_id=None, run_dir=None, rows=[])
    run_dir = runs_dir / run_id
    rows: list[VideoPreviewRow] = []
    for result_path in sorted(run_dir.glob("*/*/result.json")):
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        model = str(payload.get("model", ""))
        if model_id and model != model_id:
            continue
        video_path = _media_path_from_result_payload(payload)
        if not video_path:
            continue
        score = payload.get("score", {}) if isinstance(payload.get("score"), dict) else {}
        rows.append(
            VideoPreviewRow(
                model=model,
                task_id=str(payload.get("task", {}).get("id", "")),
                score=score.get("automated_score", "-"),
                duration=_duration_from_result_payload(payload),
                video_path=video_path,
                result_path=result_path,
            )
        )
    if not rows:
        for path in sorted(run_dir.glob("*/*/media/videos/**/*.mp4")):
            parts = path.relative_to(run_dir).parts
            model = parts[0] if len(parts) > 0 else ""
            if model_id and model != model_id:
                continue
            rows.append(
                VideoPreviewRow(
                    model=model,
                    task_id=parts[1] if len(parts) > 1 else "",
                    score="-",
                    duration="-",
                    video_path=path,
                )
            )
    return VideoPreviewState(run_id=run_id, run_dir=run_dir if run_dir.exists() else None, rows=rows)


def get_publish_summary(run_id_or_path: str | Path | None, *, runs_dir: Path = DEFAULT_RUNS_DIR) -> PublishSummary:
    if not run_id_or_path:
        return PublishSummary(run_id=None, run_dir=None, status="missing")
    run_dir = Path(run_id_or_path)
    if not run_dir.exists():
        run_dir = runs_dir / str(run_id_or_path)
    summary = get_run_summary(run_dir) if run_dir.exists() else get_run_summary(str(run_id_or_path), runs_dir=runs_dir)
    manifest_path = run_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    suite_data = manifest.get("suite", {}) if isinstance(manifest.get("suite"), dict) else {}
    sandbox_data = manifest.get("sandbox", {}) if isinstance(manifest.get("sandbox"), dict) else {}
    estimate = None
    models = [str(model) for model in manifest.get("models", [])] if manifest else (summary.models if summary else [])
    if models:
        try:
            estimate = estimate_cost(models, task_ids=[str(task_id) for task_id in suite_data.get("task_ids", [])] or None).estimated_usd
        except Exception:
            estimate = None
    return PublishSummary(
        run_id=(summary.run_id if summary else str(run_id_or_path)),
        run_dir=run_dir if run_dir.exists() else None,
        status=summary.status if summary else "missing",
        suite_id=str(suite_data.get("id")) if suite_data.get("id") else None,
        suite_version=str(suite_data.get("version")) if suite_data.get("version") else None,
        suite_title=str(suite_data.get("title")) if suite_data.get("title") else None,
        task_count=int(suite_data.get("task_count") or len(suite_data.get("task_ids", []) or [])),
        model_count=len(models),
        models=models,
        passed=summary.passed if summary else 0,
        failed=summary.failed if summary else 0,
        missing=summary.missing if summary else 0,
        cost_usd=summary.cost_usd if summary else None,
        estimated_usd=estimate,
        docker_digest=str(sandbox_data.get("docker_image_digest")) if sandbox_data.get("docker_image_digest") else None,
    )


def render_matrix(request: RenderMatrixRequest) -> RenderMatrixResult:
    if request.clear_cancel:
        _CANCEL_EVENT.clear()
    _emit_event(
        request.event_callback,
        PipelineEvent(
            "render_started",
            "Render started",
            data={"models": [item.model for item in request.model_outputs]},
        ),
    )
    suite = load_suite(request.suite_path)
    master_prompt = load_master_prompt(request.prompt_path)
    if request.model_task_ids:
        manifest_task_ids = sorted({task_id for task_ids in request.model_task_ids.values() for task_id in task_ids})
        manifest_tasks = filter_tasks(suite, manifest_task_ids)
    else:
        manifest_tasks = filter_tasks(suite, request.task_ids)
    sandbox = _make_sandbox(request)
    runtime = ManimCERuntime(executable=request.manim_executable)
    run_id = request.run_id or _new_run_id("render")
    run_dir = request.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        if not request.resume:
            raise FileExistsError(f"Refusing to overwrite immutable manifest: {manifest_path}")
    else:
        _write_manifest(
            run_dir=run_dir,
            run_id=run_id,
            suite=suite,
            tasks=manifest_tasks,
            prompt_path=request.prompt_path,
            sandbox=sandbox,
            runtime=runtime,
            models=[item.model for item in request.model_outputs],
            provider_route=request.provider_route,
        )

    jobs = []
    failures = 0
    result_paths: list[Path] = []
    for item in request.model_outputs:
        provider = FileProvider(item.outputs_dir, item.model, allow_stale=request.allow_stale)
        item_task_ids = request.model_task_ids.get(item.model) if request.model_task_ids else request.task_ids
        for task in filter_tasks(suite, item_task_ids):
            result_path = run_dir / item.model / task.id / "result.json"
            if request.resume and not request.force and result_path.exists():
                result_paths.append(result_path)
                if _result_path_failed(result_path):
                    failures += 1
                _emit_event(
                    request.event_callback,
                    PipelineEvent(
                        "status",
                        f"Skipped rendered result {item.model}/{task.id}",
                        model=item.model,
                        task_id=task.id,
                        status="skipped",
                        path=result_path,
                    ),
                )
                continue
            jobs.append((item.model, provider, task, build_task_prompt(master_prompt, task)))

    max_workers = max(1, int(request.parallel))
    total = len(jobs)
    completed = 0
    job_iter = iter(jobs)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        def submit_next() -> None:
            if _CANCEL_EVENT.is_set():
                return
            try:
                model, provider, task, task_prompt = next(job_iter)
            except StopIteration:
                return
            futures[
                executor.submit(
                    _render_provider_task,
                    run_dir,
                    suite,
                    task,
                    model,
                    provider,
                    task_prompt,
                    sandbox,
                    runtime,
                    request.timeout_seconds,
                    request.event_callback,
                )
            ] = (model, task.id)

        for _ in range(max_workers):
            submit_next()

        while futures:
            future = next(as_completed(list(futures)))
            futures.pop(future, None)
            task_path, passed, error = future.result()
            completed += 1
            result_paths.append(task_path / "result.json")
            if error:
                print(error, file=sys.stderr)
                failures += 1
            elif not passed:
                failures += 1
            _emit_event(
                request.event_callback,
                PipelineEvent(
                    "progress",
                    f"Rendered {completed}/{total}",
                    progress=(completed / total) if total else 1.0,
                    data={"completed": completed, "total": total},
                ),
            )
            submit_next()
    if _CANCEL_EVENT.is_set():
        _emit_event(
            request.event_callback,
            PipelineEvent(
                "render_cancelled",
                "Render cancelled at a safe boundary",
                status="cancelled",
                progress=(completed / total) if total else 1.0,
                data={"completed": completed, "total": total},
            ),
        )
    _emit_event(
        request.event_callback,
        PipelineEvent(
            "render_finished",
            "Render cancelled" if _CANCEL_EVENT.is_set() else "Render finished" if failures == 0 else "Render finished with failures",
            status="cancelled" if _CANCEL_EVENT.is_set() else "complete" if failures == 0 else "failed",
            data={"failures": failures, "result_paths": [str(path) for path in sorted(result_paths)]},
        ),
    )
    return RenderMatrixResult(run_id=run_id, run_dir=run_dir, failures=failures, result_paths=sorted(result_paths))


def render_one_file(
    *,
    solution_path: Path,
    task_id: str,
    model: str,
    suite_path: Path = DEFAULT_SUITE_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    sandbox_name: str = "local",
    runs_dir: Path = DEFAULT_RUNS_DIR,
    run_id: str | None = None,
    timeout_seconds: int = 180,
    container_image: str = "manimbench-manimce:latest",
    manim_executable: str = "python",
) -> RenderMatrixResult:
    suite = load_suite(suite_path)
    master_prompt = load_master_prompt(prompt_path)
    task = filter_tasks(suite, [task_id])[0]
    request = RenderMatrixRequest(
        model_outputs=[],
        suite_path=suite_path,
        prompt_path=prompt_path,
        sandbox=sandbox_name,
        runs_dir=runs_dir,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        container_image=container_image,
        manim_executable=manim_executable,
    )
    sandbox = _make_sandbox(request)
    runtime = ManimCERuntime(executable=manim_executable)
    run_id = run_id or _new_run_id("render")
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(run_dir, run_id, suite, [task], prompt_path, sandbox, runtime, [model], provider_route="manual")
    source = solution_path.read_text(encoding="utf-8")
    score = run_one_task(
        run_dir=run_dir,
        suite=suite,
        task=task,
        model=model,
        source=source,
        source_metadata={"provider": "manual", "source_path": str(solution_path)},
        task_prompt=build_task_prompt(master_prompt, task),
        sandbox=sandbox,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
    )
    return RenderMatrixResult(run_id=run_id, run_dir=run_dir, failures=0 if score.passed else 1, result_paths=[run_dir / model / task.id / "result.json"])


def report(request: ReportRequest) -> ReportResult:
    output_dir = request.output_dir or (DEFAULT_REPORTS_DIR / request.run_dir.name)
    index = write_report(request.run_dir, output_dir)
    return ReportResult(index_path=index, output_dir=output_dir)


def run_pipeline(request: PipelineRequest) -> PipelineResult:
    if request.mode not in {"smoke", "generate", "full"}:
        raise ValueError("Pipeline mode must be smoke, generate, or full")
    _CANCEL_EVENT.clear()
    run_id = request.run_id or _new_run_id(request.mode)
    _emit_event(request.event_callback, PipelineEvent("pipeline_started", f"{request.mode} pipeline started", data={"run_id": run_id}))
    if _CANCEL_EVENT.is_set():
        return PipelineResult(run_id=run_id, mode=request.mode, cancelled=True)

    generation = generate_batch(
        GenerateBatchRequest(
            models=request.models,
            suite_path=request.suite_path,
            prompt_path=request.prompt_path,
            task_ids=request.task_ids,
            output_dir=request.output_dir,
            provider=request.provider,
            force=request.force,
            smoke=request.mode == "smoke",
            dry_run=False,
            parallel=request.parallel,
            run_id=run_id,
            reasoning_effort=request.reasoning_effort,
            provider_factory=request.provider_factory,
            event_callback=request.event_callback,
            clear_cancel=False,
        )
    )
    if request.mode in {"smoke", "generate"} or _CANCEL_EVENT.is_set():
        result = PipelineResult(run_id=run_id, mode=request.mode, generation=generation, cancelled=_CANCEL_EVENT.is_set())
        _emit_event(request.event_callback, PipelineEvent("pipeline_finished", "Pipeline finished", status="complete" if result.ok else "failed", data={"run_id": run_id}))
        return result

    if not generation.ok:
        _emit_event(
            request.event_callback,
            PipelineEvent(
                "status",
                "Generation had failures; rendering available outputs for partial publish",
                status="partial",
                data={"run_id": run_id},
            ),
        )

    render = render_matrix(
        RenderMatrixRequest(
            model_outputs=[RenderInput(model, request.output_dir / model) for model in request.models],
            suite_path=request.suite_path,
            prompt_path=request.prompt_path,
            task_ids=request.task_ids,
            sandbox=request.sandbox,
            runs_dir=request.runs_dir,
            run_id=run_id,
            timeout_seconds=request.timeout_seconds,
            container_image=request.container_image,
            manim_executable=request.manim_executable,
            allow_stale=request.allow_stale,
            force=request.force,
            resume=request.resume,
            parallel=request.parallel,
            provider_route=request.provider,
            event_callback=request.event_callback,
            clear_cancel=False,
        )
    )
    if _CANCEL_EVENT.is_set():
        result = PipelineResult(run_id=run_id, mode=request.mode, generation=generation, render=render, cancelled=_CANCEL_EVENT.is_set())
        _emit_event(request.event_callback, PipelineEvent("pipeline_finished", "Pipeline finished", status="complete" if result.ok else "failed", data={"run_id": run_id}))
        return result

    report_result = report(ReportRequest(run_dir=render.run_dir, output_dir=request.report_output_dir))
    result = PipelineResult(run_id=run_id, mode=request.mode, generation=generation, render=render, report=report_result)
    _emit_event(
        request.event_callback,
        PipelineEvent(
            "pipeline_finished",
            "Pipeline finished",
            status="complete" if result.ok else "failed",
            path=report_result.index_path,
            data={"run_id": run_id},
        ),
    )
    return result


def cancel() -> bool:
    _CANCEL_EVENT.set()
    return True


def clear_cancel() -> bool:
    _CANCEL_EVENT.clear()
    return True


def retry_failed(request: RetryFailedRequest) -> RenderMatrixResult:
    _CANCEL_EVENT.clear()
    previous_run_dir = _resolve_run_dir(request.previous_run_dir)
    failed_by_model: dict[str, set[str]] = {}
    manifest_path = previous_run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    requested_models = set(request.models or manifest.get("models", []))
    manifest_models = [str(model) for model in manifest.get("models", [])]
    manifest_task_ids = [str(task_id) for task_id in manifest.get("suite", {}).get("task_ids", [])]
    for model in manifest_models:
        if requested_models and model not in requested_models:
            continue
        for task_id in manifest_task_ids:
            if not (previous_run_dir / model / task_id / "result.json").exists():
                failed_by_model.setdefault(model, set()).add(task_id)

    for result in _load_run_result_payloads(previous_run_dir):
        model = str(result.get("model", ""))
        task_id = str(result.get("task", {}).get("id", ""))
        if requested_models and model not in requested_models:
            continue
        if not model or not task_id:
            continue
        if result.get("error") or not result.get("score", {}).get("passed"):
            failed_by_model.setdefault(model, set()).add(task_id)

    if not failed_by_model:
        raise ValueError(f"No failed tasks found in {previous_run_dir}")
    model_outputs = [RenderInput(model, request.output_dir / model) for model in sorted(failed_by_model)]
    return render_matrix(
        RenderMatrixRequest(
            model_outputs=model_outputs,
            suite_path=request.suite_path,
            prompt_path=request.prompt_path,
            sandbox=request.sandbox,
            runs_dir=request.runs_dir,
            run_id=request.run_id,
            timeout_seconds=request.timeout_seconds,
            container_image=request.container_image,
            manim_executable=request.manim_executable,
            allow_stale=request.allow_stale,
            parallel=request.parallel,
            model_task_ids={model: sorted(task_ids) for model, task_ids in failed_by_model.items()},
            event_callback=request.event_callback,
            clear_cancel=False,
        )
    )


def publish(request: PublishRequest) -> PublishResult:
    if request.target not in {"draft", "live"}:
        raise ValueError("--target must be draft or live")
    run_dir = _resolve_run_dir(request.run_dir)
    if request.target == "live":
        if not request.allow_partial:
            _assert_complete_run(run_dir)
        _assert_live_publish_allowed(run_dir)
    report_dir = DEFAULT_REPORTS_DIR / run_dir.name
    if not (report_dir / "data" / "leaderboard.json").exists():
        report(ReportRequest(run_dir=run_dir, output_dir=report_dir))
    _validate_report_bundle(report_dir)
    site_repo = request.site_repo.resolve()
    site_repo.mkdir(parents=True, exist_ok=True)
    _ensure_git_repo(site_repo)
    branch = request.draft_branch if request.target == "draft" else request.live_branch
    _checkout_branch(site_repo, branch)
    bundle_files = _copy_publish_bundle(report_dir, site_repo)
    commit = _commit_publish_bundle(site_repo, run_dir.name, request.target)
    pushed = _push_if_remote(site_repo, branch)
    _append_publish_history(run_dir, request, commit, pushed)
    return PublishResult(
        target=request.target,
        branch=branch,
        site_repo=site_repo,
        commit=commit,
        pushed=pushed,
        bundle_files=bundle_files,
    )


def run_one_task(
    run_dir: Path,
    suite,
    task,
    model: str,
    source: str,
    source_metadata: dict[str, Any],
    task_prompt: str,
    sandbox,
    runtime: ManimCERuntime,
    timeout_seconds: int,
):
    task_run_dir = run_dir / model / task.id
    task_run_dir.mkdir(parents=True, exist_ok=True)
    (task_run_dir / "prompt.md").write_text(task_prompt, encoding="utf-8")
    solution_path = task_run_dir / "solution.py"
    solution_path.write_text(source, encoding="utf-8")
    render = sandbox.render(
        run_dir=task_run_dir,
        solution_path=solution_path,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        fps=int(suite.runtime.get("fps", 60)),
        scene_class=str(suite.runtime.get("scene_class", "MainScene")),
    )
    score = score_task(task, model, source, render, task_run_dir)
    payload = result_payload(task, model, source_metadata_with_hash(source_metadata, source), render, score)
    (task_run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return score


@dataclass
class _GenerateOutcome:
    state_entry: dict[str, Any]
    api_log: dict[str, Any] | None = None
    output_path: Path | None = None
    error: dict[str, Any] | None = None


def _generate_one(
    *,
    model: str,
    task,
    prompt: str,
    output_path: Path,
    provider_name: str,
    provider_factory: ProviderFactory | None,
    force: bool,
    smoke: bool,
    reasoning_effort: str | None,
    event_callback: EventCallback | None = None,
) -> _GenerateOutcome:
    del force
    if _CANCEL_EVENT.is_set():
        entry = _state_entry(
            model=model,
            task_id=task.id,
            status="cancelled",
            output_path=output_path,
            prompt=prompt,
            source="",
            metadata={"provider": provider_name, "model_id": model, "task_id": task.id, "cancelled": True},
            error="cancelled",
        )
        _emit_event(
            event_callback,
            PipelineEvent(
                "task_cancelled",
                f"Skipped queued generation for {model}/{task.id}",
                model=model,
                task_id=task.id,
                status="cancelled",
                path=output_path,
            ),
        )
        return _GenerateOutcome(state_entry=entry)
    _emit_event(
        event_callback,
        PipelineEvent(
            "task_started",
            f"Generating {model}/{task.id}",
            model=model,
            task_id=task.id,
            status="running",
            path=output_path,
        ),
    )
    started = time.monotonic()
    metadata: dict[str, Any] = {
        "provider": provider_name,
        "model_id": model,
        "task_id": task.id,
        "created_at": _now_iso(),
        "smoke": smoke,
    }
    normalized_reasoning = normalize_reasoning_effort(reasoning_effort)
    if normalized_reasoning:
        metadata["requested_reasoning_effort"] = normalized_reasoning
    try:
        provider = provider_factory(model) if provider_factory else _provider_for(provider_name, model, reasoning_effort=normalized_reasoning)
        output: ModelOutput = provider.generate(task, prompt)
        source = cleanup_generated_source(output.source)
        validate_main_scene(source)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(source, encoding="utf-8")
        metadata.update(output.metadata)
        entry = _state_entry(
            model=model,
            task_id=task.id,
            status="complete",
            output_path=output_path,
            prompt=prompt,
            source=source,
            metadata=metadata,
        )
        _emit_event(
            event_callback,
            PipelineEvent(
                "task_finished",
                f"Generated {model}/{task.id}",
                model=model,
                task_id=task.id,
                status="complete",
                cost_usd=_optional_float(metadata.get("cost_usd")),
                path=output_path,
            ),
        )
        return _GenerateOutcome(state_entry=entry, api_log=_api_log_entry(entry), output_path=output_path)
    except GenerationValidationError as error:
        source = cleanup_generated_source(error.source) if error.source else ""
        if source:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(source, encoding="utf-8")
        metadata.update(error.metadata)
        metadata["elapsed_seconds"] = metadata.get("elapsed_seconds", time.monotonic() - started)
        entry = _state_entry(
            model=model,
            task_id=task.id,
            status="partial",
            output_path=output_path,
            prompt=prompt,
            source=source,
            metadata=metadata,
            error=str(error),
        )
        _emit_event(
            event_callback,
            PipelineEvent(
                "task_failed",
                f"Generated partial output for {model}/{task.id}: {error}",
                model=model,
                task_id=task.id,
                status="partial",
                cost_usd=_optional_float(metadata.get("cost_usd")),
                path=output_path,
            ),
        )
        return _GenerateOutcome(state_entry=entry, api_log=_api_log_entry(entry), error=_error_entry(model, task.id, output_path, error))
    except Exception as error:
        metadata["elapsed_seconds"] = time.monotonic() - started
        entry = _state_entry(
            model=model,
            task_id=task.id,
            status="-",
            output_path=output_path,
            prompt=prompt,
            source="",
            metadata=metadata,
            error=str(error),
        )
        _emit_event(
            event_callback,
            PipelineEvent(
                "task_failed",
                f"Generation failed for {model}/{task.id}: {error}",
                model=model,
                task_id=task.id,
                status="failed",
                path=output_path,
            ),
        )
        return _GenerateOutcome(state_entry=entry, api_log=_api_log_entry(entry), error=_error_entry(model, task.id, output_path, error))


def _render_provider_task(
    run_dir: Path,
    suite,
    task,
    model: str,
    provider: FileProvider,
    task_prompt: str,
    sandbox,
    runtime: ManimCERuntime,
    timeout_seconds: int,
    event_callback: EventCallback | None = None,
) -> tuple[Path, bool, str | None]:
    task_run_dir = run_dir / model / task.id
    task_run_dir.mkdir(parents=True, exist_ok=True)
    if _CANCEL_EVENT.is_set():
        _emit_event(
            event_callback,
            PipelineEvent("task_cancelled", f"Skipped queued render for {model}/{task.id}", model=model, task_id=task.id, status="cancelled", path=task_run_dir),
        )
        return task_run_dir, False, "cancelled"
    _emit_event(
        event_callback,
        PipelineEvent("task_started", f"Rendering {model}/{task.id}", model=model, task_id=task.id, status="running", path=task_run_dir),
    )
    try:
        output = provider.generate(task, task_prompt)
    except Exception as error:
        _write_generation_error(task_run_dir, model, task.id, error)
        _emit_event(
            event_callback,
            PipelineEvent("task_failed", f"Render input failed for {model}/{task.id}: {error}", model=model, task_id=task.id, status="failed", path=task_run_dir),
        )
        return task_run_dir, False, f"{model}/{task.id}: generation failed: {error}"
    score = run_one_task(
        run_dir=run_dir,
        suite=suite,
        task=task,
        model=model,
        source=output.source,
        source_metadata=output.metadata,
        task_prompt=task_prompt,
        sandbox=sandbox,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
    )
    _emit_event(
        event_callback,
        PipelineEvent(
            "task_finished" if score.passed else "task_failed",
            f"Rendered {model}/{task.id}: {'pass' if score.passed else 'fail'}",
            model=model,
            task_id=task.id,
            status="pass" if score.passed else "fail",
            path=task_run_dir,
            data={"score": score.automated_score},
        ),
    )
    return task_run_dir, score.passed, None


def _provider_for(provider_name: str, model: str, *, reasoning_effort: str | None = None):
    provider_name = _resolve_provider_name(provider_name, model)
    if provider_name == "openrouter":
        try:
            return OpenRouterProvider(model, reasoning_effort=reasoning_effort)
        except KeyError as error:
            raise ProviderError(f"No OpenRouter route is configured for {model}; use --provider cursor if this is Composer.") from error
    if provider_name == "openai":
        return OpenAIProvider(model, reasoning_effort=reasoning_effort)
    if provider_name == "anthropic":
        return AnthropicProvider(model, reasoning_effort=reasoning_effort)
    if provider_name == "google":
        return GoogleProvider(model, reasoning_effort=reasoning_effort)
    if provider_name == "xai":
        return XAIProvider(model, reasoning_effort=reasoning_effort)
    if provider_name == "cursor":
        return CursorProvider(model)
    raise ProviderError(f"Unknown generation provider: {provider_name}")


def _resolve_provider_name(provider_name: str, model: str) -> str:
    if provider_name == "auto":
        return default_provider_for_model(model)
    return provider_name


def _make_sandbox(request: RenderMatrixRequest):
    if request.sandbox == "local":
        return LocalSandbox()
    return ContainerSandbox(image=request.container_image)


def _write_manifest(
    run_dir: Path,
    run_id: str,
    suite,
    tasks,
    prompt_path: Path,
    sandbox,
    runtime: ManimCERuntime,
    models: list[str],
    provider_route: str,
) -> None:
    path = run_dir / "manifest.json"
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite immutable manifest: {path}")
    docker_digest = _docker_image_digest(sandbox)
    manifest = {
        "schema_version": "0.6.0",
        "run_id": run_id,
        "created_at": _now_iso(),
        "suite": {
            "id": suite.id,
            "version": suite.version,
            "title": suite.title,
            "task_count": len(tasks),
            "task_ids": [task.id for task in tasks],
        },
        "hashes": suite_hashes(suite, prompt_path),
        "models": models,
        "openrouter_slugs": {model: _safe_openrouter_slug(model) for model in models},
        "provider_route": provider_route,
        "runtime": runtime.metadata(),
        "sandbox": {
            "name": sandbox.name,
            "official": sandbox.official,
            "docker_image": getattr(sandbox, "image", None),
            "docker_image_digest": docker_digest,
        },
        "git_commit": _git_commit(),
        "scoring_version": SCORING_VERSION,
        "publish_history": "publish-history.jsonl",
    }
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _safe_openrouter_slug(model: str) -> str | None:
    try:
        return openrouter_slug(model)
    except KeyError:
        return None


def _docker_image_digest(sandbox) -> str | None:
    if getattr(sandbox, "name", None) != "container":
        return None
    digest = None
    if hasattr(sandbox, "_image_digest"):
        digest = sandbox._image_digest()
    return digest


def _write_generation_error(run_dir: Path, model: str, task_id: str, error: Exception) -> None:
    payload = {
        "schema_version": "0.6.0",
        "model": model,
        "task": {"id": task_id},
        "error": repr(error),
        "score": {
            "task_id": task_id,
            "model": model,
            "passed": False,
            "automated_score": 0,
            "rank_score": 0,
            "failure_category": "missing_source",
            "pass_gate": {
                "schema_version": "0.6.0",
                "passed": False,
                "threshold": 70.0,
                "score_passed": False,
                "hard_checks": ["generation"],
                "advisory_checks": [],
                "failed_hard_checks": ["generation"],
                "failed_advisory_checks": [],
                "policy": "v0.6 ranks by automated score and gates only required output, render, safety, label, timing, and visual checks.",
            },
            "checks": {"generation": False},
            "rubric": {},
            "artifacts": {},
        },
    }
    (run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _state_entry(
    *,
    model: str,
    task_id: str,
    status: str,
    output_path: Path,
    prompt: str,
    source: str,
    metadata: dict[str, Any],
    error: str | None = None,
) -> dict[str, Any]:
    entry = {
        "model": model,
        "task_id": task_id,
        "status": status,
        "output_path": str(output_path),
        "updated_at": _now_iso(),
        "prompt_sha256": _sha256_text(prompt),
        "source_sha256": _sha256_text(source) if source else None,
        "metadata": metadata,
    }
    if error:
        entry["error"] = error
    return entry


def _record_generation_state(state: dict[str, Any], model: str, task_id: str, status: str, output_path: Path, prompt: str) -> None:
    source = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else ""
    _record_state_entry(
        state,
        _state_entry(
            model=model,
            task_id=task_id,
            status=status,
            output_path=output_path,
            prompt=prompt,
            source=source,
            metadata={},
        ),
    )


def _record_state_entry(state: dict[str, Any], entry: dict[str, Any]) -> None:
    state.setdefault("generations", {}).setdefault(entry["model"], {})[entry["task_id"]] = entry
    state["updated_at"] = _now_iso()


def _api_log_entry(entry: dict[str, Any]) -> dict[str, Any]:
    metadata = entry.get("metadata", {})
    return {
        "timestamp": _now_iso(),
        "request_id": metadata.get("request_id"),
        "provider": metadata.get("provider"),
        "provider_route": metadata.get("provider_route"),
        "model_id": entry.get("model"),
        "model_slug": metadata.get("model_slug"),
        "task_id": entry.get("task_id"),
        "status": entry.get("status"),
        "input_tokens": metadata.get("input_tokens"),
        "output_tokens": metadata.get("output_tokens"),
        "total_tokens": metadata.get("total_tokens"),
        "cost_usd": metadata.get("cost_usd"),
        "elapsed_seconds": metadata.get("elapsed_seconds"),
        "error": entry.get("error"),
    }


def _append_api_log(path: Path, entry: dict[str, Any] | None) -> None:
    if not entry:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _write_generation_usage(output_root: Path, state: dict[str, Any]) -> None:
    for model, tasks in state.get("generations", {}).items():
        calls = []
        for entry in tasks.values():
            metadata = entry.get("metadata", {})
            if metadata:
                calls.append(_api_log_entry(entry))
        input_tokens = sum(_number(item.get("input_tokens")) for item in calls)
        output_tokens = sum(_number(item.get("output_tokens")) for item in calls)
        total_tokens = sum(_number(item.get("total_tokens")) for item in calls)
        cost = sum(_number(item.get("cost_usd")) for item in calls)
        payload = {
            "schema_version": "0.6.0",
            "model_id": model,
            "provider_usage": {
                "calls": calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost_usd": round(cost, 8),
            },
            "generated_at": _now_iso(),
        }
        model_dir = output_root / model
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "usage.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _spent_from_selected_outputs(models: list[str], output_root: Path) -> float | None:
    costs = []
    for model in models:
        usage_path = output_root / model / "usage.json"
        if not usage_path.exists():
            continue
        try:
            payload = json.loads(usage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        provider_usage = payload.get("provider_usage", {}) if isinstance(payload, dict) else {}
        cost = _optional_float(provider_usage.get("cost_usd"))
        if cost is None:
            cost = _optional_float(payload.get("cost", {}).get("estimated_usd") if isinstance(payload.get("cost"), dict) else None)
        if cost is not None:
            costs.append(cost)
    if not costs:
        return None
    return round(sum(costs), 8)


def _summarize_output_status(statuses: dict[str, str]) -> str:
    if not statuses:
        return "missing"
    values = set(statuses.values())
    if values == {"complete"}:
        return "complete"
    if "partial" in values:
        return "partial"
    if "stale" in values:
        return "stale"
    if "complete" in values:
        return "incomplete"
    return "missing"


def _context_window(raw: dict[str, Any]) -> int | None:
    for key in ["context_window", "context_length", "context"]:
        value = raw.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _catalog_by_slug(catalog: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    data = catalog.get("data", []) if isinstance(catalog, dict) else []
    if not isinstance(data, list):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if model_id:
            rows[model_id] = item
    return rows


def _pricing_from_catalog_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    pricing = item.get("pricing", {})
    if not isinstance(pricing, dict):
        return None
    input_rate = _catalog_price_per_million(pricing.get("prompt") or pricing.get("input") or pricing.get("input_tokens"))
    output_rate = _catalog_price_per_million(pricing.get("completion") or pricing.get("output") or pricing.get("output_tokens"))
    if input_rate is None or output_rate is None:
        return None
    return {
        "method": "openrouter_catalog",
        "source": "openrouter_catalog",
        "input_usd_per_1m_tokens": input_rate,
        "output_usd_per_1m_tokens": output_rate,
    }


def _catalog_price_per_million(value: Any) -> float | None:
    numeric = _optional_float(value)
    if numeric is None:
        return None
    # OpenRouter reports token prices as USD per token.
    if numeric < 1:
        return round(numeric * 1_000_000, 8)
    return numeric


def _context_window_from_catalog_item(item: dict[str, Any] | None) -> int | None:
    if not item:
        return None
    return _context_window(item)


def _matches_context_filter(context_window: int | None, value: str) -> bool:
    if value in {"", "all"}:
        return True
    if context_window is None:
        return value == "unknown"
    if value == "short":
        return context_window < 64_000
    if value == "medium":
        return 64_000 <= context_window < 200_000
    if value == "long":
        return context_window >= 200_000
    return True


def _matches_price_filter(pricing: dict[str, Any], value: str) -> bool:
    if value in {"", "all"}:
        return True
    input_rate = _optional_float(pricing.get("input_usd_per_1m_tokens"))
    output_rate = _optional_float(pricing.get("output_usd_per_1m_tokens"))
    if input_rate is None or output_rate is None:
        return value == "unknown"
    blended = input_rate + output_rate
    if value == "low":
        return blended <= 5
    if value == "mid":
        return 5 < blended <= 25
    if value == "high":
        return blended > 25
    return True


def _latest_run_summary(runs_dir: Path) -> RunSummary | None:
    if not runs_dir.exists():
        return None
    candidates = [path for path in runs_dir.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return _summarize_run_dir(max(candidates, key=lambda path: path.stat().st_mtime))


def _summarize_generation_state(state_path: Path) -> RunSummary:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {}
    generations = state.get("generations", {}) if isinstance(state, dict) else {}
    models = sorted(generations)
    task_ids = sorted({task_id for tasks in generations.values() if isinstance(tasks, dict) for task_id in tasks})
    failed = 0
    cost = 0.0
    has_cost = False
    for tasks in generations.values():
        if not isinstance(tasks, dict):
            continue
        for entry in tasks.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("status") not in {"complete"}:
                failed += 1
            entry_cost = _optional_float(entry.get("metadata", {}).get("cost_usd") if isinstance(entry.get("metadata"), dict) else None)
            if entry_cost is not None:
                has_cost = True
                cost += entry_cost
    return RunSummary(
        run_id=str(state.get("run_id") or state_path.parent.name),
        run_dir=None,
        state_path=state_path,
        status="failed" if failed else "generated",
        created_at=state.get("created_at"),
        updated_at=state.get("updated_at") or datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc).isoformat(),
        models=models,
        task_ids=task_ids,
        failed=failed,
        cost_usd=round(cost, 8) if has_cost else None,
    )


def _summarize_run_dir(run_dir: Path) -> RunSummary:
    manifest_path = run_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    models = [str(model) for model in manifest.get("models", [])]
    task_ids = [str(task_id) for task_id in manifest.get("suite", {}).get("task_ids", [])]
    passed = failed = 0
    seen: set[tuple[str, str]] = set()
    cost = 0.0
    has_cost = False
    for payload in _load_run_result_payloads(run_dir):
        model = str(payload.get("model", ""))
        task_id = str(payload.get("task", {}).get("id", ""))
        if model and task_id:
            seen.add((model, task_id))
        if payload.get("error") or not payload.get("score", {}).get("passed"):
            failed += 1
        else:
            passed += 1
        metadata = payload.get("source_metadata", {})
        if isinstance(metadata, dict):
            value = _optional_float(metadata.get("cost_usd"))
            if value is not None:
                has_cost = True
                cost += value
    expected = {(model, task_id) for model in models for task_id in task_ids}
    missing = len(expected - seen) if expected else 0
    status = "missing" if missing else "failed" if failed else "complete" if passed else "pending"
    updated_at = datetime.fromtimestamp(run_dir.stat().st_mtime, timezone.utc).isoformat()
    return RunSummary(
        run_id=str(manifest.get("run_id") or run_dir.name),
        run_dir=run_dir,
        state_path=None,
        status=status,
        created_at=manifest.get("created_at"),
        updated_at=updated_at,
        models=models,
        task_ids=task_ids,
        passed=passed,
        failed=failed,
        missing=missing,
        cost_usd=round(cost, 8) if has_cost else None,
    )


def _load_run_result_payloads(run_dir: Path) -> list[dict[str, Any]]:
    payloads = []
    for result_path in sorted(run_dir.glob("*/*/result.json")):
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _result_path_failed(result_path: Path) -> bool:
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict):
        return True
    return bool(payload.get("error") or not payload.get("score", {}).get("passed"))


def _media_path_from_result_payload(payload: dict[str, Any]) -> Path | None:
    score = payload.get("score", {}) if isinstance(payload.get("score"), dict) else {}
    artifacts = score.get("artifacts", {}) if isinstance(score.get("artifacts"), dict) else {}
    media = artifacts.get("media")
    if media:
        return Path(str(media))
    render = payload.get("render", {}) if isinstance(payload.get("render"), dict) else {}
    media_files = render.get("media_files", [])
    if media_files:
        return Path(str(media_files[0]))
    return None


def _duration_from_result_payload(payload: dict[str, Any]) -> str:
    render = payload.get("render", {}) if isinstance(payload.get("render"), dict) else {}
    metadata = render.get("metadata", {}) if isinstance(render.get("metadata"), dict) else {}
    media = metadata.get("media", {}) if isinstance(metadata.get("media"), dict) else {}
    values = media.values() if isinstance(media, dict) else []
    for item in values:
        if not isinstance(item, dict):
            continue
        for key in ["duration", "duration_seconds"]:
            if item.get(key) is not None:
                try:
                    return f"{float(item[key]):.1f}s"
                except (TypeError, ValueError):
                    return str(item[key])
    return "-"


def _load_state(path: Path, run_id: str, request: GenerateBatchRequest) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": "0.6.0",
        "run_id": run_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "suite_path": str(request.suite_path),
        "prompt_path": str(request.prompt_path),
        "output_dir": str(request.output_dir),
        "provider": request.provider,
        "generations": {},
        "smoke": None,
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _error_entry(model: str, task_id: str, output_path: Path, error: Exception) -> dict[str, Any]:
    return {"model": model, "task_id": task_id, "path": str(output_path), "error": str(error)}


def _validate_report_bundle(report_dir: Path) -> None:
    required = [
        report_dir / "data" / "leaderboard.json",
        report_dir / "data" / "results.json",
        report_dir / "data" / "models.json",
        report_dir / "data" / "tasks.json",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing publish bundle files: " + ", ".join(str(path) for path in missing))


def _copy_publish_bundle(report_dir: Path, site_repo: Path) -> list[Path]:
    copied: list[Path] = []
    for name in ["data", "videos"]:
        source = report_dir / name
        target = site_repo / name
        if target.exists():
            shutil.rmtree(target)
        if source.exists():
            shutil.copytree(source, target)
            copied.extend(sorted(path for path in target.rglob("*") if path.is_file()))
    if (report_dir / "index.html").exists():
        shutil.copy2(report_dir / "index.html", site_repo / "report.html")
        copied.append(site_repo / "report.html")
    return copied


def _append_publish_history(run_dir: Path, request: PublishRequest, commit: str | None, pushed: bool) -> None:
    payload = {
        "schema_version": "0.6.0",
        "target": request.target,
        "site_repo": str(request.site_repo),
        "commit": commit,
        "pushed": pushed,
        "published_at": _now_iso(),
    }
    with (run_dir / "publish-history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _resolve_run_dir(value: Path) -> Path:
    if value.exists():
        return value.resolve()
    candidate = DEFAULT_RUNS_DIR / value
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(f"Run directory not found: {value}")


def _assert_complete_run(run_dir: Path) -> None:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest for publish: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = []
    for model in manifest.get("models", []):
        for task_id in manifest.get("suite", {}).get("task_ids", []):
            result_path = run_dir / model / task_id / "result.json"
            if not result_path.exists():
                missing.append(str(result_path))
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("error"):
                missing.append(str(result_path))
    if missing:
        raise ValueError("Run is partial; use --allow-partial to publish anyway. Missing/failed: " + ", ".join(missing[:8]))


def _assert_live_publish_allowed(run_dir: Path) -> None:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    sandbox = manifest.get("sandbox", {})
    if sandbox.get("name") == "container" and not sandbox.get("docker_image_digest"):
        raise ValueError("Live publish requires a recorded Docker image digest for official container runs")


def _ensure_git_repo(path: Path) -> None:
    if not (path / ".git").exists():
        _git(path, "init")
        _git(path, "config", "user.email", "manimbench@example.invalid")
        _git(path, "config", "user.name", "ManimBench")


def _checkout_branch(path: Path, branch: str) -> None:
    existing = subprocess.run(["git", "rev-parse", "--verify", branch], cwd=path, text=True, capture_output=True, check=False)
    if existing.returncode == 0:
        _git(path, "checkout", branch)
    else:
        _git(path, "checkout", "-B", branch)


def _commit_publish_bundle(path: Path, run_id: str, target: str) -> str | None:
    existing = [name for name in ["data", "videos", "report.html"] if (path / name).exists()]
    if existing:
        _git(path, "add", *existing)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=path, text=True, capture_output=True, check=False)
    if not status.stdout.strip():
        return _current_commit(path)
    _git(path, "commit", "-m", f"Publish {target} ManimBench run {run_id}")
    return _current_commit(path)


def _push_if_remote(path: Path, branch: str) -> bool:
    remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=path, text=True, capture_output=True, check=False)
    if remote.returncode != 0:
        return False
    _git(path, "push", "origin", f"HEAD:{branch}")
    return True


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=path, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def _current_commit(path: Path) -> str | None:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, text=True, capture_output=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else None


def _git_commit() -> str | None:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], text=True, capture_output=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else None


def _new_run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_openrouter_credits_payload(payload: dict[str, Any]) -> dict[str, float | None] | None:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None
    total_credits = _optional_float(data.get("total_credits"))
    total_usage = _optional_float(data.get("total_usage"))
    balance = _optional_float(data.get("balance"))
    if balance is None:
        balance = _optional_float(data.get("credits"))
    if balance is None and total_credits is not None and total_usage is not None:
        balance = round(total_credits - total_usage, 8)
    if total_credits is None and total_usage is None and balance is None:
        return None
    return {"total_credits": total_credits, "total_usage": total_usage, "balance": balance}


def _emit_event(callback: EventCallback | None, event: PipelineEvent) -> None:
    if not callback:
        return
    try:
        callback(event)
    except Exception:
        pass
