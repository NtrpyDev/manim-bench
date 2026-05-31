# ManimBench

ManimBench is a sandboxed benchmark for evaluating how well AI models generate high-quality [Manim Community Edition](https://www.manim.community/) animations and visually explain mathematics.

The benchmark is designed for public, reproducible comparison at `manimbench.site`. Every model receives the same master [`prompt.md`](prompt.md), the same versioned task definitions, and the same execution constraints.

## What It Measures

ManimBench tests whether a model can:

- Write valid ManimCE scene code.
- Render at 60 FPS within a 2 minute runtime limit.
- Clearly label examples, diagrams, graphs, equations, variables, transformations, and mathematical steps.
- Explain mathematical ideas with accurate, idiomatic, visually clear animation.
- Avoid fake, hardcoded, or superficial solutions.
- Produce reproducible results under sandboxed execution.

## Project Layout

```text
manimbench/
  prompt.md                 # Shared model instructions, used for every task.
  benchmarks/v0.4/          # Default six-task public benchmark suite.
  benchmarks/v0.3/          # Older one-video composite benchmark suite.
  benchmarks/v2/            # Previous composite benchmark suite.
  benchmarks/v1/            # Legacy multi-task public suite.
  src/manimbench/           # Runner, providers, sandbox, scoring, reports.
  sandbox/                  # Container image for official benchmark runs.
  models/                   # Example model/provider configuration.
  runs/                     # Generated run artifacts, ignored by git.
  reports/                  # Static reports, ignored by git.
  website/                  # Public site source for manimbench.site.
  docs/                     # Contributor and methodology docs.
```

Generate a deployable site bundle after reporting:

```bash
manimbench build-site --report-dir reports/<run_id> --output-dir site/<run_id>
```

See [docs/deploy-site.md](docs/deploy-site.md) for Cloudflare Pages setup.

## Quickstart

Install the package:

```bash
cd manimbench
python -m pip install -e ".[dev]"
```

For local rendering outside the official container, install the render extras too:

```bash
python -m pip install -e ".[dev,render]"
```

ManimBench V0.4 is file-backed. It does not generate model answers for you and
does not depend on editor-specific project state. Generate one Python file per
task with your model or coding tool of choice, then save the files here:

```text
outputs/<model>/
  basic_manim_layout.py
  calculus_derivative_graph.py
  linear_algebra_transformation.py
  geometry_measurement_diagram.py
  probability_distribution.py
  advanced_math_explanation.py
```

Each file must define one ManimCE scene class named `MainScene`.

Run the guided launcher:

```bash
python start_benchmark.py
```

Choose the public V0.4 suite, select the model output folder, and use the
container sandbox for official comparisons. The launcher runs the benchmark and
writes `runs/<run_id>` plus `reports/<run_id>/index.html`.

The shell wrapper is equivalent:

```bash
bash scripts/start_benchmark.sh
```

For direct non-interactive runs:

```bash
manimbench run-file-matrix \
  --model-output my-model=outputs/my-model \
  --sandbox container \
  --run-id v04-my-model
manimbench report --run-dir runs/v04-my-model
manimbench build-site --report-dir reports/v04-my-model --output-dir site/v04-my-model
```

Generated model workspaces are still available as an optional helper for agents
that work well from isolated folders:

```bash
python setup_model_workspaces.py
```

Those folders live under `model_tests/<model>/` and use the same output
contract: write `outputs/<task_id>.py`, then run `./run_benchmark.sh`.

When model workspaces finish generating outputs, auto-compare the ready models:

```bash
python run_comparison.py
```

Track usage/cost for model workspaces:

```bash
python collect_usage.py
```

List tasks:

```bash
manimbench list-tasks
```

The default suite is the public `benchmarks/v0.4/suite.yaml`, which asks each
model for six focused outputs named `outputs/<task_id>.py`. The older
`benchmarks/v0.3/suite.yaml` single-video showcase, `benchmarks/v2/suite.yaml`,
`benchmarks/v1/suite.yaml` multi-task suite, and smaller
`benchmarks/v0/suite.yaml` smoke suite remain available explicitly.

Write the exact per-task prompts that will be sent to models:

```bash
manimbench write-prompts --output-dir runs/prompts-v04
```

Run a prepared V0.4 output folder with the local development sandbox:

```bash
manimbench run \
  --model my-model \
  --provider file \
  --outputs-dir outputs/my-model \
  --sandbox local
```

If ManimCE already exists in another environment, point the local runner at that
executable with `--manim-executable /path/to/manim`.

Run the same task suite against multiple file-backed models in one comparison
run:

```bash
manimbench run-file-matrix \
  --model-output model-a=outputs/model-a \
  --model-output model-b=outputs/model-b \
  --sandbox container
```

Render and score a single saved solution:

```bash
manimbench render \
  --model my-model \
  --task-id basic_manim_layout \
  --solution outputs/my-model/basic_manim_layout.py \
  --sandbox local
```

Rerun only failed tasks from a previous run:

```bash
manimbench rerun-failed \
  --previous-run-dir runs/<run_id> \
  --model example-model \
  --outputs-dir sample_outputs/example-model \
  --sandbox local
```

Aggregate existing result JSON files into a score summary:

```bash
manimbench score --run-dir runs/<run_id>
```

Generate a static report:

```bash
manimbench report --run-dir runs/<run_id>
```

Official results should use the container sandbox:

```bash
manimbench run \
  --model frontier-model \
  --provider file \
  --outputs-dir sample_outputs/frontier-model \
  --sandbox container
```

## Report Landing Page

The generated report is designed around a benchmark dashboard landing screen. It includes:

- A hero summary with benchmark version, model count, task count, and run metadata.
- Two ranking charts comparing all models:
  - Overall ManimBench score.
  - Efficiency score, combining score with runtime and cost metadata when available.
- A model comparison table with pass rate, average score, render success, average time, cost, tokens, and artifact links.
- Per-model and per-task result sections suitable for a future `manimbench.site` results browser.
- Site-ready JSON files under `reports/<run_id>/data/`, plus per-model and per-task HTML pages.

The visual goal is a compact benchmark landing page with rankings and readable details, not a clone of any existing site.

## Benchmark Versions

Tasks live under `benchmarks/<version>/`. Public results should always record:

- Benchmark suite version.
- Master prompt hash.
- Task file hashes.
- Model metadata.
- ManimCE version.
- Python version.
- Sandbox backend and container image.
- Scoring version.

## Sandbox Policy

The container backend is the official execution path. It runs with network disabled, a controlled per-run mount, non-root user, CPU and memory limits, process limits, and a wall-clock timeout.

The local subprocess backend is provided only for development and debugging. Local results are marked `official: false`.

## Status

This repository now defaults to the V0.4 six-task public suite. The architecture is intentionally modular so new tasks, providers, scoring checks, and report views can be added without changing the public result format.
