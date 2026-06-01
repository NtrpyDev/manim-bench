# Reproduce A Run

Install the engine:

```bash
python -m pip install -e ".[dev]"
```

Use the recorded suite path from `runs/<run_id>/manifest.json`. V0.5 is the
default, and V0.4 remains available by passing `--suite benchmarks/v0.4/suite.yaml`.

Generate or place one solution per task:

```text
outputs/<model>/<task_id>.py
```

Each file must define `class MainScene`.

Run the matrix and report:

```bash
manimbench run-file-matrix \
  --model-output <model>=outputs/<model> \
  --sandbox container \
  --run-id <run_id>

manimbench report --run-dir runs/<run_id>
```

For local debugging, use `--sandbox local`. Local runs are not official.

Manifests are immutable after creation. If you need a new attempt, use a new
`--run-id` rather than overwriting an existing `runs/<run_id>/manifest.json`.
