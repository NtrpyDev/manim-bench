from manimbench.model_registry import default_provider_for_model, load_models, public_model_rows


def test_public_models_have_configured_generation_routes_and_no_private_tiers():
    models = load_models(public_only=True)

    assert models
    for model in models:
        tier = str(model.raw.get("tier", "")).lower()
        access = str(model.raw.get("access", "")).lower()
        assert tier not in {"pro", "enterprise"}
        assert access not in {"pro", "enterprise", "private"}
        if default_provider_for_model(model.id) == "openrouter":
            assert model.openrouter_slug


def test_composer_25_routes_through_cursor_registry():
    composer = next(model for model in load_models(public_only=True) if model.id == "composer-2-5")

    assert composer.provider_family == "cursor"
    assert composer.openrouter_slug is None
    assert default_provider_for_model("composer-2-5") == "cursor"
    row = next(row for row in public_model_rows(public_only=True) if row["id"] == "composer-2-5")
    assert row["default_provider"] == "cursor"
