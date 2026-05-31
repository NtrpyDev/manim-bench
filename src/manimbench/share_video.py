from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from manimbench.reporting import load_results
from manimbench.runtime import probe_media


def build_share_videos(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    models = {args.model} if args.model else None
    results_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in load_results(run_dir):
        model = result.get("model")
        if not model or (models and model not in models):
            continue
        results_by_model[model].append(result)

    if not results_by_model:
        print("No matching model results found for share-video build.")
        return 1

    manifests = []
    for model, results in sorted(results_by_model.items()):
        manifest = _build_one_model_video(run_dir, output_dir, model, results, max_seconds=args.max_seconds)
        manifests.append(manifest)
        print(f"Wrote final video: {manifest['output']}")

    manifest_path = output_dir / "share_videos.json"
    manifest_path.write_text(json.dumps(manifests, indent=2), encoding="utf-8")
    print(f"Wrote final video manifest: {manifest_path}")
    return 0


def _build_one_model_video(
    run_dir: Path,
    output_dir: Path,
    model: str,
    results: list[dict[str, Any]],
    max_seconds: int,
) -> dict[str, Any]:
    final_path = output_dir / f"{_slug(model)}.mp4"
    work_dir = output_dir / f".{_slug(model)}-parts"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    ordered = _order_results(results)
    per_segment = max(2.0, min(12.0, max_seconds / max(len(ordered), 1)))
    segments = []
    for index, result in enumerate(ordered):
        segment_path = work_dir / f"{index:04d}.mp4"
        media_path = _result_media_path(result)
        status = _result_status(result)
        title = f"{status}: {result.get('task', {}).get('title') or result.get('task', {}).get('id', 'Unknown task')}"
        if media_path and media_path.exists():
            _write_clip_segment(media_path, segment_path, title, per_segment)
        else:
            _write_card_segment(segment_path, title, per_segment)
        segments.append(segment_path)

    _concat_segments(segments, final_path)
    thumbnail_path = output_dir / f"{_slug(model)}.jpg"
    _write_thumbnail(final_path, thumbnail_path)
    metadata = probe_media(final_path)
    return {
        "model": model,
        "output": str(final_path),
        "thumbnail": str(thumbnail_path),
        "relative_output": str(final_path.relative_to(output_dir.parent)),
        "relative_thumbnail": str(thumbnail_path.relative_to(output_dir.parent)),
        "segments": len(segments),
        "max_seconds": max_seconds,
        "metadata": metadata,
    }


def _order_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}
    return sorted(
        results,
        key=lambda result: (
            priority[_result_status(result)],
            result.get("task", {}).get("difficulty", ""),
            result.get("task", {}).get("id", ""),
        ),
    )


def _result_status(result: dict[str, Any]) -> str:
    if result.get("score", {}).get("passed"):
        return "PASS"
    if _result_media_path(result):
        return "PARTIAL"
    return "FAIL"


def _result_media_path(result: dict[str, Any]) -> Path | None:
    media = result.get("score", {}).get("artifacts", {}).get("media")
    if media and Path(media).exists():
        return Path(media)
    render_files = result.get("render", {}).get("media_files", [])
    command = result.get("render", {}).get("command", [])
    media_root = None
    if "--media_dir" in command:
        index = command.index("--media_dir")
        if index + 1 < len(command):
            media_root = Path(command[index + 1])
    if media_root and render_files:
        candidate = media_root / render_files[0]
        if candidate.exists():
            return candidate
    return None


def _write_clip_segment(input_path: Path, output_path: Path, title: str, seconds: float) -> None:
    filter_graph = (
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        f"drawtext=text='{_ffmpeg_text(title)}':x=40:y=40:fontsize=42:"
        "fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=16"
    )
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-t",
        f"{seconds:.3f}",
        "-vf",
        filter_graph,
        "-r",
        "60",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    _run_ffmpeg(command)


def _write_card_segment(output_path: Path, title: str, seconds: float) -> None:
    filter_graph = (
        "drawtext=text='ManimBench':x=(w-text_w)/2:y=360:fontsize=74:fontcolor=white,"
        f"drawtext=text='{_ffmpeg_text(title)}':x=(w-text_w)/2:y=500:fontsize=46:fontcolor=white:"
        "box=1:boxcolor=black@0.4:boxborderw=18"
    )
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x111111:s=1920x1080:d={seconds:.3f}:r=60",
        "-vf",
        filter_graph,
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    _run_ffmpeg(command)


def _concat_segments(segments: list[Path], output_path: Path) -> None:
    concat_file = output_path.parent / f".{output_path.stem}-concat.txt"
    concat_file.write_text("".join(f"file '{segment}'\n" for segment in segments), encoding="utf-8")
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(output_path),
    ]
    _run_ffmpeg(command)


def _write_thumbnail(input_path: Path, output_path: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        "1",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=1280:-1",
        str(output_path),
    ]
    _run_ffmpeg(command)


def _run_ffmpeg(command: list[str]) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to build share videos")
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=240)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg failed")


def _ffmpeg_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "model"
