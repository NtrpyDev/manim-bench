# Auto Comparison

`run_comparison.py` is for generated `model_tests/<model>/outputs` folders. It
is optional; the main V0.4 path is `python start_benchmark.py` or
`manimbench run-file-matrix --model-output model=outputs/model`.

After model workspaces contain generated `outputs/*.py`, run:

```bash
cd manimbench
python run_comparison.py
```

This scans `model_tests/*/outputs` and includes models that have every selected
V0.4 task output.

Useful options:

```bash
# Include models that are only partially complete.
python run_comparison.py --include-partial

# Run only selected task IDs.
python run_comparison.py --task basic_manim_layout --task calculus_derivative_graph

# Use the local development sandbox.
python run_comparison.py --sandbox local

# Include partial models with at least 3 generated task files.
python run_comparison.py --include-partial --min-tasks 3

# CI-style behavior: exit nonzero if any benchmarked task fails.
python run_comparison.py --strict-exit-code
```

The script runs the benchmark, writes `runs/<run_id>`, scores it, and generates
`reports/<run_id>/index.html`.
