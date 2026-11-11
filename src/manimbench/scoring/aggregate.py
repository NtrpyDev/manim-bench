"""Combine the parts of a sample into one score, and samples into model scores."""

from __future__ import annotations

import random
from typing import Any

from manimbench.models import ScoringSettings

BOOTSTRAP_ROUNDS = 2000
BOOTSTRAP_SEED = 20261110


def sample_score(
    gates: dict[str, Any],
    layout: dict[str, Any] | None,
    pacing: dict[str, Any] | None,
    judge: dict[str, Any] | None,
    settings: ScoringSettings,
) -> dict[str, Any]:
    """One sample's score.

    ``quality`` is the ranked number and needs the judge. ``automated`` uses only
    the measured parts and is there so a run can be inspected before judging.
    A part that could not be measured is left out and the rest is rescaled.
    """
    if not gates["passed"]:
        return {"status": "failed_gate", "quality": 0.0, "automated": 0.0, "components": {}, "weights": {}}

    measured: dict[str, tuple[float, float]] = {}
    if layout and layout.get("available") and layout.get("score") is not None:
        measured["layout"] = (float(layout["score"]), settings.layout_weight)
    if pacing and pacing.get("available") and pacing.get("score") is not None:
        measured["pacing"] = (float(pacing["score"]), settings.pacing_weight)
    automated = _weighted(measured)

    judged = dict(measured)
    judge_ready = bool(judge) and judge.get("status") in {"complete", "partial"} and judge.get("score") is not None
    if judge_ready:
        judged["judge"] = (float(judge["score"]), settings.judge_weight)
    return {
        "status": "scored" if judge_ready else "awaiting_judge",
        "quality": _weighted(judged) if judge_ready else None,
        "automated": automated,
        "components": {name: value for name, (value, _weight) in judged.items()},
        "weights": {name: weight for name, (_value, weight) in judged.items()},
    }


def _weighted(parts: dict[str, tuple[float, float]]) -> float | None:
    total = sum(weight for _value, weight in parts.values())
    if total <= 0:
        return None
    return round(sum(value * weight for value, weight in parts.values()) / total, 2)


def summarize_model(results: list[dict[str, Any]], task_ids: list[str], samples_per_task: int) -> dict[str, Any]:
    """Aggregate one model's sample results.

    A task's score is the mean over its samples, and the model's score is the
    mean over tasks, so every task counts the same. A failed gate counts as
    zero. A sample that was never generated or never rendered is missing, not
    zero, and makes the model's result incomplete.
    """
    by_task: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in task_ids}
    for result in results:
        task_id = result["task"]["id"]
        if task_id in by_task:
            by_task[task_id].append(result)

    tasks: dict[str, Any] = {}
    quality_lists: dict[str, list[float]] = {}
    automated_lists: dict[str, list[float]] = {}
    failures: dict[str, int] = {}
    expected = len(task_ids) * samples_per_task
    scored = awaiting = failed_gate = 0
    for task_id in task_ids:
        entries = by_task[task_id]
        qualities: list[float] = []
        automated: list[float] = []
        for entry in entries:
            score = entry["score"]
            if score["status"] == "failed_gate":
                failed_gate += 1
                failure = entry["gates"].get("failure") or "unknown"
                failures[failure] = failures.get(failure, 0) + 1
                qualities.append(0.0)
                automated.append(0.0)
            elif score["status"] == "scored":
                scored += 1
                qualities.append(float(score["quality"]))
                if score["automated"] is not None:
                    automated.append(float(score["automated"]))
            else:
                awaiting += 1
                if score["automated"] is not None:
                    automated.append(float(score["automated"]))
        complete = len(entries) >= samples_per_task and len(qualities) == len(entries)
        quality_lists[task_id] = qualities
        automated_lists[task_id] = automated
        tasks[task_id] = {
            "samples": len(entries),
            "expected_samples": samples_per_task,
            "complete": complete,
            "quality": _mean(qualities) if complete else None,
            "automated": _mean(automated),
            "sample_qualities": [round(value, 2) for value in qualities] if complete else None,
            "passed_gates": sum(1 for entry in entries if entry["gates"]["passed"]),
        }

    present = sum(len(by_task[task_id]) for task_id in task_ids)
    complete = all(tasks[task_id]["complete"] for task_id in task_ids)
    # From the unrounded sample values, so the score always sits inside its own interval.
    quality = (
        round(sum(sum(quality_lists[task_id]) / len(quality_lists[task_id]) for task_id in task_ids) / len(task_ids), 2)
        if complete and task_ids
        else None
    )
    interval = _bootstrap_interval([quality_lists[task_id] for task_id in task_ids]) if complete else None
    automated_tasks = [tasks[task_id]["automated"] for task_id in task_ids if tasks[task_id]["automated"] is not None]
    return {
        "complete": complete,
        "quality": quality,
        "quality_interval": interval,
        "automated": _mean(automated_tasks) if len(automated_tasks) == len(task_ids) else None,
        "samples": {
            "expected": expected,
            "present": present,
            "missing": max(0, expected - present),
            "scored": scored,
            "awaiting_judge": awaiting,
            "failed_gate": failed_gate,
        },
        "gate_pass_rate": round(100.0 * (present - failed_gate) / present, 1) if present else None,
        "failures": dict(sorted(failures.items())),
        "tasks": tasks,
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _bootstrap_interval(task_samples: list[list[float]]) -> list[float] | None:
    """A 95% interval for the model score, resampling samples inside each task."""
    if not task_samples or any(not samples for samples in task_samples):
        return None
    generator = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_ROUNDS):
        total = 0.0
        for samples in task_samples:
            total += sum(generator.choice(samples) for _ in samples) / len(samples)
        means.append(total / len(task_samples))
    means.sort()
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(0.975 * (len(means) - 1))]
    return [round(low, 2), round(high, 2)]
