from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Task:
    id: str
    version: str
    difficulty: str
    domains: list[str]
    title: str
    prompt: str
    path: Path
    runtime_limit_seconds: int = 120
    required_labels: list[str] = field(default_factory=list)
    required_visuals: list[str] = field(default_factory=list)
    automated_checks: dict[str, Any] = field(default_factory=dict)
    rubric: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Suite:
    id: str
    version: str
    title: str
    description: str
    root: Path
    runtime: dict[str, Any]
    tasks: list[Task]


@dataclass(frozen=True)
class ModelOutput:
    model: str
    task_id: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderResult:
    backend: str
    official: bool
    command: list[str]
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    media_files: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ScoreResult:
    task_id: str
    model: str
    passed: bool
    automated_score: float
    checks: dict[str, Any]
    rubric: dict[str, Any]
    artifacts: dict[str, str]
