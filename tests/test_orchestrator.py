import json
import threading
import time
from pathlib import Path

import pytest

from manimbench.models import ModelOutput, RenderResult
from manimbench.orchestrator import (
    PipelineEvent,
    PipelineRequest,
    RetryFailedRequest,
    GenerateBatchRequest,
    ReportResult,
    RenderInput,
    RenderMatrixRequest,
    RenderMatrixResult,
    cancel,
    clear_cancel,
    estimate_cost,
    fetch_balance,
    fetch_openrouter_catalog,
    generate_batch,
    generation_status,
    get_dashboard_state,
    get_model_detail_state,
    get_output_status,
    get_publish_summary,
    get_video_preview_state,
    render_matrix,
    retry_failed,
    run_pipeline,
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
    output.write_text("from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text(\n", encoding="utf-8")
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


def test_fetch_balance_returns_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    balance = fetch_balance()

    assert not balance.available
    assert "OPENROUTER_API_KEY" in (balance.error or "")


def test_fetch_balance_uses_key_endpoint(monkeypatch):
    class CreditsClient:
        def get_json(self, url, headers, timeout):
            assert url.endswith("/key")
            assert headers["Authorization"] == "Bearer test-key"
            return {"data": {"limit": 100.5, "limit_remaining": 75.25, "usage": 25.25}}

    balance = fetch_balance(api_key="test-key", client=CreditsClient())

    assert balance.available
    assert balance.balance == 75.25
    assert balance.total_credits == 100.5


def test_fetch_balance_falls_back_to_account_credits_for_unlimited_key(monkeypatch):
    calls = []

    class CreditsClient:
        def get_json(self, url, headers, timeout):
            calls.append(url)
            if url.endswith("/key"):
                return {"data": {"limit": None, "limit_remaining": None, "usage": 25.25}}
            if url.endswith("/credits"):
                return {"data": {"total_credits": 100.5, "total_usage": 25.25}}
            raise AssertionError(url)

    balance = fetch_balance(api_key="test-key", client=CreditsClient())

    assert len(calls) == 2
    assert calls[0].endswith("/key")
    assert calls[1].endswith("/credits")
    assert balance.available
    assert balance.balance == 75.25
    assert balance.total_credits == 100.5


def test_fetch_balance_keeps_key_ok_when_account_credits_unavailable(monkeypatch):
    class CreditsClient:
        def get_json(self, url, headers, timeout):
            if url.endswith("/key"):
                return {"data": {"limit": None, "limit_remaining": None, "usage": 25.25}}
            raise RuntimeError("credits unavailable")

    balance = fetch_balance(api_key="test-key", client=CreditsClient())

    assert balance.available
    assert balance.balance is None
    assert balance.total_usage == 25.25


def test_fetch_balance_rejects_cursor_key():
    balance = fetch_balance(api_key="crsr_not-openrouter")

    assert not balance.available
    assert "Cursor key" in (balance.error or "")


def test_estimate_cost_uses_suite_prompts_and_model_rates():
    estimate = estimate_cost(["composer-2-5"], suite_path=DEFAULT_SUITE_PATH, task_ids=["coordinate_system_animation"])

    assert estimate.model_count == 1
    assert estimate.task_count == 1
    assert estimate.input_tokens > 0
    assert estimate.output_tokens == 2000
    assert estimate.estimated_usd > 0


def test_dashboard_state_includes_selected_status_and_estimate(tmp_path):
    state = get_dashboard_state(
        selected_models=["composer-2-5"],
        suite_path=DEFAULT_SUITE_PATH,
        output_dir=tmp_path / "outputs",
        runs_dir=tmp_path / "runs",
        include_balance=False,
        search="composer",
    )

    assert state.selected_models == ["composer-2-5"]
    assert state.estimate.estimated_usd > 0
    assert [row.id for row in state.models] == ["composer-2-5"]
    assert state.models[0].status == "missing"


def test_dashboard_state_uses_catalog_metadata_filters(tmp_path):
    catalog = {
        "data": [
            {
                "id": "openai/gpt-5.5",
                "context_length": 1_000_000,
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            }
        ]
    }

    state = get_dashboard_state(
        selected_models=["gpt-5-5"],
        suite_path=DEFAULT_SUITE_PATH,
        output_dir=tmp_path / "outputs",
        include_balance=False,
        catalog=catalog,
        context_filter="long",
        price_filter="low",
        search="gpt-5.5",
    )

    assert [row.id for row in state.models] == ["gpt-5-5"]
    assert state.models[0].context_window == 1_000_000
    assert state.models[0].pricing["input_usd_per_1m_tokens"] == 1.0


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


def test_generate_passes_reasoning_effort_to_provider(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "DEFAULT_ENGINE_STATE_DIR", tmp_path / "state")
    calls = []
    efforts = []

    def fake_provider_for(provider_name, model, *, reasoning_effort=None):
        efforts.append((provider_name, model, reasoning_effort))
        return FakeProvider(model, calls)

    monkeypatch.setattr(orchestrator, "_provider_for", fake_provider_for)

    result = generate_batch(
        GenerateBatchRequest(
            models=["gpt-5-5"],
            suite_path=DEFAULT_SUITE_PATH,
            task_ids=["coordinate_system_animation"],
            output_dir=tmp_path / "outputs",
            run_id="reasoning-route",
            reasoning_effort="xhigh",
        )
    )
    state = json.loads(result.state_path.read_text(encoding="utf-8"))

    assert result.ok
    assert efforts == [("openrouter", "gpt-5-5", "xhigh")]
    assert state["generations"]["gpt-5-5"]["coordinate_system_animation"]["metadata"]["requested_reasoning_effort"] == "xhigh"


def test_run_pipeline_smoke_only_runs_one_task(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "DEFAULT_ENGINE_STATE_DIR", tmp_path / "state")
    calls = []
    events = []
    result = run_pipeline(
        PipelineRequest(
            models=["composer-2-5", "gpt-5-5"],
            mode="smoke",
            suite_path=DEFAULT_SUITE_PATH,
            output_dir=tmp_path / "outputs",
            run_id="smoke-pipeline",
            provider_factory=lambda model: FakeProvider(model, calls),
            event_callback=events.append,
        )
    )

    assert result.ok
    assert calls == [("composer-2-5", "coordinate_system_animation")]
    assert any(event.type == "pipeline_finished" for event in events)


def test_run_pipeline_cancel_stops_before_render(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "DEFAULT_ENGINE_STATE_DIR", tmp_path / "state")

    def fail_render(request):
        raise AssertionError("render should not run after cancellation")

    monkeypatch.setattr(orchestrator, "render_matrix", fail_render)
    calls = []

    def callback(event: PipelineEvent):
        if event.type == "generation_finished":
            cancel()

    result = run_pipeline(
        PipelineRequest(
            models=["composer-2-5"],
            mode="full",
            suite_path=DEFAULT_SUITE_PATH,
            task_ids=["coordinate_system_animation"],
            output_dir=tmp_path / "outputs",
            run_id="cancel-pipeline",
            provider_factory=lambda model: FakeProvider(model, calls),
            event_callback=callback,
        )
    )

    assert result.cancelled
    assert calls == [("composer-2-5", "coordinate_system_animation")]


def test_run_pipeline_full_renders_and_reports_after_generation_failure(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "DEFAULT_ENGINE_STATE_DIR", tmp_path / "state")
    calls = []
    captured = {}

    class SometimesFailingProvider(FakeProvider):
        def generate(self, task, prompt):
            if self.model == "composer-2-5":
                raise RuntimeError("workspace trust required")
            return super().generate(task, prompt)

    def fake_render_matrix(request):
        captured["render_models"] = [item.model for item in request.model_outputs]
        run_dir = tmp_path / "runs" / request.run_id
        run_dir.mkdir(parents=True)
        return RenderMatrixResult(run_id=str(request.run_id), run_dir=run_dir, failures=1)

    def fake_report(request):
        captured["report_run_dir"] = request.run_dir
        output_dir = tmp_path / "reports" / request.run_dir.name
        output_dir.mkdir(parents=True)
        index = output_dir / "index.html"
        index.write_text("<html></html>", encoding="utf-8")
        return ReportResult(index_path=index, output_dir=output_dir)

    monkeypatch.setattr(orchestrator, "render_matrix", fake_render_matrix)
    monkeypatch.setattr(orchestrator, "report", fake_report)

    result = run_pipeline(
        PipelineRequest(
            models=["composer-2-5", "gpt-5-5"],
            mode="full",
            suite_path=DEFAULT_SUITE_PATH,
            task_ids=["coordinate_system_animation"],
            output_dir=tmp_path / "outputs",
            runs_dir=tmp_path / "runs",
            run_id="partial-full",
            provider_factory=lambda model: SometimesFailingProvider(model, calls),
        )
    )

    assert not result.ok
    assert result.generation and not result.generation.ok
    assert result.render and result.render.failures == 1
    assert result.report
    assert captured["render_models"] == ["composer-2-5", "gpt-5-5"]
    assert captured["report_run_dir"] == tmp_path / "runs" / "partial-full"


def test_generate_cancel_stops_queued_work(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "DEFAULT_ENGINE_STATE_DIR", tmp_path / "state")
    calls = []

    def callback(event: PipelineEvent):
        if event.type in {"task_finished", "task_failed"}:
            cancel()

    result = generate_batch(
        GenerateBatchRequest(
            models=["composer-2-5"],
            suite_path=DEFAULT_SUITE_PATH,
            task_ids=["coordinate_system_animation", "derivative_motion_story"],
            output_dir=tmp_path / "outputs",
            run_id="generate-cancel",
            parallel=1,
            provider_factory=lambda model: FakeProvider(model, calls),
            event_callback=callback,
        )
    )

    assert result.ok
    assert calls == [("composer-2-5", "coordinate_system_animation")]


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


def test_render_matrix_resume_skips_existing_results(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    sandbox = TrackingSandbox()
    monkeypatch.setattr(orchestrator, "_make_sandbox", lambda request: sandbox)
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    model_dir = tmp_path / "outputs" / "m1"
    model_dir.mkdir(parents=True)
    for task_id in ["coordinate_system_animation", "derivative_motion_story"]:
        (model_dir / f"{task_id}.py").write_text(source, encoding="utf-8")
    run_dir = tmp_path / "runs" / "resume-render"
    existing = run_dir / "m1" / "coordinate_system_animation"
    existing.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "resume-render",
                "models": ["m1"],
                "suite": {"id": "test", "version": "1", "task_count": 2, "task_ids": ["coordinate_system_animation", "derivative_motion_story"]},
                "sandbox": {"docker_image_digest": "sha256:old"},
            }
        ),
        encoding="utf-8",
    )
    (existing / "result.json").write_text(
        json.dumps({"model": "m1", "task": {"id": "coordinate_system_animation"}, "score": {"passed": True}}),
        encoding="utf-8",
    )

    result = render_matrix(
        RenderMatrixRequest(
            model_outputs=[RenderInput("m1", model_dir)],
            suite_path=DEFAULT_SUITE_PATH,
            task_ids=["coordinate_system_animation", "derivative_motion_story"],
            runs_dir=tmp_path / "runs",
            run_id="resume-render",
            sandbox="local",
            resume=True,
        )
    )

    assert len(result.result_paths) == 2
    assert (run_dir / "m1" / "derivative_motion_story" / "result.json").exists()
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["sandbox"]["docker_image_digest"] == "sha256:old"


def test_render_cancel_stops_queued_work(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    sandbox = TrackingSandbox()
    monkeypatch.setattr(orchestrator, "_make_sandbox", lambda request: sandbox)
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    model_dir = tmp_path / "outputs" / "m1"
    model_dir.mkdir(parents=True)
    for task_id in ["coordinate_system_animation", "derivative_motion_story"]:
        (model_dir / f"{task_id}.py").write_text(source, encoding="utf-8")

    def callback(event: PipelineEvent):
        if event.type in {"task_finished", "task_failed"}:
            cancel()

    result = render_matrix(
        RenderMatrixRequest(
            model_outputs=[RenderInput("m1", model_dir)],
            suite_path=DEFAULT_SUITE_PATH,
            task_ids=["coordinate_system_animation", "derivative_motion_story"],
            runs_dir=tmp_path / "runs",
            run_id="render-cancel",
            sandbox="local",
            parallel=1,
            event_callback=callback,
        )
    )

    assert len(result.result_paths) == 1
    assert result.result_paths[0].parts[-3:] == ("m1", "coordinate_system_animation", "result.json")


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


def test_detail_video_and_publish_summary_are_orchestrator_state(tmp_path):
    run_dir = tmp_path / "runs" / "display-state"
    task_dir = run_dir / "composer-2-5" / "coordinate_system_animation"
    task_dir.mkdir(parents=True)
    output_dir = tmp_path / "outputs" / "composer-2-5"
    output_dir.mkdir(parents=True)
    (output_dir / "coordinate_system_animation.py").write_text(
        "from manim import *\nclass MainScene(Scene): pass\n",
        encoding="utf-8",
    )
    video = task_dir / "media" / "videos" / "scene.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"fake")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "display-state",
                "models": ["composer-2-5"],
                "suite": {"id": "v0.5", "version": "0.5", "title": "Suite", "task_count": 1, "task_ids": ["coordinate_system_animation"]},
                "sandbox": {"docker_image_digest": "sha256:test"},
            }
        ),
        encoding="utf-8",
    )
    (task_dir / "result.json").write_text(
        json.dumps(
            {
                "model": "composer-2-5",
                "task": {"id": "coordinate_system_animation"},
                "source_metadata": {"cost_usd": 0.12},
                "render": {"media_files": [str(video)], "metadata": {"media": {"scene": {"duration": 3.2}}}},
                "score": {"passed": True, "automated_score": 92, "artifacts": {"media": str(video)}},
            }
        ),
        encoding="utf-8",
    )

    detail = get_model_detail_state("composer-2-5", run_id="display-state", output_dir=tmp_path / "outputs", runs_dir=tmp_path / "runs")
    preview = get_video_preview_state("display-state", runs_dir=tmp_path / "runs", model_id="composer-2-5")
    publish_summary = get_publish_summary("display-state", runs_dir=tmp_path / "runs")

    assert detail.tasks[0].cost_usd == 0.12
    assert preview.rows[0].video_path == video
    assert publish_summary.complete
    assert publish_summary.docker_digest == "sha256:test"


def test_retry_failed_renders_only_failed_tasks(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    sandbox = TrackingSandbox()
    monkeypatch.setattr(orchestrator, "_make_sandbox", lambda request: sandbox)
    previous = tmp_path / "runs" / "previous"
    failed_dir = previous / "m1" / "coordinate_system_animation"
    passed_dir = previous / "m1" / "derivative_motion_story"
    failed_dir.mkdir(parents=True)
    passed_dir.mkdir(parents=True)
    (previous / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "previous",
                "models": ["m1"],
                "suite": {"task_ids": ["coordinate_system_animation", "derivative_motion_story"]},
            }
        ),
        encoding="utf-8",
    )
    (failed_dir / "result.json").write_text(
        json.dumps({"model": "m1", "task": {"id": "coordinate_system_animation"}, "score": {"passed": False}}),
        encoding="utf-8",
    )
    (passed_dir / "result.json").write_text(
        json.dumps({"model": "m1", "task": {"id": "derivative_motion_story"}, "score": {"passed": True}}),
        encoding="utf-8",
    )
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    output_dir = tmp_path / "outputs" / "m1"
    output_dir.mkdir(parents=True)
    (output_dir / "coordinate_system_animation.py").write_text(source, encoding="utf-8")

    result = retry_failed(
        RetryFailedRequest(
            previous_run_dir=previous,
            suite_path=DEFAULT_SUITE_PATH,
            output_dir=tmp_path / "outputs",
            runs_dir=tmp_path / "runs",
            run_id="retry",
            sandbox="local",
        )
    )

    assert len(result.result_paths) == 1
    assert result.result_paths[0].parts[-3:] == ("m1", "coordinate_system_animation", "result.json")


def test_retry_failed_includes_missing_and_preserves_model_task_pairs(tmp_path, monkeypatch):
    import manimbench.orchestrator as orchestrator

    previous = tmp_path / "runs" / "previous"
    (previous / "m1" / "coordinate_system_animation").mkdir(parents=True)
    (previous / "m2" / "derivative_motion_story").mkdir(parents=True)
    (previous / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "previous",
                "models": ["m1", "m2"],
                "suite": {"task_ids": ["coordinate_system_animation", "derivative_motion_story"]},
            }
        ),
        encoding="utf-8",
    )
    (previous / "m1" / "coordinate_system_animation" / "result.json").write_text(
        json.dumps({"model": "m1", "task": {"id": "coordinate_system_animation"}, "score": {"passed": False}}),
        encoding="utf-8",
    )
    (previous / "m2" / "derivative_motion_story" / "result.json").write_text(
        json.dumps({"model": "m2", "task": {"id": "derivative_motion_story"}, "score": {"passed": True}}),
        encoding="utf-8",
    )
    captured = {}

    def fake_render_matrix(request):
        captured["model_task_ids"] = request.model_task_ids
        return RenderMatrixResult(run_id="retry", run_dir=tmp_path / "runs" / "retry", failures=0)

    monkeypatch.setattr(orchestrator, "render_matrix", fake_render_matrix)

    retry_failed(
        RetryFailedRequest(
            previous_run_dir=previous,
            suite_path=DEFAULT_SUITE_PATH,
            output_dir=tmp_path / "outputs",
            runs_dir=tmp_path / "runs",
            run_id="retry",
        )
    )

    assert captured["model_task_ids"] == {
        "m1": ["coordinate_system_animation", "derivative_motion_story"],
        "m2": ["coordinate_system_animation"],
    }
