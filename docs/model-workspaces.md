# Model Workspaces

The canonical V0.4 input format is a plain file-backed output directory:

```text
outputs/<model>/
  basic_manim_layout.py
  calculus_derivative_graph.py
  linear_algebra_transformation.py
  geometry_measurement_diagram.py
  probability_distribution.py
  advanced_math_explanation.py
```

Each file must define one ManimCE scene class named `MainScene`. The guided
launcher reads these folders directly:

```bash
cd manimbench
python start_benchmark.py
```

Generated model workspaces are optional. They are useful when an AI coding agent
works best inside an isolated folder, but they are not required and are not
editor-specific.

Generate them with:

```bash
cd manimbench
python setup_model_workspaces.py
```

Each generated folder under `model_tests/<model>/` contains:

- `AGENTS.md`: task instructions for an agent.
- `MODEL.md`: the model identity.
- `tasks/*.md`: resolved V0.4 benchmark prompts.
- `outputs/`: where generated `MainScene` files go.
- `run_benchmark.sh`: runs the selected suite for that model.
- `run_smoke.sh`: quick smoke run.

The workspace contract is the same as the direct output contract: read each
`tasks/*.md` file, write `outputs/<task_id>.py`, define `MainScene`, then run
`./run_benchmark.sh`.

Configured model names, display names, tokenizers, and estimate rates live in
`models/models.yaml`.
