from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from manimbench.paths import DEFAULT_PROMPT_PATH, DEFAULT_REPORTS_DIR, DEFAULT_RUNS_DIR, DEFAULT_SUITE_PATH, PROJECT_ROOT
from manimbench.orchestrator import RenderInput, RenderMatrixRequest, ReportRequest, render_matrix, report
from manimbench.reporting import load_results, summarize_models
from manimbench.tasks import filter_tasks, load_suite


MODEL_TESTS_ROOT = PROJECT_ROOT / "model_tests"


def run_auto_comparison(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite or DEFAULT_SUITE_PATH)
    tasks = filter_tasks(suite, args.task)
    required_ids = {task.id for task in tasks}
    models = discover_ready_models(required_ids, include_partial=args.include_partial, min_tasks=args.min_tasks)

    if not models:
        print("No model workspaces have enough generated outputs to compare yet.")
        print(f"Looked under: {MODEL_TESTS_ROOT}")
        return 1

    print("Models selected for comparison:")
    for model, path, count in models:
        completeness = "complete" if count == len(required_ids) else f"{count}/{len(required_ids)} tasks"
        print(f"  - {model}: {completeness}")

    run_id = args.run_id or datetime.now(timezone.utc).strftime("comparison-%Y%m%dT%H%M%SZ")
    result = render_matrix(
        RenderMatrixRequest(
            suite_path=args.suite or DEFAULT_SUITE_PATH,
            prompt_path=DEFAULT_PROMPT_PATH,
            model_outputs=[RenderInput(model, path) for model, path, _ in models],
            task_ids=args.task,
            sandbox=args.sandbox,
            runs_dir=DEFAULT_RUNS_DIR,
            run_id=run_id,
            timeout_seconds=args.timeout_seconds,
            container_image=args.container_image,
            manim_executable=args.manim_executable,
            allow_stale=True,
            parallel=getattr(args, "parallel", 1),
        )
    )
    benchmark_exit_code = 0 if result.ok else 1
    run_dir = DEFAULT_RUNS_DIR / run_id
    report_dir = DEFAULT_REPORTS_DIR / run_id
    _write_score_summary(run_dir)
    _init_review(run_dir)
    _build_share_videos(run_dir, report_dir)
    report(ReportRequest(run_dir=run_dir, output_dir=report_dir))

    print()
    print(f"Comparison run: {run_dir}")
    print(f"Comparison report: {report_dir / 'index.html'}")
    if benchmark_exit_code and not args.strict_exit_code:
        print("Some benchmark tasks failed; this is captured in the report.")
        return 0
    return benchmark_exit_code


def discover_ready_models(
    required_task_ids: set[str],
    include_partial: bool = False,
    min_tasks: int = 1,
) -> list[tuple[str, Path, int]]:
    discovered: list[tuple[str, Path, int]] = []
    if not MODEL_TESTS_ROOT.exists():
        return discovered

    for model_dir in sorted(path for path in MODEL_TESTS_ROOT.iterdir() if path.is_dir()):
        outputs_dir = model_dir / "outputs"
        if not outputs_dir.exists():
            continue
        output_ids = {path.stem for path in outputs_dir.glob("*.py")}
        matching = output_ids & required_task_ids
        if include_partial:
            if len(matching) >= min_tasks:
                discovered.append((model_dir.name, outputs_dir, len(matching)))
        elif required_task_ids <= output_ids:
            discovered.append((model_dir.name, outputs_dir, len(required_task_ids)))
    return discovered


def _write_score_summary(run_dir: Path) -> None:
    import json

    summaries = summarize_models(load_results(run_dir))
    (run_dir / "score-summary.json").write_text(json.dumps({"models": summaries}, indent=2), encoding="utf-8")


def _init_review(run_dir: Path) -> None:
    from manimbench.visual_review import init_reviews

    init_reviews(argparse.Namespace(review_command="init", run_dir=run_dir, frames=6, force=True))


def _build_share_videos(run_dir: Path, report_dir: Path) -> None:
    from manimbench.share_video import build_share_videos

    build_share_videos(argparse.Namespace(run_dir=run_dir, output_dir=report_dir / "videos", model=None, max_seconds=120))
