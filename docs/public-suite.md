# Public Suite

The default public ManimBench suite is `benchmarks/v0.4/suite.yaml`.

It contains six focused tasks:

- Basic Manim control and layout.
- Calculus graph with a derivative tangent.
- Linear algebra matrix transformation.
- Geometry diagram with lengths, angles, and a shaded region.
- Probability/statistics distribution visualization.
- Advanced math explanation with Fourier heat equation intuition.

The suite is designed to answer whether a model can:

- Generate valid ManimCE code.
- Render in a sandbox at 60 FPS.
- Stay under the 2 minute per-task runtime limit.
- Label mathematical objects, equations, graphs, and diagrams clearly.
- Avoid blank, cluttered, clipped, low-contrast, or visibly overlapping output.
- Use Manim objects directly rather than screenshots or placeholder assets.

Each task is written to and scored from its own `outputs/<task_id>.py` file.
The older `benchmarks/v0.3/suite.yaml` remains available for historical
single-video showcase comparisons, and `benchmarks/v1/suite.yaml` remains as the
legacy broad 44-task suite.

## Public Result Policy

Use container sandbox runs for official public comparisons:

```bash
manimbench run-file-matrix \
  --model-output model-a=outputs/model-a \
  --model-output model-b=outputs/model-b \
  --sandbox container \
  --run-id v04-comparison
manimbench report --run-dir runs/v04-comparison
manimbench build-site --report-dir reports/v04-comparison --output-dir site/v04-comparison
```

Local sandbox runs are useful for debugging but are marked `official: false`.

## Smoke Suite

For quick development checks, use the v0 smoke suite explicitly:

```bash
manimbench --suite benchmarks/v0/suite.yaml list-tasks
```
