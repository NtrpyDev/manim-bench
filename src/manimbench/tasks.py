from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from manimbench.models import Suite, Task


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_task(path: Path) -> Task:
    data = load_yaml(path)
    if "tasks" in data:
        raise ValueError(f"Task pack {path} cannot be loaded as a single task")
    return task_from_data(data, path)


def task_from_data(data: dict[str, Any], path: Path, defaults: dict[str, Any] | None = None) -> Task:
    merged = {**(defaults or {}), **data}
    required = ["id", "version", "difficulty", "domains", "title", "prompt"]
    missing = [key for key in required if key not in merged]
    if missing:
        raise ValueError(f"Task {path} is missing required keys: {', '.join(missing)}")

    return Task(
        id=str(merged["id"]),
        version=str(merged["version"]),
        difficulty=str(merged["difficulty"]),
        domains=list(merged.get("domains", [])),
        title=str(merged["title"]),
        prompt=str(merged["prompt"]).strip(),
        path=path,
        runtime_limit_seconds=int(merged.get("runtime_limit_seconds", 120)),
        required_labels=_string_list(merged.get("required_labels", [])),
        required_visuals=_string_list(merged.get("required_visuals", [])),
        automated_checks=dict(merged.get("automated_checks", {})),
        rubric=dict(merged.get("rubric", {})),
    )


def load_task_pack(path: Path) -> list[Task]:
    data = load_yaml(path)
    task_items = data.get("tasks")
    if not isinstance(task_items, list) or not task_items:
        raise ValueError(f"Task pack {path} must define a non-empty tasks list")
    defaults = dict(data.get("defaults", {}))
    return [task_from_data(item, path, defaults) for item in task_items]


def _string_list(values: list[Any]) -> list[str]:
    return [str(value) for value in values]


def load_suite(suite_path: Path) -> Suite:
    suite_path = suite_path.resolve()
    data = load_yaml(suite_path)
    task_paths = data.get("tasks", [])
    task_pack_paths = data.get("task_packs", [])
    if not task_paths and not task_pack_paths:
        raise ValueError(f"Suite {suite_path} must define a non-empty tasks or task_packs list")

    tasks = [load_task((suite_path.parent / Path(task_path)).resolve()) for task_path in task_paths]
    for task_pack_path in task_pack_paths:
        tasks.extend(load_task_pack((suite_path.parent / Path(task_pack_path)).resolve()))
    return Suite(
        id=str(data["id"]),
        version=str(data["version"]),
        title=str(data["title"]),
        description=str(data.get("description", "")).strip(),
        root=suite_path.parent,
        runtime=dict(data.get("runtime", {})),
        tasks=tasks,
    )


def filter_tasks(suite: Suite, task_ids: list[str] | None) -> list[Task]:
    if not task_ids:
        return suite.tasks
    requested = set(task_ids)
    tasks = [task for task in suite.tasks if task.id in requested]
    found = {task.id for task in tasks}
    missing = sorted(requested - found)
    if missing:
        raise ValueError(f"Unknown task IDs: {', '.join(missing)}")
    return tasks


def suite_hashes(suite: Suite, prompt_path: Path) -> dict[str, Any]:
    return {
        "prompt_sha256": file_sha256(prompt_path),
        "task_sha256": {task.id: file_sha256(task.path) for task in suite.tasks},
    }
