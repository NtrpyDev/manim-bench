# ManimBench

ManimBench measures how well AI models teach mathematics. Each model is asked
to write one [Manim Community Edition](https://www.manim.community/) animation
that explains an idea to a student. The animation is rendered in a locked-down
container and scored from what is on screen.

No official results have been published from this version yet.

## How a video is scored

A video first has to pass every gate. Failing one scores zero.

- The reply is valid Python with the scene class in it.
- It renders without an error, inside the time limit.
- The video is between 15 and 120 seconds long.
- It is not blank, and something on screen changes.

A video that passes gets a score from 0 to 100:

| Part | Points | Where it comes from |
| --- | --- | --- |
| Review | 65 | Vision models rate frames from the video for correct maths, step-by-step explanation, coverage of what the task asked for, and clarity. |
| Layout | 25 | Measured from the real position of every piece of text during the render: cut off by the frame, overlapping other text, or too small to read. |
| Pacing | 10 | Measured from the video: long stretches where nothing changes. |

Every rule above is written into the prompt the model receives. Each task is
sampled several times per model, and a model's score is the mean over tasks.
The full method is in [docs/scoring.md](docs/scoring.md).

## Quickstart

Needs Python 3.11 or newer and Docker.

```bash
python -m pip install -e ".[dev]"
manimbench sandbox pull          # the pinned Manim image, about 2 GB
manimbench tasks                 # list the tasks
manimbench prompt --task fourier_series_decomposition
```

Render and measure one scene file. No model is called:

```bash
manimbench check tests/fixtures/scenes/fourier_series_decomposition/good.py \
  --task fourier_series_decomposition --quality l --fps 15
```

Run the tests. The container tests render real scenes and are skipped when
Docker or the image is missing:

```bash
python -m pytest
```

## Running the benchmark

Both model routes ship switched off, so nothing can spend money or
subscription quota by accident. Turn one on in a local copy,
`models/routes.local.yaml` (see [docs/routes.md](docs/routes.md)), then:

```bash
manimbench run --models claude-opus-5-5,gpt-6-1-sol --run-id my-run
```

That one command asks the models, renders and measures every answer, sends
the videos to the judge panel, and writes a report to `reports/my-run/`.
Stopping and restarting it repeats nothing that already finished. Each step
can also be run alone: `generate`, `render`, `judge`, `report`. See
[docs/running.md](docs/running.md) and [docs/routes.md](docs/routes.md).

## Project layout

```text
.gitignore           Files git ignores: caches, secrets, generated output.
README.md            This file.
LICENSE              MIT license.
CONTRIBUTING.md      How to add tasks, models and routes.
pyproject.toml       Package metadata and dependencies.
prompt.md            The shared part of the prompt every model receives.
benchmarks/          Task suites. v0.7 is the current one.
models/              The model list, the route switches, and the judge panel.
sandbox/             The one file that pins the Manim version and image.
src/manimbench/      The benchmark: CLI, routes, sandbox, scoring, report.
tests/               Unit tests, and real scenes rendered in the container.
docs/                Method and how-to documents.
```

Generated folders, ignored by git: `outputs/` (model answers), `runs/`
(renders and results), `reports/` (report pages and data).
