from __future__ import annotations

import argparse
import stat
from pathlib import Path

import yaml

from manimbench.model_registry import PUBLIC_MODELS_PATH
from manimbench.paths import DEFAULT_PROMPT_PATH, DEFAULT_SUITE_PATH, PROJECT_ROOT
from manimbench.prompting import build_task_prompt, load_master_prompt
from manimbench.tasks import filter_tasks, load_suite


MODEL_REGISTRY = PUBLIC_MODELS_PATH
WORKSPACES_ROOT = PROJECT_ROOT / "model_tests"


def create_model_workspaces(args: argparse.Namespace) -> int:
    suite_path = args.suite or DEFAULT_SUITE_PATH
    suite = load_suite(suite_path)
    tasks = filter_tasks(suite, args.task)
    master_prompt = load_master_prompt(args.prompt or DEFAULT_PROMPT_PATH)
    models = _select_models(_load_models(MODEL_REGISTRY), getattr(args, "model", None))

    WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)
    for model in models:
        _write_model_workspace(model, suite_path, suite, tasks, master_prompt, force=args.force)

    print(f"Created/updated {len(models)} optional model test folders in {WORKSPACES_ROOT}")
    print("Canonical V0.6 input is plain outputs/<model>/<task_id>.py files.")
    return 0


def _load_models(path: Path) -> list[dict[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models = data.get("models", [])
    if not isinstance(models, list) or not models:
        raise ValueError(f"No models found in {path}")
    return models


def _select_models(models: list[dict[str, str]], requested: list[str] | None) -> list[dict[str, str]]:
    if requested:
        requested_set = set(requested)
        selected = [model for model in models if model["id"] in requested_set]
        missing = sorted(requested_set - {model["id"] for model in selected})
        if missing:
            raise ValueError(f"Unknown model IDs: {', '.join(missing)}")
        return selected
    defaults = [model for model in models if model.get("default_enabled")]
    return defaults or models


def _write_model_workspace(
    model: dict[str, str],
    suite_path: Path,
    suite,
    tasks,
    master_prompt: str,
    force: bool,
) -> None:
    model_id = model["id"]
    display_name = model["display_name"]
    root = WORKSPACES_ROOT / model_id
    prompts_dir = root / "tasks"
    outputs_dir = root / "outputs"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    expected_prompt_names = {f"{task.id}.md" for task in tasks}
    if force:
        for stale_prompt in prompts_dir.glob("*.md"):
            if stale_prompt.name not in expected_prompt_names:
                stale_prompt.unlink()

    for task in tasks:
        prompt_path = prompts_dir / f"{task.id}.md"
        if force or not prompt_path.exists():
            prompt_path.write_text(build_task_prompt(master_prompt, task), encoding="utf-8")

    _write_text(root / "README.md", _readme(model_id, display_name, suite.id, len(tasks)), force=True)
    _write_text(root / "AGENTS.md", _agents(model_id, display_name), force=True)
    _write_text(root / "MODEL.md", _model_card(model), force=True)
    _write_text(
        root / ".gitignore",
        "outputs/*.py\noutputs/*.mp4\noutputs/__pycache__/\n.manimbench/\nmedia/\nlogs/\n",
        force=True,
    )
    _write_run_script(root / "run_benchmark.sh", model_id, suite_path)
    _write_run_script(root / "run_smoke.sh", model_id, PROJECT_ROOT / "benchmarks" / "v0" / "suite.yaml")
    _write_usage_script(root / "start_usage.sh", f"usage-start --force --suite {suite_path.relative_to(PROJECT_ROOT)}")
    _write_usage_script(root / "finish_usage.sh", "usage-finish")


def _write_text(path: Path, text: str, force: bool) -> None:
    if path.exists() and not force:
        return
    path.write_text(text, encoding="utf-8")


def _write_run_script(path: Path, model_id: str, suite_path: Path) -> None:
    relative_suite = suite_path.relative_to(PROJECT_ROOT)
    text = f"""#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

RUN_ID="${{1:-{model_id}-$(date -u +%Y%m%dT%H%M%SZ)}}"
SANDBOX="${{MANIMBENCH_SANDBOX:-container}}"
MANIM_EXEC="${{MANIM_EXECUTABLE:-python}}"

set +e
if [[ "$SANDBOX" == "local" ]]; then
  PYTHONPATH=src python -m manimbench.cli --suite "{relative_suite}" run-file-matrix \\
    --model-output "{model_id}=model_tests/{model_id}/outputs" \\
    --sandbox local \\
    --manim-executable "$MANIM_EXEC" \\
    --run-id "$RUN_ID"
  BENCH_EXIT=$?
else
  PYTHONPATH=src python -m manimbench.cli --suite "{relative_suite}" run-file-matrix \\
    --model-output "{model_id}=model_tests/{model_id}/outputs" \\
    --sandbox container \\
    --run-id "$RUN_ID"
  BENCH_EXIT=$?
fi
set -e

PYTHONPATH=src python -m manimbench.cli usage-finish \\
  --model-dir "model_tests/{model_id}" \\
  --suite "{relative_suite}"
PYTHONPATH=src python -m manimbench.cli review init \\
  --run-dir "runs/$RUN_ID" \\
  --force
PYTHONPATH=src python -m manimbench.cli share-video \\
  --run-dir "runs/$RUN_ID" \\
  --model "{model_id}" \\
  --output-dir "reports/$RUN_ID/videos"
PYTHONPATH=src python -m manimbench.cli report --run-dir "runs/$RUN_ID"

echo
echo "Report: $ROOT/reports/$RUN_ID/index.html"
echo "Usage: $ROOT/model_tests/{model_id}/usage.json"
echo "Final video: $ROOT/reports/$RUN_ID/videos/{model_id}.mp4"
exit "$BENCH_EXIT"
"""
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_usage_script(path: Path, command: str) -> None:
    text = f"""#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PYTHONPATH=src python -m manimbench.cli {command} --model-dir "model_tests/$(basename "$(dirname "$0")")"
"""
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _readme(model_id: str, display_name: str, suite_id: str, task_count: int) -> str:
    return f"""# ManimBench Model Test: {display_name}

This optional workspace is for testing **{display_name}** when a coding tool works best inside an isolated folder.

The canonical V0.6 input format is plain files under `outputs/<model>/`.

## How To Use

1. Open this folder only if your tool supports folder-level instructions:

   `model_tests/{model_id}`

2. Ask the model or tool to read the task prompts and write solutions:

   `Generate the ManimBench solutions for this folder, then run the benchmark.`

3. The generated code should read `tasks/*.md`, then write one Python file per task into:

   `outputs/`

   For the default suite, this is one file per `tasks/*.md` prompt.

4. Run:

   `./run_benchmark.sh`

Usage and cost estimates are written to:

   `usage.json`

For a quick smoke test:

`MANIMBENCH_SANDBOX=local ./run_smoke.sh`

## Suite

- Suite: `{suite_id}`
- Task prompts: `{task_count}` files in `tasks/`
- Output contract: each generated file must define `MainScene` using ManimCE.
- Usage contract: each run writes `usage.json` with time, token, and USD estimates.
"""


def _agents(model_id: str, display_name: str) -> str:
    return f"""# Instructions For ManimBench Model Test

You are testing this model: {display_name}.

Do not change benchmark prompts or task files.

If shell access is available before generation, run:

```bash
./start_usage.sh
```

For every `tasks/*.md` file:

1. Read the task prompt exactly.
2. Generate Manim Community Edition code only.
3. Save the solution as `outputs/<task_id>.py`.
4. Each file must import `from manim import *`.
5. Each file must define exactly one primary scene class named `MainScene`.
6. The animation must be 60 FPS compatible and under 120 seconds.
7. Label all mathematical examples, objects, equations, graphs, axes, transformations, and steps requested by the task.

After generating the outputs, run this if shell access is available. Otherwise, tell the operator to run it:

```bash
./run_benchmark.sh
```

For quick debugging, run:

```bash
MANIMBENCH_SANDBOX=local ./run_smoke.sh
```

`./run_benchmark.sh` performs the full benchmark pipeline:

1. Render and score the generated Manim submission.
2. Write usage, token, time, and estimated USD cost to `usage.json`.
3. Sample frames and create `review.json` for visual judging.
4. Build the final shareable MP4 and thumbnail under `../../reports/<run_id>/videos/`.
5. Generate the HTML report, leaderboard JSON, and ranking graphs under `../../reports/<run_id>/`.
"""


def _model_card(model: dict[str, str]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in model.items()) + "\n"
