# Contributing

## Tasks

See [docs/tasks.md](docs/tasks.md). Every task needs reference scenes, and
every scored requirement must be shown to the model.

## Models and routes

Add models in `models/models.yaml` and check them with
`manimbench models check`. See [docs/routes.md](docs/routes.md). A new route
implements `complete(target, request)` from
`src/manimbench/providers/base.py` and must refuse to run when
`MANIMBENCH_FORBID_LIVE_CALLS` is set.

## Tests

`python -m pytest` must pass. No test may call a model: use the fake route
and fake sandbox in `tests/conftest.py`. Changes to scoring need a test with
the expected number worked out by hand.

## Results

Official results use the suite's own render settings and sample count, the
pinned sandbox image, and a judge panel with more than one vendor.
