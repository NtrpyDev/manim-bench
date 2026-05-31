from __future__ import annotations

import json
from pathlib import Path

from manimbench.models import ModelOutput, Task


class FileProvider:
    """Reads pre-generated model solutions from disk.

    Expected layout:

    outputs_dir/
      <task_id>.py

    This provider is useful before API-backed model integrations are added and
    for rerunning or reviewing saved generations.
    """

    def __init__(self, outputs_dir: Path, model: str, allow_stale: bool = False):
        self.outputs_dir = outputs_dir
        self.model = model
        self.allow_stale = allow_stale

    def generate(self, task: Task, prompt: str) -> ModelOutput:
        del prompt
        solution_path = self.outputs_dir / f"{task.id}.py"
        if not solution_path.exists():
            raise FileNotFoundError(f"Missing file-provider output for {task.id}: {solution_path}")
        self._check_freshness(solution_path)
        metadata = {"provider": "file", "source_path": str(solution_path)}
        metadata.update(self._usage_metadata())
        return ModelOutput(
            model=self.model,
            task_id=task.id,
            source=solution_path.read_text(encoding="utf-8"),
            metadata=metadata,
        )

    def _usage_metadata(self) -> dict[str, object]:
        usage_path = self.outputs_dir.parent / "usage.json"
        if not usage_path.exists():
            return {}
        try:
            usage = json.loads(usage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {
            "usage_path": str(usage_path),
            "cost_usd": usage.get("cost", {}).get("estimated_usd"),
            "elapsed_seconds": usage.get("time", {}).get("elapsed_seconds"),
            "input_tokens": usage.get("tokens", {}).get("input_tokens"),
            "output_tokens": usage.get("tokens", {}).get("output_tokens"),
            "total_tokens": usage.get("tokens", {}).get("total_tokens"),
            "tokenizer": usage.get("tokens", {}).get("tokenizer"),
            "cost_method": usage.get("cost", {}).get("method"),
        }

    def _check_freshness(self, solution_path: Path) -> None:
        if self.allow_stale:
            return
        start_path = self.outputs_dir.parent / ".manimbench" / "usage_start.json"
        if not start_path.exists():
            return
        try:
            start = json.loads(start_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        started_at = float(start.get("started_at_epoch", 0))
        baseline = start.get("output_baseline", {})
        current_mtime = solution_path.stat().st_mtime
        baseline_mtime = baseline.get(str(solution_path.resolve())) or baseline.get(str(solution_path))
        if current_mtime <= started_at or (baseline_mtime is not None and current_mtime <= float(baseline_mtime)):
            raise ValueError(
                f"Stale benchmark output detected: {solution_path}. "
                "Regenerate it after ./start_usage.sh, or rerun with --allow-stale for debugging."
            )
