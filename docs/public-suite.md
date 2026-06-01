# Public Suite

The default public ManimBench suite is `benchmarks/v0.5/suite.yaml`.

It contains six focused tasks:

- Coordinate system animation.
- Derivative motion story.
- Matrix transformation grid.
- Geometric area proof.
- Probability distribution simulation.
- Fourier series decomposition.

The suite is designed to answer whether a model can:

- Generate valid ManimCE code with `class MainScene`.
- Render in a sandbox at 60 FPS.
- Stay under the 2 minute per-task runtime limit.
- Label mathematical objects, equations, graphs, and diagrams clearly.
- Avoid blank, cluttered, clipped, low-contrast, or visibly overlapping output.
- Use Manim objects directly rather than screenshots or placeholder assets.

Each task is generated and scored from `outputs/<model>/<task_id>.py`.
`benchmarks/v0.4/suite.yaml` remains available explicitly for regression and
historical comparison.

## Public Result Policy

Use container sandbox runs for official public comparisons:

```bash
manimbench run-file-matrix \
  --model-output model-a=outputs/model-a \
  --model-output model-b=outputs/model-b \
  --sandbox container \
  --parallel 2 \
  --run-id v05-comparison
manimbench report --run-dir runs/v05-comparison
```

Local sandbox runs are useful for debugging but are marked `official: false`.

## Smoke Suite

For quick development checks, use the v0 smoke suite explicitly:

```bash
manimbench --suite benchmarks/v0/suite.yaml list-tasks
```
