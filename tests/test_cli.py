"""Command line: help, listings, the switched-off routes, exit codes, and no UI code anywhere."""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

from manimbench.cli import build_parser, main

COMMANDS = ["run", "generate", "render", "judge", "report", "check", "tasks", "prompt", "models", "sandbox", "review", "publish"]
TASK_IDS = [
    "coordinate_system_animation",
    "derivative_motion_story",
    "matrix_transformation_grid",
    "geometric_area_proof",
    "probability_distribution_simulation",
    "fourier_series_decomposition",
]


def repo_outputs_snapshot():
    folder = REPO_ROOT / "outputs"
    return sorted(str(path) for path in folder.rglob("*")) if folder.exists() else None


def test_no_arguments_prints_help_and_returns_zero(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: manimbench")
    for command in COMMANDS:
        assert command in out


def test_help_launches_no_ui_and_imports_no_ui_library():
    code = (
        "import sys\n"
        "from manimbench.cli import main\n"
        "assert main([]) == 0\n"
        "bad = [name for name in sys.modules if name.split('.')[0].lower() in ('textual', 'tui', 'rich', 'curses')]\n"
        "assert bad == [], bad\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stderr


def test_parser_exposes_exactly_the_documented_commands():
    parser = build_parser()
    (action,) = [item for item in parser._actions if item.__class__.__name__ == "_SubParsersAction"]
    assert list(action.choices) == COMMANDS


def test_tasks_lists_six_task_ids(capsys):
    assert main(["tasks"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("ManimBench 0.7 (manimbench-v0.7), 3 samples per task")
    assert [line.split("\t")[0] for line in lines[1:]] == TASK_IDS


def test_prompt_prints_the_exact_task_prompt(capsys, suite):
    from manimbench.generation import task_prompts
    from manimbench.sandbox.settings import load_sandbox_settings
    from manimbench.paths import DEFAULT_PROMPT_PATH
    from manimbench.tasks import filter_tasks

    assert main(["prompt", "--task", "fourier_series_decomposition"]) == 0
    out = capsys.readouterr().out
    expected = task_prompts(suite, DEFAULT_PROMPT_PATH, filter_tasks(suite, ["fourier_series_decomposition"]), load_sandbox_settings())
    assert out == expected["fourier_series_decomposition"] + "\n"
    assert "{{" not in out


def test_prompt_unknown_task_returns_2(capsys):
    assert main(["prompt", "--task", "no_such_task"]) == 2
    assert "Unknown task IDs: no_such_task" in capsys.readouterr().err


def test_models_shows_both_routes_off(capsys):
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert "route openrouter: off (default)" in out
    assert "route claude-cli: off" in out
    assert "claude-opus-5-5\tClaude Opus 5.5\tAnthropic\tclaude-cli, openrouter" in out
    assert ": on" not in out


def test_generate_with_routes_off_returns_2_and_writes_nothing(capsys, tmp_path):
    before = repo_outputs_snapshot()
    out_dir = tmp_path / "out"
    assert main(["generate", "--models", "claude-opus-5-5", "--outputs-dir", str(out_dir)]) == 2
    captured = capsys.readouterr()
    assert "switched off" in captured.err
    assert not out_dir.exists()
    assert repo_outputs_snapshot() == before


def test_generate_dry_run_returns_0_and_lists_the_plan(capsys, tmp_path):
    before = repo_outputs_snapshot()
    code = main(["generate", "--models", "claude-opus-5-5", "--task", "coordinate_system_animation", "--samples", "2", "--dry-run", "--outputs-dir", str(tmp_path / "o")])
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == [
        "claude-opus-5-5/coordinate_system_animation/sample-1\tmissing",
        "claude-opus-5-5/coordinate_system_animation/sample-2\tmissing",
    ]
    assert not (tmp_path / "o").exists()
    assert repo_outputs_snapshot() == before


def test_generate_unknown_model_returns_2(capsys, tmp_path):
    assert main(["generate", "--models", "no-such-model", "--outputs-dir", str(tmp_path / "o")]) == 2
    assert "Unknown model id(s): no-such-model" in capsys.readouterr().err


def test_generate_unknown_task_returns_2(capsys, tmp_path):
    assert main(["generate", "--models", "claude-opus-5-5", "--task", "no_such_task", "--outputs-dir", str(tmp_path / "o")]) == 2
    assert "Unknown task IDs" in capsys.readouterr().err


def test_generate_with_a_model_lacking_the_route_returns_2(capsys, tmp_path):
    code = main(["generate", "--models", "gpt-6-1-sol", "--route", "claude-cli", "--outputs-dir", str(tmp_path / "o")])
    assert code == 2
    assert "no claude-cli route" in capsys.readouterr().err


def test_empty_models_list_returns_2(capsys, tmp_path):
    assert main(["generate", "--models", " , ", "--outputs-dir", str(tmp_path / "o")]) == 2
    assert "at least one model id" in capsys.readouterr().err


def test_models_argument_is_required():
    with pytest.raises(SystemExit) as info:
        main(["generate"])
    assert info.value.code == 2


def test_module_runs_as_a_subprocess():
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    done = subprocess.run(
        [sys.executable, "-m", "manimbench.cli", "tasks"], capture_output=True, text=True, env=env, timeout=60, cwd=REPO_ROOT
    )
    assert done.returncode == 0, done.stderr
    assert [line.split("\t")[0] for line in done.stdout.strip().splitlines()[1:]] == TASK_IDS


def test_no_ui_code_or_dependency_anywhere_in_the_package_or_pyproject():
    # Whole words only: "getuid" contains the letters "tui" and is not a UI.
    pattern = re.compile(r"\b(textual|tui)\b", re.IGNORECASE)
    files = sorted((REPO_ROOT / "src" / "manimbench").rglob("*.py")) + [REPO_ROOT / "pyproject.toml"]
    assert len(files) > 10
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in files
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert offenders == []
    assert not any(path.parent.name == "tui" for path in files)
