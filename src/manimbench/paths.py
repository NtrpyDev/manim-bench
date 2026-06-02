from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE_PATH = PROJECT_ROOT / "benchmarks" / "v0.6" / "suite.yaml"
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "prompt.md"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_MODEL_TESTS_DIR = PROJECT_ROOT / "model_tests"
DEFAULT_ENGINE_STATE_DIR = PROJECT_ROOT / ".manimbench" / "runs"
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DEFAULT_SITE_REPO = PROJECT_ROOT.parent / "manimbench-site"
