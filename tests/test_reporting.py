import json

from manimbench.reporting import load_results, summarize_models, write_report


def test_report_generation(tmp_path):
    run_dir = tmp_path / "runs" / "demo"
    task_dir = run_dir / "model-a" / "task-a"
    task_dir.mkdir(parents=True)
    payload = {
        "schema_version": "0.1.0",
        "model": "model-a",
        "task": {"id": "task-a", "version": "1.0", "difficulty": "easy", "domains": [], "title": "Task A"},
        "source_metadata": {"cost_usd": 1.25, "elapsed_seconds": 42, "output_tokens": 1200},
        "score": {
            "task_id": "task-a",
            "model": "model-a",
            "passed": True,
            "automated_score": 87.5,
            "checks": {"render_exit_code": True, "media_generated": True},
            "rubric": {},
            "artifacts": {},
        },
    }
    (task_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")

    results = load_results(run_dir)
    summaries = summarize_models(results)
    index = write_report(run_dir, tmp_path / "reports" / "demo")

    assert len(results) == 1
    assert summaries[0]["model"] == "model-a"
    assert summaries[0]["avg_score"] == 87.5
    assert index.exists()
    assert "Overall ManimBench score" in index.read_text(encoding="utf-8")
    assert "Efficiency ranking" in index.read_text(encoding="utf-8")
    assert "Final Share Videos" in index.read_text(encoding="utf-8")
    assert (tmp_path / "reports" / "demo" / "data" / "tasks.json").exists()
    assert (tmp_path / "reports" / "demo" / "data" / "leaderboard.json").exists()
    assert (tmp_path / "reports" / "demo" / "report.md").exists()
    assert (tmp_path / "reports" / "demo" / "models" / "model-a.html").exists()
    assert (tmp_path / "reports" / "demo" / "tasks" / "task-a.html").exists()
