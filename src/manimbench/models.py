"""Plain data types shared across the benchmark."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MustShow:
    """One thing a task's video has to show. Shown to the model and to the judge."""

    id: str
    text: str


@dataclass(frozen=True)
class Task:
    id: str
    version: str
    title: str
    domains: list[str]
    prompt: str
    must_show: list[MustShow]
    judge_notes: str
    path: Path


@dataclass(frozen=True)
class Criterion:
    """One judged quality, scored 0 to 4."""

    id: str
    weight: float
    question: str


@dataclass(frozen=True)
class RuntimeSettings:
    scene_class: str = "MainScene"
    quality: str = "h"
    fps: int = 60
    min_duration_seconds: float = 15.0
    max_duration_seconds: float = 120.0
    render_timeout_seconds: int = 900


@dataclass(frozen=True)
class LayoutSettings:
    clipping_points: float = 40.0
    overlap_points: float = 40.0
    small_text_points: float = 20.0
    saturation_share: float = 0.25
    min_font_size: float = 16.0
    min_glyph_height: float = 0.075
    overlap_ratio: float = 0.15
    frame_tolerance: float = 0.05


@dataclass(frozen=True)
class PacingSettings:
    max_still_seconds: float = 8.0
    min_active_seconds: float = 2.0
    min_active_share: float = 0.10
    max_blank_share: float = 0.5


@dataclass(frozen=True)
class ScoringSettings:
    judge_weight: float = 65.0
    layout_weight: float = 25.0
    pacing_weight: float = 10.0
    must_show_criterion: str = "task_coverage"
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    pacing: PacingSettings = field(default_factory=PacingSettings)


@dataclass(frozen=True)
class Suite:
    id: str
    version: str
    title: str
    description: str
    root: Path
    path: Path
    runtime: RuntimeSettings
    scoring: ScoringSettings
    criteria: list[Criterion]
    samples_per_task: int
    tasks: list[Task]


@dataclass(frozen=True)
class RenderResult:
    exit_code: int | None
    timed_out: bool
    elapsed_seconds: float
    video: str | None
    probe: dict[str, Any]
    layout_path: str | None
    command: list[str]
    sandbox: dict[str, Any]
