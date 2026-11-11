"""Turn a run folder into a report: JSON data, videos, and static HTML pages.

Everything written here is safe to publish. It holds no paths from this
machine and no render logs.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from manimbench.html import render_pages
from manimbench.models import Suite
from manimbench.paths import DEFAULT_SUITE_PATH
from manimbench.registry import load_models
from manimbench.rendering import load_manifest, load_results
from manimbench.scoring.aggregate import summarize_model
from manimbench.tasks import load_suite

SCHEMA_VERSION = "0.7.0"


def build_report_data(run_dir: Path, suite: Suite) -> dict[str, Any]:
    """Everything the report shows, as plain data."""
    manifest = load_manifest(run_dir)
    if manifest["suite"]["id"] != suite.id or manifest["suite"]["version"] != suite.version:
        raise ValueError(f"Run {run_dir.name} was made with suite {manifest['suite']['id']}, not {suite.id}")
    task_ids = list(manifest["suite"]["task_ids"])
    samples_per_task = int(manifest["samples_per_task"])
    results = load_results(run_dir)
    registry = load_models()

    rows = []
    for model in manifest["models"]:
        own = [result for result in results if result["model"] == model]
        summary = summarize_model(own, task_ids, samples_per_task)
        entry = registry.get(model)
        rows.append(
            {
                "model": model,
                "name": entry.name if entry else model,
                "vendor": entry.vendor if entry else "",
                **summary,
                "components": _component_means(own),
                "cost": _cost(own),
            }
        )
    ranked = sorted([row for row in rows if row["complete"]], key=lambda row: row["quality"], reverse=True)
    unranked = sorted(
        [row for row in rows if not row["complete"]],
        key=lambda row: row["automated"] if row["automated"] is not None else -1.0,
        reverse=True,
    )
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position
    for row in unranked:
        row["rank"] = None

    judges = sorted({record["judge_id"] for result in results for record in result.get("judgements", [])})
    leaderboard = {
        "schema_version": SCHEMA_VERSION,
        "run_id": manifest["run_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": manifest["suite"],
        "scoring_version": manifest["scoring_version"],
        "manim_version": manifest["sandbox"].get("manim_version"),
        "samples_per_task": samples_per_task,
        "official": bool(manifest.get("official")),
        "complete": bool(rows) and all(row["complete"] for row in rows),
        "weights": {
            "judge": suite.scoring.judge_weight,
            "layout": suite.scoring.layout_weight,
            "pacing": suite.scoring.pacing_weight,
        },
        "criteria": [{"id": item.id, "weight": item.weight, "question": item.question} for item in suite.criteria],
        "judges": judges,
        "models": ranked + unranked,
    }
    return {
        "leaderboard": leaderboard,
        "results": [_public_result(result) for result in results],
        "models": [
            {"id": row["model"], "name": row["name"], "vendor": row["vendor"]} for row in leaderboard["models"]
        ],
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "domains": task.domains,
                "prompt": task.prompt,
                "must_show": [{"id": item.id, "text": item.text} for item in task.must_show],
            }
            for task in suite.tasks
            if task.id in task_ids
        ],
        "manifest": manifest,
    }


def write_report(run_dir: Path, output_dir: Path, suite_path: Path = DEFAULT_SUITE_PATH) -> Path:
    suite = load_suite(suite_path)
    data = build_report_data(run_dir, suite)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "data").mkdir(parents=True)
    for name in ["leaderboard", "results", "models", "tasks", "manifest"]:
        (output_dir / "data" / f"{name}.json").write_text(json.dumps(data[name], indent=2), encoding="utf-8")
    for result in data["results"]:
        sample = run_dir / result["model"] / result["task"]["id"] / f"sample-{result['sample']}"
        if result["video"]:
            raw = json.loads((sample / "result.json").read_text(encoding="utf-8"))
            _copy(sample / raw["render"]["video"], output_dir / result["video"])
        _copy(sample / "solution.py", output_dir / result["source"])
    for relative, page in render_pages(data).items():
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")
    return output_dir / "index.html"


def _copy(source: Path, target: Path) -> None:
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    """One sample, with nothing machine-specific in it."""
    base = f"{result['model']}/{result['task']['id']}/sample-{result['sample']}"
    render = result.get("render") or {}
    layout = result.get("layout") or {}
    pacing = result.get("pacing") or {}
    return {
        "model": result["model"],
        "task": result["task"],
        "sample": result["sample"],
        "score": result["score"],
        "gates": result["gates"],
        "layout": {key: layout.get(key) for key in ["available", "score", "problem_seconds", "issues", "reason"]} if layout else None,
        "pacing": {key: pacing.get(key) for key in ["available", "score", "active_share", "longest_still_seconds", "dead_seconds", "blank_share"]} if pacing else None,
        "judge": result["judge"],
        "judgements": result.get("judgements", []),
        "video": f"videos/{base}.mp4" if render.get("video") else None,
        "source": f"sources/{base}.py",
        "source_sha256": result["source"]["sha256"],
        "generation": result["source"]["generation"],
        "render": {
            "exit_code": render.get("exit_code"),
            "timed_out": render.get("timed_out"),
            "elapsed_seconds": render.get("elapsed_seconds"),
            **{key: (render.get("probe") or {}).get(key) for key in ["duration_seconds", "fps", "width", "height"]},
        } if render else None,
    }


def _component_means(results: list[dict[str, Any]]) -> dict[str, float | None]:
    """Mean of each score part over the samples that passed the gates."""
    means: dict[str, float | None] = {}
    for name in ["judge", "layout", "pacing"]:
        values = [
            float(result["score"]["components"][name])
            for result in results
            if result["gates"]["passed"] and name in result["score"].get("components", {})
        ]
        means[name] = round(sum(values) / len(values), 2) if values else None
    return means


def _cost(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Generation and judging cost. A sample with no reported cost is counted, not guessed."""
    generation = 0.0
    unknown = 0
    basis: set[str] = set()
    judging = 0.0
    for result in results:
        info = result["source"]["generation"]
        cost = info.get("cost_usd")
        if isinstance(cost, (int, float)):
            generation += float(cost)
            if info.get("cost_basis"):
                basis.add(str(info["cost_basis"]))
        elif info.get("route") != "manual":
            unknown += 1
        judging += sum(float(record.get("cost_usd") or 0.0) for record in result.get("judgements", []))
    return {
        "generation_usd": round(generation, 6),
        "judging_usd": round(judging, 6),
        "samples_without_cost": unknown,
        "basis": sorted(basis),
    }
