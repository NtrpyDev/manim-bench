"""Judging: frames, requests, records, retries, and how judge scores fold into results."""

from __future__ import annotations

import json

import pytest

from conftest import GOOD_SOURCE, FakeRoute, FakeSandbox, good_judge_reply

from manimbench import judging
from manimbench.judging import JudgeRequest, judge_run
from manimbench.providers.base import ProviderError
from manimbench.registry import JudgePanel
from manimbench.rendering import RenderRequest, load_results, render, sample_dir
from manimbench.scoring.judge import JUDGE_SYSTEM_PROMPT

TASK = "coordinate_system_animation"
MODEL = "claude-opus-5-5"
JUDGE_A = "claude-sonnet-5-5"
JUDGE_B = "gpt-6-1-sol"
GOOD_SCORES = {"correctness": 4, "explanation": 3, "clarity": 3}  # with all must_show "yes": 88.75


@pytest.fixture
def task(suite):
    return next(item for item in suite.tasks if item.id == TASK)


def make_run(tmp_path, sources, run_id="r1"):
    """Render the given sources (one sample each) and return the run folder."""
    outputs = tmp_path / "outputs"
    for number, source in enumerate(sources, start=1):
        path = outputs / MODEL / TASK / f"sample-{number}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    outcome = render(
        RenderRequest(
            models=[MODEL], task_ids=[TASK], samples=len(sources), outputs_dir=outputs,
            runs_dir=tmp_path / "runs", run_id=run_id, sandbox=FakeSandbox(),
        )
    )
    return outcome.run_dir


def panel(judges=(JUDGE_A,), max_frames=6):
    return JudgePanel(route="openrouter", judges=list(judges), max_frames=max_frames, max_output_tokens=None)


def do_judge(run_dir, route, judges=(JUDGE_A,), **overrides):
    values = dict(run_dir=run_dir, panel=panel(judges), route_factory=lambda _name: route)
    values.update(overrides)
    return judge_run(JudgeRequest(**values))


def sample_folder(run_dir, number=1):
    return sample_dir(run_dir, MODEL, TASK, number)


def result_json(run_dir, number=1):
    return json.loads((sample_folder(run_dir, number) / "result.json").read_text())


def test_frames_are_extracted_once_with_time_and_on_screen_text(tmp_path, task, monkeypatch):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    calls = []
    real = judging.extract_frames
    monkeypatch.setattr(judging, "extract_frames", lambda *a, **k: calls.append(1) or real(*a, **k))
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    do_judge(run_dir, route, judges=(JUDGE_A, JUDGE_B))
    assert len(calls) == 1  # one extraction for the sample, shared by both judges
    folder = sample_folder(run_dir) / "frames"
    frames = json.loads((folder / "frames.json").read_text())
    assert 1 <= len(frames) <= 6
    assert sorted(p.name for p in folder.glob("*.jpg")) == sorted(frame["file"] for frame in frames)
    times = [frame["time"] for frame in frames]
    assert times == sorted(times)
    for frame in frames:
        assert frame["text"] == ["Title", "y = x^2"]  # the clean layout's two labels


def test_frame_count_is_capped_by_max_frames(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    judge_run(JudgeRequest(run_dir=run_dir, panel=panel(max_frames=3), route_factory=lambda _n: route))
    frames = json.loads((sample_folder(run_dir) / "frames" / "frames.json").read_text())
    assert 1 <= len(frames) <= 3


def test_request_has_system_prompt_frames_and_task_title(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    do_judge(run_dir, route)
    assert len(route.calls) == 1
    target, sent = route.calls[0]
    assert target["model"] == "anthropic/claude-sonnet-5.5"
    assert sent.system == JUDGE_SYSTEM_PROMPT
    assert task.title in sent.prompt
    frames = json.loads((sample_folder(run_dir) / "frames" / "frames.json").read_text())
    assert sent.images == [sample_folder(run_dir) / "frames" / frame["file"] for frame in frames]
    assert all(path.exists() for path in sent.images)
    assert f"{len(frames)} frames attached" in sent.prompt


def test_judge_records_and_scored_result(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    outcome = do_judge(run_dir, route, judges=(JUDGE_A, JUDGE_B))
    assert outcome.ok
    assert outcome.judged == 2
    assert outcome.cost_usd == 0.02
    folder = sample_folder(run_dir) / "judge"
    assert sorted(p.name for p in folder.glob("*.json")) == sorted([f"{JUDGE_A}.json", f"{JUDGE_B}.json"])
    record = json.loads((folder / f"{JUDGE_A}.json").read_text())
    assert record["status"] == "complete"
    assert record["judge_id"] == JUDGE_A
    assert record["route"] == "openrouter"
    assert record["score"] == 88.75
    assert record["cost_usd"] == 0.01
    assert len(record["calls"]) == 1
    assert record["sample_path"] == f"{MODEL}/{TASK}/sample-1"
    result = result_json(run_dir)
    assert result["score"]["status"] == "scored"
    assert result["score"]["components"]["judge"] == 88.75
    assert result["score"]["components"]["layout"] == 100
    assert result["score"]["quality"] == 92.69  # (88.75 * 65 + 100 * 25 + 100 * 10) / 100
    assert result["judge"]["status"] == "complete"
    assert result["judge"]["judges"] == 2
    assert result["judge"]["expected"] == 2
    assert [item["judge_id"] for item in result["judgements"]] == [JUDGE_A, JUDGE_B]


def test_second_call_reuses_records_and_makes_no_calls(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    do_judge(run_dir, route)
    again = do_judge(run_dir, route)
    assert len(route.calls) == 1
    assert again.reused == 1
    assert again.judged == 0
    assert again.ok
    assert result_json(run_dir)["score"]["quality"] == 92.69


def test_route_is_not_built_when_everything_is_reused(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    do_judge(run_dir, FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES)))

    def factory(_name):
        raise AssertionError("no route needed")

    outcome = judge_run(JudgeRequest(run_dir=run_dir, panel=panel(), route_factory=factory))
    assert outcome.reused == 1


def test_force_asks_again(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    do_judge(run_dir, route)
    forced = do_judge(run_dir, route, force=True)
    assert len(route.calls) == 2
    assert forced.judged == 1
    assert forced.reused == 0


def test_malformed_reply_is_retried_once_and_second_good_one_succeeds(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    replies = iter(["this is not json", good_judge_reply(task, GOOD_SCORES)])
    route = FakeRoute(lambda _t, _r: next(replies))
    outcome = do_judge(run_dir, route)
    assert outcome.ok
    assert len(route.calls) == 2
    assert outcome.cost_usd == 0.02
    record = json.loads((sample_folder(run_dir) / "judge" / f"{JUDGE_A}.json").read_text())
    assert record["status"] == "complete"
    assert len(record["calls"]) == 2
    assert record["cost_usd"] == 0.02
    assert "last_reply" not in record
    assert result_json(run_dir)["score"]["quality"] == 92.69


def test_two_malformed_replies_fail_and_leave_the_sample_unscored(tmp_path):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: "nonsense")
    outcome = do_judge(run_dir, route)
    assert not outcome.ok
    assert len(route.calls) == 2
    assert outcome.cost_usd == 0.02
    assert len(outcome.failed) == 1
    assert outcome.failed[0]["judge"] == JUDGE_A
    assert outcome.failed[0]["sample"] == f"{MODEL}/{TASK}/sample-1"
    assert "Unusable reply" in outcome.failed[0]["error"]
    record = json.loads((sample_folder(run_dir) / "judge" / f"{JUDGE_A}.json").read_text())
    assert record["status"] == "failed"
    assert record["last_reply"] == "nonsense"
    result = result_json(run_dir)
    assert result["judge"]["status"] == "failed"
    assert result["judge"]["score"] is None
    assert result["score"]["status"] == "awaiting_judge"
    assert result["score"]["quality"] is None


def test_failed_judge_record_is_asked_again_on_the_next_run(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    do_judge(run_dir, FakeRoute(lambda _t, _r: "nonsense"))
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    outcome = do_judge(run_dir, route)
    assert outcome.ok and outcome.judged == 1
    assert result_json(run_dir)["score"]["quality"] == 92.69


def test_one_of_two_judges_failing_gives_partial_and_still_a_quality(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])

    def reply(target, _request):
        return "nonsense" if "gpt" in target["model"] else good_judge_reply(task, GOOD_SCORES)

    route = FakeRoute(reply)
    outcome = do_judge(run_dir, route, judges=(JUDGE_A, JUDGE_B))
    assert not outcome.ok
    assert len(outcome.failed) == 1 and outcome.failed[0]["judge"] == JUDGE_B
    result = result_json(run_dir)
    assert result["judge"]["status"] == "partial"
    assert result["judge"]["judges"] == 1
    assert result["judge"]["expected"] == 2
    assert result["score"]["status"] == "scored"
    assert result["score"]["quality"] == 92.69


def test_provider_error_fails_without_retry(tmp_path):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: ProviderError("route down"))
    outcome = do_judge(run_dir, route)
    assert len(route.calls) == 1
    assert not outcome.ok
    assert outcome.failed[0]["error"] == "route down"
    record = json.loads((sample_folder(run_dir) / "judge" / f"{JUDGE_A}.json").read_text())
    assert record["status"] == "failed"
    assert record["calls"] == []
    assert record["cost_usd"] == 0.0
    assert result_json(run_dir)["judge"]["status"] == "failed"


def test_samples_that_failed_a_gate_are_skipped_and_counted(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE, GOOD_SOURCE + "# fake:crash\n"])
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    outcome = do_judge(run_dir, route)
    assert outcome.skipped_failed_gate == 1
    assert outcome.judged == 1
    assert len(route.calls) == 1
    assert not (sample_folder(run_dir, 2) / "judge").exists()
    assert not (sample_folder(run_dir, 2) / "frames").exists()
    failed = result_json(run_dir, 2)
    assert failed["score"]["status"] == "failed_gate"
    assert failed["score"]["quality"] == 0.0
    assert result_json(run_dir, 1)["score"]["quality"] == 92.69


def test_empty_panel_raises(tmp_path):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    with pytest.raises(ValueError, match="empty"):
        do_judge(run_dir, FakeRoute(lambda _t, _r: ""), judges=())


def test_run_from_a_different_suite_id_raises(tmp_path):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["suite"]["id"] = "some-other-suite"
    manifest_path.write_text(json.dumps(manifest))
    route = FakeRoute(lambda _t, _r: "")
    with pytest.raises(ValueError, match="some-other-suite"):
        do_judge(run_dir, route)
    assert route.calls == []


def test_judge_without_a_route_for_the_panel_raises_before_any_call(tmp_path):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: "")
    with pytest.raises(KeyError, match="no claude-cli route"):
        judge_run(
            JudgeRequest(
                run_dir=run_dir,
                panel=JudgePanel(route="claude-cli", judges=[JUDGE_B], max_frames=6, max_output_tokens=None),
                route_factory=lambda _n: route,
            )
        )
    assert route.calls == []


def test_judge_prompts_are_identical_across_judges_and_never_name_the_sample_model(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE])
    route = FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES))
    do_judge(run_dir, route, judges=(JUDGE_A, JUDGE_B))
    folder = sample_folder(run_dir) / "judge"
    hashes = {json.loads((folder / f"{judge}.json").read_text())["prompt_sha256"] for judge in (JUDGE_A, JUDGE_B)}
    assert len(hashes) == 1
    prompts = {request.prompt for _target, request in route.calls}
    systems = {request.system for _target, request in route.calls}
    assert len(prompts) == 1 and len(systems) == 1
    for text in prompts | systems:
        assert MODEL not in text
        assert "Opus" not in text
        assert "claude" not in text.lower()


def test_load_results_after_judging_matches_files(tmp_path, task):
    run_dir = make_run(tmp_path, [GOOD_SOURCE, GOOD_SOURCE])
    do_judge(run_dir, FakeRoute(lambda _t, _r: good_judge_reply(task, GOOD_SCORES)))
    qualities = [row["score"]["quality"] for row in load_results(run_dir)]
    assert qualities == [92.69, 92.69]
