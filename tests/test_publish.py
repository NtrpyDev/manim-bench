import json
import subprocess

import pytest

from manimbench.orchestrator import PublishRequest, publish


def _make_report(tmp_path, run_id="demo"):
    run_dir = tmp_path / "runs" / run_id
    report_dir = tmp_path / "reports" / run_id
    run_dir.mkdir(parents=True)
    (report_dir / "data").mkdir(parents=True)
    for name in ["leaderboard", "results", "models", "tasks"]:
        (report_dir / "data" / f"{name}.json").write_text("{}", encoding="utf-8")
    (report_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "0.6.0",
                "run_id": run_id,
                "models": ["m1"],
                "suite": {"task_ids": ["t1"]},
                "sandbox": {"name": "local", "docker_image_digest": None},
            }
        ),
        encoding="utf-8",
    )
    task_dir = run_dir / "m1" / "t1"
    task_dir.mkdir(parents=True)
    (task_dir / "result.json").write_text(json.dumps({"model": "m1", "task": {"id": "t1"}}), encoding="utf-8")
    return run_dir, report_dir


def test_publish_draft_commits_bundle(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    run_dir, report_dir = _make_report(tmp_path)
    monkeypatch.setattr(orchestrator, "DEFAULT_REPORTS_DIR", report_dir.parent)
    site_repo = tmp_path / "site-repo"

    result = publish(PublishRequest(run_dir=run_dir, target="draft", site_repo=site_repo))
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=site_repo, text=True, capture_output=True, check=True)

    assert result.branch == "draft"
    assert branch.stdout.strip() == "draft"
    assert result.commit
    assert (site_repo / "data" / "leaderboard.json").exists()
    assert (run_dir / "publish-history.jsonl").exists()


def test_live_publish_requires_digest_for_container_runs(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    run_dir, report_dir = _make_report(tmp_path)
    monkeypatch.setattr(orchestrator, "DEFAULT_REPORTS_DIR", report_dir.parent)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["sandbox"] = {"name": "container", "docker_image_digest": None}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="Docker image digest"):
        publish(PublishRequest(run_dir=run_dir, target="live", site_repo=tmp_path / "site-repo"))
