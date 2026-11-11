"""Reporting: leaderboard ranking, exact aggregates, and a report that is safe to publish."""

from __future__ import annotations

import json
import shutil

import pytest

from conftest import GOOD_SOURCE, FakeRoute, FakeSandbox, good_judge_reply

from manimbench.pipeline import PipelineRequest, run_all
from manimbench.registry import JudgePanel
from manimbench.reporting import build_report_data, write_report
from manimbench.tasks import load_suite
from manimbench.paths import DEFAULT_SUITE_PATH

TASKS = ["coordinate_system_animation", "derivative_motion_story", "fourier_series_decomposition"]
GOOD_MODEL = "claude-opus-5-5"
BAD_MODEL = "gpt-6-1-sol"
JUDGE = "claude-sonnet-5-5"
SAMPLES = 2


def one_judge():
    return JudgePanel(route="openrouter", judges=[JUDGE], max_frames=4, max_output_tokens=None)


@pytest.fixture(autouse=True)
def judge_panel(monkeypatch):
    monkeypatch.setattr("manimbench.judging.load_judges", one_judge)


def titles(suite):
    return {task.title: task for task in suite.tasks}


def generation_route(suite, crash_tasks):
    by_title = titles(suite)

    def reply(target, request):
        if target["model"].startswith("openai/") or target["model"].startswith("gpt"):
            title = next(title for title in by_title if title in request.prompt)
            if by_title[title].id in crash_tasks:
                return GOOD_SOURCE + "# fake:crash\n"
        return GOOD_SOURCE

    return FakeRoute(reply)


def judge_route(suite):
    by_title = titles(suite)
    return FakeRoute(lambda _t, request: good_judge_reply(next(by_title[t] for t in by_title if t in request.prompt)))


def pipeline(tmp_path, suite, models, *, run_id="rep", crash_tasks=(), skip_judge=False):
    return run_all(
        PipelineRequest(
            models=models,
            outputs_dir=tmp_path / "outputs",
            runs_dir=tmp_path / "runs",
            reports_dir=tmp_path / "reports",
            run_id=run_id,
            task_ids=TASKS,
            samples=SAMPLES,
            skip_judge=skip_judge,
            generate_route_factory=lambda _n: generation_route(suite, crash_tasks),
            judge_route_factory=lambda _n: judge_route(suite),
            sandbox=FakeSandbox(),
        )
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Two models, listed worst-first. The second crashes on two of the three tasks."""
    base = tmp_path_factory.mktemp("report")
    suite = load_suite(DEFAULT_SUITE_PATH)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("manimbench.judging.load_judges", one_judge)
        result = pipeline(base, suite, [BAD_MODEL, GOOD_MODEL], crash_tasks={TASKS[0], TASKS[1]})
    assert result.ok
    report = base / "reports" / "rep"
    return {
        "base": base,
        "suite": suite,
        "report": report,
        "run_dir": base / "runs" / "rep",
        "leaderboard": json.loads((report / "data" / "leaderboard.json").read_text()),
        "results": json.loads((report / "data" / "results.json").read_text()),
    }


def rows(built):
    return {row["model"]: row for row in built["leaderboard"]["models"]}


def test_complete_models_are_ranked_by_quality_descending(built):
    models = built["leaderboard"]["models"]
    assert [row["model"] for row in models] == [GOOD_MODEL, BAD_MODEL]
    assert [row["rank"] for row in models] == [1, 2]
    assert models[0]["quality"] == 92.69
    assert models[1]["quality"] == 30.9  # (92.69 + 0 + 0) / 3
    assert all(row["complete"] for row in models)
    assert built["leaderboard"]["complete"] is True


def test_leaderboard_header_fields(built):
    board = built["leaderboard"]
    assert board["run_id"] == "rep"
    assert board["suite"]["id"] == built["suite"].id
    assert board["suite"]["task_ids"] == TASKS
    assert board["samples_per_task"] == SAMPLES
    assert board["official"] is False
    assert board["weights"] == {"judge": 65.0, "layout": 25.0, "pacing": 10.0}
    assert board["judges"] == [JUDGE]
    assert [item["id"] for item in board["criteria"]] == ["correctness", "explanation", "task_coverage", "clarity"]


def test_failures_and_gate_pass_rate_are_exact(built):
    bad, good = rows(built)[BAD_MODEL], rows(built)[GOOD_MODEL]
    assert bad["failures"] == {"render_error": 4}
    assert bad["gate_pass_rate"] == 33.3  # 2 of 6
    assert bad["samples"] == {"expected": 6, "present": 6, "missing": 0, "scored": 2, "awaiting_judge": 0, "failed_gate": 4}
    assert good["failures"] == {}
    assert good["gate_pass_rate"] == 100.0
    assert good["samples"]["scored"] == 6


def test_components_are_means_over_samples_that_passed_the_gates(built):
    good, bad = rows(built)[GOOD_MODEL]["components"], rows(built)[BAD_MODEL]["components"]
    assert good == {"judge": 88.75, "layout": 100.0, "pacing": 100.0}
    assert bad == good  # crashed samples are left out of the means


def test_cost_is_generation_plus_judging_exact(built):
    good, bad = rows(built)[GOOD_MODEL]["cost"], rows(built)[BAD_MODEL]["cost"]
    assert good == {"generation_usd": 0.06, "judging_usd": 0.06, "samples_without_cost": 0, "basis": ["fake"]}
    assert bad == {"generation_usd": 0.06, "judging_usd": 0.02, "samples_without_cost": 0, "basis": ["fake"]}


def test_row_names_and_vendors_come_from_the_model_list(built):
    assert rows(built)[GOOD_MODEL]["name"] == "Claude Opus 5.5"
    assert rows(built)[GOOD_MODEL]["vendor"] == "Anthropic"
    models_json = json.loads((built["report"] / "data" / "models.json").read_text())
    assert [item["id"] for item in models_json] == [GOOD_MODEL, BAD_MODEL]


def test_results_rows_have_videos_for_passing_and_none_for_crashed(built):
    report = built["report"]
    assert len(built["results"]) == 12
    for row in built["results"]:
        base = f"{row['model']}/{row['task']['id']}/sample-{row['sample']}"
        assert row["source"] == f"sources/{base}.py"
        assert (report / row["source"]).read_text() != ""
        crashed = row["model"] == BAD_MODEL and row["task"]["id"] in TASKS[:2]
        if crashed:
            assert row["video"] is None
            assert row["gates"]["failure"] == "render_error"
            assert row["score"]["quality"] == 0.0
        else:
            assert row["video"] == f"videos/{base}.mp4"
            assert (report / row["video"]).stat().st_size > 0
            assert row["score"]["quality"] == 92.69


def test_no_data_file_holds_a_local_path(built):
    data = built["report"] / "data"
    files = sorted(data.glob("*.json"))
    assert [path.name for path in files] == ["leaderboard.json", "manifest.json", "models.json", "results.json", "tasks.json"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert str(built["base"]) not in text, path.name
        assert "/home/" not in text, path.name


def test_tasks_json_has_prompts_and_must_show_but_not_judge_notes(built):
    text = (built["report"] / "data" / "tasks.json").read_text()
    tasks = json.loads(text)
    assert [task["id"] for task in tasks] == TASKS
    suite_tasks = {task.id: task for task in built["suite"].tasks}
    for task in tasks:
        source = suite_tasks[task["id"]]
        assert task["prompt"] == source.prompt
        assert task["must_show"] == [{"id": item.id, "text": item.text} for item in source.must_show]
        assert "judge_notes" not in task
        assert source.judge_notes.strip()[:40] not in text
    assert "judge_notes" not in text


def test_run_from_another_suite_id_raises(built, tmp_path):
    copy = tmp_path / "run"
    shutil.copytree(built["run_dir"], copy)
    manifest = json.loads((copy / "manifest.json").read_text())
    manifest["suite"]["id"] = "other-suite"
    (copy / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="other-suite"):
        build_report_data(copy, built["suite"])
    with pytest.raises(ValueError, match="other-suite"):
        write_report(copy, tmp_path / "out")


def test_model_with_a_missing_sample_is_unranked_and_listed_last(built, tmp_path):
    copy = tmp_path / "run"
    shutil.copytree(built["run_dir"], copy)
    # The model that would rank first loses one sample, so it is incomplete and drops below the ranked one.
    (copy / GOOD_MODEL / TASKS[0] / "sample-2" / "result.json").unlink()
    data = build_report_data(copy, built["suite"])
    models = data["leaderboard"]["models"]
    assert [row["model"] for row in models] == [BAD_MODEL, GOOD_MODEL]
    assert [row["rank"] for row in models] == [1, None]
    assert models[1]["complete"] is False
    assert models[1]["quality"] is None
    assert models[1]["samples"]["missing"] == 1
    assert models[1]["samples"]["present"] == 5
    assert data["leaderboard"]["complete"] is False


def test_unjudged_model_is_unranked_and_run_is_incomplete(tmp_path):
    suite = load_suite(DEFAULT_SUITE_PATH)
    first = pipeline(tmp_path, suite, [GOOD_MODEL])
    assert first.ok
    second = pipeline(tmp_path, suite, [BAD_MODEL], skip_judge=True, crash_tasks={TASKS[0]})
    assert second.judge is None
    data = json.loads((tmp_path / "reports" / "rep" / "data" / "leaderboard.json").read_text())
    models = data["models"]
    assert [row["model"] for row in models] == [GOOD_MODEL, BAD_MODEL]
    assert [row["rank"] for row in models] == [1, None]
    assert data["complete"] is False
    unjudged = models[1]
    assert unjudged["quality"] is None
    assert unjudged["samples"]["awaiting_judge"] == 4
    assert unjudged["samples"]["failed_gate"] == 2
    assert unjudged["samples"]["scored"] == 0
    assert unjudged["automated"] is not None


def test_unranked_models_are_ordered_by_automated_score(tmp_path):
    suite = load_suite(DEFAULT_SUITE_PATH)
    pipeline(tmp_path, suite, [GOOD_MODEL, BAD_MODEL], skip_judge=True, crash_tasks={TASKS[0]})
    data = json.loads((tmp_path / "reports" / "rep" / "data" / "leaderboard.json").read_text())
    models = data["models"]
    assert all(row["rank"] is None for row in models)
    assert data["complete"] is False
    assert [row["model"] for row in models] == [GOOD_MODEL, BAD_MODEL]
    assert models[0]["automated"] == 100.0
    assert models[1]["automated"] == pytest.approx(66.67, abs=0.01)
