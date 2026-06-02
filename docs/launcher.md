# Guided Launcher

The launcher is a guided run path. It runs saved ManimCE solution files;
it does not ask an editor or coding agent to generate code.

Run:

```bash
cd manimbench
python start_benchmark.py
```

The launcher asks for:

- Benchmark size: full public suite, smoke test, or selected task IDs.
- Model output folder(s), discovered from `outputs/` and `model_outputs/`.
- Sandbox: official container or local development fallback.
- Run ID and timeout.

It then runs the benchmark and generates the report automatically.

Each selected model needs a directory containing one Python file per V0.6 task ID:

```text
outputs/my-model/
  coordinate_system_animation.py
  derivative_motion_story.py
  matrix_transformation_grid.py
  geometric_area_proof.py
  probability_distribution_simulation.py
  fourier_series_decomposition.py
```

Each file must define exactly one primary scene class named `MainScene`.

API-backed generation is available through `manimbench generate` and
`manimbench generate-batch`.
