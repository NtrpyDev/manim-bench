# Running the benchmark

## One command

```bash
manimbench run --models claude-opus-5-5,gpt-6-1-sol --run-id my-run --parallel 4
```

This does four steps in order. Each can also be run alone.

| Step | Command | Reads | Writes |
| --- | --- | --- | --- |
| Ask the models | `manimbench generate --models ...` | `prompt.md`, the suite | `outputs/<model>/<task>/sample-N.py` and `.json` |
| Render and measure | `manimbench render --models ... --run-id R` | `outputs/` | `runs/R/<model>/<task>/sample-N/` |
| Judge | `manimbench judge --run-dir runs/R` | `runs/R/` | judge records, updated results |
| Report | `manimbench report --run-dir runs/R` | `runs/R/` | `reports/R/` |

Model ids come from `models/models.yaml`. `manimbench models` lists them and
shows whether each route is on.

## Stopping and restarting

Every step keeps what it finished.

- **Generate** skips any sample that already has a record. A reply with no
  code in it is a finished answer and is not asked again. A call that failed
  for a reason outside the model (rate limit, timeout) is asked again next
  time. `--dry-run` shows what would be asked.
- **Render** reuses any sample that already has a result in the run.
- **Judge** reuses every judge record that completed.

`--force` on any step redoes it.

## Stale answers

An answer records the exact prompt it was written for. If the prompt, the
suite, or the Manim version changes, older answers are marked stale. They are
not regenerated and not rendered unless you say so (`generate --force`, or
`render --allow-stale` for debugging). This keeps answers written for
different rules from being mixed into one result.

## Official and not official

A run is official when it uses the suite's own render quality, frame rate and
sample count. `--quality`, `--fps` and a smaller `--samples` are for testing
and mark the run as not official in its report. A run id is tied to its
settings: continuing a run with different settings is refused.

## Checking one file

```bash
manimbench check my_scene.py --task derivative_motion_story --quality l --fps 15 --out /tmp/check
```

Renders the file in the sandbox and prints the gates, layout and pacing. With
`--out` the render, logs and layout record are kept in that folder.

## Cost

Every answer's record holds the tokens and cost the route reported. The
report adds them up per model, split into generation and judging, and counts
any sample whose cost was not reported instead of guessing it.
