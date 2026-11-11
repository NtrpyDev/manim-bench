"""Copy a finished report into the separate site repository and commit it."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from manimbench.paths import DEFAULT_REPORTS_DIR, DEFAULT_SITE_REPO

REQUIRED_DATA_FILES = ["leaderboard.json", "results.json", "models.json", "tasks.json", "manifest.json"]


@dataclass(frozen=True)
class PublishRequest:
    run_dir: Path
    target: str
    site_repo: Path = DEFAULT_SITE_REPO
    report_dir: Path | None = None
    allow_incomplete: bool = False
    draft_branch: str = "draft"
    live_branch: str = "main"


@dataclass(frozen=True)
class PublishResult:
    target: str
    branch: str
    site_repo: Path
    commit: str | None
    pushed: bool
    files: int


def publish(request: PublishRequest) -> PublishResult:
    if request.target not in {"draft", "live"}:
        raise ValueError("target must be draft or live")
    run_dir = request.run_dir.resolve()
    report_dir = (request.report_dir or DEFAULT_REPORTS_DIR / run_dir.name).resolve()
    missing = [name for name in REQUIRED_DATA_FILES if not (report_dir / "data" / name).exists()]
    if missing:
        raise FileNotFoundError(f"Build the report first. Missing in {report_dir / 'data'}: {', '.join(missing)}")
    leaderboard = json.loads((report_dir / "data" / "leaderboard.json").read_text(encoding="utf-8"))
    if request.target == "live":
        problems = []
        if not leaderboard.get("official"):
            problems.append("the run did not use the suite's official render settings and sample count")
        if not leaderboard.get("complete"):
            problems.append("some samples are missing or not judged")
        if problems and not request.allow_incomplete:
            raise ValueError("Refusing to publish live: " + "; ".join(problems) + ".")
    site_repo = request.site_repo.resolve()
    if not (site_repo / ".git").exists():
        raise FileNotFoundError(f"{site_repo} is not a git repository. Clone the site repository there first.")
    branch = request.draft_branch if request.target == "draft" else request.live_branch
    _checkout(site_repo, branch)
    files = _copy_bundle(report_dir, site_repo)
    commit = _commit(site_repo, run_dir.name, request.target)
    pushed = _push(site_repo, branch)
    with (run_dir / "publish-history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "target": request.target,
                    "branch": branch,
                    "commit": commit,
                    "pushed": pushed,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                },
                sort_keys=True,
            )
            + "\n"
        )
    return PublishResult(request.target, branch, site_repo, commit, pushed, files)


def _copy_bundle(report_dir: Path, site_repo: Path) -> int:
    count = 0
    for name in ["data", "videos"]:
        source, target = report_dir / name, site_repo / name
        if target.exists():
            shutil.rmtree(target)
        if source.exists():
            shutil.copytree(source, target)
            count += sum(1 for path in target.rglob("*") if path.is_file())
    return count


def _checkout(repo: Path, branch: str) -> None:
    exists = subprocess.run(["git", "rev-parse", "--verify", branch], cwd=repo, capture_output=True, check=False)
    _git(repo, "checkout", branch) if exists.returncode == 0 else _git(repo, "checkout", "-b", branch)


def _commit(repo: Path, run_id: str, target: str) -> str | None:
    present = [name for name in ["data", "videos"] if (repo / name).exists()]
    if present:
        _git(repo, "add", "--all", *present)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, text=True, capture_output=True, check=False)
    if status.stdout.strip():
        _git(repo, "commit", "-m", f"Publish {target} results from run {run_id}")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=False)
    return head.stdout.strip() if head.returncode == 0 else None


def _push(repo: Path, branch: str) -> bool:
    remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True, check=False)
    if remote.returncode != 0:
        return False
    _git(repo, "push", "origin", f"HEAD:{branch}")
    return True


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()
