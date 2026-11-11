"""Send rendered samples to the judge panel and fold the answers into the results.

Judging is its own step so a run can be judged, or judged again by a different
panel, without rendering anything twice. Each judge's answer is kept in the
sample's ``judge/`` folder exactly as it was scored.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from manimbench.media import extract_frames
from manimbench.models import Suite, Task
from manimbench.paths import DEFAULT_SUITE_PATH
from manimbench.providers.base import ProviderError, Request, Route
from manimbench.registry import JudgePanel, ModelEntry, load_judges, load_models, make_route
from manimbench.rendering import load_manifest, rescore, write_result
from manimbench.scoring.judge import (
    JUDGE_SYSTEM_PROMPT,
    JudgeReplyError,
    build_judge_prompt,
    judge_score,
    parse_judge_reply,
    prompt_sha256,
    select_frame_times,
)
from manimbench.scoring.layout import load_layout, on_screen_text, snapshot_times
from manimbench.tasks import load_suite

REPLY_ATTEMPTS = 2

RouteFactory = Callable[[str], Route]


@dataclass(frozen=True)
class JudgeRequest:
    run_dir: Path
    suite_path: Path = DEFAULT_SUITE_PATH
    panel: JudgePanel | None = None
    parallel: int = 1
    force: bool = False
    route_factory: RouteFactory | None = None
    on_event: Callable[[str], None] | None = None


@dataclass
class JudgeOutcome:
    judged: int = 0
    reused: int = 0
    failed: list[dict[str, Any]] = field(default_factory=list)
    skipped_failed_gate: int = 0
    cost_usd: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed


def prepare_frames(sample_path: Path, result: dict[str, Any], max_frames: int) -> list[dict[str, Any]]:
    """Save the frames the judge will see, with the text on screen at each one."""
    render = result.get("render") or {}
    video = sample_path / str(render.get("video"))
    duration = float((render.get("probe") or {}).get("duration_seconds") or 0.0)
    layout = load_layout(sample_path / str(render.get("layout_path"))) if render.get("layout_path") else None
    times = select_frame_times(snapshot_times(layout), duration, max_frames)
    frames = extract_frames(video, times, sample_path / "frames")
    for frame in frames:
        frame["text"] = on_screen_text(layout, frame["time"])
    (sample_path / "frames" / "frames.json").write_text(json.dumps(frames, indent=2), encoding="utf-8")
    return frames


def judge_run(request: JudgeRequest) -> JudgeOutcome:
    run_dir = request.run_dir
    suite = load_suite(request.suite_path)
    manifest = load_manifest(run_dir)
    if manifest["suite"]["id"] != suite.id or manifest["suite"]["version"] != suite.version:
        raise ValueError(f"Run {run_dir.name} was made with suite {manifest['suite']['id']}, not {suite.id}")
    panel = request.panel or load_judges()
    if not panel.judges:
        raise ValueError("The judge panel is empty")
    registry = load_models()
    judges = [registry[judge_id] for judge_id in panel.judges]
    for judge in judges:
        judge.target(panel.route)
    tasks = {task.id: task for task in suite.tasks}

    outcome = JudgeOutcome()
    work: list[tuple[Path, ModelEntry]] = []
    samples: list[Path] = []
    for result_path in sorted(run_dir.glob("*/*/sample-*/result.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result["gates"]["passed"]:
            outcome.skipped_failed_gate += 1
            continue
        samples.append(result_path.parent)
        for judge in judges:
            record = _read(result_path.parent / "judge" / f"{judge.id}.json")
            if record and record.get("status") == "complete" and not request.force:
                outcome.reused += 1
            else:
                work.append((result_path.parent, judge))

    if work:
        route = request.route_factory(panel.route) if request.route_factory else make_route(panel.route)
        # Frames are cut once per sample, before any judge runs, so judges never race to write them.
        for sample_path in sorted({item[0] for item in work}):
            if request.force or not (sample_path / "frames" / "frames.json").exists():
                prepare_frames(
                    sample_path, json.loads((sample_path / "result.json").read_text(encoding="utf-8")), panel.max_frames
                )

        def run_one(item: tuple[Path, ModelEntry]) -> dict[str, Any]:
            sample_path, judge = item
            result = json.loads((sample_path / "result.json").read_text(encoding="utf-8"))
            return judge_sample(sample_path, result, suite, tasks[result["task"]["id"]], judge, panel, route)

        with ThreadPoolExecutor(max_workers=max(1, int(request.parallel))) as executor:
            for record in executor.map(run_one, work):
                outcome.cost_usd += float(record.get("cost_usd") or 0.0)
                if record["status"] == "complete":
                    outcome.judged += 1
                else:
                    outcome.failed.append(
                        {"sample": record["sample_path"], "judge": record["judge_id"], "error": record.get("error")}
                    )
                if request.on_event:
                    request.on_event(f"{record['sample_path']} judged by {record['judge_id']}: {record['status']}")

    for sample_path in samples:
        result = json.loads((sample_path / "result.json").read_text(encoding="utf-8"))
        records = [_read(sample_path / "judge" / f"{judge.id}.json") for judge in judges]
        rescore(result, suite, [_public(record) for record in records if record], expected_judges=len(judges))
        write_result(sample_path, result)
    outcome.cost_usd = round(outcome.cost_usd, 6)
    return outcome


def judge_sample(
    sample_path: Path,
    result: dict[str, Any],
    suite: Suite,
    task: Task,
    judge: ModelEntry,
    panel: JudgePanel,
    route: Route,
) -> dict[str, Any]:
    """Ask one judge about one sample and save its record."""
    frames_file = sample_path / "frames" / "frames.json"
    frames = _read_list(frames_file) or prepare_frames(sample_path, result, panel.max_frames)
    duration = float(((result.get("render") or {}).get("probe") or {}).get("duration_seconds") or 0.0)
    record: dict[str, Any] = {
        "judge_id": judge.id,
        "route": panel.route,
        "sample_path": str(Path(result["model"]) / result["task"]["id"] / f"sample-{result['sample']}"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "frames": len(frames),
        "cost_usd": 0.0,
    }
    if not frames:
        record.update({"status": "failed", "error": "No frames could be read from the video."})
        return _save(sample_path, judge.id, record)

    prompt = build_judge_prompt(suite, task, frames, duration)
    record["prompt_sha256"] = prompt_sha256(JUDGE_SYSTEM_PROMPT, prompt)
    request = Request(
        system=JUDGE_SYSTEM_PROMPT,
        prompt=prompt,
        images=[sample_path / "frames" / frame["file"] for frame in frames],
        max_output_tokens=panel.max_output_tokens,
        reasoning_effort=judge.reasoning_effort,
    )
    error = "no attempt made"
    calls = []
    for _attempt in range(REPLY_ATTEMPTS):
        try:
            completion = route.complete(judge.target(panel.route), request)
        except ProviderError as failure:
            error = str(failure)[:1000]
            break
        calls.append(completion.metadata())
        record["cost_usd"] = round(record["cost_usd"] + float(completion.cost_usd or 0.0), 8)
        try:
            parsed = parse_judge_reply(completion.text, suite, task)
        except JudgeReplyError as failure:
            error = f"Unusable reply: {failure}"
            record["last_reply"] = completion.text[:4000]
            continue
        scored = judge_score(parsed, suite)
        record.update({"status": "complete", "calls": calls, "reply": parsed, **scored})
        record.pop("last_reply", None)
        return _save(sample_path, judge.id, record)
    record.update({"status": "failed", "error": error, "calls": calls})
    return _save(sample_path, judge.id, record)


def _save(sample_path: Path, judge_id: str, record: dict[str, Any]) -> dict[str, Any]:
    folder = sample_path / "judge"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{judge_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _public(record: dict[str, Any]) -> dict[str, Any]:
    """The part of a judge record that goes into result.json."""
    keep = ["judge_id", "route", "status", "score", "criteria", "reply", "error", "cost_usd", "frames", "prompt_sha256"]
    return {key: record[key] for key in keep if key in record}


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _read_list(path: Path) -> list[dict[str, Any]] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) and data else None
