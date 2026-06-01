from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from manimbench.model_registry import default_provider_for_model, openrouter_slug, public_model_rows
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
from manimbench.providers.common import GenerationValidationError, ProviderError, cleanup_generated_source, validate_main_scene
from manimbench.providers.cursor import CursorProvider
from manimbench.providers.file_provider import FileProvider
from manimbench.providers.google import GoogleProvider
from manimbench.providers.openai import OpenAIProvider
from manimbench.providers.openrouter import OpenRouterProvider
from manimbench.providers.xai import XAIProvider
from manimbench.reporting import write_report
from manimbench.runtime import ManimCERuntime
from manimbench.sandbox import ContainerSandbox, LocalSandbox
from manimbench.scoring import SCORING_VERSION, result_payload, score_task, source_metadata_with_hash
from manimbench.tasks import filter_tasks, load_suite, suite_hashes


ProviderFactory = Callable[[str], Any]


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
    provider_factory: ProviderFactory | None = None


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
    provider_factory: ProviderFactory | None = None


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
    parallel: int = 1
    provider_route: str = "file"


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
    return {
        task.id: generation_status(output_dir / model / f"{task.id}.py", build_task_prompt(master_prompt, task), state, model, task.id)
        for task in suite.tasks
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
        provider_factory=request.provider_factory,
    )
    return generate_batch(batch)


def generate_batch(request: GenerateBatchRequest) -> GenerateResult:
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
                continue
            work.append((model, task, prompt, output_path, provider_name))

    if request.dry_run:
        _write_state(state_path, state)
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
        work = work[1:]

    with ThreadPoolExecutor(max_workers=max(1, int(request.parallel))) as executor:
        futures = [
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
            )
            for model, task, prompt, output_path, provider_name in work
        ]
        for future in as_completed(futures):
            outcome = future.result()
            _record_state_entry(state, outcome.state_entry)
            _append_api_log(api_log_path, outcome.api_log)
            if outcome.error:
                result.failed.append(outcome.error)
            elif outcome.output_path:
                result.generated.append(outcome.output_path)

    _write_state(state_path, state)
    _write_generation_usage(request.output_dir, state)
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


def render_matrix(request: RenderMatrixRequest) -> RenderMatrixResult:
    suite = load_suite(request.suite_path)
    master_prompt = load_master_prompt(request.prompt_path)
    tasks = filter_tasks(suite, request.task_ids)
    sandbox = _make_sandbox(request)
    runtime = ManimCERuntime(executable=request.manim_executable)
    run_id = request.run_id or _new_run_id("render")
    run_dir = request.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(
        run_dir=run_dir,
        run_id=run_id,
        suite=suite,
        tasks=tasks,
        prompt_path=request.prompt_path,
        sandbox=sandbox,
        runtime=runtime,
        models=[item.model for item in request.model_outputs],
        provider_route=request.provider_route,
    )

    jobs = []
    for item in request.model_outputs:
        provider = FileProvider(item.outputs_dir, item.model, allow_stale=request.allow_stale)
        for task in tasks:
            jobs.append((item.model, provider, task, build_task_prompt(master_prompt, task)))

    failures = 0
    result_paths: list[Path] = []
    with ThreadPoolExecutor(max_workers=max(1, int(request.parallel))) as executor:
        futures = [
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
            )
            for model, provider, task, task_prompt in jobs
        ]
        for future in as_completed(futures):
            task_path, passed, error = future.result()
            result_paths.append(task_path / "result.json")
            if error:
                print(error, file=sys.stderr)
                failures += 1
            elif not passed:
                failures += 1
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
    branch = "draft" if request.target == "draft" else "main"
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
) -> _GenerateOutcome:
    del force
    started = time.monotonic()
    metadata: dict[str, Any] = {
        "provider": provider_name,
        "model_id": model,
        "task_id": task.id,
        "created_at": _now_iso(),
        "smoke": smoke,
    }
    try:
        provider = provider_factory(model) if provider_factory else _provider_for(provider_name, model)
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
) -> tuple[Path, bool, str | None]:
    task_run_dir = run_dir / model / task.id
    task_run_dir.mkdir(parents=True, exist_ok=True)
    try:
        output = provider.generate(task, task_prompt)
    except Exception as error:
        _write_generation_error(task_run_dir, model, task.id, error)
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
    return task_run_dir, score.passed, None


def _provider_for(provider_name: str, model: str):
    provider_name = _resolve_provider_name(provider_name, model)
    if provider_name == "openrouter":
        try:
            return OpenRouterProvider(model)
        except KeyError as error:
            raise ProviderError(f"No OpenRouter route is configured for {model}; use --provider cursor if this is Composer.") from error
    if provider_name == "openai":
        return OpenAIProvider(model)
    if provider_name == "anthropic":
        return AnthropicProvider(model)
    if provider_name == "google":
        return GoogleProvider(model)
    if provider_name == "xai":
        return XAIProvider(model)
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
        "schema_version": "0.5.0",
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
        "schema_version": "0.5.0",
        "model": model,
        "task": {"id": task_id},
        "error": repr(error),
        "score": {
            "task_id": task_id,
            "model": model,
            "passed": False,
            "automated_score": 0,
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
            "schema_version": "0.5.0",
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


def _load_state(path: Path, run_id: str, request: GenerateBatchRequest) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "schema_version": "0.5.0",
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
        "schema_version": "0.5.0",
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
