"""The whole benchmark in one call: generate, render, judge, report."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from manimbench.generation import GenerateRequest, GenerateResult, generate
from manimbench.judging import JudgeOutcome, JudgeRequest, judge_run
from manimbench.paths import DEFAULT_OUTPUTS_DIR, DEFAULT_PROMPT_PATH, DEFAULT_REPORTS_DIR, DEFAULT_RUNS_DIR, DEFAULT_SUITE_PATH
from manimbench.providers.base import RouteDisabledError
from manimbench.rendering import RenderOutcome, RenderRequest, new_run_id, render
from manimbench.reporting import write_report


@dataclass(frozen=True)
class PipelineRequest:
    models: list[str]
    suite_path: Path = DEFAULT_SUITE_PATH
    prompt_path: Path = DEFAULT_PROMPT_PATH
    task_ids: list[str] | None = None
    outputs_dir: Path = DEFAULT_OUTPUTS_DIR
    runs_dir: Path = DEFAULT_RUNS_DIR
    reports_dir: Path = DEFAULT_REPORTS_DIR
    run_id: str | None = None
    route: str | None = None
    samples: int | None = None
    parallel: int = 1
    force: bool = False
    skip_generate: bool = False
    skip_judge: bool = False
    quality: str | None = None
    fps: int | None = None
    timeout_seconds: int | None = None
    on_event: Callable[[str], None] | None = None
    generate_route_factory: Callable | None = None
    judge_route_factory: Callable | None = None
    sandbox: object | None = None


@dataclass
class PipelineResult:
    run_id: str
    generation: GenerateResult | None
    render: RenderOutcome
    judge: JudgeOutcome | None
    judge_skipped_reason: str | None
    report_index: Path

    @property
    def ok(self) -> bool:
        return (
            (self.generation is None or self.generation.ok)
            and self.render.ok
            and self.judge is not None
            and self.judge.ok
        )


def run_all(request: PipelineRequest) -> PipelineResult:
    say = request.on_event or (lambda _message: None)
    run_id = request.run_id or new_run_id()

    generation = None
    if not request.skip_generate:
        say("Step 1 of 4: generating answers")
        generation = generate(
            GenerateRequest(
                models=request.models,
                suite_path=request.suite_path,
                prompt_path=request.prompt_path,
                task_ids=request.task_ids,
                output_dir=request.outputs_dir,
                route=request.route,
                samples=request.samples,
                force=request.force,
                parallel=request.parallel,
                route_factory=request.generate_route_factory,
                sandbox_settings=getattr(request.sandbox, "settings", None),
                on_event=say,
            )
        )
    say("Step 2 of 4: rendering and measuring")
    rendered = render(
        RenderRequest(
            models=request.models,
            suite_path=request.suite_path,
            prompt_path=request.prompt_path,
            task_ids=request.task_ids,
            outputs_dir=request.outputs_dir,
            runs_dir=request.runs_dir,
            run_id=run_id,
            samples=request.samples,
            parallel=request.parallel,
            force=request.force,
            quality=request.quality,
            fps=request.fps,
            timeout_seconds=request.timeout_seconds,
            sandbox=request.sandbox,
            on_event=say,
        )
    )
    judged = None
    reason = None
    if request.skip_judge:
        reason = "judging was skipped on request"
    else:
        say("Step 3 of 4: judging")
        try:
            judged = judge_run(
                JudgeRequest(
                    run_dir=rendered.run_dir,
                    suite_path=request.suite_path,
                    parallel=request.parallel,
                    route_factory=request.judge_route_factory,
                    on_event=say,
                )
            )
        except RouteDisabledError as error:
            reason = str(error)
            say(f"Judging did not run: {reason}")
    say("Step 4 of 4: writing the report")
    index = write_report(rendered.run_dir, request.reports_dir / run_id, request.suite_path)
    return PipelineResult(run_id, generation, rendered, judged, reason, index)
