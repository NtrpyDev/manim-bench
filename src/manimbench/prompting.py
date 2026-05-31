from __future__ import annotations

from pathlib import Path

from manimbench.models import Task


def load_master_prompt(prompt_path: Path) -> str:
    return prompt_path.read_text(encoding="utf-8").strip()


def build_task_prompt(master_prompt: str, task: Task) -> str:
    labels = "\n".join(f"- {label}" for label in task.required_labels)
    visuals = "\n".join(f"- {visual}" for visual in task.required_visuals)

    return "\n\n".join(
        [
            master_prompt.strip(),
            "## Benchmark Task",
            f"Task ID: {task.id}",
            f"Difficulty: {task.difficulty}",
            f"Title: {task.title}",
            task.prompt.strip(),
            "## Required Labels",
            labels or "- None specified",
            "## Required Visual Elements",
            visuals or "- None specified",
            "## Task Runtime Limit",
            f"The animation must be no longer than {task.runtime_limit_seconds} seconds.",
        ]
    )
