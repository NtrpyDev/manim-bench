from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def discover_media_files(media_dir: Path) -> list[Path]:
    if not media_dir.exists():
        return []
    return sorted(
        path
        for path in media_dir.rglob("*")
        if path.suffix.lower() in {".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg"}
    )


def probe_media(media_file: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not media_file.exists():
        return {}

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=avg_frame_rate,r_frame_rate,width,height,codec_name",
        "-of",
        "json",
        str(media_file),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=20)
    if completed.returncode != 0:
        return {"ffprobe_error": completed.stderr.strip()}
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ffprobe_error": "invalid ffprobe JSON"}

    duration = None
    if data.get("format", {}).get("duration"):
        duration = float(data["format"]["duration"])

    video_stream = next((stream for stream in data.get("streams", []) if stream.get("width")), {})
    fps = _parse_fraction(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
    return {
        "duration_seconds": duration,
        "fps": fps,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name"),
    }


def _parse_fraction(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" not in value:
        return float(value)
    numerator, denominator = value.split("/", 1)
    denominator_value = float(denominator)
    if denominator_value == 0:
        return None
    return float(numerator) / denominator_value


class ManimCERuntime:
    def __init__(self, executable: str = "python"):
        self.executable = executable

    def command(
        self,
        solution_path: Path,
        media_dir: Path,
        scene_class: str = "MainScene",
        fps: int = 60,
        output_file: str = "result",
        quality: str = "-qh",
    ) -> list[str]:
        if self.executable == "python":
            prefix = ["python", "-m", "manim"]
        else:
            prefix = [self.executable]

        return [
            *prefix,
            quality,
            "--fps",
            str(fps),
            "--media_dir",
            str(media_dir),
            "--output_file",
            output_file,
            "--disable_caching",
            "--flush_cache",
            "--progress_bar",
            "none",
            str(solution_path),
            scene_class,
        ]

    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": "manimce",
            "python_version": sys.version,
            "executable": self.executable,
            "manim_version": self._manim_version(),
        }

    def _manim_version(self) -> str | None:
        command = ["python", "-m", "manim", "--version"] if self.executable == "python" else [self.executable, "--version"]
        try:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        output = (completed.stdout or completed.stderr).strip()
        return output or None
