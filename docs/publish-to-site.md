# Publish To Site

The benchmark repo is engine-only. It exports report data and videos, then
publishes them into a separate site repository.

Build a report first:

```bash
manimbench report --run-dir runs/<run_id>
```

Publish a draft bundle:

```bash
manimbench publish \
  --run-dir runs/<run_id> \
  --target draft \
  --site-repo ../manimbench-site
```

`draft` checks out or creates the `draft` branch in the site repo, copies
`reports/<run_id>/data/`, copies `reports/<run_id>/videos/` when present,
commits once, and pushes when an `origin` remote exists.

Publish live:

```bash
manimbench publish \
  --run-dir runs/<run_id> \
  --target live \
  --site-repo ../manimbench-site
```

`live` targets the `main` branch. It requires a complete run unless
`--allow-partial` is provided. Official container runs must include a recorded
Docker image digest before live publish.

Publish records are appended to `runs/<run_id>/publish-history.jsonl`; the run
manifest itself is not rewritten.
