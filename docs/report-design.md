# Report Landing Page Design

The ManimBench report landing page is designed as a compact benchmark dashboard.

It intentionally emphasizes:

- A centered hero with benchmark identity and methodology summary.
- A small row of run stats: model count, task count, best score, and run ID.
- Two separate ranked model charts:
  - V0.6 capability score.
  - Efficiency ranking, which balances score against cost and runtime metadata when available.
- A detailed comparison table beneath the charts with pass rate, coverage,
  render success, and failure mix.
- Per-task result cards for quick inspection.

This gives visitors an immediate model ranking view without hiding why tasks
failed. The raw data stays available in `data/results.json`,
`data/models.json`, and `data/leaderboard.json` for the hosted results browser
at `manimbench.site`.
