"""Build the exact prompt a model receives for a task.

Everything the scorer checks is written into this prompt from the same suite
settings the scorer reads, so a model is never graded on a rule it was not
shown.
"""

from __future__ import annotations

from pathlib import Path

from manimbench.models import Suite, Task

_RESOLUTIONS = {"l": "854x480", "m": "1280x720", "h": "1920x1080", "p": "2560x1440", "k": "3840x2160"}


def load_master_prompt(prompt_path: Path) -> str:
    return prompt_path.read_text(encoding="utf-8").strip()


def build_task_prompt(master_prompt: str, suite: Suite, task: Task, *, manim_version: str, python_version: str) -> str:
    runtime = suite.runtime
    header = (
        master_prompt.replace("{{manim_version}}", manim_version)
        .replace("{{python_version}}", python_version)
        .replace("{{scene_class}}", runtime.scene_class)
        .replace("{{resolution}}", _RESOLUTIONS.get(runtime.quality, runtime.quality))
        .replace("{{fps}}", str(runtime.fps))
        .replace("{{render_timeout_seconds}}", str(runtime.render_timeout_seconds))
    )
    if "{{" in header:
        raise ValueError("The master prompt contains an unknown {{placeholder}}")
    must_show = "\n".join(f"- {item.text}" for item in task.must_show)
    return "\n\n".join(
        [
            header,
            f"## Task: {task.title}",
            task.prompt,
            "## The video must show",
            must_show,
            scoring_section(suite),
            "## Output",
            "Reply with the Python source code only: one complete file, with no explanation before or after it.",
        ]
    )


def scoring_section(suite: Suite) -> str:
    """Describe the whole scoring method in plain words."""
    runtime = suite.runtime
    scoring = suite.scoring
    layout = scoring.layout
    pacing = scoring.pacing
    total_criteria = sum(item.weight for item in suite.criteria)
    criteria_lines = []
    for item in suite.criteria:
        share = 100.0 * item.weight / total_criteria
        line = f"- {item.question} ({_number(share)}% of the review)"
        if item.id == scoring.must_show_criterion:
            line += " This is checked item by item against the list above."
        criteria_lines.append(line)
    saturation = _number(100 * layout.saturation_share)
    return "\n".join(
        [
            "## How your video is scored",
            "",
            "First it has to pass every one of these. Failing any one scores zero:",
            "",
            "- The reply is valid Python that defines the scene class.",
            "- The scene renders without an error and inside the time limit.",
            f"- The video is between {_number(runtime.min_duration_seconds)} and "
            f"{_number(runtime.max_duration_seconds)} seconds long.",
            f"- The video is not blank for more than {_number(100 * pacing.max_blank_share)}% of its length.",
            f"- Something visibly changes for at least {_number(pacing.min_active_seconds)} seconds and at least "
            f"{_number(100 * pacing.min_active_share)}% of the video.",
            "",
            "Then it gets a score from 0 to 100, made of three parts:",
            "",
            f"- Review of the video, {_number(scoring.judge_weight)} points. Reviewers watch frames from the video "
            "and rate each of these from 0 to 4:",
            *[f"  {line}" for line in criteria_lines],
            f"- Layout, {_number(scoring.layout_weight)} points, measured from the positions of the text on screen. "
            f"Points are lost for text cut off by the edge of the frame ({_number(layout.clipping_points)}% of this "
            f"part), text overlapping other text ({_number(layout.overlap_points)}%), and text smaller than font "
            f"size {_number(layout.min_font_size)} or with no character taller than {_number(layout.min_glyph_height)} "
            f"scene units, so shrinking text inside LaTeX counts too ({_number(layout.small_text_points)}%). "
            f"Each loss grows with how "
            f"long the problem is on screen and is at its maximum at {saturation}% of the video.",
            f"- Pacing, {_number(scoring.pacing_weight)} points. Points are lost for stretches longer than "
            f"{_number(pacing.max_still_seconds)} seconds where nothing on screen changes.",
        ]
    )


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"
