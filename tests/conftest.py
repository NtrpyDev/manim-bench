"""Shared test helpers.

No test may call a real model. ``MANIMBENCH_FORBID_LIVE_CALLS`` is set for the
whole session, which makes both real transports refuse. Tests talk to fake
routes instead.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
import pytest

os.environ["MANIMBENCH_FORBID_LIVE_CALLS"] = "1"

from manimbench.models import RenderResult  # noqa: E402
from manimbench.providers.base import Completion, ProviderError, Request  # noqa: E402
from manimbench.sandbox.settings import SandboxSettings, load_sandbox_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCENES = FIXTURES / "scenes"

GOOD_SOURCE = "from manim import *\n\n\nclass MainScene(Scene):\n    def construct(self):\n        self.play(Write(Text('hello')))\n"


def write_video(
    path: Path,
    *,
    seconds: float = 20.0,
    fps: int = 10,
    size: tuple[int, int] = (320, 180),
    kind: str = "moving",
) -> Path:
    """Write a small synthetic video.

    kind: ``moving`` (a square travels the whole time), ``static`` (the same
    picture throughout), ``blank`` (nothing but background), or ``stall`` (moves
    for the first quarter, then holds still).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    total = int(seconds * fps)
    for index in range(total):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        if kind != "blank":
            progress = index / max(1, total - 1)
            if kind == "static":
                progress = 0.5
            elif kind == "stall":
                progress = min(progress, 0.25)
            x = int(20 + progress * (width - 80))
            cv2.rectangle(frame, (x, 60), (x + 40, 100), (255, 255, 255), -1)
            cv2.rectangle(frame, (10, 10), (120, 30), (200, 200, 200), -1)
        writer.write(frame)
    writer.release()
    return path


def text_item(string: str, box: list[float], *, font_size: float = 36.0, opacity: float = 1.0, kind: str = "text", ident: int = 0) -> dict[str, Any]:
    return {"id": ident or abs(hash(string)) % 10**9, "kind": kind, "string": string, "box": box, "font_size": font_size, "opacity": opacity}


def snapshot(time: float, text: list[dict[str, Any]], *, projection: str = "2d", frame: dict[str, float] | None = None) -> dict[str, Any]:
    return {
        "time": time,
        "animations": ["Wait"],
        "frame": frame or {"cx": 0.0, "cy": 0.0, "width": 14.2222, "height": 8.0},
        "projection": projection,
        "mobject_count": len(text),
        "text": text,
    }


def clean_layout(seconds: float = 20.0) -> dict[str, Any]:
    """A layout record with two well-placed labels on screen the whole time."""
    labels = [text_item("Title", [-2.0, 3.0, 2.0, 3.5]), text_item("y = x^2", [-1.0, -3.5, 1.0, -3.0], kind="tex")]
    steps = 5
    return {
        "schema": 2,
        "manim_version": "0.22.1",
        "python_version": "3.14.10",
        "scene_class": "MainScene",
        "camera_class": "Camera",
        "snapshots": [snapshot(seconds * index / steps, labels) for index in range(1, steps + 1)],
        "truncated": False,
        "capture_errors": [],
    }


class FakeSandbox:
    """Stands in for the container. Writes a synthetic video and layout record instead of rendering.

    ``behavior`` maps a marker found in the source code to what the fake render
    does: ``ok``, ``crash``, ``timeout``, ``static``, ``blank``, ``short``.
    The default is ``ok``.
    """

    name = "fake"

    def __init__(self, settings: SandboxSettings | None = None, layout: dict[str, Any] | None = None):
        self.settings = settings or load_sandbox_settings()
        self.layout = layout
        self.rendered: list[Path] = []

    def ensure_image(self) -> None:
        return None

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "image": self.settings.image,
            "image_digest": self.settings.digest,
            "manim_version": self.settings.manim_version,
            "python_version": self.settings.python_version,
        }

    def render(self, sample_dir: Path, *, timeout_seconds: int, quality: str, fps: int, scene_class: str) -> RenderResult:
        from manimbench.media import probe_video

        self.rendered.append(sample_dir)
        source = (sample_dir / "solution.py").read_text(encoding="utf-8")
        behavior = next((name for name in ["crash", "timeout", "static", "blank", "short"] if f"# fake:{name}" in source), "ok")
        (sample_dir / "logs").mkdir(exist_ok=True)
        (sample_dir / "logs" / "stderr.log").write_text("Traceback: boom\n" if behavior == "crash" else "", encoding="utf-8")
        if behavior in {"crash", "timeout"}:
            return RenderResult(
                exit_code=None if behavior == "timeout" else 1,
                timed_out=behavior == "timeout",
                elapsed_seconds=0.1,
                video=None,
                probe={},
                layout_path=None,
                command=["fake"],
                sandbox=self.metadata(),
            )
        seconds = 5.0 if behavior == "short" else 20.0
        kind = behavior if behavior in {"static", "blank"} else "moving"
        video = write_video(sample_dir / "media" / "videos" / "solution" / "480p15" / "result.mp4", seconds=seconds, kind=kind)
        (sample_dir / "layout.json").write_text(json.dumps(self.layout or clean_layout(seconds)), encoding="utf-8")
        return RenderResult(
            exit_code=0,
            timed_out=False,
            elapsed_seconds=0.1,
            video=str(video.relative_to(sample_dir)),
            probe=probe_video(video),
            layout_path="layout.json",
            command=["fake"],
            sandbox=self.metadata(),
        )


class FakeRoute:
    """A route that answers from a function instead of a model, and remembers every call."""

    def __init__(self, reply: Callable[[dict[str, Any], Request], str | Completion | Exception], name: str = "fake"):
        self.name = name
        self.reply = reply
        self.calls: list[tuple[dict[str, Any], Request]] = []

    def complete(self, target: dict[str, Any], request: Request) -> Completion:
        self.calls.append((target, request))
        answer = self.reply(target, request)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, Completion):
            return answer
        return Completion(
            text=answer,
            route=self.name,
            requested_model=str(target["model"]),
            response_model=str(target["model"]),
            request_id=f"req-{len(self.calls)}",
            finish_reason="stop",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.01,
            cost_basis="fake",
            elapsed_seconds=0.01,
        )


def good_judge_reply(task, scores: dict[str, float] | None = None, verdict: str = "yes") -> str:
    """A well-formed judge reply for a task, as JSON text."""
    scores = scores or {"correctness": 4, "explanation": 3, "clarity": 3}
    return json.dumps(
        {
            "must_show": {item.id: {"verdict": verdict, "evidence": "Frame 2."} for item in task.must_show},
            "criteria": {name: {"score": value, "evidence": "Frame 3."} for name, value in scores.items()},
            "math_errors": [],
            "summary": "Clear and correct.",
        }
    )


@pytest.fixture
def suite():
    from manimbench.paths import DEFAULT_SUITE_PATH
    from manimbench.tasks import load_suite

    return load_suite(DEFAULT_SUITE_PATH)


@pytest.fixture
def fake_sandbox() -> FakeSandbox:
    return FakeSandbox()


def docker_ready() -> bool:
    """True when Docker is usable and the pinned image is on this machine."""
    engine = shutil.which("docker") or shutil.which("podman")
    if not engine:
        return False
    try:
        reference = load_sandbox_settings().reference
        done = subprocess.run([engine, "image", "inspect", reference], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


__all__ = [
    "FIXTURES",
    "GOOD_SOURCE",
    "REPO_ROOT",
    "SCENES",
    "FakeRoute",
    "FakeSandbox",
    "ProviderError",
    "clean_layout",
    "docker_ready",
    "good_judge_reply",
    "snapshot",
    "text_item",
    "write_video",
]
