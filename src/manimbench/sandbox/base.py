from __future__ import annotations

from pathlib import Path
from typing import Protocol

from manimbench.models import RenderResult
from manimbench.runtime.manimce import ManimCERuntime


class SandboxBackend(Protocol):
    name: str
    official: bool

    def render(
        self,
        run_dir: Path,
        solution_path: Path,
        runtime: ManimCERuntime,
        timeout_seconds: int,
        fps: int,
        scene_class: str,
    ) -> RenderResult:
        ...
