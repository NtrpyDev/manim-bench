# Report Landing Page Design

The ManimBench report landing page is designed as a compact benchmark dashboard.

It intentionally emphasizes:

- A centered hero with benchmark identity and methodology summary.
- A small row of run stats: model count, task count, best score, and run ID.
- Two separate ranked model charts:
  - Overall ManimBench score.
  - Efficiency ranking, which balances score against cost and runtime metadata when available.
- A detailed comparison table beneath the charts.
- Per-task result cards for quick inspection.

This gives visitors an immediate model ranking view while keeping the raw data
available in `data/results.json` and `data/models.json` for a future hosted
results browser at `manimbench.site`.
