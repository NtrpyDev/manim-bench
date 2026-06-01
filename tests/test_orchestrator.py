import json
import threading
import time
from pathlib import Path

import pytest

from manimbench.models import ModelOutput, RenderResult
from manimbench.orchestrator import (
    GenerateBatchRequest,
    RenderInput,
    RenderMatrixRequest,
    fetch_openrouter_catalog,
    generate_batch,
    generation_status,
    get_output_status,
    render_matrix,
)
from manimbench.paths import DEFAULT_SUITE_PATH


class FakeProvider:
    def __init__(self, model, calls):
        self.model = model
        self.calls = calls

    def generate(self, task, prompt):
        self.calls.append((self.model, task.id))
        return ModelOutput(
            model=self.model,
            task_id=task.id,
            source="from manim import *\n\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n",
            metadata={
                "provider": "fake",
                "provider_route": "fake",
                "model_slug": self.model,
                "request_id": f"req-{self.model}-{task.id}",
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "cost_usd": 0.04,
            },
        )


def test_generate_checkpoint_skip_resume_and_api_log(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "DEFAULT_ENGINE_STATE_DIR", tmp_path / "state")
    calls = []

    request = GenerateBatchRequest(
        models=["composer-2-5"],
        suite_path=DEFAULT_SUITE_PATH,
        task_ids=["coordinate_system_animation"],
        output_dir=tmp_path / "outputs",
        run_id="resume-test",
        provider_factory=lambda model: FakeProvider(model, calls),
    )
    first = generate_batch(request)
    second = generate_batch(request)

    output = tmp_path / "outputs" / "composer-2-5" / "coordinate_system_animation.py"
    state = json.loads(first.state_path.read_text(encoding="utf-8"))
    log_lines = first.api_log_path.read_text(encoding="utf-8").strip().splitlines()

    assert first.ok
    assert second.ok
    assert calls == [("composer-2-5", "coordinate_system_animation")]
    assert output.exists()
    assert state["generations"]["composer-2-5"]["coordinate_system_animation"]["status"] == "complete"
    assert json.loads(log_lines[0])["request_id"] == "req-composer-2-5-coordinate_system_animation"
    assert (tmp_path / "outputs" / "composer-2-5" / "usage.json").exists()


def test_smoke_does_not_pay_for_same_task_twice(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "DEFAULT_ENGINE_STATE_DIR", tmp_path / "state")
    calls = []
    request = GenerateBatchRequest(
        models=["composer-2-5"],
        suite_path=DEFAULT_SUITE_PATH,
        task_ids=["coordinate_system_animation"],
        output_dir=tmp_path / "outputs",
        run_id="smoke-test",
        smoke=True,
        provider_factory=lambda model: FakeProvider(model, calls),
    )

    result = generate_batch(request)
    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    output = tmp_path / "outputs" / "composer-2-5" / "coordinate_system_animation.py"

    assert result.ok
    assert calls == [("composer-2-5", "coordinate_system_animation")]
    assert output.exists()
    assert state["smoke"]["output_path"] == str(output)
    assert state["generations"]["composer-2-5"]["coordinate_system_animation"]["metadata"]["smoke"]


def test_generation_status_values(tmp_path):
    state = {"generations": {}}
    output = tmp_path / "task.py"
    prompt = "prompt"

    assert generation_status(output, prompt, state, "model", "task") == "-"
    output.write_text("print('x')", encoding="utf-8")
    assert generation_status(output, prompt, state, "model", "task") == "partial"
    output.write_text("from manim import *\nclass MainScene(Scene): pass\n", encoding="utf-8")
    assert generation_status(output, prompt, state, "model", "task") == "complete"
    state["generations"] = {"model": {"task": {"status": "complete", "prompt_sha256": "old", "source_sha256": "old"}}}
    assert generation_status(output, prompt, state, "model", "task") == "stale"


def test_get_output_status_and_catalog_adapter(tmp_path):
    class CatalogClient:
        def get_json(self, url, headers, timeout):
            return {"data": [{"id": "openai/gpt-5.5"}], "url": url, "headers": headers}

    status = get_output_status(
        "model-a",
        suite_path=DEFAULT_SUITE_PATH,
        output_dir=tmp_path / "outputs",
    )
    catalog = fetch_openrouter_catalog(client=CatalogClient())

    assert set(status.values()) == {"-"}
    assert catalog["data"][0]["id"] == "openai/gpt-5.5"


def test_generate_dry_run_auto_routes_composer_to_cursor(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "DEFAULT_ENGINE_STATE_DIR", tmp_path / "state")
    request = GenerateBatchRequest(
        models=["composer-2-5", "gpt-5-5"],
        suite_path=DEFAULT_SUITE_PATH,
        task_ids=["coordinate_system_animation"],
        output_dir=tmp_path / "outputs",
        run_id="auto-route-test",
        dry_run=True,
    )

    result = generate_batch(request)
    routes = {item["model"]: item["provider"] for item in result.dry_run}

    assert routes == {"composer-2-5": "cursor", "gpt-5-5": "openrouter"}


class TrackingSandbox:
    name = "local"
    official = False

    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def render(self, run_dir, solution_path, runtime, timeout_seconds, fps, scene_class):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.03)
        with self.lock:
            self.active -= 1
        return RenderResult(
            backend="fake",
            official=False,
            command=["fake"],
            exit_code=0,
            timed_out=False,
            stdout="",
            stderr="",
            media_files=[],
            metadata={"media": {}},
        )


class DigestSandbox(TrackingSandbox):
    name = "container"
    official = True
    image = "manimbench-manimce:latest"

    def _image_digest(self):
        return "sha256:testdigest"


def test_render_matrix_parallel_bound_and_manifest_immutability(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    sandbox = TrackingSandbox()
    monkeypatch.setattr(orchestrator, "_make_sandbox", lambda request: sandbox)
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    for model in ["m1", "m2"]:
        model_dir = tmp_path / "outputs" / model
        model_dir.mkdir(parents=True)
        (model_dir / "coordinate_system_animation.py").write_text(source, encoding="utf-8")

    request = RenderMatrixRequest(
        model_outputs=[RenderInput("m1", tmp_path / "outputs" / "m1"), RenderInput("m2", tmp_path / "outputs" / "m2")],
        suite_path=DEFAULT_SUITE_PATH,
        task_ids=["coordinate_system_animation"],
        runs_dir=tmp_path / "runs",
        run_id="parallel-test",
        sandbox="local",
        parallel=2,
    )
    result = render_matrix(request)

    assert sandbox.max_active == 2
    assert len(result.result_paths) == 2
    assert (result.run_dir / "manifest.json").exists()
    with pytest.raises(FileExistsError):
        render_matrix(request)


def test_container_manifest_records_docker_digest(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    sandbox = DigestSandbox()
    monkeypatch.setattr(orchestrator, "_make_sandbox", lambda request: sandbox)
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    model_dir = tmp_path / "outputs" / "m1"
    model_dir.mkdir(parents=True)
    (model_dir / "coordinate_system_animation.py").write_text(source, encoding="utf-8")

    result = render_matrix(
        RenderMatrixRequest(
            model_outputs=[RenderInput("m1", model_dir)],
            suite_path=DEFAULT_SUITE_PATH,
            task_ids=["coordinate_system_animation"],
            runs_dir=tmp_path / "runs",
            run_id="digest-test",
            sandbox="container",
        )
    )
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["sandbox"]["docker_image_digest"] == "sha256:testdigest"
