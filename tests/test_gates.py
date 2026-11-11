"""Tests for the pass or fail gates."""

from __future__ import annotations

from conftest import GOOD_SOURCE

from manimbench.models import RenderResult, RuntimeSettings
from manimbench.scoring.gates import GATE_ORDER, check_source, evaluate_gates

RUNTIME = RuntimeSettings()  # 15 to 120 seconds, 900 second timeout


def _render(*, exit_code=0, timed_out=False, video="v.mp4", duration=20.0):
    probe = {"duration_seconds": duration} if duration is not None else {}
    return RenderResult(exit_code=exit_code, timed_out=timed_out, elapsed_seconds=1.0, video=video, probe=probe, layout_path=None, command=[], sandbox={})


def _motion(**over):
    data = {"available": True, "not_blank": True, "blank_share": 0.0, "has_motion": True, "active_seconds": 10.0, "required_active_seconds": 2.0}
    data.update(over)
    return data


def _gates(render, motion=None, source=GOOD_SOURCE):
    return evaluate_gates(check_source(source, "MainScene"), render, motion, RUNTIME)


def test_empty_source_fails_with_no_code():
    result = check_source("  \n", "MainScene")
    assert result["failure"] == "no_code"
    assert result["checks"]["code_parses"]["passed"] is False


def test_syntax_error_fails_with_syntax_error():
    result = check_source("def (:\n", "MainScene")
    assert result["failure"] == "syntax_error"
    assert "line 1" in result["checks"]["code_parses"]["detail"]


def test_null_byte_source_fails_with_syntax_error():
    assert check_source("x = 1\0\n", "MainScene")["failure"] == "syntax_error"


def test_invalid_escape_in_latex_string_passes():
    source = 'from manim import *\n\n\nclass MainScene(Scene):\n    def construct(self):\n        self.add(MathTex("\\pi"))\n'
    assert "\\pi" in source
    result = check_source(source, "MainScene")
    assert result["failure"] is None
    assert result["checks"]["code_parses"]["passed"] is True


def test_missing_scene_class_fails():
    result = check_source("from manim import *\n\n\nclass Other(Scene):\n    pass\n", "MainScene")
    assert result["failure"] == "missing_scene_class"
    assert result["checks"]["code_parses"]["passed"] is True
    assert result["checks"]["scene_class"]["passed"] is False


def test_scene_class_nested_in_function_does_not_count():
    source = "def make():\n    class MainScene:\n        pass\n    return MainScene\n"
    assert check_source(source, "MainScene")["failure"] == "missing_scene_class"


def test_good_source_passes():
    result = check_source(GOOD_SOURCE, "MainScene")
    assert result["failure"] is None
    assert result["checks"]["scene_class"]["passed"] is True


def test_render_timeout():
    result = _gates(_render(exit_code=None, timed_out=True, video=None, duration=None))
    assert result["failure"] == "render_timeout"
    assert result["passed"] is False
    assert result["not_run"] == ["video", "duration", "not_blank", "has_motion"]


def test_render_error():
    result = _gates(_render(exit_code=1, video=None, duration=None))
    assert result["failure"] == "render_error"
    assert result["checks"]["renders"]["passed"] is False
    assert result["not_run"] == ["video", "duration", "not_blank", "has_motion"]


def test_no_video():
    result = _gates(_render(video=None, duration=None))
    assert result["failure"] == "no_video"
    assert result["checks"]["renders"]["passed"] is True
    assert result["not_run"] == ["duration", "not_blank", "has_motion"]


def test_too_short():
    result = _gates(_render(duration=5.0), _motion())
    assert result["failure"] == "too_short"
    assert result["not_run"] == ["not_blank", "has_motion"]


def test_too_long():
    result = _gates(_render(duration=200.0), _motion())
    assert result["failure"] == "too_long"


def test_blank_video():
    result = _gates(_render(), _motion(not_blank=False, blank_share=0.9))
    assert result["failure"] == "blank_video"
    assert result["not_run"] == ["has_motion"]
    assert "90%" in result["checks"]["not_blank"]["detail"]


def test_static_video():
    result = _gates(_render(), _motion(has_motion=False, active_seconds=0.0))
    assert result["failure"] == "static_video"
    assert result["not_run"] == []
    assert result["checks"]["has_motion"]["passed"] is False


def test_unreadable_motion_reports_no_video():
    assert _gates(_render(), {"available": False})["failure"] == "no_video"


def test_full_pass():
    result = _gates(_render(), _motion())
    assert result["passed"] is True
    assert result["failure"] is None
    assert result["not_run"] == []
    assert list(result["checks"]) == GATE_ORDER


def test_source_failure_skips_render_gates():
    result = _gates(_render(), _motion(), source="def (:\n")
    assert result["failure"] == "syntax_error"
    assert result["passed"] is False
    assert result["not_run"] == ["renders", "video", "duration", "not_blank", "has_motion"]


def test_not_rendered_yet_is_not_a_pass():
    result = _gates(None)
    assert result["passed"] is False
    assert result["failure"] is None
    assert result["not_run"] == ["renders", "video", "duration", "not_blank", "has_motion"]


def test_checks_follow_gate_order():
    result = _gates(_render(), _motion(has_motion=False))
    assert list(result["checks"]) == [name for name in GATE_ORDER if name in result["checks"]]
