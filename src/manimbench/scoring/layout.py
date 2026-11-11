"""Layout score, measured from where the text really was during the render.

The sandbox harness writes down every text object on screen at the start and
end of each animation, and once a second during long ones. This module reads
that record and measures three problems a viewer would see: text cut off by
the frame edge, text sitting on other text, and text too small to read. Each
is weighed by how long it stayed on screen.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manimbench.models import LayoutSettings

DEFAULT_FRAME_HEIGHT = 8.0
MIN_SOLID_OPACITY = 0.3
MAX_LAYOUT_BYTES = 50_000_000
MAX_REPORTED_ISSUES = 12


def load_layout(path: Path) -> dict[str, Any] | None:
    """Read the harness record. It was written by untrusted code, so trust nothing."""
    try:
        if path.stat().st_size > MAX_LAYOUT_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("snapshots"), list):
        return None
    return data


def score_layout(layout: dict[str, Any] | None, settings: LayoutSettings) -> dict[str, Any]:
    """Return ``{"available", "score", ...}``. ``score`` is None when nothing could be measured."""
    snapshots = _clean_snapshots(layout)
    flat = [item for item in snapshots if item["projection"] == "2d"]
    if len(flat) < 2:
        return {
            "available": False,
            "score": None,
            "reason": "no_snapshots" if not snapshots else "not_enough_2d_snapshots",
            "snapshots": len(snapshots),
        }

    seconds = {"clipping": 0.0, "overlap": 0.0, "small_text": 0.0}
    measured = 0.0
    issues: dict[tuple[str, str], float] = {}
    strings: set[str] = set()
    for current, following in zip(snapshots, snapshots[1:]):
        # Each record stands for the stretch of video up to the next record.
        duration = max(0.0, following["time"] - current["time"])
        if current["projection"] != "2d" or duration <= 0:
            continue
        measured += duration
        found = _snapshot_problems(current, settings)
        for kind, descriptions in found.items():
            if descriptions:
                seconds[kind] += duration
            for description in set(descriptions):  # Once per snapshot, however many items share the text.
                issues[(kind, description)] = issues.get((kind, description), 0.0) + duration
    for snapshot in snapshots:
        strings.update(item["string"] for item in snapshot["text"] if item["string"])

    if measured <= 0:
        return {"available": False, "score": None, "reason": "no_measured_time", "snapshots": len(snapshots)}

    shares = {kind: min(1.0, (value / measured) / settings.saturation_share) for kind, value in seconds.items()}
    points = {
        "clipping": settings.clipping_points,
        "overlap": settings.overlap_points,
        "small_text": settings.small_text_points,
    }
    total_points = sum(points.values())
    lost = sum(points[kind] * shares[kind] for kind in points)
    score = 100.0 * (1.0 - lost / total_points) if total_points > 0 else 100.0
    worst = sorted(issues.items(), key=lambda entry: entry[1], reverse=True)[:MAX_REPORTED_ISSUES]
    return {
        "available": True,
        "score": round(score, 2),
        "measured_seconds": round(measured, 3),
        "problem_seconds": {kind: round(value, 3) for kind, value in seconds.items()},
        "problem_shares": {kind: round(value, 4) for kind, value in shares.items()},
        "issues": [{"kind": kind, "text": text, "seconds": round(value, 3)} for (kind, text), value in worst],
        "snapshots": len(snapshots),
        "text_seen": len(strings),
    }


def on_screen_text(layout: dict[str, Any] | None, time: float) -> list[str]:
    """The text strings on screen at a moment, for showing to the judge."""
    snapshots = _clean_snapshots(layout)
    chosen: dict[str, Any] | None = None
    for snapshot in snapshots:
        if snapshot["time"] <= time + 1e-6:
            chosen = snapshot
        else:
            break
    if chosen is None:
        return []
    seen: list[str] = []
    for item in chosen["text"]:
        if item["string"] and item["string"] not in seen:
            seen.append(item["string"])
    return seen


def snapshot_times(layout: dict[str, Any] | None) -> list[float]:
    """Moments just after an animation finished, when the picture has settled."""
    return [snapshot["time"] for snapshot in _clean_snapshots(layout) if snapshot["phase"] == "end"]


def _snapshot_problems(snapshot: dict[str, Any], settings: LayoutSettings) -> dict[str, list[str]]:
    frame = snapshot["frame"]
    tolerance = settings.frame_tolerance
    left = frame["cx"] - frame["width"] / 2 - tolerance
    right = frame["cx"] + frame["width"] / 2 + tolerance
    bottom = frame["cy"] - frame["height"] / 2 - tolerance
    top = frame["cy"] + frame["height"] / 2 + tolerance
    zoom = DEFAULT_FRAME_HEIGHT / frame["height"] if frame["height"] > 0 else 1.0

    visible = []
    clipped: list[str] = []
    small: list[str] = []
    for item in snapshot["text"]:
        x0, y0, x1, y1 = item["box"]
        if x1 < left or x0 > right or y1 < bottom or y0 > top:
            continue  # Entirely off screen: not visible, so not a layout problem.
        visible.append(item)
        if x0 < left or x1 > right or y0 < bottom or y1 > top:
            clipped.append(_label(item))
        # Judged by the drawn characters. The font size Manim reports is not used: it is wrong
        # after a Transform and blind to sizing inside LaTeX.
        glyph = item["glyph_height"]
        if glyph is not None and glyph * zoom < settings.min_glyph_height:
            small.append(_label(item))

    overlapping: list[str] = []
    solid = [item for item in visible if item["opacity"] >= MIN_SOLID_OPACITY]
    for index, first in enumerate(solid):
        for second in solid[index + 1 :]:
            if _overlap_ratio(first["box"], second["box"]) > settings.overlap_ratio:
                overlapping.append(" / ".join(sorted([_label(first), _label(second)])))
    return {"clipping": clipped, "overlap": overlapping, "small_text": small}


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return (width * height) / smaller if smaller > 0 else 0.0


def _label(item: dict[str, Any]) -> str:
    text = " ".join(item["string"].split())
    return text[:60] if text else f"<{item['kind']}>"


def _clean_snapshots(layout: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Keep only well-formed snapshots and text items, sorted by time."""
    if not isinstance(layout, dict):
        return []
    cleaned = []
    for raw in layout.get("snapshots", []):
        try:
            frame = raw["frame"]
            snapshot = {
                "time": float(raw["time"]),
                "projection": "3d" if raw.get("projection") == "3d" else "2d",
                "phase": raw.get("phase") if raw.get("phase") in {"start", "mid"} else "end",
                "frame": {key: float(frame[key]) for key in ("cx", "cy", "width", "height")},
                "text": [],
            }
        except (KeyError, TypeError, ValueError):
            continue
        for item in raw.get("text", []) if isinstance(raw.get("text"), list) else []:
            try:
                box = [float(value) for value in item["box"]]
                if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
                    continue
                glyph = item.get("glyph_height")
                snapshot["text"].append(
                    {
                        "kind": str(item.get("kind", "text")),
                        "string": str(item.get("string", "")),
                        "box": box,
                        "glyph_height": float(glyph) if isinstance(glyph, (int, float)) and glyph > 0 else None,
                        "opacity": float(item.get("opacity", 1.0)),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        cleaned.append(snapshot)
    cleaned.sort(key=lambda entry: entry["time"])
    return cleaned
