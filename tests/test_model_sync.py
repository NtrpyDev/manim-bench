import json

import yaml

from manimbench.model_registry import load_models
from manimbench.model_sync import apply_model_candidates, check_openrouter_models


def _catalog(*items):
    return {"data": list(items)}


def _model(slug, name, *, prompt="0.0000003", completion="0.0000012", created=100):
    return {
        "id": slug,
        "name": name,
        "created": created,
        "context_length": 1048576,
        "architecture": {"modality": "text->text"},
        "top_provider": {"max_completion_tokens": 512000},
        "pricing": {"prompt": prompt, "completion": completion},
        "supported_parameters": ["reasoning", "max_tokens"],
    }


def _write_registry(tmp_path):
    openrouter_path = tmp_path / "openrouter.yaml"
    public_path = tmp_path / "public.yaml"
    openrouter_path.write_text(
        yaml.safe_dump({"schema_version": "0.5.0", "models": {"gpt-5-5": "openai/gpt-5.5"}}, sort_keys=False),
        encoding="utf-8",
    )
    public_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.5.0",
                "models": [
                    {
                        "id": "gpt-5-5",
                        "display_name": "GPT-5.5",
                        "provider_family": "openai",
                        "tokenizer": "openai_estimate_v1",
                        "pricing": {"method": "configured_benchmark_estimate_rate"},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return openrouter_path, public_path


def test_model_check_seeds_first_daily_check_without_reporting_catalog_backlog(tmp_path):
    openrouter_path, public_path = _write_registry(tmp_path)
    state_path = tmp_path / "model-check.json"
    result = check_openrouter_models(
        catalog=_catalog(_model("openai/gpt-5.5", "OpenAI: GPT-5.5"), _model("minimax/minimax-m3", "MiniMax: MiniMax M3")),
        state_path=state_path,
        openrouter_path=openrouter_path,
        public_path=public_path,
    )

    assert result.new_models == []
    assert {model.openrouter_slug for model in result.all_models} == {"openai/gpt-5.5", "minimax/minimax-m3"}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "minimax/minimax-m3" in state["known_openrouter_slugs"]


def test_forced_model_check_can_apply_missing_openrouter_models(tmp_path):
    openrouter_path, public_path = _write_registry(tmp_path)
    state_path = tmp_path / "model-check.json"
    result = check_openrouter_models(
        force=True,
        apply_updates=True,
        catalog=_catalog(_model("openai/gpt-5.5", "OpenAI: GPT-5.5"), _model("minimax/minimax-m3", "MiniMax: MiniMax M3")),
        state_path=state_path,
        openrouter_path=openrouter_path,
        public_path=public_path,
    )

    assert result.applied is True
    assert [model.id for model in result.new_models] == ["minimax-m3"]

    routes = yaml.safe_load(openrouter_path.read_text(encoding="utf-8"))["models"]
    assert routes["minimax-m3"] == "minimax/minimax-m3"

    rows = yaml.safe_load(public_path.read_text(encoding="utf-8"))["models"]
    assert rows[0]["id"] == "minimax-m3"
    assert rows[0]["pricing"]["input_usd_per_1m_tokens"] == 0.3
    assert rows[0]["pricing"]["output_usd_per_1m_tokens"] == 1.2


def test_fresh_cached_model_check_can_apply_previous_new_models(tmp_path):
    openrouter_path, public_path = _write_registry(tmp_path)
    state_path = tmp_path / "model-check.json"
    check_openrouter_models(
        force=True,
        catalog=_catalog(_model("openai/gpt-5.5", "OpenAI: GPT-5.5"), _model("minimax/minimax-m3", "MiniMax: MiniMax M3")),
        state_path=state_path,
        openrouter_path=openrouter_path,
        public_path=public_path,
    )

    result = check_openrouter_models(
        apply_updates=True,
        catalog={"data": []},
        state_path=state_path,
        openrouter_path=openrouter_path,
        public_path=public_path,
    )

    assert result.skipped is True
    assert result.applied is True
    assert yaml.safe_load(openrouter_path.read_text(encoding="utf-8"))["models"]["minimax-m3"] == "minimax/minimax-m3"


def test_hidden_catalog_imports_are_runnable_but_not_public(tmp_path, monkeypatch):
    openrouter_path, public_path = _write_registry(tmp_path)
    result = check_openrouter_models(
        force=True,
        catalog=_catalog(_model("deepseek/deepseek-v4-pro", "DeepSeek: DeepSeek V4 Pro")),
        state_path=tmp_path / "model-check.json",
        openrouter_path=openrouter_path,
        public_path=public_path,
    )

    apply_model_candidates(result.new_models, openrouter_path=openrouter_path, public_path=public_path, hidden=True)

    routes = yaml.safe_load(openrouter_path.read_text(encoding="utf-8"))["models"]
    assert routes["deepseek-v4-pro"] == "deepseek/deepseek-v4-pro"
    rows = yaml.safe_load(public_path.read_text(encoding="utf-8"))["models"]
    assert rows[0]["id"] == "deepseek-v4-pro"
    assert rows[0]["catalog_hidden"] is True

    import manimbench.model_registry as registry

    monkeypatch.setattr(registry, "OPENROUTER_MODELS_PATH", openrouter_path)
    monkeypatch.setattr(registry, "PUBLIC_MODELS_PATH", public_path)

    assert "deepseek-v4-pro" not in {model.id for model in load_models(public_only=True)}
    assert "deepseek-v4-pro" in {model.id for model in load_models(public_only=False)}


def test_hidden_catalog_imports_remain_in_unregistered_catalog_view(tmp_path):
    openrouter_path, public_path = _write_registry(tmp_path)
    catalog = _catalog(_model("deepseek/deepseek-v4-pro", "DeepSeek: DeepSeek V4 Pro"))
    result = check_openrouter_models(
        force=True,
        catalog=catalog,
        state_path=tmp_path / "model-check.json",
        openrouter_path=openrouter_path,
        public_path=public_path,
        include_unregistered=True,
    )
    apply_model_candidates(result.unregistered_models, openrouter_path=openrouter_path, public_path=public_path, hidden=True)

    result = check_openrouter_models(
        force=True,
        catalog=catalog,
        state_path=tmp_path / "model-check.json",
        openrouter_path=openrouter_path,
        public_path=public_path,
        include_unregistered=True,
    )

    assert [model.id for model in result.unregistered_models] == ["deepseek-v4-pro"]


def test_pin_catalog_import_removes_hidden_marker(tmp_path):
    openrouter_path, public_path = _write_registry(tmp_path)
    result = check_openrouter_models(
        force=True,
        catalog=_catalog(_model("deepseek/deepseek-v4-pro", "DeepSeek: DeepSeek V4 Pro")),
        state_path=tmp_path / "model-check.json",
        openrouter_path=openrouter_path,
        public_path=public_path,
    )

    apply_model_candidates(result.new_models, openrouter_path=openrouter_path, public_path=public_path, hidden=True)
    apply_model_candidates(result.new_models, openrouter_path=openrouter_path, public_path=public_path, hidden=False)

    rows = yaml.safe_load(public_path.read_text(encoding="utf-8"))["models"]
    assert rows[0]["id"] == "deepseek-v4-pro"
    assert "catalog_hidden" not in rows[0]
