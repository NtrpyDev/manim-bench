# ManimBench

You are writing one Manim Community Edition animation that teaches a piece of
mathematics. The viewer is a student seeing the idea for the first time. The
video has no narration, so everything has to be understood from what is on
screen.

## Runtime

- Manim Community Edition {{manim_version}}, Cairo renderer, Python {{python_version}}.
- Start with `from manim import *`. NumPy and the Python standard library are
  available. No other packages are.
- Define one scene class named `{{scene_class}}`. It is the only scene rendered.
- The scene is rendered at {{resolution}} and {{fps}} frames per second.
- There is no network, no input, and no files to read. Do not load images,
  SVGs, sounds, or fonts.
- LaTeX is a minimal TeX Live install. `amsmath`, `amssymb`, `physics`,
  `xcolor`, `mathrsfs`, `dsfont`, and `wasysym` are available. `mathtools`,
  `tikz`, `cancel`, `bm`, and `siunitx` are not.
- The render is stopped after {{render_timeout_seconds}} seconds of wall time.

## What makes a good answer

- The mathematics is correct, and the video shows why it is true, not only
  the final result.
- Ideas arrive one at a time, in an order a student can follow.
- Every object that matters is labeled on screen: axes, points, curves,
  vectors, regions, equations, and the steps of a derivation.
- Text is large enough to read, stays inside the frame, and does not sit on
  top of other text.
- Motion is used to explain. Avoid long stretches where nothing changes.
