from pathlib import Path

import argparse
import json
import time

import pytest

from manimbench.providers.file_provider import FileProvider
from manimbench.usage import build_usage_payload, count_tokens, start_usage


def test_count_tokens_is_deterministic():
    assert count_tokens("a^2 + b^2 = c^2") == count_tokens("a^2 + b^2 = c^2")
    assert count_tokens("a^2 + b^2 = c^2") > 0


def test_build_usage_payload(tmp_path):
    model_dir = tmp_path / "model-a"
    tasks = model_dir / "tasks"
    outputs = model_dir / "outputs"
    tasks.mkdir(parents=True)
    outputs.mkdir()
    (tasks / "task.md").write_text("Prompt text", encoding="utf-8")
    (outputs / "task.py").write_text("from manim import *\nclass MainScene(Scene): pass\n", encoding="utf-8")

    payload = build_usage_payload(model_dir)

    assert payload["model_id"] == "model-a"
    assert payload["tokens"]["input_tokens"] > 0
    assert payload["tokens"]["output_tokens"] > 0
    assert payload["tokens"]["tokenizer"]
    assert payload["cost"]["estimated_usd"] > 0


def test_build_usage_payload_can_scope_to_suite(tmp_path):
    suite_root = tmp_path / "benchmarks" / "v2"
    tasks_root = suite_root / "tasks"
    tasks_root.mkdir(parents=True)
    suite_path = suite_root / "suite.yaml"
    suite_path.write_text(
        "\n".join(
            [
                "id: test-v2",
                'version: "2.0.0"',
                "title: Test V2",
                "tasks:",
                "  - tasks/submission.yaml",
            ]
        ),
        encoding="utf-8",
    )
    (tasks_root / "submission.yaml").write_text(
        "\n".join(
            [
                "id: submission",
                'version: "2.0.0"',
                "difficulty: composite",
                "domains: []",
                "title: Submission",
                "prompt: Make one video.",
            ]
        ),
        encoding="utf-8",
    )

    model_dir = tmp_path / "model-a"
    prompts = model_dir / "tasks"
    outputs = model_dir / "outputs"
    prompts.mkdir(parents=True)
    outputs.mkdir()
    (prompts / "submission.md").write_text("Official prompt", encoding="utf-8")
    (outputs / "submission.py").write_text("official output", encoding="utf-8")
    (prompts / "old.md").write_text("old prompt " * 100, encoding="utf-8")
    (outputs / "old.py").write_text("old output " * 100, encoding="utf-8")

    scoped = build_usage_payload(model_dir, suite_path=suite_path)
    unscoped = build_usage_payload(model_dir)

    assert scoped["tokens"]["input_files"] == 1
    assert scoped["tokens"]["output_files"] == 1
    assert scoped["tokens"]["total_tokens"] < unscoped["tokens"]["total_tokens"]
    assert scoped["suite"]["id"] == "test-v2"


def test_stale_output_detection(tmp_path):
    model_dir = tmp_path / "model-a"
    tasks = model_dir / "tasks"
    outputs = model_dir / "outputs"
    tasks.mkdir(parents=True)
    outputs.mkdir()
    solution = outputs / "submission.py"
    solution.write_text("from manim import *\nclass MainScene(Scene): pass\n", encoding="utf-8")

    start_usage(argparse.Namespace(model_dir=model_dir, suite=None, force=True))
    time.sleep(0.01)

    provider = FileProvider(outputs, "model-a")
    task = type("Task", (), {"id": "submission"})()
    with pytest.raises(ValueError, match="Stale benchmark output"):
        provider.generate(task, "")
