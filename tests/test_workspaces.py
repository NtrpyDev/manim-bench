import argparse

from manimbench.paths import DEFAULT_SUITE_PATH
from manimbench import workspaces


def test_workspace_generator_is_agent_neutral(tmp_path, monkeypatch):
    registry = tmp_path / "models.yaml"
    registry.write_text(
        "\n".join(
            [
                "models:",
                "  - id: model-a",
                "    display_name: Model A",
            ]
        ),
        encoding="utf-8",
    )
    root = tmp_path / "model_tests"
    monkeypatch.setattr(workspaces, "MODEL_REGISTRY", registry)
    monkeypatch.setattr(workspaces, "WORKSPACES_ROOT", root)

    rc = workspaces.create_model_workspaces(
        argparse.Namespace(
            suite=DEFAULT_SUITE_PATH,
            prompt=None,
            task=["basic_manim_layout"],
            force=True,
        )
    )

    model_dir = root / "model-a"
    assert rc == 0
    assert not (model_dir / ".cursor").exists()
    assert (model_dir / "tasks" / "basic_manim_layout.md").exists()
    readme = (model_dir / "README.md").read_text(encoding="utf-8")
    agents = (model_dir / "AGENTS.md").read_text(encoding="utf-8")
    assert "Cursor" not in readme
    assert "Cursor" not in agents
    assert "optional workspace" in readme
    assert "outputs/<model>" in readme
    assert "outputs/<task_id>.py" in agents
