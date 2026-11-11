"""Ask models for their answers and save them, several samples per task.

Each sample is two files next to each other::

    outputs/<model>/<task>/sample-1.py     the code that will be rendered
    outputs/<model>/<task>/sample-1.json   how it was produced: route, tokens, cost

The JSON file is the record of truth. A sample with a record is never asked
for again unless ``force`` is set, so stopping and restarting a run costs
nothing twice.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from manimbench.extract import extract_code
from manimbench.models import Suite, Task
from manimbench.paths import DEFAULT_OUTPUTS_DIR, DEFAULT_PROMPT_PATH, DEFAULT_SUITE_PATH
from manimbench.prompting import build_task_prompt, load_master_prompt
from manimbench.providers.base import ProviderError, Request, Route
from manimbench.registry import ModelEntry, load_models, load_routes, make_route
from manimbench.sandbox.settings import SandboxSettings, load_sandbox_settings
from manimbench.tasks import filter_tasks, load_suite

SCHEMA_VERSION = "0.7.0"
GENERATION_SYSTEM_PROMPT = (
    "You write animations with Manim Community Edition. "
    "Reply with one complete Python file and nothing else."
)

# A record in one of these states is a finished answer and is kept.
FINAL_STATUSES = {"complete", "no_code"}

RouteFactory = Callable[[str], Route]


@dataclass(frozen=True)
class GenerateRequest:
    models: list[str]
    suite_path: Path = DEFAULT_SUITE_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    task_ids: list[str] | None = None
    output_dir: Path = DEFAULT_OUTPUTS_DIR
    route: str | None = None
    samples: int | None = None
    force: bool = False
    dry_run: bool = False
    parallel: int = 1
    route_factory: RouteFactory | None = None
    sandbox_settings: SandboxSettings | None = None
    on_event: Callable[[str], None] | None = None


@dataclass
class GenerateResult:
    route: str
    planned: list[dict[str, Any]] = field(default_factory=list)
    generated: list[Path] = field(default_factory=list)
    no_code: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    stale: list[Path] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed and not self.stale


def sample_paths(output_dir: Path, model: str, task_id: str, sample: int) -> tuple[Path, Path, Path]:
    """The code file, the record file, and the raw reply file for one sample."""
    folder = output_dir / model / task_id
    return folder / f"sample-{sample}.py", folder / f"sample-{sample}.json", folder / f"sample-{sample}.reply.txt"


def read_record(record_path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def sample_status(output_dir: Path, model: str, task_id: str, sample: int, prompt_sha256: str) -> str:
    """One of: missing, complete, no_code, provider_error, stale."""
    code_path, record_path, _reply = sample_paths(output_dir, model, task_id, sample)
    record = read_record(record_path)
    if record is None:
        return "missing"
    status = str(record.get("status", "missing"))
    if status not in FINAL_STATUSES:
        return "provider_error" if status == "provider_error" else "missing"
    if record.get("prompt_sha256") != prompt_sha256:
        return "stale"  # Written for a different prompt, suite, or Manim version.
    if status == "complete":
        if not code_path.exists() or sha256_text(code_path.read_text(encoding="utf-8")) != record.get("source_sha256"):
            return "stale"  # The code was edited after the model wrote it.
    return status


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def task_prompts(suite: Suite, prompt_path: Path, tasks: list[Task], settings: SandboxSettings) -> dict[str, str]:
    master = load_master_prompt(prompt_path)
    return {
        task.id: build_task_prompt(
            master, suite, task, manim_version=settings.manim_version, python_version=settings.python_version
        )
        for task in tasks
    }


def generation_prompt_sha256(prompt: str) -> str:
    return sha256_text(GENERATION_SYSTEM_PROMPT + "\n\n" + prompt)


def generate(request: GenerateRequest) -> GenerateResult:
    suite = load_suite(request.suite_path)
    tasks = filter_tasks(suite, request.task_ids)
    settings = request.sandbox_settings or load_sandbox_settings()
    prompts = task_prompts(suite, request.prompt_path, tasks, settings)
    samples = request.samples or suite.samples_per_task
    route_name = request.route or load_routes()["default_route"]
    registry = load_models()
    unknown = [model for model in request.models if model not in registry]
    if unknown:
        raise KeyError(f"Unknown model id(s): {', '.join(unknown)}")
    entries = [registry[model] for model in request.models]
    for entry in entries:
        entry.target(route_name)  # Fail before any call if a model lacks this route.

    result = GenerateResult(route=route_name)
    work: list[tuple[ModelEntry, Task, int]] = []
    for entry in entries:
        for task in tasks:
            digest = generation_prompt_sha256(prompts[task.id])
            for sample in range(1, samples + 1):
                code_path = sample_paths(request.output_dir, entry.id, task.id, sample)[0]
                status = sample_status(request.output_dir, entry.id, task.id, sample, digest)
                result.planned.append({"model": entry.id, "task_id": task.id, "sample": sample, "status": status})
                if status in FINAL_STATUSES and not request.force:
                    result.skipped.append(code_path)
                elif status == "stale" and not request.force:
                    result.stale.append(code_path)
                else:
                    work.append((entry, task, sample))

    if request.dry_run or not work:
        return result

    # Only now is a live route needed; a fully cached run never touches one.
    route = request.route_factory(route_name) if request.route_factory else make_route(route_name)

    def run_one(item: tuple[ModelEntry, Task, int]) -> dict[str, Any]:
        entry, task, sample = item
        return _generate_one(route, route_name, entry, task, sample, prompts[task.id], request.output_dir)

    with ThreadPoolExecutor(max_workers=max(1, int(request.parallel))) as executor:
        for record in executor.map(run_one, work):
            code_path = sample_paths(request.output_dir, record["model"], record["task_id"], record["sample"])[0]
            cost = (record.get("completion") or {}).get("cost_usd")
            if isinstance(cost, (int, float)):
                result.cost_usd += float(cost)
            if record["status"] == "complete":
                result.generated.append(code_path)
            elif record["status"] == "no_code":
                result.no_code.append(code_path)
            else:
                result.failed.append(
                    {"model": record["model"], "task_id": record["task_id"], "sample": record["sample"], "error": record.get("error")}
                )
            if request.on_event:
                request.on_event(f"{record['model']}/{record['task_id']}/sample-{record['sample']}: {record['status']}")
    result.cost_usd = round(result.cost_usd, 6)
    return result


def _generate_one(
    route: Route, route_name: str, entry: ModelEntry, task: Task, sample: int, prompt: str, output_dir: Path
) -> dict[str, Any]:
    code_path, record_path, reply_path = sample_paths(output_dir, entry.id, task.id, sample)
    code_path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model": entry.id,
        "task_id": task.id,
        "sample": sample,
        "route": route_name,
        "prompt_sha256": generation_prompt_sha256(prompt),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reasoning_effort": entry.reasoning_effort,
        "max_output_tokens": entry.max_output_tokens,
    }
    for stale_file in (code_path, reply_path):
        stale_file.unlink(missing_ok=True)
    try:
        completion = route.complete(
            entry.target(route_name),
            Request(
                system=GENERATION_SYSTEM_PROMPT,
                prompt=prompt,
                max_output_tokens=entry.max_output_tokens,
                reasoning_effort=entry.reasoning_effort,
            ),
        )
    except ProviderError as error:
        # Says nothing about the model. The sample stays unanswered and is asked again next run.
        record.update({"status": "provider_error", "error": str(error)[:2000]})
        _write_json(record_path, record)
        return record

    record["completion"] = completion.metadata()
    reply_path.write_text(completion.text, encoding="utf-8")
    code = extract_code(completion.text)
    if "class " in code:
        code_path.write_text(code, encoding="utf-8")
        record.update({"status": "complete", "source_sha256": sha256_text(code)})
    else:
        # The model answered, and nothing in the answer defines a class, so it cannot be a scene:
        # an empty reply, a refusal, or plain prose. That is a result, scored as zero.
        record.update({"status": "no_code", "source_sha256": None})
    _write_json(record_path, record)
    return record


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
