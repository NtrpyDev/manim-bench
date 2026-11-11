"""Tests for the vision judge prompt, reply parsing and scoring."""

from __future__ import annotations

import json

import pytest
from conftest import good_judge_reply

from manimbench.scoring.judge import (
    JudgeReplyError,
    build_judge_prompt,
    combine_judges,
    judge_score,
    parse_judge_reply,
    select_frame_times,
)


@pytest.fixture
def task(suite):
    return suite.tasks[0]


def _data(task, **over):
    data = json.loads(good_judge_reply(task))
    data.update(over)
    return data


# select_frame_times


def test_few_snapshots_fall_back_to_uniform_times():
    # Under 4 candidates: 8 uniform times duration * i / 9, plus the last moment 19.95.
    times = select_frame_times([5.0, 10.0], 20.0)
    expected = sorted({round(20.0 * (i + 1) / 9, 3) for i in range(8)} | {19.95})
    assert times == expected
    assert len(times) == 9


def test_many_snapshots_are_capped_and_include_last_moment():
    times = select_frame_times([float(n) for n in range(1, 41)], 41.0, max_frames=12)
    assert len(times) <= 12
    assert times == sorted(times)
    assert len(set(times)) == len(times)
    assert times[-1] == pytest.approx(41.0 - 0.05)


def test_snapshot_just_before_end_is_the_last_frame():
    times = select_frame_times([float(n) for n in range(1, 21)], 20.0, max_frames=5)
    assert times[-1] == 19.95
    assert len(times) <= 5


def test_zero_duration_gives_no_frames():
    assert select_frame_times([1.0, 2.0], 0.0) == []


def test_zero_max_frames_gives_no_frames():
    assert select_frame_times([1.0, 2.0], 10.0, max_frames=0) == []


def test_snapshot_times_are_shifted_slightly_earlier():
    times = select_frame_times([2.0, 4.0, 6.0, 8.0], 10.0)
    assert times == [1.95, 3.95, 5.95, 7.95, 9.95]


# build_judge_prompt


def test_judge_prompt_contains_task_and_must_show(suite, task):
    prompt = build_judge_prompt(suite, task, [{"time": 2.0, "text": ["Title"]}], 20.0)
    assert task.prompt in prompt
    for item in task.must_show:
        assert f"`{item.id}`: {item.text}" in prompt


def test_judge_prompt_contains_judge_notes(suite, task):
    assert task.judge_notes in build_judge_prompt(suite, task, [], 20.0)


def test_judge_prompt_lists_each_frame_time_and_text(suite, task):
    frames = [{"time": 2.0, "text": ["Title", "y = x^2"]}, {"time": 10.0, "text": []}]
    prompt = build_judge_prompt(suite, task, frames, 20.0)
    assert "Frame 1 at 2.0 s. On-screen text: Title; y = x^2" in prompt
    assert "Frame 2 at 10.0 s. On-screen text: (no text on screen)" in prompt
    assert "20.0 seconds, 2 frames" in prompt


def test_judge_prompt_asks_every_criterion_except_must_show(suite, task):
    prompt = build_judge_prompt(suite, task, [], 20.0)
    for item in suite.criteria:
        if item.id == suite.scoring.must_show_criterion:
            assert f"`{item.id}`" not in prompt
        else:
            assert f"`{item.id}`: {item.question}" in prompt


def test_judge_prompt_names_no_model(suite, task):
    prompt = build_judge_prompt(suite, task, [], 20.0).lower()
    for name in ["claude", "gpt", "gemini", "openai", "anthropic", "llama"]:
        assert name not in prompt


def test_judge_prompt_clips_long_on_screen_text(suite, task):
    prompt = build_judge_prompt(suite, task, [{"time": 1.0, "text": ["x" * 500]}], 5.0)
    assert "x" * 200 not in prompt


# parse_judge_reply


def test_parse_accepts_plain_json(suite, task):
    parsed = parse_judge_reply(good_judge_reply(task), suite, task)
    assert set(parsed["criteria"]) == {"correctness", "explanation", "clarity"}
    assert parsed["criteria"]["correctness"]["score"] == 4.0
    assert all(item["verdict"] == "yes" for item in parsed["must_show"].values())


def test_parse_accepts_fenced_json(suite, task):
    parsed = parse_judge_reply(f"```json\n{good_judge_reply(task)}\n```", suite, task)
    assert parsed["summary"] == "Clear and correct."


def test_parse_accepts_json_with_prose_around_it(suite, task):
    parsed = parse_judge_reply(f"Here is my review:\n{good_judge_reply(task)}\nThanks.", suite, task)
    assert parsed["criteria"]["clarity"]["score"] == 3.0


def test_parse_accepts_half_scores_and_uppercase_verdict(suite, task):
    data = _data(task)
    data["criteria"]["clarity"]["score"] = 2.5
    first = task.must_show[0].id
    data["must_show"][first]["verdict"] = "PARTIAL"
    parsed = parse_judge_reply(json.dumps(data), suite, task)
    assert parsed["criteria"]["clarity"]["score"] == 2.5
    assert parsed["must_show"][first]["verdict"] == "partial"


def test_parse_rejects_missing_must_show_item(suite, task):
    data = _data(task)
    del data["must_show"][task.must_show[0].id]
    with pytest.raises(JudgeReplyError, match="must_show"):
        parse_judge_reply(json.dumps(data), suite, task)


def test_parse_rejects_invalid_verdict(suite, task):
    data = _data(task)
    data["must_show"][task.must_show[0].id]["verdict"] = "maybe"
    with pytest.raises(JudgeReplyError):
        parse_judge_reply(json.dumps(data), suite, task)


def test_parse_rejects_missing_criterion(suite, task):
    data = _data(task)
    del data["criteria"]["clarity"]
    with pytest.raises(JudgeReplyError, match="clarity"):
        parse_judge_reply(json.dumps(data), suite, task)


@pytest.mark.parametrize("bad", [5, -1, True, "3", None, 4.01])
def test_parse_rejects_bad_scores(suite, task, bad):
    data = _data(task)
    data["criteria"]["correctness"]["score"] = bad
    with pytest.raises(JudgeReplyError, match="correctness"):
        parse_judge_reply(json.dumps(data), suite, task)


def test_parse_rejects_missing_criteria_object(suite, task):
    data = _data(task)
    del data["criteria"]
    with pytest.raises(JudgeReplyError):
        parse_judge_reply(json.dumps(data), suite, task)


def test_parse_rejects_non_json(suite, task):
    with pytest.raises(JudgeReplyError, match="no JSON"):
        parse_judge_reply("I think it was good.", suite, task)


def test_parse_rejects_broken_json(suite, task):
    with pytest.raises(JudgeReplyError, match="not valid JSON"):
        parse_judge_reply('{"must_show": oops}', suite, task)


def test_parse_rejects_json_list(suite, task):
    with pytest.raises(JudgeReplyError):
        parse_judge_reply("[1, 2, 3]", suite, task)


# judge_score


def test_judge_score_all_yes_with_4_3_3_is_88_75(suite, task):
    # Weights 30/25/25/20. correctness 4/4, explanation 3/4, coverage 4/4, clarity 3/4:
    # 30 + 18.75 + 25 + 15 = 88.75
    parsed = parse_judge_reply(good_judge_reply(task), suite, task)
    result = judge_score(parsed, suite)
    assert result["score"] == 88.75
    assert result["criteria"] == {"correctness": 4.0, "explanation": 3.0, "task_coverage": 4.0, "clarity": 3.0}


def test_judge_score_all_no_with_zeros_is_zero(suite, task):
    reply = good_judge_reply(task, {"correctness": 0, "explanation": 0, "clarity": 0}, verdict="no")
    assert judge_score(parse_judge_reply(reply, suite, task), suite)["score"] == 0.0


def test_judge_score_all_perfect_is_100(suite, task):
    reply = good_judge_reply(task, {"correctness": 4, "explanation": 4, "clarity": 4})
    assert judge_score(parse_judge_reply(reply, suite, task), suite)["score"] == 100.0


def test_judge_score_partial_verdicts_count_half(suite, task):
    # Coverage 4 * 0.5 = 2 of 4. Others 4 of 4: 30 + 25 + 25 * 0.5 + 20 = 87.5
    reply = good_judge_reply(task, {"correctness": 4, "explanation": 4, "clarity": 4}, verdict="partial")
    result = judge_score(parse_judge_reply(reply, suite, task), suite)
    assert result["score"] == 87.5
    assert result["criteria"]["task_coverage"] == 2.0


def test_judge_score_coverage_is_mean_of_verdicts(suite, task):
    data = _data(task)
    ids = [item.id for item in task.must_show]
    for index, item_id in enumerate(ids):
        data["must_show"][item_id]["verdict"] = "yes" if index == 0 else "no"
    result = judge_score(parse_judge_reply(json.dumps(data), suite, task), suite)
    assert result["criteria"]["task_coverage"] == round(4.0 / len(ids), 4)


# combine_judges


def _record(score, judge_id, a=4.0, b=2.0):
    return {"status": "complete", "score": score, "judge_id": judge_id, "criteria": {"a": a, "b": b}}


def test_combine_no_records_is_pending():
    result = combine_judges([], 2)
    assert result["status"] == "pending"
    assert result["score"] is None


def test_combine_all_failed_is_failed():
    result = combine_judges([{"status": "failed"}, {"status": "failed"}], 2)
    assert result["status"] == "failed"
    assert result["score"] is None


def test_combine_some_failed_and_none_complete_is_pending():
    assert combine_judges([{"status": "failed"}], 2)["status"] == "pending"


def test_combine_some_complete_is_partial():
    result = combine_judges([_record(80.0, "j1"), {"status": "failed"}], 2)
    assert result["status"] == "partial"
    assert result["score"] == 80.0
    assert result["judges"] == 1
    assert result["expected"] == 2


def test_combine_all_complete_gives_mean_spread_and_criteria_means():
    result = combine_judges([_record(80.0, "j1", a=4.0, b=2.0), _record(70.0, "j2", a=3.0, b=3.0)], 2)
    assert result["status"] == "complete"
    assert result["score"] == 75.0
    assert result["spread"] == 10.0
    assert result["criteria"] == {"a": 3.5, "b": 2.5}
    assert result["judge_ids"] == ["j1", "j2"]
