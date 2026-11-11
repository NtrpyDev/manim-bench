"""Proof that every scored rule is disclosed to the model."""

from __future__ import annotations

from dataclasses import replace

import pytest

from manimbench.paths import DEFAULT_PROMPT_PATH, DEFAULT_SUITE_PATH
from manimbench.prompting import build_task_prompt, load_master_prompt
from manimbench.tasks import load_suite

SUITE = load_suite(DEFAULT_SUITE_PATH)
MASTER = load_master_prompt(DEFAULT_PROMPT_PATH)
MANIM = "9.8.7"
PYTHON = "3.99.1"


def _build(suite=SUITE, task=None, master=MASTER):
    return build_task_prompt(master, suite, task or suite.tasks[0], manim_version=MANIM, python_version=PYTHON)


@pytest.mark.parametrize("task", SUITE.tasks, ids=lambda task: task.id)
class TestEveryTask:
    def test_contains_every_must_show_text(self, task):
        prompt = _build(task=task)
        for item in task.must_show:
            assert f"- {item.text}" in prompt

    def test_contains_task_title_and_prompt(self, task):
        prompt = _build(task=task)
        assert task.title in prompt
        assert task.prompt in prompt

    def test_contains_every_criterion_question_with_its_share(self, task):
        prompt = _build(task=task)
        # Weights 30/25/25/20 sum to 100, so shares are the weights.
        shares = {"correctness": "30", "explanation": "25", "task_coverage": "25", "clarity": "20"}
        for item in SUITE.criteria:
            assert f"{item.question} ({shares[item.id]}% of the review)" in prompt

    def test_contains_duration_limits(self, task):
        assert "between 15 and 120 seconds long" in _build(task=task)

    def test_contains_layout_numbers(self, task):
        prompt = _build(task=task)
        assert "under 0.09 scene units" in prompt
        assert "font size 13 for Tex and MathTex and 9 for Text" in prompt
        assert "(40% of this part)" in prompt  # clipping
        assert "overlapping other text (40%)" in prompt
        assert "(20%)" in prompt  # small text
        assert "at its maximum at 25% of the video" in prompt

    def test_contains_score_weights(self, task):
        prompt = _build(task=task)
        assert "Review of the video, 65 points" in prompt
        assert "Layout, 25 points" in prompt
        assert "Pacing, 10 points" in prompt

    def test_contains_pacing_still_limit(self, task):
        assert "longer than 8 seconds where nothing on screen changes" in _build(task=task)

    def test_contains_blank_and_activity_limits(self, task):
        prompt = _build(task=task)
        assert "not blank for more than 50% of its length" in prompt
        assert "at least 2 seconds and at least 10% of the video" in prompt

    def test_contains_manim_version_python_version_and_scene_class(self, task):
        prompt = _build(task=task)
        assert MANIM in prompt
        assert PYTHON in prompt
        assert "`MainScene`" in prompt

    def test_contains_render_settings(self, task):
        prompt = _build(task=task)
        assert "1920x1080" in prompt
        assert "60 frames per second" in prompt
        assert "900 seconds" in prompt

    def test_does_not_contain_judge_notes(self, task):
        prompt = _build(task=task)
        assert task.judge_notes not in prompt
        for line in task.judge_notes.splitlines():
            line = line.strip()
            if len(line) >= 25:
                assert line not in prompt

    def test_has_no_unfilled_placeholder(self, task):
        assert "{{" not in _build(task=task)


def test_unknown_placeholder_raises():
    with pytest.raises(ValueError, match="placeholder"):
        _build(master=MASTER + "\n{{bogus}}")


def test_custom_scene_class_appears_in_prompt():
    suite = replace(SUITE, runtime=replace(SUITE.runtime, scene_class="MyScene"))
    assert "`MyScene`" in _build(suite)


def test_changed_font_size_changes_prompt():
    suite = replace(SUITE, scoring=replace(SUITE.scoring, layout=replace(SUITE.scoring.layout, min_glyph_height=0.2)))
    prompt = _build(suite)
    assert "under 0.2 scene units" in prompt
    assert "under 0.09 scene units" not in prompt


def test_changed_layout_points_change_prompt():
    layout = replace(SUITE.scoring.layout, clipping_points=50.0, overlap_points=30.0, saturation_share=0.5)
    prompt = _build(replace(SUITE, scoring=replace(SUITE.scoring, layout=layout)))
    assert "(50% of this part)" in prompt
    assert "overlapping other text (30%)" in prompt
    assert "at its maximum at 50% of the video" in prompt


def test_changed_pacing_numbers_change_prompt():
    pacing = replace(SUITE.scoring.pacing, max_still_seconds=12.0, min_active_seconds=3.0, max_blank_share=0.25)
    prompt = _build(replace(SUITE, scoring=replace(SUITE.scoring, pacing=pacing)))
    assert "longer than 12 seconds" in prompt
    assert "at least 3 seconds" in prompt
    assert "not blank for more than 25%" in prompt


def test_changed_weights_change_prompt():
    scoring = replace(SUITE.scoring, judge_weight=50.0, layout_weight=30.0, pacing_weight=20.0)
    prompt = _build(replace(SUITE, scoring=scoring))
    assert "Review of the video, 50 points" in prompt
    assert "Layout, 30 points" in prompt
    assert "Pacing, 20 points" in prompt


def test_changed_duration_limits_change_prompt():
    runtime = replace(SUITE.runtime, min_duration_seconds=20.0, max_duration_seconds=90.0)
    assert "between 20 and 90 seconds long" in _build(replace(SUITE, runtime=runtime))


def test_prompt_never_leaks_other_tasks_judge_notes():
    prompt = _build(task=SUITE.tasks[0])
    for other in SUITE.tasks[1:]:
        assert other.judge_notes not in prompt
