# ManimBench

ManimBench is a sandboxed benchmark for evaluating how well AI models generate
high-quality [Manim Community Edition](https://www.manim.community/) animations
and visually explain mathematics.

The engine repo contains the benchmark runner, task suites, provider adapters,
scoring, reports, and publish handoff. The public site is published from a
separate site repository; this repo does not contain a `website/` tree.

## Quickstart

```bash
python -m pip install -e ".[dev]"
```

For local rendering outside the official container, install the render extras:

```bash
python -m pip install -e ".[dev,render]"
```

List the default V0.6 public suite:

```bash
manimbench list-tasks
```

Generate outputs through the provider registry. `auto` is the default: it uses
OpenRouter for public API models and Cursor Agent CLI for Composer 2.5.

```bash
manimbench generate --model composer-2-5 --provider cursor --output-dir outputs --smoke
```

Run and report those generated files:

```bash
manimbench run-file-matrix \
  --model-output composer-2-5=outputs/composer-2-5 \
  --sandbox container \
  --parallel 2 \
  --run-id v06-composer-2-5

manimbench report --run-dir runs/v06-composer-2-5
```

Publish report data and videos to the separate site repository:

```bash
manimbench publish \
  --run-dir runs/v06-composer-2-5 \
  --target draft \
  --site-repo ../manimbench-site
```

See [docs/reproduce.md](docs/reproduce.md),
[docs/cursor-composer.md](docs/cursor-composer.md), and
[docs/publish-to-site.md](docs/publish-to-site.md) for the full workflows.

## Project Layout

```text
manimbench/
  prompt.md                 # Shared model instructions, used for every task.
  benchmarks/v0.6/          # Default six-task public benchmark suite.
  benchmarks/v0.5/          # Previous six-task public benchmark suite.
  benchmarks/v0.4/          # Older six-task public benchmark suite.
  benchmarks/v0.3/          # Older one-video composite benchmark suite.
  benchmarks/v2/            # Previous composite benchmark suite.
  benchmarks/v1/            # Legacy multi-task public suite.
  src/manimbench/           # Orchestrator, CLI, providers, sandbox, scoring.
  sandbox/                  # Container image for official benchmark runs.
  models/                   # Public model registry and provider routes.
  runs/                     # Generated run artifacts, ignored by git.
  reports/                  # Static reports and JSON exports, ignored by git.
  outputs/                  # Generated model outputs, ignored by git.
  docs/                     # Contributor and methodology docs.
```

## Output Contract

The default suite is `benchmarks/v0.6/suite.yaml`. Each generated output is one
Python file under:

```text
outputs/<model>/<task_id>.py
```

Each file must define a ManimCE scene class named `MainScene`, render at 60 FPS,
and stay under the 120 second task limit. Earlier suites remain runnable by path:

```bash
manimbench --suite benchmarks/v0.4/suite.yaml list-tasks
manimbench --suite benchmarks/v0.4/suite.yaml run-file-matrix \
  --model-output my-model=outputs/my-model \
  --sandbox local
```

## Generation

`generate` and `generate-batch` default to `--provider auto`. Auto routes
`composer-2-5` through Cursor Agent CLI because OpenRouter does not currently
publish a Composer model slug; other public models route through OpenRouter.
Direct provider routes are exposed for bypass testing:

```bash
manimbench list-models --public

cursor-agent login
manimbench generate --model composer-2-5 --provider cursor --output-dir outputs

export OPENROUTER_API_KEY=...
manimbench generate-batch \
  --models gpt-5-5,opus-4-8 \
  --provider auto \
  --output-dir outputs \
  --parallel 2 \
  --smoke
```

Generation is resumable. Complete files are skipped unless `--force` is passed.
Checkpoint state is written to `.manimbench/runs/<run_id>/state.json`, and API
call records are appended to `.manimbench/runs/<run_id>/generation.log`.
Provider usage is also summarized in `outputs/<model>/usage.json` when real
token or cost data is available. Cursor Agent CLI does not return token/cost
metadata, so Cursor spend remains visible in the Cursor dashboard.

## Rendering And Reports

Run a prepared output folder:

```bash
manimbench run \
  --model my-model \
  --provider file \
  --outputs-dir outputs/my-model \
  --sandbox local
```

Run multiple models with bounded concurrency:

```bash
manimbench run-file-matrix \
  --model-output model-a=outputs/model-a \
  --model-output model-b=outputs/model-b \
  --parallel 2 \
  --sandbox container
```

Render and score one saved solution:

```bash
manimbench render \
  --model my-model \
  --task-id coordinate_system_animation \
  --solution outputs/my-model/coordinate_system_animation.py \
  --sandbox local
```

Reports write human-readable pages plus machine-readable data under
`reports/<run_id>/data/*.json`. The exported `leaderboard.json` uses schema
version `0.6.0`.

V0.6 rankings use a capability score as the primary model ranking and publish
pass rate, source coverage, render success, and failure buckets as separate
fields. Required source terms remain score evidence, but they are no longer a
hard pass/fail gate by themselves. Because this changes leaderboard semantics,
official V0.6 results require a fresh full-suite rerun.

## Reproducibility

Run manifests are immutable once created. They record the suite metadata,
prompt hash, task hashes, configured OpenRouter slugs, provider route, Docker
image digest when available, git commit, scoring version, and publish history
reference.

Official results should use the container sandbox. The local subprocess backend
is for development and debugging; local results are marked `official: false`.
