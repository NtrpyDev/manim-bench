"""Load a benchmark suite and its tasks from YAML."""

from __future__ import annotations

import hashlib
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

import yaml

from manimbench.models import (
    Criterion,
    LayoutSettings,
    MustShow,
    PacingSettings,
    RuntimeSettings,
    ScoringSettings,
    Suite,
    Task,
)

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping in {path}")
    return data


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_task(path: Path) -> Task:
    data = load_yaml(path)
    missing = [key for key in ["id", "version", "title", "prompt", "must_show"] if key not in data]
    if missing:
        raise ValueError(f"Task {path} is missing required keys: {', '.join(missing)}")
    task_id = str(data["id"])
    if not _ID_PATTERN.match(task_id):
        raise ValueError(f"Task {path} has an invalid id: {task_id!r}")
    must_show = []
    for item in data["must_show"]:
        if not isinstance(item, dict) or "id" not in item or "text" not in item:
            raise ValueError(f"Task {path}: every must_show entry needs an id and text")
        if not _ID_PATTERN.match(str(item["id"])):
            raise ValueError(f"Task {path}: invalid must_show id {item['id']!r}")
        must_show.append(MustShow(id=str(item["id"]), text=" ".join(str(item["text"]).split())))
    if not must_show:
        raise ValueError(f"Task {path} must list at least one must_show item")
    ids = [item.id for item in must_show]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Task {path} has duplicate must_show ids")
    return Task(
        id=task_id,
        version=str(data["version"]),
        title=str(data["title"]),
        domains=[str(value) for value in data.get("domains", [])],
        prompt=str(data["prompt"]).strip(),
        must_show=must_show,
        judge_notes=str(data.get("judge_notes", "")).strip(),
        path=path,
    )


def load_suite(suite_path: Path) -> Suite:
    suite_path = suite_path.resolve()
    data = load_yaml(suite_path)
    task_paths = data.get("tasks", [])
    if not task_paths:
        raise ValueError(f"Suite {suite_path} must list at least one task")
    tasks = [load_task((suite_path.parent / str(item)).resolve()) for item in task_paths]
    task_ids = [task.id for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError(f"Suite {suite_path} has duplicate task ids")

    judge = data.get("judge", {}) or {}
    criteria = [
        Criterion(id=str(item["id"]), weight=float(item["weight"]), question=" ".join(str(item["question"]).split()))
        for item in judge.get("criteria", [])
    ]
    if not criteria:
        raise ValueError(f"Suite {suite_path} must define judge criteria")
    if sum(item.weight for item in criteria) <= 0:
        raise ValueError(f"Suite {suite_path}: judge criteria weights must sum to more than zero")

    scoring_data = dict(data.get("scoring", {}) or {})
    weights = scoring_data.get("weights", {}) or {}
    scoring = ScoringSettings(
        judge_weight=float(weights.get("judge", ScoringSettings.judge_weight)),
        layout_weight=float(weights.get("layout", ScoringSettings.layout_weight)),
        pacing_weight=float(weights.get("pacing", ScoringSettings.pacing_weight)),
        must_show_criterion=str(scoring_data.get("must_show_criterion", ScoringSettings.must_show_criterion)),
        layout=_settings(LayoutSettings, scoring_data.get("layout")),
        pacing=_settings(PacingSettings, scoring_data.get("pacing")),
    )
    if scoring.must_show_criterion not in {item.id for item in criteria}:
        raise ValueError(
            f"Suite {suite_path}: must_show_criterion {scoring.must_show_criterion!r} is not a judge criterion"
        )
    samples = int(data.get("samples_per_task", 1))
    if samples < 1:
        raise ValueError(f"Suite {suite_path}: samples_per_task must be at least 1")
    return Suite(
        id=str(data["id"]),
        version=str(data["version"]),
        title=str(data["title"]),
        description=" ".join(str(data.get("description", "")).split()),
        root=suite_path.parent,
        path=suite_path,
        runtime=_settings(RuntimeSettings, data.get("runtime")),
        scoring=scoring,
        criteria=criteria,
        samples_per_task=samples,
        tasks=tasks,
    )


def _settings(cls: type, values: Any):
    values = dict(values or {})
    known = {item.name: item for item in fields(cls)}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} keys: {', '.join(unknown)}")
    converted = {}
    for key, value in values.items():
        default = known[key].default
        converted[key] = type(default)(value) if isinstance(default, (int, float, str)) else value
    return cls(**converted)


def filter_tasks(suite: Suite, task_ids: list[str] | None) -> list[Task]:
    if not task_ids:
        return list(suite.tasks)
    requested = set(task_ids)
    missing = sorted(requested - {task.id for task in suite.tasks})
    if missing:
        raise ValueError(f"Unknown task IDs: {', '.join(missing)}")
    return [task for task in suite.tasks if task.id in requested]


def suite_hashes(suite: Suite, prompt_path: Path) -> dict[str, Any]:
    return {
        "prompt_sha256": file_sha256(prompt_path),
        "suite_sha256": file_sha256(suite.path),
        "task_sha256": {task.id: file_sha256(task.path) for task in suite.tasks},
    }
