from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVIEW_STATUSES = {"pass", "partial", "fail", "pending"}
REVIEW_FIELDS = [
    "geometry_correctness",
    "text_readability",
    "label_overlap",
    "layout_composition",
    "pacing",
    "prompt_section_coverage",
    "fake_or_superficial_visuals",
    "final_shareability",
]


def init_reviews(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    count = int(args.frames)
    initialized = 0
    for result_path in sorted(run_dir.rglob("result.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        review_path = result_path.with_name("review.json")
        review = default_review(result)
        media_path = _result_media_path(result)
        frames_dir = result_path.parent / "frames"
        if media_path and media_path.exists():
            review["frames"] = sample_frames(media_path, frames_dir, count=count)
        else:
            review["frames"] = {"status": "missing_media", "files": []}
        if review_path.exists() and not args.force:
            continue
        review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
        initialized += 1
    print(f"Initialized {initialized} review file(s) under {run_dir}")
    return 0


def set_review(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    if args.status not in REVIEW_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(REVIEW_STATUSES))}")
    updated = 0
    for review_path in _matching_review_paths(run_dir, args.model, args.task):
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if args.field == "overall":
            review["overall"] = args.status
        else:
            if args.field not in REVIEW_FIELDS:
                raise ValueError(f"field must be 'overall' or one of: {', '.join(REVIEW_FIELDS)}")
            review.setdefault("fields", {})[args.field]["status"] = args.status
        if args.notes:
            review.setdefault("notes", "")
            review["notes"] = (review["notes"] + "\n" + args.notes).strip()
        review["updated_at"] = _now_iso()
        review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
        updated += 1
    print(f"Updated {updated} review file(s)")
    return 0


def summarize_reviews(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    counts = {status: 0 for status in sorted(REVIEW_STATUSES)}
    for review_path in sorted(run_dir.rglob("review.json")):
        review = json.loads(review_path.read_text(encoding="utf-8"))
        counts[str(review.get("overall", "pending"))] = counts.get(str(review.get("overall", "pending")), 0) + 1
    print(json.dumps({"run_dir": str(run_dir), "counts": counts}, indent=2))
    return 0


def merge_review(result: dict[str, Any], result_path: Path) -> dict[str, Any]:
    review_path = result_path.with_name("review.json")
    if not review_path.exists():
        return result
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return result
    result["visual_review"] = review
    rubric = result.setdefault("score", {}).setdefault("rubric", {})
    rubric["visual_review"] = review
    adjusted = adjusted_score(result)
    if adjusted is not None:
        result.setdefault("score", {})["adjusted_visual_score"] = adjusted
    return result


def default_review(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.4.0",
        "model": result.get("model"),
        "task_id": result.get("task", {}).get("id"),
        "overall": "pending",
        "fields": {
            field: {"status": "pending", "notes": ""}
            for field in REVIEW_FIELDS
        },
        "critical_issues": [],
        "notes": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def adjusted_score(result: dict[str, Any]) -> float | None:
    review = result.get("visual_review") or result.get("score", {}).get("rubric", {}).get("visual_review")
    if not isinstance(review, dict):
        return None
    base = float(result.get("score", {}).get("automated_score", 0.0))
    status = review.get("overall", "pending")
    if status == "pass":
        return base
    if status == "partial":
        return round(base * 0.7, 2)
    if status == "fail":
        return round(base * 0.25, 2)
    return None


def sample_frames(media_path: Path, frames_dir: Path, count: int = 6) -> dict[str, Any]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for existing in frames_dir.glob("frame_*.jpg"):
        existing.unlink()
    if not shutil.which("ffmpeg"):
        return {"status": "ffmpeg_missing", "files": []}
    pattern = frames_dir / "frame_%02d.jpg"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(media_path),
        "-vf",
        f"fps={count}/120,scale=1280:-1",
        "-frames:v",
        str(count),
        str(pattern),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=120)
    if completed.returncode != 0:
        return {"status": "ffmpeg_failed", "error": completed.stderr.strip(), "files": []}
    files = sorted(str(path) for path in frames_dir.glob("frame_*.jpg"))
    manifest = {"status": "sampled", "media": str(media_path), "files": files}
    (frames_dir / "frames.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _matching_review_paths(run_dir: Path, model: str | None, task: str | None) -> list[Path]:
    paths = []
    for review_path in sorted(run_dir.rglob("review.json")):
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if model and review.get("model") != model:
            continue
        if task and review.get("task_id") != task:
            continue
        paths.append(review_path)
    return paths


def _result_media_path(result: dict[str, Any]) -> Path | None:
    media = result.get("score", {}).get("artifacts", {}).get("media")
    if media and Path(media).exists():
        return Path(media)
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
