"""Real renders in the real sandbox image. No model is called.

These tests are the proof that the scorer does what it says: hand-written
scenes with a known right answer are rendered in the pinned container and
must score the way they should. They need Docker and the pinned image, and
are skipped when either is missing.

Renders use low quality and a low frame rate to stay fast. Layout is measured
in Manim's own units and motion on downscaled frames, so the verdicts do not
depend on resolution.
"""

from __future__ import annotations

import json
import time

import pytest
from conftest import SCENES, docker_ready

from manimbench.rendering import render_sample
from manimbench.sandbox import ContainerSandbox
from manimbench.sandbox.container import MAX_LOG_BYTES

pytestmark = [
    pytest.mark.container,
    pytest.mark.skipif(not docker_ready(), reason="Docker or the pinned sandbox image is not available"),
]

TASK_IDS = [
    "coordinate_system_animation",
    "derivative_motion_story",
    "matrix_transformation_grid",
    "geometric_area_proof",
    "probability_distribution_simulation",
    "fourier_series_decomposition",
]


@pytest.fixture(scope="module")
def sandbox() -> ContainerSandbox:
    return ContainerSandbox()


def check(tmp_path, suite, sandbox, scene_path, task_id="fourier_series_decomposition", timeout_seconds=300):
    task = next(task for task in suite.tasks if task.id == task_id)
    source = scene_path.read_text(encoding="utf-8")
    target = tmp_path / "sample"
    result = render_sample(
        target, suite, task, "fixture", 1, source, None, sandbox, quality="l", fps=15, timeout_seconds=timeout_seconds
    )
    return result, target


def test_suite_lists_the_tasks_these_tests_cover(suite):
    assert [task.id for task in suite.tasks] == TASK_IDS


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_good_scene_passes_every_gate_with_clean_layout(tmp_path, suite, sandbox, task_id):
    result, _target = check(tmp_path, suite, sandbox, SCENES / task_id / "good.py", task_id)
    assert result["gates"]["passed"], result["gates"]
    assert result["gates"]["not_run"] == []
    assert result["layout"]["available"]
    assert result["layout"]["score"] >= 97, result["layout"]["issues"]
    assert result["pacing"]["score"] == 100.0
    assert result["score"]["status"] == "awaiting_judge"
    assert result["score"]["automated"] >= 97
    assert suite.runtime.min_duration_seconds <= result["render"]["probe"]["duration_seconds"] <= suite.runtime.max_duration_seconds


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_bad_layout_scene_renders_but_loses_layout_points(tmp_path, suite, sandbox, task_id):
    result, _target = check(tmp_path, suite, sandbox, SCENES / task_id / "bad_layout.py", task_id)
    assert result["gates"]["passed"], result["gates"]
    assert result["layout"]["score"] <= 50, result["layout"]
    seconds = result["layout"]["problem_seconds"]
    assert seconds["clipping"] > 0 and seconds["overlap"] > 0 and seconds["small_text"] > 0
    # The same lesson with a clean layout must outscore it on the measured parts.
    assert result["score"]["automated"] < 70


@pytest.mark.parametrize(
    ("scene", "failure"),
    [
        ("crash.py", "render_error"),
        ("static.py", "static_video"),
        ("blank.py", "blank_video"),
        ("too_short.py", "too_short"),
        ("too_long.py", "too_long"),
    ],
)
def test_generic_bad_scene_fails_the_right_gate(tmp_path, suite, sandbox, scene, failure):
    result, _target = check(tmp_path, suite, sandbox, SCENES / "generic" / scene)
    assert not result["gates"]["passed"]
    assert result["gates"]["failure"] == failure
    assert result["score"]["quality"] == 0.0
    assert result["layout"] is None


@pytest.mark.parametrize(("scene", "failure"), [("syntax_error.py", "syntax_error"), ("no_scene_class.py", "missing_scene_class")])
def test_unusable_code_is_rejected_without_starting_a_container(tmp_path, suite, sandbox, scene, failure):
    result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / scene)
    assert result["gates"]["failure"] == failure
    assert result["render"] is None
    assert not (target / "logs").exists()


def test_a_scene_that_never_finishes_is_stopped_and_its_container_is_gone(tmp_path, suite, sandbox):
    import subprocess

    started = time.monotonic()
    result, _target = check(tmp_path, suite, sandbox, SCENES / "generic" / "never_finishes.py", timeout_seconds=15)
    assert time.monotonic() - started < 90
    assert result["gates"]["failure"] == "render_timeout"
    assert result["render"]["timed_out"] is True
    # Look for this render's own container, so other renders on the machine do not matter.
    command = result["render"]["command"]
    name = command[command.index("--name") + 1]
    assert name.startswith("manimbench-")
    left_over = subprocess.run(
        [sandbox.engine, "ps", "--all", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert left_over.stdout.strip() == ""


def test_the_sandbox_has_no_network(tmp_path, suite, sandbox):
    result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "network.py")
    assert result["gates"]["failure"] == "render_error"
    log = (target / "logs" / "stderr.log").read_text(encoding="utf-8")
    assert "URLError" in log or "Temporary failure in name resolution" in log or "Network is unreachable" in log


def test_a_scene_cannot_write_outside_its_own_folder(tmp_path, suite, sandbox):
    result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "escape.py")
    log = (target / "logs" / "stderr.log").read_text(encoding="utf-8")
    assert "SANDBOX ESCAPE" not in log
    assert result["gates"]["passed"], result["gates"]


def test_render_output_is_capped(tmp_path, suite, sandbox):
    result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "noisy.py")
    assert result["gates"]["passed"], result["gates"]
    assert (target / "logs" / "stdout.log").stat().st_size <= MAX_LOG_BYTES


def test_the_final_video_is_used_not_a_partial_clip(tmp_path, suite, sandbox):
    result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "escape.py")
    video = result["render"]["video"]
    assert video.endswith("result.mp4") and "partial_movie_files" not in video
    # Manim leaves its partial clips behind; they must not be mistaken for the result.
    assert list((target / "media").rglob("partial_movie_files/*/*.mp4"))


def test_the_container_reports_the_pinned_manim_version(tmp_path, suite, sandbox):
    _result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "escape.py")
    layout = json.loads((target / "layout.json").read_text(encoding="utf-8"))
    assert layout["manim_version"] == sandbox.settings.manim_version
    assert layout["python_version"] == sandbox.settings.python_version


def test_result_holds_no_path_from_this_machine(tmp_path, suite, sandbox):
    _result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "escape.py")
    text = (target / "result.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert "/home/" not in text


def test_the_container_command_is_locked_down(sandbox, tmp_path):
    command = sandbox.command(tmp_path, "name", quality="l", fps=15, scene_class="MainScene")
    joined = " ".join(command)
    for flag in ["--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--pids-limit", "--memory", "--user"]:
        assert flag in joined, flag
    assert sandbox.settings.digest in joined
    assert "harness.py:ro" in joined
    assert "--privileged" not in joined


def test_text_shrunk_inside_latex_is_caught_as_small(tmp_path, suite, sandbox):
    result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "shrunk_latex.py")
    assert result["gates"]["passed"], result["gates"]
    layout = json.loads((target / "layout.json").read_text(encoding="utf-8"))
    caption = next(item for item in layout["snapshots"][0]["text"] if "too small" in item["string"])
    assert caption["font_size"] >= 16  # What Manim reports. It is recorded but never used for scoring.
    assert caption["glyph_height"] < suite.scoring.layout.min_glyph_height
    assert result["layout"]["problem_seconds"]["small_text"] > 0
    assert result["layout"]["score"] == 80.0


def test_readouts_are_recorded_as_drawn_and_matrix_brackets_are_not_text(tmp_path, suite, sandbox):
    result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "readouts.py")
    assert result["gates"]["passed"], result["gates"]
    layout = json.loads((target / "layout.json").read_text(encoding="utf-8"))
    first = [item["string"] for item in layout["snapshots"][0]["text"]]
    last = [item["string"] for item in layout["snapshots"][-1]["text"]]
    assert "+1.00" in first and "+3.50" in last
    assert sorted(value for value in first if value != "+1.00") == ["0", "1", "1", "2"]
    assert not any("array" in value or "left" in value for value in first + last)
    assert result["layout"]["score"] == 100.0


def test_a_transformed_label_is_recorded_as_what_it_now_shows(tmp_path, suite, sandbox):
    result, target = check(tmp_path, suite, sandbox, SCENES / "generic" / "transformed_label.py")
    assert result["gates"]["passed"], result["gates"]
    layout = json.loads((target / "layout.json").read_text(encoding="utf-8"))
    assert [item["string"] for item in layout["snapshots"][0]["text"]] == [r"S_1(x)=\frac{4}{\pi}\sin x"]
    final = layout["snapshots"][-1]["text"]
    assert [item["string"] for item in final] == ["terms up to k = 31"]
    # Manim's own font size for the reshaped object is far below the 32 it was given.
    assert final[0]["font_size"] < 24
    assert final[0]["glyph_height"] > suite.scoring.layout.min_glyph_height
    assert result["layout"]["problem_seconds"]["small_text"] == 0.0
    assert result["layout"]["score"] == 100.0
