# Scoring Methodology

ManimBench v0.6 combines automated checks with human review while separating
ranking score from operational pass/fail status.

Automated checks include:

- Required `MainScene` class.
- Forbidden import and operation checks.
- Required visible label presence in Manim text/equation calls.
- AST-aware source term checks that ignore comments and unused strings.
- Suspicious source detection for placeholders, inactive scenes, static assets,
  and keyword stuffing.
- Sandbox exit code and timeout.
- Generated media presence.
- FPS verification.
- Duration verification.
- Rendered-frame sanity checks for blank output, clutter, edge clipping, low
  contrast, and likely label collisions.
- Best-effort local layout probing for label bounds and obvious overlaps.

Human review uses a 0-5 scale for:

- Mathematical correctness.
- Manim correctness and idiomatic usage.
- Visual clarity and labeling.
- Animation quality and pacing.
- Faithfulness to the prompt.
- Mathematical depth.
- Robustness and reproducibility.

## V0.6 Ranking Policy

The primary leaderboard ranking is the capability score. It is the automated
score after caps for severe render, source, and visual failures.

Operational pass/fail is a separate gate. A task passes when:

- The submitted source parses and defines `MainScene`.
- Forbidden imports and operations are absent.
- Required visible labels and required sections are present.
- The scene renders, produces media, uses the expected FPS, and stays within
  the task duration limit.
- Visual sanity and available layout probes do not find severe issues.
- The capability score is at least 70.

Required source terms are advisory in v0.6. They still reduce the score and are
published in failure evidence, but a single missing implementation hint does
not fail an otherwise valid rendered animation. Keyword stuffing remains a hard
failure because it is evidence that the source checks were gamed.

Reports publish pass rate, source coverage, render success, and failure buckets
beside the capability score. This keeps model ranking separate from run
completeness and error diagnosis.

Severe visual failures cap the automated score even when the source contains
the expected terms. The automated score is still not a complete quality measure,
so public rankings should show whether human review is pending or complete.
