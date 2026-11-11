# Writing tasks

A task is one YAML file in a suite's `tasks/` folder, listed in `suite.yaml`.

```yaml
id: derivative_motion_story
version: "0.7.0"
title: The derivative as the slope of the tangent
domains: [calculus]
prompt: |
  What to teach, in plain words. Fix the example (the function, the matrix)
  so every model explains the same thing.
must_show:
  - id: secant
    text: A line through two points on the curve, with its slope worked out.
judge_notes: |
  The correct mathematics, for the judge to check against.
```

Rules:

- **Everything scored is shown.** `must_show` is printed into the prompt and
  is what the judge checks item by item. Do not grade anything the prompt
  does not ask for.
- **Say what to show, not how to code it.** Never require a particular Manim
  class or function.
- **`judge_notes` holds facts only.** It is not shown to the model. It may
  state what is mathematically correct. It must not add requirements.
- **Each item must be checkable from frames.** "The tangent line, with its
  slope stated" can be seen. "A clear explanation" cannot.
- **Ids are permanent** once results are published.

Every task needs reference scenes in `tests/fixtures/scenes/<task_id>/`:
`good.py`, a correct, well laid out answer, and `bad_layout.py`, the same
lesson with deliberate layout faults. The container tests render both and
check that they score as they should.
