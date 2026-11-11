# Publishing

The report in `reports/<run_id>/` is complete on its own: `index.html`, a page
per model and per task, the videos, the source files, and the data as JSON
under `data/`. It contains no paths from the machine that made it.

`manimbench publish` copies the `data/` and `videos/` folders into a separate
site repository and commits them:

```bash
manimbench publish --run-dir runs/my-run --target draft --site-repo ../manimbench-site
```

- `draft` commits to the `draft` branch. `live` commits to `main`.
- `live` is refused unless the run is official and complete, with every
  sample rendered and judged. `--allow-incomplete` overrides that.
- The site repository must already exist as a git repository. It is pushed
  only if it has an `origin` remote.
