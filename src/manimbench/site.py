from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from manimbench.paths import WEBSITE_ROOT


def build_site(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not report_dir.exists():
        raise FileNotFoundError(f"Report directory does not exist: {report_dir}")

    template_root = Path(args.template_dir).resolve() if args.template_dir else WEBSITE_ROOT
    if not template_root.exists():
        raise FileNotFoundError(f"Website template directory does not exist: {template_root}")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(
        template_root,
        output_dir,
        ignore=shutil.ignore_patterns("dist", "node_modules", ".DS_Store"),
    )

    report_data = report_dir / "data"
    site_data = output_dir / "data"
    site_data.mkdir(parents=True, exist_ok=True)

    leaderboard_path = report_data / "leaderboard.json"
    if leaderboard_path.exists():
        payload = json.loads(leaderboard_path.read_text(encoding="utf-8"))
    else:
        payload = _empty_leaderboard()

    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["source_report"] = str(report_dir)
    (site_data / "leaderboard.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for name in ("results.json", "models.json", "tasks.json", "manifest.json"):
        source = report_data / name
        if source.exists():
            shutil.copy2(source, site_data / name)

    report_videos = report_dir / "videos"
    site_videos = output_dir / "videos"
    if report_videos.exists():
        if site_videos.exists():
            shutil.rmtree(site_videos)
        shutil.copytree(report_videos, site_videos)

    manifest = {
        "schema_version": "0.4.0",
        "source_report": str(report_dir),
        "output_dir": str(output_dir),
        "entrypoint": "index.html",
        "leaderboard": "data/leaderboard.json",
        "updated_at": payload["updated_at"],
    }
    (output_dir / "site_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Built site bundle: {output_dir}")
    return 0


def _empty_leaderboard() -> dict:
    return {
        "schema_version": "0.4.0",
        "status": "awaiting_data",
        "run_id": None,
        "suite": {"id": "manimbench-v0.4-public", "title": "ManimBench V0.4 Public Suite"},
        "models": [],
    }
