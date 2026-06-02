from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, ProgressBar, RichLog, Select, Static

from manimbench import orchestrator
from manimbench.model_sync import ModelCandidate, apply_model_candidates, check_openrouter_models
from manimbench.orchestrator import BalanceResult, DashboardState, PipelineEvent, PipelineRequest, PublishRequest, RetryFailedRequest
from manimbench.reasoning import REASONING_EFFORT_CHOICES, display_reasoning_effort, stored_reasoning_effort
from manimbench.tui.notifications import os_notify
from manimbench.tui.state import UIState


class ManimBenchApp(App[None]):
    CSS = """
    Screen {
        background: #07090d;
        color: #c7cbd6;
    }

    #topline {
        height: 3;
        border: solid #6f7cff;
        padding: 0 1;
        color: #f69a3d;
        text-style: bold;
    }

    .panel {
        border: solid #515766;
        padding: 0 1;
    }

    .compact {
        height: auto;
    }

    .toolbar {
        height: 5;
        padding: 0 1;
    }

    .monitor-actions {
        height: 3;
        padding: 0;
    }

    .monitor-actions Button {
        margin: 0 1 0 0;
    }

    #start-full, #start-smoke, #retry-failed, #cancel-run {
        width: 10;
    }

    .monitor-actions #back {
        width: 10;
    }

    #start-generate {
        width: 12;
    }

    #publish-draft, #publish-live {
        width: 15;
    }

    .toolbar Select {
        width: 16;
        margin-right: 1;
    }

    #model-scope {
        width: 24;
    }

    #model-sort {
        width: 17;
    }

    .toolbar Input {
        width: 1fr;
        margin-right: 1;
    }

    .actions {
        height: 10;
        padding: 0 1;
    }

    .action-row {
        height: 3;
        width: auto;
        align-horizontal: left;
    }

    .action-row Button {
        margin: 0 1 0 0;
        width: 11;
    }

    #run, #smoke {
        width: 9;
    }

    #retry {
        width: 14;
    }

    #settings {
        width: 12;
    }

    .option-row {
        height: 3;
        width: 100%;
        align-horizontal: center;
    }

    .option-row Checkbox {
        margin: 0 2 0 0;
        width: 24;
    }

    .option-row Select {
        margin: 0 2 0 0;
        width: 24;
    }

    .form-row Select {
        width: 1fr;
    }

    #force-rerun {
        width: 22;
    }

    #model-table {
        height: 16;
        border: solid #6f7cff;
    }

    #monitor-model-table {
        height: 27;
        border: solid #515766;
    }

    #run-log, #detail-log, #publish-log, #history-table, #task-table, #video-table {
        height: 1fr;
        border: solid #515766;
    }

    #progress-row {
        height: 4;
        padding: 1;
    }

    #run-progress {
        width: 1fr;
        margin-right: 2;
    }

    #status-line {
        width: 48;
        content-align: left middle;
    }

    .form-row {
        height: 3;
        margin-bottom: 1;
    }

    .form-row Label {
        width: 22;
        content-align: left middle;
    }

    .form-row Input {
        width: 1fr;
    }

    .screen-title {
        height: 3;
        border: solid #6f7cff;
        padding: 0 1;
        color: #f69a3d;
        text-style: bold;
    }

    .muted {
        color: #8f96a3;
    }
    """

    BINDINGS = [
        ("q", "quit", "quit"),
        ("d", "dashboard", "dashboard"),
        ("s", "settings", "settings"),
        ("h", "history", "history"),
        ("u", "publish", "publish"),
    ]

    def __init__(self, ui_state: UIState | None = None, *, enable_live_metadata: bool = True):
        super().__init__()
        self.ui_state = ui_state or UIState.load()
        self.enable_live_metadata = enable_live_metadata

    def on_mount(self) -> None:
        orchestrator.clear_cancel()
        self.push_screen(DashboardScreen())

    def persist(self) -> None:
        self.ui_state.save()

    def start_background(self, work) -> None:
        threading.Thread(target=work, daemon=True).start()

    def call_threadsafe(self, callback, *args, **kwargs) -> None:
        try:
            self.call_from_thread(callback, *args, **kwargs)
        except RuntimeError:
            return

    def action_dashboard(self) -> None:
        self.push_screen(DashboardScreen())

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())

    def action_history(self) -> None:
        self.push_screen(RunHistoryScreen())

    def action_publish(self) -> None:
        self.push_screen(PublishScreen())

    def notify_event(self, title: str, message: str, *, severity: str = "information", os_level: bool = False) -> None:
        self.notify(message, title=title, severity=severity)
        if os_level:
            os_notify(title, message)


class DashboardScreen(Screen[None]):
    AUTO_FOCUS = "#model-table"

    SORTABLE_HEADERS = {
        "provider": "provider",
        "price": "price",
        "context": "context",
        "params": "params",
    }

    BINDINGS = [
        ("space", "toggle_model", "toggle"),
        ("a", "select_all", "select all"),
        ("c", "catalog", "catalog"),
        ("/", "focus_search", "search"),
        ("f", "run", "run"),
        ("m", "monitor", "monitor"),
        ("o", "monitor", "monitor"),
        ("enter", "model_detail", "detail"),
        ("p", "preview", "preview"),
        ("u", "publish", "publish"),
        ("s", "settings", "settings"),
        ("r", "history", "history"),
        ("q", "quit", "quit"),
    ]

    def __init__(self):
        super().__init__()
        self.dashboard: DashboardState | None = None
        self.balance_cache: BalanceResult | None = None
        self.catalog_cache: dict[str, Any] | None = None
        self.all_model_candidates: dict[str, ModelCandidate] = {}
        self.model_rows: dict[str, dict[str, Any]] = {}
        self.model_sort_reverse = False
        self.dashboard_refresh_version = 0
        self.focus_model_table_after_render = True
        self.spent_this_run: float = 0.0

    def compose(self) -> ComposeResult:
        yield Static("ManimBench v0.6", id="topline")
        with Horizontal(classes="toolbar panel"):
            yield Select([("Models: curated", "curated")], id="model-scope", allow_blank=False, value="curated")
            yield Select([("Provider: all", "all")], id="provider-filter", allow_blank=False, value="all")
            yield Select([("Sort: provider", "provider")], id="model-sort", allow_blank=False, value="provider")
            yield Select([("Context: all", "all")], id="context-filter", allow_blank=False, value="all")
            yield Select([("Price: all", "all")], id="price-filter", allow_blank=False, value="all")
            yield Select([("Status: all", "all")], id="status-filter", allow_blank=False, value="all")
            yield Input(placeholder="Search models...", id="model-search")
            yield Button("Refresh", id="refresh")
        yield DataTable(id="model-table")
        with Vertical(classes="panel actions"):
            yield Static("Selected: 0 models", id="selected-summary")
            with Horizontal(classes="action-row"):
                yield Button("Run", id="run", variant="primary")
                yield Button("Smoke", id="smoke")
                yield Button("Cancel", id="cancel")
                yield Button("Retry failed", id="retry")
                yield Button("Publish", id="publish")
                yield Button("Settings", id="settings")
                yield Button("History", id="history")
            with Horizontal(classes="option-row"):
                yield Select(_reasoning_options(), id="reasoning-effort", allow_blank=False, value="default")
                yield Checkbox("Skip complete", id="skip-complete")
                yield Checkbox("Force rerun", id="force-rerun")
        with Horizontal(id="progress-row", classes="panel compact"):
            yield ProgressBar(total=100, id="run-progress")
            yield Static("idle", id="status-line")
        yield RichLog(id="run-log", wrap=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#model-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        self._configure_filters()
        self.balance_cache = BalanceResult(error="checking")
        self._render_loading_dashboard()
        self.call_after_refresh(self._refresh_dashboard_background)
        if self.app_ref.enable_live_metadata:
            self.call_after_refresh(self._refresh_live_metadata)

    @property
    def app_ref(self) -> ManimBenchApp:
        return self.app  # type: ignore[return-value]

    def _configure_filters(self) -> None:
        scope = self.query_one("#model-scope", Select)
        scope.set_options(
            [
                ("Models: curated", "curated"),
                ("Models: all OpenRouter", "all_openrouter"),
                ("Models: latest/provider", "latest_per_provider"),
            ]
        )
        scope.value = self.app_ref.ui_state.model_scope
        sort = self.query_one("#model-sort", Select)
        sort.set_options(
            [
                ("Sort: provider", "provider"),
                ("Sort: newest", "newest"),
                ("Sort: price", "price"),
                ("Sort: context", "context"),
                ("Sort: params", "params"),
                ("Sort: name", "name"),
            ]
        )
        sort.value = self.app_ref.ui_state.model_sort
        self._configure_provider_options()
        self._configure_static_filters()

    def _configure_provider_options(self) -> None:
        provider = self.query_one("#provider-filter", Select)
        current = self.app_ref.ui_state.provider_filter
        if self.app_ref.ui_state.model_scope in {"all_openrouter", "latest_per_provider"} and self.all_model_candidates:
            providers = sorted({_candidate_provider(candidate) for candidate in self.all_model_candidates.values()})
            provider.set_options([("Provider: all", "all")] + [(name, name) for name in providers])
            if current not in {"all", *providers}:
                current = "all"
                self.app_ref.ui_state.provider_filter = current
        else:
            provider.set_options(
                [
                    ("Provider: all", "all"),
                    ("OpenRouter", "openrouter"),
                    ("Cursor", "cursor"),
                    ("OpenAI", "openai"),
                    ("Anthropic", "anthropic"),
                    ("Google", "google"),
                    ("xAI", "xai"),
                ]
            )
        provider.value = current

    def _configure_static_filters(self) -> None:
        context = self.query_one("#context-filter", Select)
        context.set_options(
            [
                ("Context: all", "all"),
                ("<64K", "short"),
                ("64K-199K", "medium"),
                (">=200K", "long"),
                ("Unknown", "unknown"),
            ]
        )
        context.value = self.app_ref.ui_state.context_filter
        price = self.query_one("#price-filter", Select)
        price.set_options(
            [
                ("Price: all", "all"),
                ("Low", "low"),
                ("Mid", "mid"),
                ("High", "high"),
                ("Unknown", "unknown"),
            ]
        )
        price.value = self.app_ref.ui_state.price_filter
        status = self.query_one("#status-filter", Select)
        status.set_options(
            [
                ("Status: all", "all"),
                ("Complete", "complete"),
                ("Incomplete", "incomplete"),
                ("Partial", "partial"),
                ("Stale", "stale"),
                ("Missing", "missing"),
            ]
        )
        status.value = self.app_ref.ui_state.status_filter
        self.query_one("#model-search", Input).value = self.app_ref.ui_state.search
        self.query_one("#reasoning-effort", Select).value = self.app_ref.ui_state.reasoning_effort
        self.query_one("#skip-complete", Checkbox).value = self.app_ref.ui_state.skip_complete
        self.query_one("#force-rerun", Checkbox).value = self.app_ref.ui_state.force_rerun

    def refresh_dashboard(self) -> None:
        self.dashboard_refresh_version += 1
        self._configure_provider_options()
        dashboard = orchestrator.get_dashboard_state(**self._dashboard_request_kwargs())
        self._apply_dashboard_state(dashboard)

    def _dashboard_request_kwargs(self) -> dict[str, Any]:
        ui = self.app_ref.ui_state
        return {
            "selected_models": ui.selected_models,
            "output_dir": ui.output_path,
            "runs_dir": ui.runs_path,
            "site_repo": ui.site_repo_path,
            "provider_filter": ui.provider_filter,
            "status_filter": ui.status_filter,
            "context_filter": ui.context_filter,
            "price_filter": ui.price_filter,
            "search": ui.search,
            "last_run_id": ui.last_run_id,
            "include_balance": False,
            "balance": self.balance_cache,
            "catalog": self.catalog_cache,
        }

    def _refresh_dashboard_background(self) -> None:
        self.dashboard_refresh_version += 1
        version = self.dashboard_refresh_version
        kwargs = self._dashboard_request_kwargs()

        def work() -> None:
            try:
                dashboard = orchestrator.get_dashboard_state(**kwargs)
            except Exception as error:
                self.app_ref.call_threadsafe(self._handle_worker_error, "Dashboard refresh failed", error)
                return
            self.app_ref.call_threadsafe(self._handle_dashboard_state, version, dashboard)

        self.app_ref.start_background(work)

    def _handle_dashboard_state(self, version: int, dashboard: DashboardState) -> None:
        if version != self.dashboard_refresh_version or not self.is_mounted:
            return
        self._apply_dashboard_state(dashboard)

    def _apply_dashboard_state(self, dashboard: DashboardState) -> None:
        self.dashboard = dashboard
        self.balance_cache = self.dashboard.balance
        self._configure_provider_options()
        self._render_topline()
        self._render_table()
        if self.focus_model_table_after_render:
            self.query_one("#model-table", DataTable).focus()
            self.focus_model_table_after_render = False
        self._render_summary()

    def _render_loading_dashboard(self) -> None:
        self.query_one("#topline", Static).update("ManimBench v0.6    loading dashboard")
        table = self.query_one("#model-table", DataTable)
        table.clear(columns=True)
        table.add_column("", width=5, key="selected")
        table.add_column("Model", width=30, key="model")
        table.add_column("Provider", width=14, key="provider")
        table.add_column("Input/Output price", width=24, key="price")
        table.add_column("Context", width=10, key="context")
        table.add_column("Params", width=16, key="params")
        table.add_column("Status", width=12, key="status")
        table.add_row("", "Loading dashboard...", "", "", "", "", "", key="__loading__")
        self.model_rows = {}
        selected = len(self.app_ref.ui_state.selected_models)
        self.query_one("#selected-summary", Static).update(f"Selected: {selected} models | loading suite and output status")
        self.query_one("#status-line", Static).update("loading dashboard")

    def _refresh_live_metadata(self) -> None:
        ui = self.app_ref.ui_state
        catalog_enabled = ui.openrouter_catalog_enabled
        openrouter_env = ui.env_var_names.get("openrouter", "OPENROUTER_API_KEY")

        def work() -> None:
            balance: BalanceResult | None = None
            catalog: dict[str, Any] | None = None
            model_check = None
            try:
                key = os.getenv(openrouter_env)
                balance = orchestrator.fetch_balance(api_key=key, timeout_seconds=5) if key else BalanceResult(error=f"{openrouter_env} is not set")
            except Exception as error:
                balance = BalanceResult(error=str(error))
            if catalog_enabled and os.getenv(openrouter_env):
                try:
                    catalog = orchestrator.fetch_openrouter_catalog(api_key=os.getenv(openrouter_env))
                except Exception:
                    catalog = None
            if catalog_enabled:
                model_check = check_openrouter_models(catalog=catalog, include_unregistered=True)
            try:
                self.app.call_from_thread(self._handle_live_metadata, balance, catalog, model_check)
            except RuntimeError:
                return

        threading.Thread(target=work, daemon=True).start()

    def _handle_live_metadata(self, balance: BalanceResult | None, catalog: dict[str, Any] | None, model_check: Any | None = None) -> None:
        if balance is None:
            return
        self.balance_cache = balance
        if catalog is not None:
            self.catalog_cache = catalog
        if model_check is not None:
            candidates = getattr(model_check, "all_models", None) or getattr(model_check, "unregistered_models", None)
            if candidates:
                self.all_model_candidates = {candidate.id: candidate for candidate in candidates}
        if model_check is not None and not model_check.skipped and model_check.new_models:
            message = f"{len(model_check.new_models)} new OpenRouter model(s). Run `manimbench check-models --apply` to add them."
            try:
                self.query_one("#run-log", RichLog).write(message)
            except Exception:
                pass
            self.app_ref.notify_event("New Models", message)
        self.refresh_dashboard()

    def _render_topline(self) -> None:
        if not self.dashboard:
            return
        balance = self.dashboard.balance
        balance_text = _format_balance_text(balance)
        estimate = self.dashboard.estimate.estimated_usd
        spent = self.dashboard.spent_usd
        if self.spent_this_run:
            spent = (spent or 0.0) + self.spent_this_run
        spent_text = f"${spent:.2f}" if spent is not None else "unavailable"
        reasoning = display_reasoning_effort(self.app_ref.ui_state.reasoning_effort)
        self.query_one("#topline", Static).update(
            f"ManimBench v0.6    {balance_text}    |    Est. ${estimate:.2f}    |    Spent {spent_text}    |    Reasoning {reasoning}"
        )

    def _render_table(self) -> None:
        if not self.dashboard:
            return
        table = self.query_one("#model-table", DataTable)
        position = self._table_position_snapshot(table)
        table.clear(columns=True)
        table.add_column("", width=5, key="selected")
        table.add_column("Model", width=30, key="model")
        table.add_column("Provider", width=14, key="provider")
        table.add_column("Input/Output price", width=24, key="price")
        table.add_column("Context", width=10, key="context")
        table.add_column("Params", width=16, key="params")
        table.add_column("Status", width=12, key="status")
        rows = self._visible_model_rows()
        self.model_rows = {str(row["id"]): row for row in rows}
        for row in rows:
            table.add_row(
                "[x]" if row["selected"] else "[ ]",
                str(row["display_name"]),
                str(row["provider"]),
                _format_pricing(row["pricing"]),
                _format_context(row["context_window"]),
                str(row["params"]),
                "—" if row["status"] == "missing" else str(row["status"]),
                key=str(row["id"]),
            )
        if position is not None:
            self.call_after_refresh(self._restore_table_position, position)

    def _table_position_snapshot(self, table: DataTable) -> dict[str, Any] | None:
        if table.row_count == 0:
            return None
        row_key = None
        try:
            row_key = _key_value(table.coordinate_to_cell_key(table.cursor_coordinate).row_key)
        except Exception:
            pass
        return {
            "row_key": row_key,
            "row_index": table.cursor_coordinate.row,
            "column": table.cursor_coordinate.column,
            "scroll_x": table.scroll_x,
            "scroll_y": table.scroll_y,
        }

    def _restore_table_position(self, position: dict[str, Any]) -> None:
        if not self.is_mounted:
            return
        table = self.query_one("#model-table", DataTable)
        if table.row_count == 0:
            return
        row_index = None
        row_key = position.get("row_key")
        if row_key:
            try:
                row_index = table.get_row_index(str(row_key))
            except Exception:
                row_index = None
        if row_index is None:
            row_index = int(position.get("row_index") or 0)
        row_index = max(0, min(row_index, table.row_count - 1))
        column = max(0, min(int(position.get("column") or 0), max(0, len(table.columns) - 1)))
        table.move_cursor(row=row_index, column=column, animate=False, scroll=False)
        table.scroll_to(
            x=float(position.get("scroll_x") or 0),
            y=float(position.get("scroll_y") or 0),
            animate=False,
            immediate=True,
        )

    def _visible_model_rows(self) -> list[dict[str, Any]]:
        if not self.dashboard:
            return []
        ui = self.app_ref.ui_state
        selected = set(ui.selected_models)
        if ui.model_scope in {"all_openrouter", "latest_per_provider"}:
            candidates = list(self.all_model_candidates.values())
            if ui.model_scope == "latest_per_provider":
                candidates = _latest_candidates_by_provider(candidates)
            rows = [self._candidate_row(candidate, selected) for candidate in candidates]
        else:
            rows = [self._dashboard_row(row) for row in self.dashboard.models]
        rows = [row for row in rows if self._row_matches_filters(row)]
        return sorted(rows, key=_dashboard_sort_key(ui.model_sort), reverse=self.model_sort_reverse)

    def _dashboard_row(self, row: Any) -> dict[str, Any]:
        provider = row.openrouter_slug.split("/", 1)[0] if row.openrouter_slug else row.default_provider
        return {
            "id": row.id,
            "display_name": row.display_name,
            "selected": row.selected,
            "provider": provider,
            "pricing": row.pricing or {},
            "context_window": row.context_window,
            "params": "-",
            "status": row.status,
            "search": " ".join([row.id, row.display_name, row.default_provider, row.provider_family, row.openrouter_slug or ""]).lower(),
            "candidate": None,
            "created": 0,
        }

    def _candidate_row(self, candidate: ModelCandidate, selected: set[str]) -> dict[str, Any]:
        provider = _candidate_provider(candidate)
        return {
            "id": candidate.id,
            "display_name": candidate.display_name,
            "selected": candidate.id in selected,
            "provider": provider,
            "pricing": candidate.pricing or {},
            "context_window": candidate.context_length,
            "params": _format_catalog_params(candidate),
            "status": _fast_output_status(candidate.id, self.dashboard.task_ids, self.app_ref.ui_state.output_path),
            "search": " ".join([candidate.id, candidate.display_name, candidate.openrouter_slug, provider]).lower(),
            "candidate": candidate,
            "created": int(candidate.created or 0),
        }

    def _row_matches_filters(self, row: dict[str, Any]) -> bool:
        ui = self.app_ref.ui_state
        if ui.provider_filter not in {"", "all"} and ui.provider_filter != row["provider"]:
            return False
        if ui.status_filter not in {"", "all"} and ui.status_filter != row["status"]:
            return False
        if not _matches_context_value(row["context_window"], ui.context_filter):
            return False
        if not _matches_price_value(row["pricing"], ui.price_filter):
            return False
        search_lc = ui.search.strip().lower()
        return not search_lc or search_lc in row["search"]

    def _render_summary(self) -> None:
        if not self.dashboard:
            return
        selected = len(self.app_ref.ui_state.selected_models)
        run_text = "no run"
        if self.dashboard.current_run:
            run_text = f"{self.dashboard.current_run.run_id}: {self.dashboard.current_run.status}"
        self.query_one("#selected-summary", Static).update(
            f"Selected: {selected} models | Suite: {self.dashboard.suite_version} ({len(self.dashboard.task_ids)} tasks) | "
            f"Reasoning: {display_reasoning_effort(self.app_ref.ui_state.reasoning_effort)} | Run: {run_text}"
        )

    def action_focus_search(self) -> None:
        self.query_one("#model-search", Input).focus()

    def action_catalog(self) -> None:
        ui = self.app_ref.ui_state
        if ui.model_scope != "all_openrouter":
            ui.model_scope = "all_openrouter"
            self.query_one("#model-scope", Select).value = "all_openrouter"
            self.app_ref.persist()
            if not self.all_model_candidates:
                self.query_one("#status-line", Static).update("loading OpenRouter catalog")
                self._refresh_live_metadata()
            self.refresh_dashboard()
        self.action_focus_search()

    def action_select_all(self) -> None:
        if not self.dashboard:
            return
        visible = list(self.model_rows)
        selected = set(self.app_ref.ui_state.selected_models)
        if visible and all(model in selected for model in visible):
            selected.difference_update(visible)
        else:
            self._register_visible_candidates([model for model in visible if model not in selected])
            selected.update(visible)
        self.app_ref.ui_state.selected_models = sorted(selected)
        self.app_ref.persist()
        self.refresh_dashboard()

    def action_toggle_model(self) -> None:
        table = self.query_one("#model-table", DataTable)
        if table.row_count == 0:
            return
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return
        self._toggle_model_key(row_key)

    def _toggle_model_key(self, row_key: Any) -> None:
        model_id = _key_value(row_key)
        selected = set(self.app_ref.ui_state.selected_models)
        if model_id in selected:
            selected.remove(model_id)
        else:
            self._register_visible_candidates([model_id])
            selected.add(model_id)
        self.app_ref.ui_state.selected_models = sorted(selected)
        self.app_ref.persist()
        self.refresh_dashboard()

    def _register_visible_candidates(self, model_ids: list[str]) -> None:
        candidates = []
        for model_id in model_ids:
            row = self.model_rows.get(model_id)
            candidate = row.get("candidate") if row else None
            if isinstance(candidate, ModelCandidate):
                candidates.append(candidate)
        if candidates:
            apply_model_candidates(candidates, hidden=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._toggle_model_key(event.row_key)

    def on_select_changed(self, event: Select.Changed) -> None:
        ui = self.app_ref.ui_state
        changed = False
        if event.select.id == "provider-filter":
            value = str(event.value)
            if ui.provider_filter != value:
                ui.provider_filter = value
                changed = True
        elif event.select.id == "model-scope":
            value = str(event.value)
            if ui.model_scope != value:
                ui.model_scope = value
                changed = True
            if changed and ui.model_scope in {"all_openrouter", "latest_per_provider"} and not self.all_model_candidates:
                self._refresh_live_metadata()
            self._configure_provider_options()
        elif event.select.id == "model-sort":
            value = str(event.value)
            if ui.model_sort != value:
                ui.model_sort = value
                self.model_sort_reverse = False
                changed = True
        elif event.select.id == "status-filter":
            value = str(event.value)
            if ui.status_filter != value:
                ui.status_filter = value
                changed = True
        elif event.select.id == "context-filter":
            value = str(event.value)
            if ui.context_filter != value:
                ui.context_filter = value
                changed = True
        elif event.select.id == "price-filter":
            value = str(event.value)
            if ui.price_filter != value:
                ui.price_filter = value
                changed = True
        elif event.select.id == "reasoning-effort":
            value = stored_reasoning_effort(str(event.value))
            if ui.reasoning_effort != value:
                ui.reasoning_effort = value
                changed = True
        if not changed:
            return
        self.app_ref.persist()
        self.refresh_dashboard()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "model-search":
            if self.app_ref.ui_state.search == event.value:
                return
            self.app_ref.ui_state.search = event.value
            self.app_ref.persist()
            self.refresh_dashboard()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        changed = False
        if event.checkbox.id == "skip-complete":
            value = bool(event.value)
            if self.app_ref.ui_state.skip_complete != value:
                self.app_ref.ui_state.skip_complete = value
                changed = True
            if value:
                self.query_one("#force-rerun", Checkbox).value = False
                if self.app_ref.ui_state.force_rerun:
                    self.app_ref.ui_state.force_rerun = False
                    changed = True
        elif event.checkbox.id == "force-rerun":
            value = bool(event.value)
            if self.app_ref.ui_state.force_rerun != value:
                self.app_ref.ui_state.force_rerun = value
                changed = True
            if value:
                self.query_one("#skip-complete", Checkbox).value = False
                if self.app_ref.ui_state.skip_complete:
                    self.app_ref.ui_state.skip_complete = False
                    changed = True
        if not changed:
            return
        self.app_ref.persist()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "refresh":
            self.refresh_dashboard()
            if self.app_ref.enable_live_metadata:
                self._refresh_live_metadata()
        elif button_id == "run":
            self.action_run()
        elif button_id == "smoke":
            self._start_run("smoke")
        elif button_id == "cancel":
            orchestrator.cancel()
            self.app_ref.notify_event("Cancelled", "Cancellation requested. Active work stops at a safe boundary.", severity="warning")
        elif button_id == "retry":
            self._retry_failed()
        elif button_id == "publish":
            self.action_publish()
        elif button_id == "settings":
            self.action_settings()
        elif button_id == "history":
            self.action_history()

    def action_run(self) -> None:
        self._start_run("full")

    def action_monitor(self) -> None:
        self.app.push_screen(RunMonitorScreen(resume_run_id=self.app_ref.ui_state.last_run_id))

    def action_model_detail(self) -> None:
        table = self.query_one("#model-table", DataTable)
        if table.row_count == 0:
            return
        try:
            model_id = _key_value(table.coordinate_to_cell_key(table.cursor_coordinate).row_key)
        except Exception:
            return
        self.app.push_screen(ModelDetailScreen(model_id))

    def action_preview(self) -> None:
        self.app.push_screen(VideoPreviewScreen(self.app_ref.ui_state.last_run_id))

    def action_publish(self) -> None:
        self.app.push_screen(PublishScreen())

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_history(self) -> None:
        self.app.push_screen(RunHistoryScreen())

    def _start_run(self, mode: str) -> None:
        self.spent_this_run = 0.0
        monitor = RunMonitorScreen(mode=mode, auto_start=True)
        self.app.push_screen(monitor)

    def _retry_failed(self) -> None:
        ui = self.app_ref.ui_state
        if not ui.last_run_id:
            self.app_ref.notify_event("Retry failed", "No previous run is selected.", severity="warning")
            return
        self.query_one("#status-line", Static).update("retrying failed tasks")
        self.query_one("#run-log", RichLog).write(f"Retrying failed tasks from {ui.last_run_id}", scroll_end=True)

        def callback(event: PipelineEvent) -> None:
            self.app_ref.call_threadsafe(self._handle_event, event)

        def work() -> None:
            try:
                orchestrator.retry_failed(
                    RetryFailedRequest(
                        previous_run_dir=ui.runs_path / ui.last_run_id,
                        models=ui.selected_models,
                        output_dir=ui.output_path,
                        runs_dir=ui.runs_path,
                        parallel=ui.default_parallel,
                        container_image=ui.docker_image,
                        event_callback=callback,
                    )
                )
            except Exception as error:
                self.app_ref.call_threadsafe(self._handle_worker_error, "Retry failed", error)

        self.app_ref.start_background(work)

    def _handle_event(self, event: PipelineEvent) -> None:
        log = self.query_one("#run-log", RichLog)
        line = event.message
        if event.model and event.task_id:
            line = f"{event.model} / {event.task_id}: {event.message}"
        log.write(line, scroll_end=True)
        if event.cost_usd is not None:
            self.spent_this_run += event.cost_usd
            self._render_topline()
        if event.progress is not None:
            self.query_one("#run-progress", ProgressBar).update(progress=int(event.progress * 100))
        if event.status:
            self.query_one("#status-line", Static).update(event.status)

    def _handle_worker_error(self, title: str, error: Exception) -> None:
        self.query_one("#run-log", RichLog).write(f"{title}: {error}", scroll_end=True)
        self.query_one("#status-line", Static).update("failed")
        self.app_ref.notify_event(title, str(error), severity="error")

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.data_table.id != "model-table":
            return
        sort_mode = self.SORTABLE_HEADERS.get(_key_value(event.column_key))
        if not sort_mode:
            return
        event.stop()
        if self.app_ref.ui_state.model_sort == sort_mode:
            self.model_sort_reverse = not self.model_sort_reverse
        else:
            self.app_ref.ui_state.model_sort = sort_mode
            self.model_sort_reverse = False
            sort_select = self.query_one("#model-sort", Select)
            if sort_select.value != sort_mode:
                sort_select.value = sort_mode
        self.app_ref.persist()
        self._render_table()

class RunMonitorScreen(Screen[None]):
    BINDINGS = [
        ("escape", "back", "back"),
        ("r", "start_full", "run"),
        ("g", "start_generate", "generate"),
        ("t", "start_smoke", "smoke"),
        ("c", "cancel", "cancel"),
        ("enter", "model_detail", "detail"),
        ("u", "publish_draft", "publish draft"),
        ("l", "publish_live", "publish live"),
    ]

    def __init__(self, mode: str = "full", auto_start: bool = False, resume_run_id: str | None = None):
        super().__init__()
        self.mode = mode
        self.auto_start = auto_start
        self.resume_run_id = resume_run_id
        self.running = False
        self.model_status: dict[str, dict[str, Any]] = {}
        self.monitor_phase = "idle"
        self.spent_this_run: float = 0.0

    def compose(self) -> ComposeResult:
        yield Static("Run Monitor", classes="screen-title")
        with Vertical(classes="panel compact"):
            yield Static("Configure before start", id="monitor-summary")
            with Horizontal(classes="toolbar monitor-actions"):
                yield Button("Run", id="start-full", variant="primary")
                yield Button("Generate", id="start-generate")
                yield Button("Smoke", id="start-smoke")
                yield Button("Retry", id="retry-failed")
                yield Button("Cancel", id="cancel-run")
            with Horizontal(classes="toolbar monitor-actions"):
                yield Button("Publish draft", id="publish-draft")
                yield Button("Publish live", id="publish-live")
                yield Button("Back", id="back")
        with Horizontal(id="progress-row", classes="panel compact"):
            yield ProgressBar(total=100, id="monitor-progress")
            yield Static("idle", id="monitor-status")
        yield DataTable(id="monitor-model-table")
        yield RichLog(id="run-log", wrap=True, highlight=True)
        yield Footer()

    @property
    def app_ref(self) -> ManimBenchApp:
        return self.app  # type: ignore[return-value]

    def on_mount(self) -> None:
        self._configure_model_table()
        self._update_summary()
        if self.auto_start:
            self.start(self.mode)

    def _configure_model_table(self) -> None:
        table = self.query_one("#monitor-model-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_column("Model", width=22)
        table.add_column("Status", width=14)
        table.add_column("Task", width=52)
        table.add_column("Cost", width=12)
        for model in self.app_ref.ui_state.selected_models:
            self.model_status.setdefault(model, _new_monitor_state())
        self._render_model_status()

    def _render_model_status(self) -> None:
        table = self.query_one("#monitor-model-table", DataTable)
        table.clear(columns=False)
        for model, state in sorted(self.model_status.items()):
            cost = state.get("cost", 0.0)
            table.add_row(model, str(state.get("status", "ready")), _monitor_task_text(state), f"${cost:.4f}" if cost else "-", key=model)

    def _update_summary(self) -> None:
        ui = self.app_ref.ui_state
        prefix = f"Resume: {self.resume_run_id} | " if self.resume_run_id else ""
        force = "force rerun" if ui.force_rerun or not ui.skip_complete else "skip complete"
        self.query_one("#monitor-summary", Static).update(
            f"{prefix}Selected: {len(ui.selected_models)} models | parallel {ui.default_parallel} | "
            f"reasoning {display_reasoning_effort(ui.reasoning_effort)} | {force} | output {ui.output_dir}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-full":
            self.start("full")
        elif event.button.id == "start-generate":
            self.start("generate")
        elif event.button.id == "start-smoke":
            self.start("smoke")
        elif event.button.id == "retry-failed":
            self.retry_failed()
        elif event.button.id == "cancel-run":
            self.action_cancel()
        elif event.button.id == "publish-draft":
            self.action_publish_draft()
        elif event.button.id == "publish-live":
            self.action_publish_live()
        elif event.button.id == "back":
            self.action_back()

    def action_start_full(self) -> None:
        self.start("full")

    def action_start_generate(self) -> None:
        self.start("generate")

    def action_start_smoke(self) -> None:
        self.start("smoke")

    def action_cancel(self) -> None:
        orchestrator.cancel()
        self.app_ref.notify_event("Cancelled", "Cancellation requested.", severity="warning")
        self.query_one("#monitor-status", Static).update("cancelling")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_publish_draft(self) -> None:
        self.app.push_screen(PublishScreen(initial_target="draft"))

    def action_publish_live(self) -> None:
        self.app.push_screen(PublishScreen(initial_target="live"))

    def action_model_detail(self) -> None:
        model_id = self._selected_model()
        if model_id:
            self.app.push_screen(ModelDetailScreen(model_id))

    def _selected_model(self) -> str | None:
        table = self.query_one("#monitor-model-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            return _key_value(table.coordinate_to_cell_key(table.cursor_coordinate).row_key)
        except Exception:
            return None

    def retry_failed(self) -> None:
        if self.running:
            return
        ui = self.app_ref.ui_state
        run_id = self.resume_run_id or ui.last_run_id
        if not run_id:
            self.app_ref.notify_event("Retry blocked", "No previous run is selected.", severity="warning")
            return
        self.running = True
        self.query_one("#monitor-status", Static).update("retrying failed")
        self.query_one("#run-log", RichLog).write(f"Retrying failed tasks from {run_id}", scroll_end=True)

        def callback(event: PipelineEvent) -> None:
            self.app_ref.call_threadsafe(self._handle_event, event)

        def work() -> None:
            try:
                result = orchestrator.retry_failed(
                    RetryFailedRequest(
                        previous_run_dir=ui.runs_path / run_id,
                        models=ui.selected_models or None,
                        output_dir=ui.output_path,
                        runs_dir=ui.runs_path,
                        parallel=ui.default_parallel,
                        container_image=ui.docker_image,
                        event_callback=callback,
                    )
                )
                self.app_ref.call_threadsafe(self._handle_result, result.run_id, result.ok, False)
            except Exception as error:
                self.app_ref.call_threadsafe(self._handle_error, error)

        self.app_ref.start_background(work)

    def start(self, mode: str) -> None:
        if self.running:
            return
        ui = self.app_ref.ui_state
        if not ui.selected_models:
            self.app_ref.notify_event("Run blocked", "Select at least one model.", severity="warning")
            return
        self.running = True
        self.mode = mode
        self.query_one("#monitor-status", Static).update(f"{mode} running")
        self.query_one("#run-log", RichLog).write(f"Starting {mode} pipeline", scroll_end=True)

        def callback(event: PipelineEvent) -> None:
            self.app_ref.call_threadsafe(self._handle_event, event)

        def work() -> None:
            try:
                result = orchestrator.run_pipeline(
                    PipelineRequest(
                        models=ui.selected_models,
                        mode=mode,
                        output_dir=ui.output_path,
                        runs_dir=ui.runs_path,
                        run_id=self.resume_run_id,
                        force=ui.force_rerun or not ui.skip_complete,
                        resume=True,
                        parallel=ui.default_parallel,
                        container_image=ui.docker_image,
                        reasoning_effort=ui.reasoning_effort,
                        event_callback=callback,
                    )
                )
                self.app_ref.call_threadsafe(self._handle_result, result.run_id, result.ok, result.cancelled)
            except Exception as error:
                self.app_ref.call_threadsafe(self._handle_error, error)

        self.app_ref.start_background(work)

    def _handle_event(self, event: PipelineEvent) -> None:
        log = self.query_one("#run-log", RichLog)
        line = event.message
        if event.model and event.task_id:
            line = f"{event.model} / {event.task_id}: {event.message}"
        log.write(line, scroll_end=True)
        if event.type == "pipeline_started" and event.data.get("run_id"):
            run_id = str(event.data["run_id"])
            self.resume_run_id = run_id
            self.app_ref.ui_state.last_run_id = run_id
            self.app_ref.persist()
            self._update_summary()
        if event.type == "generation_started":
            self._reset_monitor_phase("generation", event.data.get("models"))
        elif event.type == "render_started":
            self._reset_monitor_phase("render", event.data.get("models"))
        if event.model:
            row = self.model_status.setdefault(event.model, _new_monitor_state())
            if event.type == "progress":
                row["done"] = event.data.get("completed", row.get("done", 0))
                row["total"] = event.data.get("total", row.get("total", 0))
            elif event.type == "model_progress":
                row["done"] = event.data.get("completed", row.get("done", 0))
                row["total"] = event.data.get("total", row.get("total", 0))
                row["status"] = _monitor_status_text(row)
            else:
                _update_monitor_row(row, event, self.monitor_phase)
                if event.cost_usd is not None:
                    row["cost"] = float(row.get("cost", 0.0)) + event.cost_usd
                    self.spent_this_run += event.cost_usd
            self._render_model_status()
        if event.progress is not None:
            self.query_one("#monitor-progress", ProgressBar).update(progress=int(event.progress * 100))
        if event.status:
            status = event.status
            if self.spent_this_run:
                status = f"{event.status} | spent ${self.spent_this_run:.4f}"
            self.query_one("#monitor-status", Static).update(status)

    def _handle_result(self, run_id: str, ok: bool, cancelled: bool) -> None:
        self.running = False
        self.app_ref.ui_state.last_run_id = run_id
        self.app_ref.persist()
        status = "cancelled" if cancelled else "complete" if ok else "failed"
        self.query_one("#monitor-status", Static).update(status)
        self.app_ref.notify_event("Run finished", f"{run_id}: {status}", severity="information" if ok else "warning", os_level=True)

    def _handle_error(self, error: Exception) -> None:
        self.running = False
        self.query_one("#monitor-status", Static).update("failed")
        self.query_one("#run-log", RichLog).write(f"Run failed: {error}", scroll_end=True)
        self.app_ref.notify_event("Run failed", str(error), severity="error", os_level=True)

    def _reset_monitor_phase(self, phase: str, models: Any = None) -> None:
        self.monitor_phase = phase
        model_ids = [str(model) for model in models] if isinstance(models, list) else list(self.model_status)
        if not model_ids:
            model_ids = list(self.app_ref.ui_state.selected_models)
        for model in model_ids:
            previous = self.model_status.get(model, {})
            cost = float(previous.get("cost", 0.0) or 0.0)
            state = _new_monitor_state(status="generating" if phase == "generation" else "rendering")
            state["phase"] = phase
            state["cost"] = cost
            self.model_status[model] = state
        self._render_model_status()


class ModelDetailScreen(Screen[None]):
    BINDINGS = [("escape", "back", "back"), ("p", "preview", "preview")]

    def __init__(self, model_id: str):
        super().__init__()
        self.model_id = model_id

    def compose(self) -> ComposeResult:
        yield Static(f"Model Detail: {self.model_id}", classes="screen-title")
        yield DataTable(id="task-table")
        yield RichLog(id="detail-log", wrap=True, highlight=True)
        yield Footer()

    @property
    def app_ref(self) -> ManimBenchApp:
        return self.app  # type: ignore[return-value]

    def on_mount(self) -> None:
        ui = self.app_ref.ui_state
        detail = orchestrator.get_model_detail_state(
            self.model_id,
            run_id=ui.last_run_id,
            output_dir=ui.output_path,
            runs_dir=ui.runs_path,
        )
        table = self.query_one("#task-table", DataTable)
        table.add_column("Task", width=34)
        table.add_column("Output", width=12)
        table.add_column("Render", width=12)
        table.add_column("Score", width=10)
        table.add_column("Reason", width=18)
        table.add_column("Cost", width=12)
        table.add_column("Source", width=46)
        table.add_column("Video", width=46)
        for task in detail.tasks:
            table.add_row(
                task.task_id,
                task.output_status,
                task.render_status,
                str(task.score),
                _task_failure_reason(task.result_path),
                f"${task.cost_usd:.4f}" if task.cost_usd is not None else "-",
                str(task.source_path),
                str(task.video_path or "-"),
            )
        self.query_one("#detail-log", RichLog).write(f"Provider: {detail.default_provider}", scroll_end=True)
        self.query_one("#detail-log", RichLog).write(f"OpenRouter: {detail.openrouter_slug or 'n/a'}", scroll_end=True)
        if detail.usage_path:
            self.query_one("#detail-log", RichLog).write(f"Usage: {detail.usage_path}", scroll_end=True)

    def action_preview(self) -> None:
        self.app.push_screen(VideoPreviewScreen(self.app_ref.ui_state.last_run_id, self.model_id))

    def action_back(self) -> None:
        self.app.pop_screen()


class VideoPreviewScreen(Screen[None]):
    BINDINGS = [("escape", "back", "back"), ("o", "open_selected", "open")]

    def __init__(self, run_id: str | None, model_id: str | None = None):
        super().__init__()
        self.run_id = run_id
        self.model_id = model_id
        self.paths: list[Path] = []

    def compose(self) -> ComposeResult:
        yield Static("Video Preview", classes="screen-title")
        yield DataTable(id="video-table")
        with Horizontal(classes="panel compact"):
            yield Button("Open", id="open-video", variant="primary")
            yield Button("Back", id="back")
        yield Footer()

    @property
    def app_ref(self) -> ManimBenchApp:
        return self.app  # type: ignore[return-value]

    def on_mount(self) -> None:
        table = self.query_one("#video-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Model", width=24)
        table.add_column("Task", width=36)
        table.add_column("Score", width=10)
        table.add_column("Duration", width=12)
        table.add_column("Video path", width=80)
        if not self.run_id:
            return
        state = orchestrator.get_video_preview_state(self.run_id, runs_dir=self.app_ref.ui_state.runs_path, model_id=self.model_id)
        for row in state.rows:
            path = row.video_path
            self.paths.append(path)
            table.add_row(row.model, row.task_id, str(row.score), str(row.duration or "-"), str(path), key=str(len(self.paths) - 1))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-video":
            self.action_open_selected()
        elif event.button.id == "back":
            self.action_back()

    def action_open_selected(self) -> None:
        table = self.query_one("#video-table", DataTable)
        if table.row_count == 0:
            return
        try:
            row_key = _key_value(table.coordinate_to_cell_key(table.cursor_coordinate).row_key)
            path = self.paths[int(row_key)]
        except Exception:
            return
        _open_external(path)

    def action_back(self) -> None:
        self.app.pop_screen()


class PublishScreen(Screen[None]):
    BINDINGS = [("escape", "back", "back"), ("p", "publish", "publish")]

    def __init__(self, initial_target: str = "draft"):
        super().__init__()
        self.initial_target = initial_target if initial_target in {"draft", "live"} else "draft"

    def compose(self) -> ComposeResult:
        yield Static("Publish", classes="screen-title")
        with Vertical(classes="panel compact"):
            with Horizontal(classes="form-row"):
                yield Label("Target")
                yield Select([("Draft", "draft"), ("Live", "live")], id="publish-target", allow_blank=False, value=self.initial_target)
            yield Checkbox("Allow partial live publish", id="allow-partial")
            yield Static("", id="publish-check")
            with Horizontal(classes="toolbar"):
                yield Button("Publish", id="publish-run", variant="primary")
                yield Button("Back", id="back")
        yield RichLog(id="publish-log", wrap=True, highlight=True)
        yield Footer()

    @property
    def app_ref(self) -> ManimBenchApp:
        return self.app  # type: ignore[return-value]

    def on_mount(self) -> None:
        self._update_check()

    def _update_check(self) -> None:
        ui = self.app_ref.ui_state
        summary = orchestrator.get_publish_summary(ui.last_run_id, runs_dir=ui.runs_path)
        target = self.query_one("#publish-target", Select).value
        allow = self.query_one("#allow-partial", Checkbox).value
        complete = summary.complete
        has_run = summary.run_dir is not None
        disabled = not has_run or (target == "live" and not complete and not allow)
        self.query_one("#publish-run", Button).disabled = disabled
        text = "No run selected"
        if summary.run_id:
            if not has_run:
                text = f"Run {summary.run_id}: no render results found. Rerun full to create render results before publishing."
            else:
                spend = f"${summary.cost_usd:.4f}" if summary.cost_usd is not None else "unavailable"
                estimate = f"${summary.estimated_usd:.4f}" if summary.estimated_usd is not None else "unavailable"
                digest = summary.docker_digest or "missing"
                text = (
                    f"Run {summary.run_id}: {summary.status} | suite {summary.suite_id or '-'} {summary.suite_version or ''} | "
                    f"models {summary.model_count} | tasks {summary.task_count} | pass {summary.passed} fail {summary.failed} missing {summary.missing} | "
                    f"est {estimate} actual {spend} | docker {digest}"
                )
                if disabled:
                    text += " | live disabled until partial override is checked"
        self.query_one("#publish-check", Static).update(text)

    def on_select_changed(self, event: Select.Changed) -> None:
        self._update_check()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._update_check()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "publish-run":
            self.action_publish()
        elif event.button.id == "back":
            self.action_back()

    def action_publish(self) -> None:
        ui = self.app_ref.ui_state
        if not ui.last_run_id:
            self.app_ref.notify_event("Publish blocked", "No run selected.", severity="warning")
            return
        target = str(self.query_one("#publish-target", Select).value)
        allow = bool(self.query_one("#allow-partial", Checkbox).value)
        summary = orchestrator.get_publish_summary(ui.last_run_id, runs_dir=ui.runs_path)
        if summary.run_dir is None:
            self.app_ref.notify_event(
                "Publish blocked",
                f"No render results found for {ui.last_run_id}. Rerun full to create render results before publishing.",
                severity="warning",
            )
            return
        if target == "live" and not summary.complete and not allow:
            self.app_ref.notify_event("Publish blocked", "Live publish requires a complete run or partial override.", severity="warning")
            return
        log = self.query_one("#publish-log", RichLog)
        log.write(f"Publishing {ui.last_run_id} to {target}", scroll_end=True)

        def work() -> None:
            try:
                result = orchestrator.publish(
                    PublishRequest(
                        run_dir=ui.runs_path / str(ui.last_run_id),
                        target=target,
                        site_repo=ui.site_repo_path,
                        allow_partial=allow,
                        draft_branch=ui.draft_branch,
                        live_branch=ui.live_branch,
                    )
                )
                self.app_ref.call_threadsafe(log.write, f"Published to {result.branch} at {result.site_repo}", scroll_end=True)
                self.app_ref.call_threadsafe(self.app_ref.notify_event, "Publish complete", f"{result.target} on {result.branch}", os_level=True)
            except Exception as error:
                self.app_ref.call_threadsafe(log.write, f"Publish failed: {error}", scroll_end=True)
                self.app_ref.call_threadsafe(self.app_ref.notify_event, "Publish failed", str(error), severity="error")

        self.app_ref.start_background(work)

    def action_back(self) -> None:
        self.app.pop_screen()


class SettingsScreen(Screen[None]):
    BINDINGS = [("escape", "back", "back"), ("ctrl+s", "save", "save")]

    def compose(self) -> ComposeResult:
        yield Static("Settings", classes="screen-title")
        with Vertical(classes="panel"):
            with Horizontal(classes="form-row"):
                yield Label("OpenRouter key env")
                yield Input(id="openrouter-env")
            with Horizontal(classes="form-row"):
                yield Label("GitHub token env")
                yield Input(id="github-token-env")
            with Horizontal(classes="form-row"):
                yield Label("GitHub repo")
                yield Input(id="github-repo")
            with Horizontal(classes="form-row"):
                yield Label("Draft branch")
                yield Input(id="draft-branch")
            with Horizontal(classes="form-row"):
                yield Label("Live branch")
                yield Input(id="live-branch")
            with Horizontal(classes="form-row"):
                yield Label("Cloudflare hook env")
                yield Input(id="cloudflare-hook-env")
            with Horizontal(classes="form-row"):
                yield Label("Docker image")
                yield Input(id="docker-image")
            with Horizontal(classes="form-row"):
                yield Label("Output dir")
                yield Input(id="output-dir")
            with Horizontal(classes="form-row"):
                yield Label("Runs dir")
                yield Input(id="runs-dir")
            with Horizontal(classes="form-row"):
                yield Label("Site repo")
                yield Input(id="site-repo")
            with Horizontal(classes="form-row"):
                yield Label("Parallelism")
                yield Input(id="parallel")
            with Horizontal(classes="form-row"):
                yield Label("Spend warning USD")
                yield Input(id="spend-warning")
            with Horizontal(classes="form-row"):
                yield Label("Reasoning effort")
                yield Select(_reasoning_options(), id="settings-reasoning-effort", allow_blank=False, value="default")
            yield Checkbox("Skip complete outputs by default", id="settings-skip-complete")
            yield Checkbox("Force rerun by default", id="settings-force-rerun")
            yield Checkbox("Fetch OpenRouter model metadata", id="settings-catalog")
            yield Static("", id="env-status")
            with Horizontal(classes="toolbar"):
                yield Button("Save settings", id="save-settings", variant="primary")
                yield Button("Back", id="back")
        yield Footer()

    @property
    def app_ref(self) -> ManimBenchApp:
        return self.app  # type: ignore[return-value]

    def on_mount(self) -> None:
        ui = self.app_ref.ui_state
        self.query_one("#openrouter-env", Input).value = ui.env_var_names.get("openrouter", "OPENROUTER_API_KEY")
        self.query_one("#github-token-env", Input).value = ui.github_token_env
        self.query_one("#github-repo", Input).value = ui.github_repo
        self.query_one("#draft-branch", Input).value = ui.draft_branch
        self.query_one("#live-branch", Input).value = ui.live_branch
        self.query_one("#cloudflare-hook-env", Input).value = ui.cloudflare_deploy_hook_env
        self.query_one("#docker-image", Input).value = ui.docker_image
        self.query_one("#output-dir", Input).value = ui.output_dir
        self.query_one("#runs-dir", Input).value = ui.runs_dir
        self.query_one("#site-repo", Input).value = ui.site_repo
        self.query_one("#parallel", Input).value = str(ui.default_parallel)
        self.query_one("#spend-warning", Input).value = str(ui.spend_warning_usd)
        self.query_one("#settings-reasoning-effort", Select).value = ui.reasoning_effort
        self.query_one("#settings-skip-complete", Checkbox).value = ui.skip_complete
        self.query_one("#settings-force-rerun", Checkbox).value = ui.force_rerun
        self.query_one("#settings-catalog", Checkbox).value = ui.openrouter_catalog_enabled
        rows = []
        envs = {**ui.env_var_names, "github": ui.github_token_env, "cloudflare": ui.cloudflare_deploy_hook_env}
        for provider, env_name in sorted(envs.items()):
            rows.append(f"{provider}: {env_name} {_format_env_status(os.getenv(env_name))}")
        self.query_one("#env-status", Static).update("\n".join(rows))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-settings":
            self.action_save()
        elif event.button.id == "back":
            self.action_back()

    def action_save(self) -> None:
        ui = self.app_ref.ui_state
        ui.env_var_names["openrouter"] = self.query_one("#openrouter-env", Input).value
        ui.github_token_env = self.query_one("#github-token-env", Input).value
        ui.github_repo = self.query_one("#github-repo", Input).value
        ui.draft_branch = self.query_one("#draft-branch", Input).value
        ui.live_branch = self.query_one("#live-branch", Input).value
        ui.cloudflare_deploy_hook_env = self.query_one("#cloudflare-hook-env", Input).value
        ui.docker_image = self.query_one("#docker-image", Input).value
        ui.output_dir = self.query_one("#output-dir", Input).value
        ui.runs_dir = self.query_one("#runs-dir", Input).value
        ui.site_repo = self.query_one("#site-repo", Input).value
        ui.default_parallel = _safe_int(self.query_one("#parallel", Input).value, 1)
        ui.spend_warning_usd = _safe_float(self.query_one("#spend-warning", Input).value, 25.0)
        ui.reasoning_effort = stored_reasoning_effort(str(self.query_one("#settings-reasoning-effort", Select).value))
        ui.skip_complete = bool(self.query_one("#settings-skip-complete", Checkbox).value)
        ui.force_rerun = bool(self.query_one("#settings-force-rerun", Checkbox).value)
        ui.openrouter_catalog_enabled = bool(self.query_one("#settings-catalog", Checkbox).value)
        path = ui.save()
        self.app_ref.notify_event("Settings saved", str(path))

    def action_back(self) -> None:
        self.app.pop_screen()


class RunHistoryScreen(Screen[None]):
    BINDINGS = [("escape", "back", "back"), ("enter", "open_run", "open"), ("r", "resume", "resume")]

    def compose(self) -> ComposeResult:
        yield Static("Run History", classes="screen-title")
        yield DataTable(id="history-table")
        with Horizontal(classes="panel compact"):
            yield Button("Open", id="open-run", variant="primary")
            yield Button("Resume", id="resume-run")
            yield Button("Back", id="back")
        yield Footer()

    @property
    def app_ref(self) -> ManimBenchApp:
        return self.app  # type: ignore[return-value]

    def on_mount(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Run", width=30)
        table.add_column("Status", width=12)
        table.add_column("Spend", width=12)
        table.add_column("Pass rate", width=12)
        table.add_column("Updated", width=32)
        table.add_column("Models", width=10)
        table.add_column("Model ids", width=36)
        for summary in orchestrator.list_run_history(runs_dir=self.app_ref.ui_state.runs_path):
            spend = f"${summary.cost_usd:.2f}" if summary.cost_usd is not None else "-"
            total = summary.passed + summary.failed + summary.missing
            pass_rate = f"{(summary.passed / total) * 100:.0f}%" if total else "-"
            table.add_row(
                summary.run_id,
                summary.status,
                spend,
                pass_rate,
                summary.updated_at or "",
                str(len(summary.models)),
                ", ".join(summary.models),
                key=summary.run_id,
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-run":
            self.action_open_run()
        elif event.button.id == "resume-run":
            self.action_resume()
        elif event.button.id == "back":
            self.action_back()

    def action_open_run(self) -> None:
        run_id = self._selected_run()
        if not run_id:
            return
        self.app_ref.ui_state.last_run_id = run_id
        self.app_ref.persist()
        self.app.push_screen(RunMonitorScreen(mode="full", auto_start=False, resume_run_id=run_id))

    def action_resume(self) -> None:
        run_id = self._selected_run()
        if not run_id:
            return
        self.app_ref.ui_state.last_run_id = run_id
        self.app_ref.persist()
        self.app.push_screen(RunMonitorScreen(mode="generate", auto_start=False, resume_run_id=run_id))

    def _selected_run(self) -> str | None:
        table = self.query_one("#history-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            return _key_value(table.coordinate_to_cell_key(table.cursor_coordinate).row_key)
        except Exception:
            return None

    def action_back(self) -> None:
        self.app.pop_screen()


def _format_context(value: int | None) -> str:
    if value is None:
        return "-"
    if value >= 1_000_000:
        return f"{value // 1_000_000}M"
    if value >= 1_000:
        return f"{value // 1_000}K"
    return str(value)


def _format_pricing(pricing: dict[str, Any]) -> str:
    input_rate = pricing.get("input_usd_per_1m_tokens")
    output_rate = pricing.get("output_usd_per_1m_tokens")
    if input_rate is None or output_rate is None:
        return "-"
    return f"${input_rate} / ${output_rate} MTok"


def _dashboard_sort_key(sort_mode: str):
    def key(row: dict[str, Any]):
        output_rate = _optional_catalog_float(row["pricing"].get("output_usd_per_1m_tokens"))
        context = row.get("context_window")
        if sort_mode == "newest":
            return (-int(row.get("created") or 0), str(row["provider"]), str(row["display_name"]).lower())
        if sort_mode == "price":
            return (output_rate is None, output_rate or 0.0, str(row["provider"]), str(row["display_name"]).lower())
        if sort_mode == "context":
            return (context is None, int(context or 0), str(row["provider"]), str(row["display_name"]).lower())
        if sort_mode == "params":
            return (str(row.get("params") or ""), str(row["provider"]), str(row["display_name"]).lower())
        if sort_mode == "name":
            return (str(row["display_name"]).lower(), str(row["provider"]))
        return (str(row["provider"]), str(row["display_name"]).lower())

    return key


def _matches_context_value(context_window: int | None, value: str) -> bool:
    if value in {"", "all"}:
        return True
    if context_window is None:
        return value == "unknown"
    if value == "short":
        return context_window < 64_000
    if value == "medium":
        return 64_000 <= context_window < 200_000
    if value == "long":
        return context_window >= 200_000
    return True


def _matches_price_value(pricing: dict[str, Any], value: str) -> bool:
    if value in {"", "all"}:
        return True
    input_rate = _optional_catalog_float(pricing.get("input_usd_per_1m_tokens"))
    output_rate = _optional_catalog_float(pricing.get("output_usd_per_1m_tokens"))
    if input_rate is None or output_rate is None:
        return value == "unknown"
    blended = input_rate + output_rate
    if value == "low":
        return blended <= 5
    if value == "mid":
        return 5 < blended <= 25
    if value == "high":
        return blended > 25
    return True


def _fast_output_status(model_id: str, task_ids: list[str], output_dir: Path) -> str:
    if not task_ids:
        return "missing"
    existing = sum(1 for task_id in task_ids if (output_dir / model_id / f"{task_id}.py").exists())
    if existing == len(task_ids):
        return "complete"
    if existing:
        return "incomplete"
    return "missing"


def _candidate_provider(candidate: ModelCandidate) -> str:
    return candidate.openrouter_slug.split("/", 1)[0] if "/" in candidate.openrouter_slug else candidate.provider_family


def _latest_candidates_by_provider(candidates: list[ModelCandidate]) -> list[ModelCandidate]:
    latest: dict[str, ModelCandidate] = {}
    for candidate in candidates:
        provider = _candidate_provider(candidate)
        existing = latest.get(provider)
        if existing is None or int(candidate.created or 0) > int(existing.created or 0):
            latest[provider] = candidate
    return list(latest.values())


def _format_catalog_params(candidate: ModelCandidate) -> str:
    params = {str(param) for param in candidate.supported_parameters}
    labels = []
    if "reasoning" in params:
        labels.append("reasoning")
    if "max_tokens" in params or "max_completion_tokens" in params:
        labels.append("max tokens")
    return ", ".join(labels) if labels else "-"


def _optional_catalog_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status_for_monitor(event: PipelineEvent) -> str:
    if event.status == "skipped":
        return "skipped"
    if event.status in {"pass", "fail", "partial", "failed", "cancelled"}:
        return str(event.status)
    if event.type == "task_started":
        if "render" in event.message.lower():
            return "rendering"
        return "generating"
    if event.type == "task_finished":
        return "pass" if event.status == "pass" else "ready"
    if event.type == "task_failed":
        return "fail"
    return str(event.status or "ready")


def _new_monitor_state(status: str = "ready") -> dict[str, Any]:
    return {
        "status": status,
        "task": "-",
        "cost": 0.0,
        "done": 0,
        "total": 0,
        "phase": "idle",
        "passed": 0,
        "failed": 0,
        "generated": 0,
        "skipped": 0,
        "cancelled": 0,
        "failure_reasons": {},
        "seen_tasks": set(),
    }


def _update_monitor_row(state: dict[str, Any], event: PipelineEvent, phase: str) -> None:
    state["phase"] = phase
    if event.task_id:
        state["task"] = event.task_id
    if event.type == "task_started":
        state["status"] = _status_for_monitor(event)
        return
    if event.status != "skipped" and event.type not in {"task_finished", "task_failed", "task_cancelled"}:
        state["status"] = _status_for_monitor(event)
        return
    if not _mark_monitor_task_done(state, event.task_id):
        state["status"] = _monitor_status_text(state)
        return
    if event.type == "task_cancelled" or event.status == "cancelled":
        state["cancelled"] = int(state.get("cancelled") or 0) + 1
    elif event.status == "pass":
        state["passed"] = int(state.get("passed") or 0) + 1
    elif event.status == "complete" and phase == "generation":
        state["generated"] = int(state.get("generated") or 0) + 1
    elif event.status == "skipped":
        _record_skipped_monitor_outcome(state, event, phase)
    elif event.type == "task_failed" or event.status in {"fail", "failed", "partial"}:
        _record_monitor_failure(state, _monitor_failure_reason(event, phase))
    else:
        state["generated"] = int(state.get("generated") or 0) + 1
    state["status"] = _monitor_status_text(state)


def _record_skipped_monitor_outcome(state: dict[str, Any], event: PipelineEvent, phase: str) -> None:
    if phase == "render":
        reason = _monitor_result_reason(event)
        if reason == "pass":
            state["passed"] = int(state.get("passed") or 0) + 1
            return
        if reason:
            _record_monitor_failure(state, reason)
            return
    state["skipped"] = int(state.get("skipped") or 0) + 1


def _record_monitor_failure(state: dict[str, Any], reason: str) -> None:
    state["failed"] = int(state.get("failed") or 0) + 1
    reasons = state.setdefault("failure_reasons", {})
    if isinstance(reasons, dict):
        reasons[reason] = int(reasons.get(reason) or 0) + 1


def _monitor_status_text(state: dict[str, Any]) -> str:
    phase = str(state.get("phase") or "idle")
    done = int(state.get("done") or 0)
    total = int(state.get("total") or 0)
    denominator = total or done
    failed = int(state.get("failed") or 0)
    passed = int(state.get("passed") or 0)
    cancelled = int(state.get("cancelled") or 0)
    skipped = int(state.get("skipped") or 0)
    if failed:
        prefix = "gen fail" if phase == "generation" else "fail"
        return f"{prefix} {failed}/{denominator}" if denominator else prefix
    if cancelled:
        return f"cancelled {cancelled}/{denominator}" if denominator else "cancelled"
    if phase == "render":
        if passed and denominator:
            return f"pass {passed}/{denominator}"
        return "rendering"
    if phase == "generation":
        if done and denominator:
            if skipped == done:
                return f"skipped {done}/{denominator}"
            return f"generated {done}/{denominator}"
        return "generating"
    if skipped and denominator:
        return f"skipped {skipped}/{denominator}"
    return str(state.get("status") or "ready")


def _monitor_task_text(state: dict[str, Any]) -> str:
    task = str(state.get("task") or "-")
    done = int(state.get("done") or 0)
    total = int(state.get("total") or 0)
    reasons = _monitor_reason_text(state)
    parts: list[str] = []
    if total:
        parts.append(f"{done}/{total}")
    elif done:
        parts.append(f"{done} done")
    if task and task != "-":
        parts.append(task)
    if reasons:
        parts.append(f"failures: {reasons}")
    return " | ".join(parts) if parts else "-"


def _monitor_reason_text(state: dict[str, Any]) -> str:
    reasons = state.get("failure_reasons", {})
    if not isinstance(reasons, dict) or not reasons:
        return ""
    ranked = sorted(((str(reason), int(count)) for reason, count in reasons.items()), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{reason} {count}" for reason, count in ranked[:3])


def _mark_monitor_task_done(state: dict[str, Any], task_id: str | None) -> bool:
    if not task_id:
        return False
    seen = state.setdefault("seen_tasks", set())
    if isinstance(seen, set) and task_id not in seen:
        seen.add(task_id)
        state["done"] = int(state.get("done") or 0) + 1
        return True
    return False


def _monitor_failure_reason(event: PipelineEvent, phase: str) -> str:
    reason = _monitor_result_reason(event)
    if reason and reason != "pass":
        return reason
    message = event.message.lower()
    if "missing file-provider output" in message:
        return "missing source"
    if "render input failed" in message:
        return "render input"
    if "generation failed" in message:
        return "generation failed"
    if event.status == "partial" or phase == "generation":
        return "generation partial"
    if "rendered" in message and event.status == "fail":
        return "score fail"
    return "task fail"


def _monitor_result_reason(event: PipelineEvent) -> str | None:
    payload = _monitor_result_payload(event.path)
    if not payload:
        return None
    return _classify_monitor_result(payload)


def _monitor_result_payload(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    result_path = path if path.name == "result.json" else path / "result.json"
    if not result_path.exists():
        return None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _task_failure_reason(result_path: Path | None) -> str:
    payload = _monitor_result_payload(result_path)
    if not payload:
        return "-"
    reason = _classify_monitor_result(payload)
    return "-" if reason == "pass" else reason


def _classify_monitor_result(payload: dict[str, Any]) -> str:
    score = payload.get("score", {}) if isinstance(payload.get("score"), dict) else {}
    if score.get("passed") is True:
        return "pass"
    error = str(payload.get("error") or "")
    if "Missing file-provider output" in error:
        return "missing source"
    checks = score.get("checks", {}) if isinstance(score.get("checks"), dict) else {}
    render = payload.get("render", {}) if isinstance(payload.get("render"), dict) else {}
    if render.get("timed_out") or _check_failed(checks.get("render_not_timed_out")):
        return "timeout"
    if _render_exit_failed(render) or _check_failed(checks.get("render_exit_code")):
        return "render crash"
    if _check_failed(checks.get("media_generated")):
        return "no media"
    if _passed_field_failed(checks.get("required_source_terms")):
        return "source terms"
    if _passed_field_failed(checks.get("minimum_required_labels")):
        return "labels"
    if _passed_field_failed(checks.get("required_sections")):
        return "sections"
    if _passed_field_failed(checks.get("visual_sanity")):
        return "visual"
    if _passed_field_failed(checks.get("source_parse")):
        return "parse"
    if _check_failed(checks.get("scene_class")):
        return "scene class"
    if _passed_field_failed(checks.get("suspicious_source_patterns")):
        return "suspicious source"
    if _passed_field_failed(checks.get("duration")):
        return "duration"
    if _passed_field_failed(checks.get("fps")):
        return "fps"
    if _check_failed(checks.get("generation")):
        return "generation failed"
    return "score fail"


def _render_exit_failed(render: dict[str, Any]) -> bool:
    if not render:
        return False
    exit_code = render.get("exit_code")
    return exit_code is not None and exit_code != 0


def _check_failed(value: Any) -> bool:
    return value is False


def _passed_field_failed(value: Any) -> bool:
    return isinstance(value, dict) and value.get("passed") is False


def _key_value(row_key: Any) -> str:
    return str(getattr(row_key, "value", row_key))


def _safe_int(value: str, default: int) -> int:
    try:
        return max(1, int(value))
    except ValueError:
        return default


def _safe_float(value: str, default: float) -> float:
    try:
        return float(value)
    except ValueError:
        return default


def _format_balance_text(balance: BalanceResult) -> str:
    if balance.available:
        if balance.balance is not None:
            return f"OpenRouter ${balance.balance:.2f}"
        return "OpenRouter key ok"
    error = "unavailable"
    if balance.error:
        error = " ".join(str(balance.error).split())
        if len(error) > 52:
            error = f"{error[:49]}..."
    return f"OpenRouter {error}"


def _format_env_status(value: str | None) -> str:
    if not value:
        return "missing"
    clean = value.strip()
    if clean.startswith("crsr_"):
        return f"present (cursor-looking, len {len(clean)})"
    if clean.startswith("sk-or-"):
        return f"present (openrouter-looking, len {len(clean)})"
    if clean.startswith("sk-"):
        return f"present (generic key-looking, len {len(clean)})"
    return f"present (unknown format, len {len(clean)})"


def _reasoning_options() -> list[tuple[str, str]]:
    labels = {
        "default": "Reasoning: default",
        "minimal": "Reasoning: minimal",
        "low": "Reasoning: low",
        "medium": "Reasoning: medium",
        "high": "Reasoning: high",
        "xhigh": "Reasoning: xhigh",
        "max": "Reasoning: max",
    }
    return [(labels[effort], effort) for effort in REASONING_EFFORT_CHOICES]


def _open_external(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, str(path)])
