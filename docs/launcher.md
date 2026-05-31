# Guided Launcher

The launcher is the primary V0.4 run path. It runs saved ManimCE solution files;
it does not ask an editor or coding agent to generate code.

Run:

```bash
cd manimbench
python start_benchmark.py
```

The launcher asks for:

- Benchmark size: full public suite, smoke test, or selected task IDs.
- Model output folder(s), discovered from `outputs/`, `sample_outputs/`, and `model_outputs/`.
- Sandbox: official container or local development fallback.
- Run ID and timeout.

It then runs the benchmark and generates the report automatically.

Current provider support is file-backed. Each selected model needs a directory
containing one Python file per V0.4 task ID:

```text
outputs/my-model/
  basic_manim_layout.py
  calculus_derivative_graph.py
  linear_algebra_transformation.py
  geometry_measurement_diagram.py
  probability_distribution.py
  advanced_math_explanation.py
```

Each file must define exactly one primary scene class named `MainScene`.

API-backed model generation is intentionally a provider extension point; the
launcher will pick it up once provider adapters are implemented.
