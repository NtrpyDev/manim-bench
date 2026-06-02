from pathlib import Path
import tomllib

import yaml

import manimbench
from manimbench.paths import DEFAULT_SUITE_PATH, PROJECT_ROOT
from manimbench.reporting import REPORT_SCHEMA_VERSION
from manimbench.scoring import SCORING_VERSION
from manimbench.tasks import load_suite


RELEASE_VERSION = "0.6.0"


def test_release_versions_match_v06():
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == RELEASE_VERSION
    assert manimbench.__version__ == RELEASE_VERSION
    assert SCORING_VERSION == RELEASE_VERSION
    assert REPORT_SCHEMA_VERSION == RELEASE_VERSION


def test_default_suite_is_v06():
    suite = load_suite(DEFAULT_SUITE_PATH)

    assert DEFAULT_SUITE_PATH == PROJECT_ROOT / "benchmarks" / "v0.6" / "suite.yaml"
    assert suite.id == "manimbench-v0.6-public"
    assert suite.version == RELEASE_VERSION
    assert suite.title == "ManimBench V0.6 Public Suite"


def test_active_model_metadata_is_v06():
    for path in [
        PROJECT_ROOT / "models" / "openrouter.yaml",
        PROJECT_ROOT / "models" / "providers.yaml",
        PROJECT_ROOT / "models" / "public.yaml",
    ]:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        assert str(data["schema_version"]) == RELEASE_VERSION
