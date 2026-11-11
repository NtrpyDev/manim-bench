# Scoring

This is the whole method. The numbers below come from
`benchmarks/v0.7/suite.yaml`, and the same numbers are printed into the prompt
each model receives (`manimbench prompt --task <id>` shows it), so a model is
never graded on a rule it was not shown.

## Gates

A sample must pass every gate. A failed gate scores zero and is reported by
name. Gates are checked in this order and stop at the first failure.

| Gate | Fails when | Reported as |
| --- | --- | --- |
| Code parses | The reply is empty or is not valid Python | `no_code`, `syntax_error` |
| Scene class | No top-level class named `MainScene` | `missing_scene_class` |
| Renders | The render exits with an error or passes the time limit | `render_error`, `render_timeout` |
| Video | No readable video came out | `no_video` |
| Duration | Shorter than 15 s or longer than 120 s | `too_short`, `too_long` |
| Not blank | More than half the sampled frames show only background | `blank_video` |
| Has motion | Less than 2 s, or less than 10% of the video, has anything changing | `static_video` |

Code that does not parse is never rendered. What a scene may import is not
checked from its source: the sandbox has no network and a read-only
filesystem, so there is nothing for it to reach.

## The quality score

A sample that passes the gates gets three part scores, each 0 to 100, combined
by weight: review 65, layout 25, pacing 10. A part that could not be measured
is left out and the others are rescaled, and the result says so.

### Layout, 25 points

While the scene renders, a small harness inside the container records every
text object on screen: its string, its bounding box, the height of its
tallest character, and its opacity. It records at the start and end of
every animation, and once a second during animations of three seconds or
more, so one long animation cannot hide what happens inside it. Layout is
scored from that record, not from the source code and not from guessing at
pixels.

Three problems are measured, each by how many seconds it was on screen:

- **Cut off.** Text partly outside the camera frame. Text entirely outside
  the frame is not visible and is ignored.
- **Overlapping.** Two pieces of text whose boxes overlap by more than 15% of
  the smaller one. Text over a shape is not counted, since a label inside a
  square is normal.
- **Too small.** The tallest character is under 0.09 scene units after
  allowing for camera zoom. The frame is 8 units tall, so that is about 1.1%
  of its height, or roughly font size 13 for LaTeX and 9 for `Text`. It is
  measured from the drawn characters. The font size Manim reports is not
  used, because it is wrong after a `Transform` and blind to sizing inside
  LaTeX.

Each problem's share of the video is divided by 25%, capped at 1, and takes
that fraction of its points: 40 for cut off, 40 for overlapping, 20 for too
small. A problem on screen for a quarter of the video or more loses all of its
points. Scenes with a 3D camera are not measured for layout.

### Pacing, 10 points

The video is sampled five times a second. A stretch where no sampled frame
differs from the one before is a still stretch. Still stretches up to 8 s are
free, because a viewer needs time to read. Every second past 8 s counts as
dead time, and the score is `100 * (1 - dead time / half the video length)`,
floored at zero.

### Review, 65 points

Each sample goes to a panel of vision models (`models/judges.yaml`). A judge
sees up to 12 frames, taken just after animations finish and spread over the
video, with the text that was on screen at each frame. It also gets the task,
the list of things the video had to show, and reference facts for checking
the maths. It is not told which model made the video and does not see the
code.

The judge returns, with one sentence of evidence each:

- For every item the task said the video must show: `yes`, `partial` or `no`.
- A 0 to 4 rating for each of: is the maths correct, does it build the idea
  step by step, is it easy to read.

The item verdicts become the coverage rating (yes 1, partial 0.5, no 0,
averaged, times 4). The four ratings are combined by weight (correctness 30,
explanation 25, coverage 25, clarity 20) into 0 to 100. A reply that is
missing a verdict or has a rating out of range is rejected and asked for once
more. A judge that fails twice is recorded as failed and never guessed at.
The panel's score is the mean of the judges that answered, and the spread
between them is reported.

## From samples to a model's score

- A task's score is the mean over its samples. A failed gate counts as zero.
- A model's score is the mean over tasks, so every task counts the same.
- The 95% interval comes from resampling the samples inside each task 2,000
  times with a fixed seed.
- A sample that was never generated or never rendered is missing, not zero.
  A model with missing or unjudged samples is listed but not ranked.

## What this method cannot do yet

- A vision judge can be wrong, and can favor videos in its own style. Use
  judges from more than one vendor, and check them against a person with
  `manimbench review` (see [judge.md](judge.md)).
- Layout only compares text with text and with the frame. A label covered by
  a curve or a shape is not measured; only the judge's clarity rating can
  catch it.
- The judge sees frames, not motion. An animation that is wrong only between
  the sampled frames can be missed.
- The layout record is written inside the same process as the model's code,
  so code written to cheat could tamper with it. The video itself cannot be
  faked that way, and the judge and pacing parts use only the video.
- No judge or model has been called from this code yet. The whole pipeline is
  tested with recorded and fake replies.
