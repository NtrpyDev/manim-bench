"""Render one scene inside the sandbox and record what is on screen.

This file runs inside the container, not on the host. It is mounted read-only
and started as ``python /harness/harness.py ...``. It must not import anything
from ``manimbench``: only the standard library and Manim are available there.

It does two things:

1. Renders the scene through Manim's own command line, so the video is exactly
   what ``manim render`` would produce.
2. Writes down the text that is on screen and where it sits: at the start and
   end of every ``play`` (which includes every ``wait``), and once a second
   during long ones. The host reads that record to check layout without
   guessing from the source code.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

LAYOUT_SCHEMA = 2
MAX_SNAPSHOTS = 2000
MAX_ITEMS_PER_SNAPSHOT = 400
MAX_STRING = 300
MIN_VISIBLE_OPACITY = 0.05
# Animations at least this long are also sampled while they run, so one long
# animation cannot hide what happens inside it. Shorter ones are transitions.
MIN_SAMPLED_PLAY_SECONDS = 3.0
SAMPLE_SECONDS = 1.0


class _Recorder:
    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.scene_class: str | None = None
        self.camera_class: str | None = None
        self.truncated = False
        self.play_start = 0.0
        self.last_sample = 0.0

    def begin_play(self, scene: Any, animations: tuple[Any, ...]) -> None:
        try:
            self.play_start = float(scene.time)
        except Exception:
            self.play_start = 0.0
        self.last_sample = 0.0
        self.capture(scene, animations, "start")

    def sample(self, scene: Any, elapsed: float) -> None:
        """Called on every frame of an animation; records about once a second in long ones."""
        try:
            duration = float(getattr(scene, "duration", 0.0) or 0.0)
            if duration < MIN_SAMPLED_PLAY_SECONDS:
                return
            if elapsed - self.last_sample < SAMPLE_SECONDS or duration - elapsed < SAMPLE_SECONDS / 2:
                return
        except Exception:
            return
        self.last_sample = elapsed
        self.capture(scene, (), "mid", time=self.play_start + elapsed)

    def capture(self, scene: Any, animations: tuple[Any, ...], phase: str, time: float | None = None) -> None:
        if len(self.snapshots) >= MAX_SNAPSHOTS:
            self.truncated = True
            return
        try:
            self.snapshots.append(_snapshot(scene, animations, phase, time))
            self.scene_class = type(scene).__name__
            self.camera_class = type(scene.camera).__name__
        except Exception:  # A capture problem must never break the render.
            if len(self.errors) < 20:
                self.errors.append(traceback.format_exc(limit=3))

    def payload(self) -> dict[str, Any]:
        import manim

        return {
            "schema": LAYOUT_SCHEMA,
            "manim_version": manim.__version__,
            "python_version": sys.version.split()[0],
            "scene_class": self.scene_class,
            "camera_class": self.camera_class,
            "snapshots": self.snapshots,
            "truncated": self.truncated,
            "capture_errors": self.errors,
        }


def _snapshot(scene: Any, animations: tuple[Any, ...], phase: str, time: float | None) -> dict[str, Any]:
    camera = scene.camera
    frame = _frame(camera)
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    mobject_count = 0
    for top in list(scene.mobjects) + list(getattr(scene, "foreground_mobjects", [])):
        mobject_count += 1
        _collect_text(top, items, seen)
    return {
        "time": round(float(scene.time if time is None else time), 4),
        "phase": phase,
        "animations": [type(item).__name__ for item in animations][:12],
        "frame": frame,
        "projection": "3d" if "ThreeD" in type(camera).__name__ else "2d",
        "mobject_count": mobject_count,
        "text": items[:MAX_ITEMS_PER_SNAPSHOT],
    }


def _frame(camera: Any) -> dict[str, float]:
    center = camera.frame_center
    return {
        "cx": round(float(center[0]), 4),
        "cy": round(float(center[1]), 4),
        "width": round(float(camera.frame_width), 4),
        "height": round(float(camera.frame_height), 4),
    }


def _text_kind(mobject: Any) -> str | None:
    """Return a short kind for text-like mobjects, else None."""
    from manim import DecimalNumber, MarkupText, Paragraph, Text
    from manim.mobject.text.tex_mobject import SingleStringMathTex

    if isinstance(mobject, SingleStringMathTex):
        return "tex"
    if isinstance(mobject, (Text, MarkupText, Paragraph)):
        return "text"
    if isinstance(mobject, DecimalNumber):
        return "number"
    return None


def _collect_text(mobject: Any, items: list[dict[str, Any]], seen: set[int]) -> None:
    if id(mobject) in seen or len(items) >= MAX_ITEMS_PER_SNAPSHOT:
        return
    seen.add(id(mobject))
    _skip_brackets(mobject, seen)
    kind = _text_kind(mobject)
    if kind is not None:
        item = _text_item(mobject, kind)
        if item is not None:
            items.append(item)
        return  # A text mobject is one item; its glyphs are not separate labels.
    for child in getattr(mobject, "submobjects", []):
        _collect_text(child, items, seen)


def _skip_brackets(mobject: Any, seen: set[int]) -> None:
    """A matrix's brackets are drawn with LaTeX but are not text a viewer reads."""
    from manim import Matrix

    if isinstance(mobject, Matrix):
        for bracket in getattr(mobject, "brackets", []) or []:
            seen.add(id(bracket))


def _text_item(mobject: Any, kind: str) -> dict[str, Any] | None:
    if not mobject.family_members_with_points():
        return None
    opacity = _opacity(mobject)
    if opacity < MIN_VISIBLE_OPACITY:
        return None
    box = [
        float(mobject.get_left()[0]),
        float(mobject.get_bottom()[1]),
        float(mobject.get_right()[0]),
        float(mobject.get_top()[1]),
    ]
    if not all(math.isfinite(value) for value in box):
        return None
    if box[2] - box[0] <= 0 or box[3] - box[1] <= 0:
        return None
    return {
        "id": id(mobject),
        "kind": kind,
        "string": _string(mobject, kind)[:MAX_STRING],
        "box": [round(value, 4) for value in box],
        "font_size": _font_size(mobject),
        "glyph_height": _glyph_height(mobject),
        "opacity": round(opacity, 3),
    }


def _string(mobject: Any, kind: str) -> str:
    if kind == "tex":
        return str(getattr(mobject, "tex_string", ""))
    if kind == "number":
        try:
            return str(mobject._get_num_string(mobject.number))  # What is drawn, such as "+1.00".
        except Exception:
            pass
        try:
            return str(mobject.get_value())
        except Exception:
            return ""
    return str(getattr(mobject, "original_text", getattr(mobject, "text", "")))


def _font_size(mobject: Any) -> float | None:
    try:
        value = float(mobject.font_size)
    except Exception:
        return None
    return round(value, 2) if math.isfinite(value) else None


def _glyph_height(mobject: Any) -> float | None:
    """Height of the tallest single character, in scene units.

    The font size Manim reports is fooled by sizing inside LaTeX, such as
    ``\\tiny``. The drawn characters are not.
    """
    try:
        heights = [float(member.height) for member in mobject.family_members_with_points()]
    except Exception:
        return None
    heights = [value for value in heights if math.isfinite(value) and value > 0]
    return round(max(heights), 4) if heights else None


def _opacity(mobject: Any) -> float:
    best = 0.0
    for member in mobject.family_members_with_points():
        for getter in ("get_fill_opacity", "get_stroke_opacity"):
            try:
                best = max(best, float(getattr(member, getter)()))
            except Exception:
                continue
        if best >= 1.0:
            break
    return best


def _install(recorder: _Recorder) -> None:
    from manim import Scene

    original_play = Scene.play
    original_update = Scene.update_to_time

    def play(self: Any, *args: Any, **kwargs: Any) -> Any:
        recorder.begin_play(self, args)
        result = original_play(self, *args, **kwargs)
        recorder.capture(self, args, "end")
        return result

    def update_to_time(self: Any, t: float) -> None:
        original_update(self, t)
        recorder.sample(self, float(t))

    Scene.play = play  # type: ignore[method-assign]
    Scene.update_to_time = update_to_time  # type: ignore[method-assign]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("solution")
    parser.add_argument("--scene", default="MainScene")
    parser.add_argument("--quality", default="h", choices=["l", "m", "h", "p", "k"])
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--media-dir", required=True)
    parser.add_argument("--layout", required=True)
    args = parser.parse_args(argv)

    recorder = _Recorder()
    _install(recorder)

    from manim.__main__ import main as manim_main

    exit_code = 0
    try:
        manim_main(
            args=[
                "render",
                f"-q{args.quality}",
                "--fps",
                str(args.fps),
                "--format",
                "mp4",
                "--media_dir",
                args.media_dir,
                "--output_file",
                "result",
                "--disable_caching",
                "--progress_bar",
                "none",
                args.solution,
                args.scene,
            ],
            standalone_mode=False,
        )
    except SystemExit as error:
        exit_code = int(error.code) if isinstance(error.code, int) else 1
    except BaseException:
        traceback.print_exc()
        exit_code = 1
    finally:
        Path(args.layout).write_text(json.dumps(recorder.payload()), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
