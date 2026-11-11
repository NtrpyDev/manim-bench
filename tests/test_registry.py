"""Model list, routes, judge panel. The shipped routes must stay switched off."""

from __future__ import annotations

import textwrap

import pytest
import yaml

from manimbench.paths import JUDGES_PATH, MODELS_PATH, ROUTES_PATH
from manimbench.providers.base import RouteDisabledError
from manimbench.providers.claude_cli import ClaudeCliRoute
from manimbench.providers.openrouter import OpenRouterRoute
from manimbench.registry import JudgePanel, ModelEntry, load_judges, load_model, load_models, load_routes, make_route

CLAUDE_IDS = ["claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5"]


def write(path, text):
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_shipped_models_load_with_unique_ids():
    raw = yaml.safe_load(MODELS_PATH.read_text(encoding="utf-8"))["models"]
    ids = [item["id"] for item in raw]
    assert len(ids) == len(set(ids))
    models = load_models()
    assert list(models) == ids
    assert len(models) >= 4


def test_every_shipped_model_has_an_openrouter_route_with_model_and_provider():
    for entry in load_models().values():
        target = entry.target("openrouter")
        assert target["model"], entry.id
        assert target["provider"], entry.id


def test_the_four_claude_models_also_have_a_claude_cli_route():
    models = load_models()
    for model_id in CLAUDE_IDS:
        target = models[model_id].target("claude-cli")
        assert target["model"] == model_id


def test_non_claude_models_have_no_claude_cli_route():
    for entry in load_models().values():
        if entry.id not in CLAUDE_IDS:
            assert "claude-cli" not in entry.routes, entry.id


def test_shipped_routes_are_both_switched_off():
    routes = load_routes()["routes"]
    assert set(routes) == {"openrouter", "claude-cli"}
    assert routes["openrouter"]["enabled"] is False
    assert routes["claude-cli"]["enabled"] is False


@pytest.mark.parametrize("name", ["openrouter", "claude-cli"])
def test_make_route_refuses_the_shipped_disabled_routes(name):
    with pytest.raises(RouteDisabledError):
        make_route(name)


def test_shipped_default_route_is_a_known_route():
    assert load_routes()["default_route"] in load_routes()["routes"]


def test_make_route_returns_the_right_classes_when_enabled(tmp_path):
    path = write(
        tmp_path / "routes.yaml",
        """
        default_route: openrouter
        routes:
          openrouter:
            enabled: true
            base_url: https://example.invalid/api/v1/
            api_key_env: MY_KEY
            timeout_seconds: 12
          claude-cli:
            enabled: true
            command: my-claude
            timeout_seconds: 34
        """,
    )
    openrouter = make_route("openrouter", path)
    assert isinstance(openrouter, OpenRouterRoute)
    assert openrouter.base_url == "https://example.invalid/api/v1"
    assert openrouter.api_key_env == "MY_KEY"
    assert openrouter.timeout_seconds == 12.0
    cli = make_route("claude-cli", path)
    assert isinstance(cli, ClaudeCliRoute)
    assert cli.command == "my-claude"
    assert cli.timeout_seconds == 34.0


def test_route_without_enabled_key_is_off(tmp_path):
    path = write(tmp_path / "routes.yaml", "routes:\n  openrouter: {}\n")
    with pytest.raises(RouteDisabledError):
        make_route("openrouter", path)


def test_make_route_unknown_name_raises_key_error(tmp_path):
    path = write(tmp_path / "routes.yaml", "routes:\n  openrouter: {enabled: true}\n")
    with pytest.raises(KeyError):
        make_route("carrier-pigeon", path)
    with pytest.raises(KeyError):
        make_route("claude-cli", path)  # known name, not configured in this file


def test_routes_file_with_unknown_route_name_is_rejected(tmp_path):
    path = write(tmp_path / "routes.yaml", "routes:\n  pigeon: {enabled: true}\n")
    with pytest.raises(ValueError, match="unknown route"):
        load_routes(path)


def test_target_raises_for_a_route_the_model_lacks():
    entry = load_models()["gpt-6-1-sol"]
    with pytest.raises(KeyError, match="no claude-cli route"):
        entry.target("claude-cli")


def test_target_returns_a_copy():
    entry = ModelEntry("m", "M", "V", None, None, {"openrouter": {"model": "a/b"}})
    entry.target("openrouter")["model"] = "changed"
    assert entry.routes["openrouter"]["model"] == "a/b"


def test_load_model_unknown_id_raises_key_error():
    with pytest.raises(KeyError, match="Unknown model id"):
        load_model("nope")
    assert load_model("claude-opus-5-5").id == "claude-opus-5-5"


def test_shipped_judges_exist_in_model_list_and_have_the_panel_route():
    panel = load_judges()
    models = load_models()
    assert panel.judges
    assert panel.route in load_routes()["routes"]
    for judge_id in panel.judges:
        assert judge_id in models
        models[judge_id].target(panel.route)
    assert len(set(panel.judges)) == len(panel.judges)
    assert panel.max_frames >= 1
    assert JUDGES_PATH.exists() and ROUTES_PATH.exists()


def test_models_file_values_are_read_with_defaults(tmp_path):
    path = write(
        tmp_path / "models.yaml",
        """
        models:
          - id: alpha
            name: Alpha One
            vendor: Acme
            reasoning_effort: high
            max_output_tokens: 1000
            routes:
              openrouter: {model: acme/alpha, provider: acme}
          - id: beta
            routes:
              openrouter: {model: acme/beta}
        """,
    )
    models = load_models(path)
    alpha = models["alpha"]
    assert (alpha.name, alpha.vendor, alpha.reasoning_effort, alpha.max_output_tokens) == ("Alpha One", "Acme", "high", 1000)
    beta = models["beta"]
    assert (beta.name, beta.vendor, beta.reasoning_effort, beta.max_output_tokens) == ("beta", "", None, None)


def test_duplicate_model_id_is_rejected(tmp_path):
    path = write(
        tmp_path / "models.yaml",
        """
        models:
          - {id: a, routes: {openrouter: {model: x/a}}}
          - {id: a, routes: {openrouter: {model: x/b}}}
        """,
    )
    with pytest.raises(ValueError, match="duplicate model id a"):
        load_models(path)


def test_unknown_route_name_on_a_model_is_rejected(tmp_path):
    path = write(tmp_path / "models.yaml", "models:\n  - {id: a, routes: {pigeon: {model: x}}}\n")
    with pytest.raises(ValueError, match="unknown route"):
        load_models(path)


def test_route_without_model_is_rejected(tmp_path):
    path = write(tmp_path / "models.yaml", "models:\n  - {id: a, routes: {openrouter: {provider: p}}}\n")
    with pytest.raises(ValueError, match="needs a model"):
        load_models(path)


def test_duplicate_judge_is_rejected(tmp_path):
    path = write(tmp_path / "judges.yaml", "judges: [a, b, a]\n")
    with pytest.raises(ValueError, match="listed twice"):
        load_judges(path)


def test_judges_file_values_and_defaults(tmp_path):
    path = write(tmp_path / "judges.yaml", "route: claude-cli\nmax_frames: 5\nmax_output_tokens: 99\njudges: [a, b]\n")
    assert load_judges(path) == JudgePanel(route="claude-cli", judges=["a", "b"], max_frames=5, max_output_tokens=99)
    path = write(tmp_path / "j2.yaml", "judges: [a]\n")
    assert load_judges(path) == JudgePanel(route="openrouter", judges=["a"], max_frames=12, max_output_tokens=None)


def test_a_local_file_replaces_the_shipped_one_and_tests_ignore_it(tmp_path, monkeypatch):
    from manimbench.registry import load_routes, local_override

    shipped = tmp_path / "routes.yaml"
    shipped.write_text("default_route: openrouter\nroutes:\n  openrouter: {enabled: false}\n", encoding="utf-8")
    local = local_override(shipped)
    assert local.name == "routes.local.yaml"
    local.write_text("default_route: claude-cli\nroutes:\n  claude-cli: {enabled: true}\n", encoding="utf-8")
    assert load_routes(shipped)["default_route"] == "openrouter"  # The test session ignores local files.
    monkeypatch.delenv("MANIMBENCH_IGNORE_LOCAL_CONFIG")
    assert load_routes(shipped)["default_route"] == "claude-cli"
    assert load_routes(shipped)["routes"]["claude-cli"]["enabled"] is True
