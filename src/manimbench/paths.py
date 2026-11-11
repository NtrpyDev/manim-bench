from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE_PATH = PROJECT_ROOT / "benchmarks" / "v0.7" / "suite.yaml"
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "prompt.md"
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_SITE_REPO = PROJECT_ROOT.parent / "manimbench-site"
MODELS_PATH = PROJECT_ROOT / "models" / "models.yaml"
ROUTES_PATH = PROJECT_ROOT / "models" / "routes.yaml"
JUDGES_PATH = PROJECT_ROOT / "models" / "judges.yaml"
SANDBOX_RUNTIME_PATH = PROJECT_ROOT / "sandbox" / "runtime.yaml"
HARNESS_PATH = Path(__file__).resolve().parent / "sandbox" / "harness.py"
