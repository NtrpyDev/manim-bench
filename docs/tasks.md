# Adding Benchmark Tasks

Tasks live under versioned suite directories such as `benchmarks/v0.4/tasks/`.
The default public suite is `benchmarks/v0.4/suite.yaml`; `benchmarks/v0`
remains as a small smoke-test suite.

Each task should define:

- Stable `id` and `version`.
- `difficulty`: a stable suite-specific level, such as `focused`, `easy`,
  `medium`, `hard`, or `extreme`.
- Mathematical `domains`.
- A task-specific prompt.
- Required labels and visual elements.
- Automated checks.
- Human review rubric notes.

The public suite may use task packs with this shape:

```yaml
defaults:
  version: "1.0"
  difficulty: medium
tasks:
  - id: example_task
    domains: [calculus]
    title: Example Task
    prompt: Explain the concept visually.
    required_labels: [concept, equation]
    required_visuals: [graph, equation]
```

After a suite is public, avoid changing task semantics in place. Add a new task
version or benchmark suite version instead.
