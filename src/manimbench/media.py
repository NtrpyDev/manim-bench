"""Read facts and frames out of a rendered video."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import cv2
import numpy as np


def probe_video(path: Path) -> dict[str, Any]:
    """Duration, frame rate and size of a video, or an empty dict if unreadable."""
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return {}
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        capture.release()
    if fps <= 0 or frames <= 0:
        return {}
    return {
        "duration_seconds": round(frames / fps, 4),
        "fps": round(fps, 4),
        "frames": frames,
        "width": width,
        "height": height,
    }


def sample_gray_frames(path: Path, *, per_second: float = 5.0, width: int = 320) -> Iterator[tuple[float, np.ndarray]]:
    """Yield ``(time, small grayscale frame)`` at a steady rate through the video."""
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            return
        step = max(1, round(fps / per_second))
        index = 0
        while True:
            ok = capture.grab()
            if not ok:
                break
            if index % step == 0:
                ok, frame = capture.retrieve()
                if not ok:
                    break
                yield index / fps, _small_gray(frame, width)
            index += 1
    finally:
        capture.release()


def _small_gray(frame: np.ndarray, width: int) -> np.ndarray:
    height = max(1, round(frame.shape[0] * width / frame.shape[1]))
    small = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def extract_frames(path: Path, times: list[float], output_dir: Path, *, width: int = 1280) -> list[dict[str, Any]]:
    """Save one JPEG per requested time. Returns ``[{"time", "file"}]`` for frames written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(path))
    written: list[dict[str, Any]] = []
    try:
        if not capture.isOpened():
            return written
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or total <= 0:
            return written
        for number, moment in enumerate(times, start=1):
            index = min(total - 1, max(0, round(moment * fps)))
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                continue
            if frame.shape[1] > width:
                height = max(1, round(frame.shape[0] * width / frame.shape[1]))
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            name = f"frame_{number:02d}.jpg"
            if cv2.imwrite(str(output_dir / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 88]):
                written.append({"time": round(index / fps, 3), "file": name})
    finally:
        capture.release()
    return written
