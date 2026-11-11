"""Render saved answers in the sandbox and score what can be measured.

A run is a folder::

    runs/<run_id>/manifest.json
    runs/<run_id>/<model>/<task>/sample-1/
        solution.py   layout.json   media/   logs/   result.json

``result.json`` holds the gates, the layout and pacing measurements, and the
score. The judge step adds to it later without rendering again.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from manimbench.generation import generation_prompt_sha256, read_record, sample_paths, sha256_text, task_prompts
from manimbench.models import Suite, Task
from manimbench.paths import DEFAULT_OUTPUTS_DIR, DEFAULT_PROMPT_PATH, DEFAULT_RUNS_DIR, DEFAULT_SUITE_PATH, PROJECT_ROOT
from manimbench.sandbox import ContainerSandbox
from manimbench.scoring import SCORING_VERSION
from manimbench.scoring.aggregate import sample_score
from manimbench.scoring.gates import check_source, evaluate_gates
from manimbench.scoring.judge import combine_judges
from manimbench.scoring.layout import load_layout, score_layout
from manimbench.scoring.motion import analyze_motion
from manimbench.tasks import filter_tasks, load_suite, suite_hashes

SCHEMA_VERSION = "0.7.0"


@dataclass(frozen=True)
class RenderRequest:
    models: list[str]
    suite_path: Path = DEFAULT_SUITE_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    task_ids: list[str] | None = None
    outputs_dir: Path = DEFAULT_OUTPUTS_DIR
    runs_dir: Path = DEFAULT_RUNS_DIR
    run_id: str | None = None
    samples: int | None = None
    parallel: int = 1
    force: bool = False
    allow_stale: bool = False
    quality: str | None = None
    fps: int | None = None
    timeout_seconds: int | None = None
    sandbox: Any | None = None
    on_event: Callable[[str], None] | None = None


@dataclass
class RenderOutcome:
    run_id: str
    run_dir: Path
    rendered: list[Path] = field(default_factory=list)
    reused: list[Path] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    stale: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.stale


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def sample_dir(run_dir: Path, model: str, task_id: str, sample: int) -> Path:
    return run_dir / model / task_id / f"sample-{sample}"


def load_results(run_dir: Path) -> list[dict[str, Any]]:
    results = []
    for path in sorted(run_dir.glob("*/*/sample-*/result.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            results.append(data)
    return results


def load_manifest(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def render(request: RenderRequest) -> RenderOutcome:
    suite = load_suite(request.suite_path)
    tasks = filter_tasks(suite, request.task_ids)
    sandbox = request.sandbox or ContainerSandbox()
    sandbox.ensure_image()
    samples = request.samples or suite.samples_per_task
    quality = request.quality or suite.runtime.quality
    fps = request.fps or suite.runtime.fps
    timeout = request.timeout_seconds or suite.runtime.render_timeout_seconds
    prompts = task_prompts(suite, request.prompt_path, tasks, sandbox.settings)

    run_id = request.run_id or new_run_id()
    run_dir = request.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(run_id, suite, tasks, request, sandbox, samples, quality, fps, timeout)
    _write_or_check_manifest(run_dir / "manifest.json", manifest)

    outcome = RenderOutcome(run_id=run_id, run_dir=run_dir)
    work: list[tuple[str, Task, int, dict[str, Any] | None]] = []
    for model in request.models:
        for task in tasks:
            digest = generation_prompt_sha256(prompts[task.id])
            for sample in range(1, samples + 1):
                target = sample_dir(run_dir, model, task.id, sample)
                code_path, record_path, _reply = sample_paths(request.outputs_dir, model, task.id, sample)
                record = read_record(record_path)
                where = {"model": model, "task_id": task.id, "sample": sample}
                if record is None and not code_path.exists():
                    outcome.missing.append({**where, "reason": "not_generated"})
                    continue
                if record is not None and record.get("status") == "provider_error":
                    outcome.missing.append({**where, "reason": "provider_error"})
                    continue
                if record is not None and record.get("prompt_sha256") != digest and not request.allow_stale:
                    outcome.stale.append({**where, "reason": "written_for_a_different_prompt"})
                    continue
                if (target / "result.json").exists() and not request.force:
                    outcome.reused.append(target / "result.json")
                    continue
                work.append((model, task, sample, record))

    def run_one(item: tuple[str, Task, int, dict[str, Any] | None]) -> Path:
        model, task, sample, record = item
        code_path = sample_paths(request.outputs_dir, model, task.id, sample)[0]
        source = code_path.read_text(encoding="utf-8") if code_path.exists() else ""
        target = sample_dir(run_dir, model, task.id, sample)
        result = render_sample(
            target, suite, task, model, sample, source, record, sandbox, quality=quality, fps=fps, timeout_seconds=timeout
        )
        if request.on_event:
            request.on_event(f"{model}/{task.id}/sample-{sample}: {result['gates']['failure'] or 'passed gates'}")
        return target / "result.json"

    with ThreadPoolExecutor(max_workers=max(1, int(request.parallel))) as executor:
        outcome.rendered.extend(executor.map(run_one, work))
    return outcome


def render_sample(
    target: Path,
    suite: Suite,
    task: Task,
    model: str,
    sample: int,
    source: str,
    record: dict[str, Any] | None,
    sandbox: Any,
    *,
    quality: str,
    fps: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Render and measure one sample. Always writes ``result.json`` and returns it."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / "solution.py").write_text(source, encoding="utf-8")

    source_check = check_source(source, suite.runtime.scene_class)
    render_result = None
    motion = None
    layout: dict[str, Any] | None = None
    if source_check["failure"] is None:
        render_result = sandbox.render(
            target, timeout_seconds=timeout_seconds, quality=quality, fps=fps, scene_class=suite.runtime.scene_class
        )
        if render_result.video:
            motion = analyze_motion(target / render_result.video, suite.scoring.pacing)
        if render_result.layout_path:
            layout = score_layout(load_layout(target / render_result.layout_path), suite.scoring.layout)
    gates = evaluate_gates(source_check, render_result, motion, suite.runtime)
    if not gates["passed"]:
        layout = None  # A failed sample has no quality to measure.

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "scoring_version": SCORING_VERSION,
        "model": model,
        "task": {"id": task.id, "version": task.version, "title": task.title},
        "sample": sample,
        "source": {"sha256": sha256_text(source), "generation": _generation_summary(record)},
        "render": asdict(render_result) if render_result else None,
        "gates": gates,
        "layout": layout,
        "pacing": motion,
        "judge": {"status": "pending", "score": None, "judges": 0, "expected": 0},
        "judgements": [],
    }
    result["score"] = sample_score(gates, layout, motion, result["judge"], suite.scoring)
    write_result(target, result)
    return result


def rescore(result: dict[str, Any], suite: Suite, judgements: list[dict[str, Any]], expected_judges: int) -> dict[str, Any]:
    """Fold judge records into a result and recompute its score."""
    result["judgements"] = judgements
    result["judge"] = combine_judges(judgements, expected_judges)
    result["score"] = sample_score(result["gates"], result.get("layout"), result.get("pacing"), result["judge"], suite.scoring)
    return result


def write_result(target: Path, result: dict[str, Any]) -> None:
    temporary = target / "result.json.tmp"
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(target / "result.json")


def _generation_summary(record: dict[str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {"status": "manual", "route": "manual"}
    completion = record.get("completion") or {}
    return {
        "status": record.get("status"),
        "route": record.get("route"),
        "created_at": record.get("created_at"),
        "reasoning_effort": record.get("reasoning_effort"),
        **{key: completion.get(key) for key in [
            "requested_model", "response_model", "request_id", "finish_reason", "input_tokens", "output_tokens",
            "reasoning_tokens", "cost_usd", "cost_basis", "elapsed_seconds", "attempts",
        ]},
    }


def _manifest(
    run_id: str, suite: Suite, tasks: list[Task], request: RenderRequest, sandbox: Any, samples: int,
    quality: str, fps: int, timeout: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scoring_version": SCORING_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite": {"id": suite.id, "version": suite.version, "title": suite.title, "task_ids": [task.id for task in tasks]},
        "hashes": suite_hashes(suite, request.prompt_path),
        "models": list(request.models),
        "samples_per_task": samples,
        "render": {"quality": quality, "fps": fps, "timeout_seconds": timeout},
        "official": (
            quality == suite.runtime.quality
            and fps == suite.runtime.fps
            and timeout == suite.runtime.render_timeout_seconds
            and samples >= suite.samples_per_task
        ),
        "sandbox": sandbox.metadata(),
        "git_commit": _git_commit(),
    }


# Parts of the manifest that must not change when a run is continued.
_FIXED_KEYS = ["suite", "hashes", "samples_per_task", "render", "sandbox", "scoring_version"]


def _write_or_check_manifest(path: Path, manifest: dict[str, Any]) -> None:
    if not path.exists():
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return
    existing = json.loads(path.read_text(encoding="utf-8"))
    changed = [key for key in _FIXED_KEYS if existing.get(key) != manifest.get(key)]
    if changed:
        raise ValueError(
            f"Run {path.parent.name} was started with different settings ({', '.join(changed)}). "
            "Use a new run id so results from different setups are never mixed."
        )
    models = list(dict.fromkeys(list(existing.get("models", [])) + manifest["models"]))
    if models != existing.get("models"):
        existing["models"] = models
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True, capture_output=True, check=False, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None
