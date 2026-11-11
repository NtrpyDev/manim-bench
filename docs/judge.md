# The judge panel

`models/judges.yaml` lists the models that review videos and the route they
are called through. What each judge is asked, and how its reply becomes a
score, is in [scoring.md](scoring.md).

Use judges from more than one vendor when ranking models. A judge can favor
videos in its own style, and averaging across vendors reduces that.

Judging is its own step, so a run can be judged again by a different panel
without rendering anything twice:

```bash
manimbench judge --run-dir runs/my-run
manimbench report --run-dir runs/my-run
```

## Checking the judge against a person

A judge is only worth trusting where it agrees with a human.

```bash
manimbench review export --run-dir runs/my-run --sheet ratings/sheet.csv --limit 30
```

This writes a sheet of samples to rate and copies their videos next to it
under numbers, so nothing you open says which model made a video. Rate each
video from 0 to 4 on the same four questions the judge uses. Leave a cell
empty to skip it. Do not open the `-key.csv` file while rating.

```bash
manimbench review agreement --run-dir runs/my-run --sheet ratings/sheet.csv
```

For each question this prints how many samples were compared, the rank
correlation between your ratings and the judge's, the average gap, and
whether the judge runs higher or lower than you. A question with a low
correlation is one where the judge should not be trusted yet.
