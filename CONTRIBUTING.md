# Contributing To ManimBench

Contribution guidelines are intentionally short while the benchmark suite is young.

## Adding Tasks

- Add tasks under a versioned suite directory such as `benchmarks/v0/tasks/`.
- Keep task IDs stable after public release.
- Include required labels, expected mathematical content, and automated checks.
- Prefer tasks that evaluate mathematical understanding, not only Manim syntax.

## Adding Model Providers

- Implement the provider interface in `src/manimbench/providers/`.
- Preserve the master prompt exactly.
- Store provider metadata in result manifests.

## Publishing Results

- Use the container sandbox for official results.
- Record prompt hashes, task versions, runtime versions, sandbox metadata, and scoring version.
- Do not mark local sandbox runs as official.
