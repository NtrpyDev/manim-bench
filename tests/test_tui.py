import asyncio
import json

from textual.widgets import Button, DataTable, Input, Select

from manimbench import orchestrator
from manimbench.orchestrator import BalanceResult, PipelineEvent, PipelineResult, PublishSummary, RunSummary
from manimbench.model_sync import ModelCandidate
from manimbench.tui.app import ManimBenchApp, PublishScreen, RunHistoryScreen, VideoPreviewScreen
from manimbench.tui.state import UIState, state_path


def _stub_balance(monkeypatch):
    monkeypatch.setattr(orchestrator, "fetch_balance", lambda **kwargs: BalanceResult(error="test"))


def _quiet_notifications(monkeypatch):
    monkeypatch.setattr(ManimBenchApp, "notify_event", lambda *args, **kwargs: None)


def test_dashboard_renders_model_table(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)

    async def run():
        async with ManimBenchApp(UIState.defaults(), enable_live_metadata=False).run_test() as pilot:
            await pilot.pause()
            table = pilot.app.screen.query_one("#model-table", DataTable)
            assert table.row_count > 0
            assert "Selected:" in str(pilot.app.screen.query_one("#selected-summary").render())

    asyncio.run(run())


def test_dashboard_smoke_button_calls_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)
    _quiet_notifications(monkeypatch)
    calls = []

    def fake_run_pipeline(request):
        calls.append(request)
        request.event_callback(PipelineEvent("pipeline_finished", "done", status="complete"))
        return PipelineResult(run_id="fake-run", mode=request.mode)

    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)
    state = UIState.defaults()
    state.selected_models = ["composer-2-5"]

    async def run():
        async with ManimBenchApp(state, enable_live_metadata=False).run_test() as pilot:
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            await pilot.click("#smoke")
            await pilot.pause(0.2)

    asyncio.run(run())

    assert calls
    assert calls[0].mode == "smoke"
    assert calls[0].models == ["composer-2-5"]


def test_dashboard_run_button_starts_full_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)
    _quiet_notifications(monkeypatch)
    calls = []

    def fake_run_pipeline(request):
        calls.append(request)
        request.event_callback(PipelineEvent("pipeline_started", "started", status="running", data={"run_id": "full-run"}))
        request.event_callback(PipelineEvent("task_started", "Generating composer-2-5/task", model="composer-2-5", task_id="task", status="running"))
        request.event_callback(PipelineEvent("task_finished", "Generated composer-2-5/task", model="composer-2-5", task_id="task", status="complete", cost_usd=0.01))
        return PipelineResult(run_id="full-run", mode=request.mode)

    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)
    state = UIState.defaults()
    state.selected_models = ["composer-2-5"]
    state.force_rerun = True

    async def run():
        async with ManimBenchApp(state, enable_live_metadata=False).run_test() as pilot:
            await pilot.resize_terminal(140, 45)
            await pilot.pause()
            await pilot.click("#run")
            await pilot.pause(0.2)
            table = pilot.app.screen.query_one("#monitor-model-table", DataTable)
            assert table.row_count == 1

    asyncio.run(run())

    assert calls
    assert calls[0].mode == "full"
    assert calls[0].force
    assert state.last_run_id == "full-run"


def test_run_monitor_aggregates_render_failures_by_reason(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)
    _quiet_notifications(monkeypatch)

    def write_result(task_id, payload):
        task_dir = tmp_path / "runs" / "agg-run" / "composer-2-5" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        return task_dir

    def fake_run_pipeline(request):
        request.event_callback(PipelineEvent("pipeline_started", "started", status="running", data={"run_id": "agg-run"}))
        request.event_callback(PipelineEvent("generation_started", "Generation started", data={"models": ["composer-2-5"]}))
        request.event_callback(PipelineEvent("render_started", "Render started", data={"models": ["composer-2-5"]}))
        pass_dir = write_result("pass_task", {"score": {"passed": True}})
        request.event_callback(PipelineEvent("task_started", "Rendering composer-2-5/pass_task", model="composer-2-5", task_id="pass_task", status="running", path=pass_dir))
        request.event_callback(PipelineEvent("task_finished", "Rendered composer-2-5/pass_task: pass", model="composer-2-5", task_id="pass_task", status="pass", path=pass_dir))
        fail_dir = write_result(
            "fail_task",
            {
                "render": {"exit_code": 0, "timed_out": False},
                "score": {
                    "passed": False,
                    "checks": {
                        "render_exit_code": True,
                        "render_not_timed_out": True,
                        "media_generated": True,
                        "required_source_terms": {"passed": False},
                    },
                },
            },
        )
        request.event_callback(PipelineEvent("task_started", "Rendering composer-2-5/fail_task", model="composer-2-5", task_id="fail_task", status="running", path=fail_dir))
        request.event_callback(PipelineEvent("task_failed", "Rendered composer-2-5/fail_task: fail", model="composer-2-5", task_id="fail_task", status="fail", path=fail_dir))
        request.event_callback(PipelineEvent("model_progress", "composer-2-5: rendered 2/2", model="composer-2-5", data={"completed": 2, "total": 2}))
        request.event_callback(PipelineEvent("pipeline_finished", "done", status="failed", data={"run_id": "agg-run"}))
        return PipelineResult(run_id="agg-run", mode=request.mode)

    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)
    state = UIState.defaults()
    state.selected_models = ["composer-2-5"]

    async def run():
        async with ManimBenchApp(state, enable_live_metadata=False).run_test() as pilot:
            await pilot.resize_terminal(140, 45)
            await pilot.pause()
            await pilot.click("#run")
            await pilot.pause(0.2)
            table = pilot.app.screen.query_one("#monitor-model-table", DataTable)
            row = [str(cell) for cell in table.get_row_at(0)]
            assert row[1] == "fail 1/2"
            assert "source terms 1" in row[2]

    asyncio.run(run())


def test_dashboard_cancel_and_retry_call_orchestrator(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)
    _quiet_notifications(monkeypatch)
    cancelled = []
    retried = []

    monkeypatch.setattr(orchestrator, "cancel", lambda: cancelled.append(True) or True)

    def fake_retry_failed(request):
        retried.append(request)
        return None

    monkeypatch.setattr(orchestrator, "retry_failed", fake_retry_failed)
    state = UIState.defaults()
    state.last_run_id = "previous"

    async def run():
        async with ManimBenchApp(state, enable_live_metadata=False).run_test() as pilot:
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            await pilot.click("#cancel")
            await pilot.click("#retry")
            await pilot.pause(0.2)

    asyncio.run(run())

    assert cancelled == [True]
    assert retried
    assert retried[0].previous_run_dir.name == "previous"


def test_settings_persists_env_names_not_secret_values(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-do-not-write")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    state = UIState.defaults()
    state.reasoning_effort = "xhigh"
    path = state_path()

    state.save()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["env_var_names"]["openrouter"] == "OPENROUTER_API_KEY"
    assert payload["reasoning_effort"] == "xhigh"
    assert "sk-do-not-write" not in path.read_text(encoding="utf-8")
    assert path.name == "dashboard.json"


def test_publish_live_disabled_until_partial_override(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)

    def fake_publish_summary(run_id, runs_dir):
        return PublishSummary(
            run_id=str(run_id),
            run_dir=tmp_path / "runs" / str(run_id),
            status="failed",
            passed=1,
            failed=1,
            missing=0,
            task_count=2,
            model_count=1,
        )

    monkeypatch.setattr(orchestrator, "get_publish_summary", fake_publish_summary)
    state = UIState.defaults()
    state.last_run_id = "partial-run"

    async def run():
        app = ManimBenchApp(state, enable_live_metadata=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(PublishScreen())
            await pilot.pause()
            screen = app.screen
            screen.query_one("#publish-target", Select).value = "live"
            screen._update_check()
            assert screen.query_one("#publish-run", Button).disabled
            screen.query_one("#allow-partial").value = True
            screen._update_check()
            assert not screen.query_one("#publish-run", Button).disabled

    asyncio.run(run())


def test_publish_disabled_when_render_run_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)

    state = UIState.defaults()
    state.last_run_id = "generation-only"

    async def run():
        app = ManimBenchApp(state, enable_live_metadata=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(PublishScreen())
            await pilot.pause()
            screen = app.screen
            assert screen.query_one("#publish-run", Button).disabled
            assert "no render results found" in str(screen.query_one("#publish-check").render())

    asyncio.run(run())


def test_run_history_resume_preserves_run_id(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)

    monkeypatch.setattr(
        orchestrator,
        "list_run_history",
        lambda runs_dir: [
            RunSummary(
                run_id="resume-me",
                run_dir=tmp_path / "runs" / "resume-me",
                state_path=None,
                status="generated",
                updated_at="2026-01-01T00:00:00+00:00",
                models=["composer-2-5"],
            )
        ],
    )
    state = UIState.defaults()

    async def run():
        app = ManimBenchApp(state, enable_live_metadata=False)
        async with app.run_test() as pilot:
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            app.push_screen(RunHistoryScreen())
            await pilot.pause()
            app.screen.action_resume()
            await pilot.pause()
            assert app.ui_state.last_run_id == "resume-me"
            assert getattr(app.screen, "resume_run_id") == "resume-me"

    asyncio.run(run())


def test_dashboard_keyboard_navigation_reaches_preview_settings_history(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)
    state = UIState.defaults()
    state.last_run_id = "last-run"

    async def run():
        app = ManimBenchApp(state, enable_live_metadata=False)
        async with app.run_test() as pilot:
            await pilot.resize_terminal(140, 45)
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
            assert isinstance(app.screen, VideoPreviewScreen)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.click("#settings")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "SettingsScreen"
            await pilot.press("escape")
            await pilot.pause()
            await pilot.click("#history")
            await pilot.pause()
            assert isinstance(app.screen, RunHistoryScreen)

    asyncio.run(run())


def test_dashboard_all_models_scope_selects_model_for_current_run(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)
    _quiet_notifications(monkeypatch)
    candidate = ModelCandidate(
        id="deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        provider_family="openrouter",
        openrouter_slug="deepseek/deepseek-v4-pro",
        tokenizer="manimbench_regex_estimator_v1",
        pricing={"input_usd_per_1m_tokens": 0.435, "output_usd_per_1m_tokens": 0.87},
        context_length=128000,
        supported_parameters=["max_tokens"],
    )
    applied = []
    calls = []

    def fake_apply(candidates, **kwargs):
        applied.append((list(candidates), kwargs))

    def fake_run_pipeline(request):
        calls.append(request)
        request.event_callback(PipelineEvent("pipeline_finished", "done", status="complete"))
        return PipelineResult(run_id="all-model-run", mode=request.mode)

    import manimbench.tui.app as tui_app

    monkeypatch.setattr(tui_app, "apply_model_candidates", fake_apply)
    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)
    state = UIState.defaults()
    state.selected_models = []

    async def run():
        app = ManimBenchApp(state, enable_live_metadata=False)
        async with app.run_test() as pilot:
            await pilot.resize_terminal(140, 45)
            await pilot.pause()
            screen = app.screen
            screen.all_model_candidates = {candidate.id: candidate}
            state.model_scope = "all_openrouter"
            screen.refresh_dashboard()
            table = screen.query_one("#model-table", DataTable)
            assert table.row_count == 1
            await pilot.press("space")
            await pilot.pause()
            await pilot.click("#smoke")
            await pilot.pause(0.2)

    asyncio.run(run())

    assert applied
    assert applied[0][0] == [candidate]
    assert applied[0][1]["hidden"] is True
    assert state.selected_models == ["deepseek-v4-pro"]
    assert calls
    assert calls[0].mode == "smoke"
    assert calls[0].models == ["deepseek-v4-pro"]


def test_dashboard_catalog_shortcut_focuses_openrouter_search(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)
    candidate = ModelCandidate(
        id="qwen-3-max",
        display_name="Qwen 3 Max",
        provider_family="openrouter",
        openrouter_slug="qwen/qwen-3-max",
        tokenizer="manimbench_regex_estimator_v1",
        pricing={"input_usd_per_1m_tokens": 0.3, "output_usd_per_1m_tokens": 1.2},
        context_length=262144,
        supported_parameters=["max_tokens"],
    )
    state = UIState.defaults()
    state.selected_models = []

    async def run():
        app = ManimBenchApp(state, enable_live_metadata=False)
        async with app.run_test() as pilot:
            await pilot.resize_terminal(140, 45)
            await pilot.pause()
            screen = app.screen
            screen.all_model_candidates = {candidate.id: candidate}
            screen.action_catalog()
            await pilot.pause()
            search = screen.query_one("#model-search", Input)
            table = screen.query_one("#model-table", DataTable)
            assert state.model_scope == "all_openrouter"
            assert screen.query_one("#model-scope", Select).value == "all_openrouter"
            assert screen.focused is search
            assert table.row_count == 1

    asyncio.run(run())


def test_dashboard_toggle_keeps_scrolled_table_position(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _stub_balance(monkeypatch)
    state = UIState.defaults()
    state.selected_models = []

    async def run():
        app = ManimBenchApp(state, enable_live_metadata=False)
        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            table = app.screen.query_one("#model-table", DataTable)
            assert table.row_count > 12
            table.focus()
            table.move_cursor(row=12, column=0, animate=False, scroll=False)
            table.scroll_to(y=6, animate=False, immediate=True)
            await pilot.pause()
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            model_id = str(getattr(row_key, "value", row_key))
            starting_scroll_y = table.scroll_y
            assert starting_scroll_y > 0

            await pilot.press("space")
            await pilot.pause()

            current_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            assert str(getattr(current_key, "value", current_key)) == model_id
            assert table.scroll_y == starting_scroll_y
            assert model_id in state.selected_models

    asyncio.run(run())
