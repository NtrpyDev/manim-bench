"""The whole pipeline with a fake sandbox and fake routes. No model, no Docker."""

from __future__ import annotations

import json

from conftest import GOOD_SOURCE, FakeRoute, FakeSandbox, good_judge_reply

from manimbench.pipeline import PipelineRequest, run_all
from manimbench.registry import JudgePanel


def test_pipeline_runs_end_to_end_with_fakes(tmp_path, suite, monkeypatch):
    tasks = {task.title: task for task in suite.tasks}

    def judge_reply(_target, request):
        title = next(title for title in tasks if title in request.prompt)
        return good_judge_reply(tasks[title])

    monkeypatch.setattr(
        "manimbench.judging.load_judges",
        lambda: JudgePanel(route="openrouter", judges=["claude-opus-5-5", "gpt-6-1-sol"], max_frames=6, max_output_tokens=None),
    )
    result = run_all(
        PipelineRequest(
            models=["claude-opus-5-5"],
            outputs_dir=tmp_path / "outputs",
            runs_dir=tmp_path / "runs",
            reports_dir=tmp_path / "reports",
            run_id="smoke",
            samples=2,
            generate_route_factory=lambda _name: FakeRoute(lambda _target, _request: GOOD_SOURCE),
            judge_route_factory=lambda _name: FakeRoute(judge_reply),
            sandbox=FakeSandbox(),
        )
    )
    assert result.ok
    leaderboard = json.loads((tmp_path / "reports" / "smoke" / "data" / "leaderboard.json").read_text())
    row = leaderboard["models"][0]
    assert row["complete"] and row["rank"] == 1
    assert row["samples"] == {"expected": 12, "present": 12, "missing": 0, "scored": 12, "awaiting_judge": 0, "failed_gate": 0}
    # correctness 4, explanation 3, coverage 4 (all yes), clarity 3 -> (30*4 + 25*3 + 25*4 + 20*3) / 4 = 88.75
    assert row["components"]["judge"] == 88.75
    assert row["components"]["layout"] == 100.0
    assert row["cost"]["generation_usd"] == 0.12
