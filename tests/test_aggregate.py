"""Tests for sample and model score aggregation. Default weights: judge 65, layout 25, pacing 10."""

from __future__ import annotations

import pytest

from manimbench.models import ScoringSettings
from manimbench.scoring.aggregate import _bootstrap_interval, sample_score, summarize_model

SETTINGS = ScoringSettings()
PASSED = {"passed": True}
LAYOUT = {"available": True, "score": 80.0}
PACING = {"available": True, "score": 100.0}


def test_failed_gate_scores_zero():
    result = sample_score({"passed": False, "failure": "render_error"}, LAYOUT, PACING, {"status": "complete", "score": 90.0}, SETTINGS)
    assert result["status"] == "failed_gate"
    assert result["quality"] == 0.0
    assert result["automated"] == 0.0
    assert result["components"] == {}


def test_awaiting_judge_has_automated_score_from_layout_and_pacing():
    # (80 * 25 + 100 * 10) / 35 = 3000 / 35 = 85.714...
    result = sample_score(PASSED, LAYOUT, PACING, None, SETTINGS)
    assert result["status"] == "awaiting_judge"
    assert result["quality"] is None
    assert result["automated"] == 85.71
    assert result["weights"] == {"layout": 25.0, "pacing": 10.0}


def test_pending_judge_status_is_still_awaiting():
    result = sample_score(PASSED, LAYOUT, PACING, {"status": "pending", "score": None}, SETTINGS)
    assert result["status"] == "awaiting_judge"


def test_fully_scored_sample():
    # (80 * 25 + 100 * 10 + 90 * 65) / 100 = (2000 + 1000 + 5850) / 100 = 88.5
    result = sample_score(PASSED, LAYOUT, PACING, {"status": "complete", "score": 90.0}, SETTINGS)
    assert result["status"] == "scored"
    assert result["quality"] == 88.5
    assert result["components"] == {"layout": 80.0, "pacing": 100.0, "judge": 90.0}
    assert result["weights"] == {"layout": 25.0, "pacing": 10.0, "judge": 65.0}


def test_layout_unavailable_rescales_weights():
    # (100 * 10 + 90 * 65) / 75 = 6850 / 75 = 91.333...
    result = sample_score(PASSED, {"available": False, "score": None}, PACING, {"status": "complete", "score": 90.0}, SETTINGS)
    assert result["quality"] == 91.33
    assert result["weights"] == {"pacing": 10.0, "judge": 65.0}


def test_missing_layout_and_pacing_leaves_only_judge():
    result = sample_score(PASSED, None, None, {"status": "complete", "score": 70.0}, SETTINGS)
    assert result["quality"] == 70.0


def test_nothing_measured_and_no_judge_has_no_automated_score():
    result = sample_score(PASSED, None, None, None, SETTINGS)
    assert result["automated"] is None
    assert result["quality"] is None


def test_partial_judge_counts_as_scored():
    result = sample_score(PASSED, LAYOUT, PACING, {"status": "partial", "score": 90.0}, SETTINGS)
    assert result["status"] == "scored"
    assert result["quality"] == 88.5


def test_failed_judge_leaves_sample_awaiting():
    assert sample_score(PASSED, LAYOUT, PACING, {"status": "failed", "score": None}, SETTINGS)["status"] == "awaiting_judge"


def test_custom_weights_are_used():
    settings = ScoringSettings(judge_weight=50.0, layout_weight=50.0, pacing_weight=0.0)
    # (80 * 50 + 90 * 50) / 100 = 85
    assert sample_score(PASSED, LAYOUT, PACING, {"status": "complete", "score": 90.0}, settings)["quality"] == 85.0


# summarize_model


def _scored(task, quality, passed=True):
    return {"task": {"id": task}, "score": {"status": "scored", "quality": quality, "automated": quality}, "gates": {"passed": passed}}


def _failed(task, failure="render_error"):
    return {"task": {"id": task}, "score": {"status": "failed_gate", "quality": 0.0, "automated": 0.0}, "gates": {"passed": False, "failure": failure}}


def _awaiting(task, automated):
    return {"task": {"id": task}, "score": {"status": "awaiting_judge", "quality": None, "automated": automated}, "gates": {"passed": True}}


def test_complete_model_exact_quality():
    # a: mean(80, 60) = 70; b: mean(90, 90) = 90; model = 80.
    results = [_scored("a", 80.0), _scored("a", 60.0), _scored("b", 90.0), _scored("b", 90.0)]
    summary = summarize_model(results, ["a", "b"], 2)
    assert summary["complete"] is True
    assert summary["quality"] == 80.0
    assert summary["tasks"]["a"]["quality"] == 70.0
    assert summary["tasks"]["a"]["sample_qualities"] == [80.0, 60.0]
    assert summary["samples"] == {"expected": 4, "present": 4, "missing": 0, "scored": 4, "awaiting_judge": 0, "failed_gate": 0}
    assert summary["gate_pass_rate"] == 100.0


def test_failed_gate_counts_as_zero_and_appears_in_failures():
    # a: mean(80, 0) = 40; b: 60; model = 50. Pass rate 3 of 4 = 75.0.
    results = [_scored("a", 80.0), _failed("a"), _scored("b", 60.0), _scored("b", 60.0)]
    summary = summarize_model(results, ["a", "b"], 2)
    assert summary["quality"] == 50.0
    assert summary["failures"] == {"render_error": 1}
    assert summary["samples"]["failed_gate"] == 1
    assert summary["gate_pass_rate"] == 75.0
    assert summary["tasks"]["a"]["passed_gates"] == 1


def test_failures_are_counted_by_name():
    results = [_failed("a", "no_video"), _failed("a", "no_video"), _failed("b", "blank_video"), _scored("b", 50.0)]
    assert summarize_model(results, ["a", "b"], 2)["failures"] == {"blank_video": 1, "no_video": 2}


def test_failed_gate_without_failure_name_is_counted_as_unknown():
    result = _failed("a")
    result["gates"] = {"passed": False}
    assert summarize_model([result], ["a"], 1)["failures"] == {"unknown": 1}


def test_missing_sample_makes_model_incomplete_with_no_quality():
    results = [_scored("a", 80.0), _scored("a", 60.0), _scored("b", 90.0)]
    summary = summarize_model(results, ["a", "b"], 2)
    assert summary["complete"] is False
    assert summary["quality"] is None
    assert summary["quality_interval"] is None
    assert summary["samples"]["missing"] == 1
    assert summary["tasks"]["b"]["complete"] is False
    assert summary["tasks"]["b"]["quality"] is None


def test_task_with_no_samples_is_incomplete():
    summary = summarize_model([_scored("a", 80.0)], ["a", "b"], 1)
    assert summary["complete"] is False
    assert summary["automated"] is None


def test_awaiting_judge_is_incomplete_but_has_automated_score():
    # a: mean(80, 70) = 75; b: mean(90, 90) = 90; automated = 82.5
    results = [_awaiting("a", 80.0), _awaiting("a", 70.0), _awaiting("b", 90.0), _awaiting("b", 90.0)]
    summary = summarize_model(results, ["a", "b"], 2)
    assert summary["complete"] is False
    assert summary["quality"] is None
    assert summary["automated"] == 82.5
    assert summary["samples"]["awaiting_judge"] == 4


def test_every_task_is_weighted_equally_regardless_of_sample_count():
    # a has 3 samples all 100, b has 2 samples 50 and 0. Task means 100 and 25, model 62.5.
    # Pooling every sample would give (300 + 50) / 5 = 70 instead.
    results = [_scored("a", 100.0)] * 3 + [_scored("b", 50.0), _failed("b")]
    summary = summarize_model(results, ["a", "b"], 2)
    assert summary["quality"] == 62.5


def test_results_for_unlisted_tasks_are_ignored():
    summary = summarize_model([_scored("a", 80.0), _scored("zzz", 0.0)], ["a"], 1)
    assert summary["quality"] == 80.0
    assert summary["samples"]["present"] == 1


def test_gate_pass_rate_rounds_to_one_decimal():
    results = [_scored("a", 50.0), _scored("a", 50.0), _failed("a")]
    assert summarize_model(results, ["a"], 3)["gate_pass_rate"] == 66.7


def test_no_results_has_no_gate_pass_rate():
    assert summarize_model([], ["a"], 1)["gate_pass_rate"] is None


# bootstrap


def test_bootstrap_interval_is_deterministic():
    results = [_scored("a", 80.0), _scored("a", 60.0), _scored("b", 90.0), _scored("b", 30.0)]
    first = summarize_model(results, ["a", "b"], 2)["quality_interval"]
    second = summarize_model(results, ["a", "b"], 2)["quality_interval"]
    assert first == second


def test_bootstrap_interval_contains_point_estimate():
    results = [_scored("a", 80.0), _scored("a", 60.0), _scored("b", 90.0), _scored("b", 30.0)]
    summary = summarize_model(results, ["a", "b"], 2)
    low, high = summary["quality_interval"]
    assert low <= summary["quality"] <= high
    assert low < high


def test_bootstrap_interval_is_a_point_when_all_samples_equal():
    results = [_scored("a", 40.0)] * 3 + [_scored("b", 40.0)] * 3
    summary = summarize_model(results, ["a", "b"], 3)
    assert summary["quality_interval"] == [40.0, 40.0]


def test_bootstrap_of_empty_task_is_none():
    assert _bootstrap_interval([[1.0], []]) is None
    assert _bootstrap_interval([]) is None
