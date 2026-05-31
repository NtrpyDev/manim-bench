# Scoring Methodology

ManimBench combines automated checks with human review.

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

Severe visual failures cap the automated score even when the source contains
the expected terms. The automated score is still not a complete quality measure,
so public rankings should show whether human review is pending or complete.
