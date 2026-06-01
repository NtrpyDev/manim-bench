from pathlib import Path

from manimbench.paths import DEFAULT_SUITE_PATH
from manimbench.tasks import load_suite


def test_load_default_suite():
    suite = load_suite(DEFAULT_SUITE_PATH)

    assert suite.id == "manimbench-v0.5-public"
    assert len(suite.tasks) == 6
    assert {task.id for task in suite.tasks} == {
        "coordinate_system_animation",
        "derivative_motion_story",
        "matrix_transformation_grid",
        "geometric_area_proof",
        "probability_distribution_simulation",
        "fourier_series_decomposition",
    }
    assert suite.tasks[0].automated_checks["min_required_labels"] == 5


def test_load_v04_suite_by_path():
    suite = load_suite(DEFAULT_SUITE_PATH.parents[1] / "v0.4" / "suite.yaml")

    assert suite.id == "manimbench-v0.4-public"
    assert len(suite.tasks) == 6
    assert {task.id for task in suite.tasks} == {
        "basic_manim_layout",
        "calculus_derivative_graph",
        "linear_algebra_transformation",
        "geometry_measurement_diagram",
        "probability_distribution",
        "advanced_math_explanation",
    }


def test_task_paths_are_absolute():
    suite = load_suite(DEFAULT_SUITE_PATH)

    assert all(task.path.is_absolute() for task in suite.tasks)
    assert all(Path(task.path).exists() for task in suite.tasks)


def test_load_smoke_suite():
    suite = load_suite(DEFAULT_SUITE_PATH.parents[1] / "v0" / "suite.yaml")

    assert suite.id == "manimbench-v0"
    assert len(suite.tasks) == 7


def test_load_v1_suite():
    suite = load_suite(DEFAULT_SUITE_PATH.parents[1] / "v1" / "suite.yaml")

    assert suite.id == "manimbench-v1-public"
    assert len(suite.tasks) == 44
    assert {task.difficulty for task in suite.tasks} >= {"easy", "medium", "hard", "extreme"}


def test_load_v2_suite():
    suite = load_suite(DEFAULT_SUITE_PATH.parents[1] / "v2" / "suite.yaml")

    assert suite.id == "manimbench-v2-composite"
    assert len(suite.tasks) == 1


def test_load_v03_suite():
    suite = load_suite(DEFAULT_SUITE_PATH.parents[1] / "v0.3" / "suite.yaml")

    assert suite.id == "manimbench-v0.3-composite"
    assert len(suite.tasks) == 1
