# ManimBench Master Prompt

You are generating a Manim Community Edition animation for a public benchmark.

## Runtime Contract

- Use Manim Community Edition only.
- Import with `from manim import *`.
- Define exactly one primary scene class named `MainScene`.
- The scene must render as an MP4 at 60 FPS.
- The final animation must be no longer than 120 seconds.
- Do not use network access.
- Do not read files outside the working directory.
- Do not require user interaction.
- Do not depend on external assets unless the task explicitly provides them.
- Prefer deterministic code and stable layouts.

## Visual Communication Requirements

Every important visual element must be clearly labeled in the video:

- Examples.
- Diagrams.
- Graphs and axes.
- Equations.
- Variables.
- Coordinates.
- Transformations.
- Mathematical objects.
- Intermediate steps in derivations or proofs.

Use concise, information-dense animation. Avoid unnecessary waits, repeated decorative transitions, filler scenes, and slow pacing. Camera movement should support the explanation rather than distract from it.

## Mathematical Requirements

The animation must be mathematically correct and faithful to the task. Show enough structure that a viewer can understand why the claim, construction, or computation is true.

Do not fake the result by drawing only the final answer while skipping the requested reasoning. Do not hardcode a superficial visual when the task asks for a derivation, dynamic process, or general construction.

## Output Contract

Return only Python source code for the ManimCE scene. Do not wrap it in Markdown fences. Do not include prose outside the code.

The benchmark runner will save your response as `solution.py` and render:

```bash
python -m manim -qh --fps 60 --media_dir <media_dir> --output_file result solution.py MainScene
```
