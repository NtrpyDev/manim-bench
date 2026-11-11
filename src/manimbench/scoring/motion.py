"""What the video itself shows over time: is it blank, does it move, does it stall."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from manimbench.media import sample_gray_frames
from manimbench.models import PacingSettings

SAMPLES_PER_SECOND = 5.0
PIXEL_CHANGE_LEVELS = 16
CHANGED_PIXEL_SHARE = 0.0004
FOREGROUND_LEVELS = 24
BLANK_FOREGROUND_SHARE = 0.002


def analyze_motion(video_path: Path, settings: PacingSettings) -> dict[str, Any]:
    """Measure blank time, moving time and still stretches, and score the pacing."""
    times: list[float] = []
    changed: list[bool] = []
    blank: list[bool] = []
    previous: np.ndarray | None = None
    for moment, frame in sample_gray_frames(video_path, per_second=SAMPLES_PER_SECOND):
        current = frame.astype(np.int16)
        times.append(moment)
        blank.append(_is_blank(current))
        if previous is not None and previous.shape == current.shape:
            share = float(np.mean(np.abs(current - previous) > PIXEL_CHANGE_LEVELS))
            changed.append(share > CHANGED_PIXEL_SHARE)
        previous = current

    if len(times) < 2:
        return {"available": False, "reason": "unreadable_video"}

    step = (times[-1] - times[0]) / (len(times) - 1)
    duration = times[-1] + step
    active_seconds = sum(changed) * step
    blank_share = sum(blank) / len(blank)
    still_runs = _still_runs(changed, step)
    longest_still = max(still_runs, default=0.0)
    dead = sum(max(0.0, run - settings.max_still_seconds) for run in still_runs)
    pacing = 100.0 * (1.0 - min(1.0, dead / (0.5 * duration))) if duration > 0 else 0.0
    required_active = max(settings.min_active_seconds, settings.min_active_share * duration)
    return {
        "available": True,
        "sampled_frames": len(times),
        "duration_seconds": round(duration, 3),
        "active_seconds": round(active_seconds, 3),
        "active_share": round(active_seconds / duration, 4) if duration > 0 else 0.0,
        "required_active_seconds": round(required_active, 3),
        "blank_share": round(blank_share, 4),
        "longest_still_seconds": round(longest_still, 3),
        "dead_seconds": round(dead, 3),
        "has_motion": active_seconds >= required_active,
        "not_blank": blank_share <= settings.max_blank_share,
        "score": round(pacing, 2),
    }


def _is_blank(frame: np.ndarray) -> bool:
    background = float(np.median(frame))
    foreground = float(np.mean(np.abs(frame - background) > FOREGROUND_LEVELS))
    return foreground < BLANK_FOREGROUND_SHARE


def _still_runs(changed: list[bool], step: float) -> list[float]:
    runs: list[float] = []
    current = 0
    for moved in changed:
        if moved:
            if current:
                runs.append(current * step)
            current = 0
        else:
            current += 1
    if current:
        runs.append(current * step)
    return runs
