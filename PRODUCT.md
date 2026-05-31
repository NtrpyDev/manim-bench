# Product

## Register

brand

## Users

AI researchers, ML engineers, and developers comparing frontier models on mathematical animation quality. Secondary audience: contributors running the benchmark locally with their preferred AI coding agent. They arrive to scan rankings (score, cost, time, tokens), understand methodology, and optionally reproduce a run. Context is usually quick reading at a desk, not a long onboarding flow.

## Product Purpose

ManimBench.site is the public home for an open, reproducible benchmark. It publishes model rankings from identical Manim Community Edition tasks under sandboxed conditions. Success means a visitor understands who leads, on what metrics, when results last changed, and how to run the benchmark themselves. The site is the product face; the Python benchmark repo is the engine.

## Brand Personality

Clinical, credible, precise. Calm expert voice. Data-forward without hype. Reads like a serious measurement project, not a startup landing page. Typography and spacing should feel intentional and human, not template-generated.

## Anti-references

Purple gradients, glassmorphism, gradient text, and generic "AI SaaS" palettes. Em dashes and marketing buzzwords (streamline, empower, seamless, cutting-edge). Hero-metric templates (big number + three stat pills). Logo-in-a-box wordmarks. Side-stripe card accents. Numbered section eyebrows on every block (01 / 02 / 03). Excessive blank space. Overlapping empty-state copy. Fake leaderboard data without clear labeling. Copying DeepSWE or Phantom layouts verbatim; use them only as reference for clarity and motion quality.

## Design Principles

1. **Data first.** Rankings, metric toggles, and the model table should be visible early. Documentation supports the numbers; it does not bury them.
2. **Show, don't tell.** Prefer charts, tables, and eventual video thumbnails over long explanatory prose above the fold.
3. **Honest states.** Empty leaderboard before first official run is fine. Say so plainly; do not overlay text on captions or imply results that do not exist.
4. **Motion with purpose.** Scroll-linked reveals and chart updates should aid comprehension. Always provide reduced-motion alternatives.
5. **Practice the benchmark.** The site itself should demonstrate careful layout, labeling, and readability, the same qualities ManimBench scores in generated animations.

## Accessibility & Inclusion

Target WCAG 2.1 AA contrast for body text and controls. Support `prefers-reduced-motion: reduce` for parallax and reveal animations. Keyboard-accessible metric tabs and model selector. Tables must remain readable on small screens (horizontal scroll acceptable; do not hide critical columns without alternative).
