from __future__ import annotations

import argparse
import sys
from pathlib import Path

from manimbench.orchestrator import (
    GenerateBatchRequest,
    GenerateRequest,
    PublishRequest,
    RenderInput,
    RenderMatrixRequest,
    ReportRequest,
    generate,
    generate_batch,
    list_models,
    publish,
    render_matrix,
    render_one_file,
    report,
)
from manimbench.paths import (
    DEFAULT_MODEL_TESTS_DIR,
    DEFAULT_OUTPUTS_DIR,
    DEFAULT_PROMPT_PATH,
    DEFAULT_RUNS_DIR,
    DEFAULT_SITE_REPO,
    DEFAULT_SUITE_PATH,
)
from manimbench.prompting import build_task_prompt, load_master_prompt
from manimbench.reporting import load_results, summarize_models
from manimbench.tasks import load_suite


PROVIDERS = ["auto", "openrouter", "cursor", "openai", "anthropic", "google", "xai"]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manimbench")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT_PATH)
    subparsers = parser.add_subparsers(required=True)

    start = subparsers.add_parser("start", help="Launch an interactive benchmark runner.")
    start.set_defaults(func=cmd_start)

    list_models_cmd = subparsers.add_parser("list-models", help="List configured benchmark models.")
    list_models_cmd.add_argument("--public", action="store_true", help="Only list public models.")
    list_models_cmd.set_defaults(func=cmd_list_models)

    workspaces = subparsers.add_parser("create-workspaces", help="Create file-backed model workspaces.")
    workspaces.add_argument("--model", action="append", help="Model ID to create. Repeat for multiple models.")
    workspaces.add_argument("--task", action="append", help="Task ID to include. Repeat to include multiple tasks.")
    workspaces.add_argument("--force", action="store_true", help="Overwrite generated instructions and prompts.")
    workspaces.set_defaults(func=cmd_create_workspaces)

    compare_ready = subparsers.add_parser("compare-ready", help="Discover ready file-backed outputs and compare them.")
    compare_ready.add_argument("--task", action="append", help="Task ID to compare. Repeat to include multiple tasks.")
    compare_ready.add_argument("--include-partial", action="store_true")
    compare_ready.add_argument("--min-tasks", type=int, default=1)
    compare_ready.add_argument("--sandbox", choices=["container", "local"], default="container")
    compare_ready.add_argument("--run-id")
    compare_ready.add_argument("--timeout-seconds", type=int, default=180)
    compare_ready.add_argument("--container-image", default="manimbench-manimce:latest")
    compare_ready.add_argument("--manim-executable", default="python")
    compare_ready.add_argument("--parallel", type=int, default=1)
    compare_ready.add_argument("--strict-exit-code", action="store_true")
    compare_ready.set_defaults(func=cmd_compare_ready)

    usage_start = subparsers.add_parser("usage-start", help="Start timing model workspace generation.")
    usage_start.add_argument("--model-dir", type=Path, default=Path.cwd())
    usage_start.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH)
    usage_start.add_argument("--force", action="store_true")
    usage_start.set_defaults(func=cmd_usage_start)

    usage_finish = subparsers.add_parser("usage-finish", help="Finish timing and write usage.json for a model workspace.")
    usage_finish.add_argument("--model-dir", type=Path, default=Path.cwd())
    usage_finish.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH)
    usage_finish.set_defaults(func=cmd_usage_finish)

    usage_collect = subparsers.add_parser("usage-collect", help="Collect usage.json for all model_tests folders.")
    usage_collect.add_argument("--root", type=Path, default=DEFAULT_MODEL_TESTS_DIR)
    usage_collect.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH)
    usage_collect.add_argument("--include-empty", action="store_true")
    usage_collect.set_defaults(func=cmd_usage_collect)

    share_video = subparsers.add_parser("share-video", help="Build final shareable MP4 videos from a run directory.")
    share_video.add_argument("--run-dir", type=Path, required=True)
    share_video.add_argument("--output-dir", type=Path, required=True)
    share_video.add_argument("--model")
    share_video.add_argument("--max-seconds", type=int, default=120)
    share_video.set_defaults(func=cmd_share_video)

    review = subparsers.add_parser("review", help="Create and update visual review files.")
    review_subparsers = review.add_subparsers(dest="review_command", required=True)
    review_init = review_subparsers.add_parser("init")
    review_init.add_argument("--run-dir", type=Path, required=True)
    review_init.add_argument("--frames", type=int, default=6)
    review_init.add_argument("--force", action="store_true")
    review_init.set_defaults(func=cmd_review)
    review_set = review_subparsers.add_parser("set")
    review_set.add_argument("--run-dir", type=Path, required=True)
    review_set.add_argument("--model")
    review_set.add_argument("--task")
    review_set.add_argument("--field", required=True)
    review_set.add_argument("--status", required=True, choices=["pass", "partial", "fail", "pending"])
    review_set.add_argument("--notes", default="")
    review_set.set_defaults(func=cmd_review)
    review_summary = review_subparsers.add_parser("summarize")
    review_summary.add_argument("--run-dir", type=Path, required=True)
    review_summary.set_defaults(func=cmd_review)

    list_tasks = subparsers.add_parser("list-tasks", help="List benchmark tasks.")
    list_tasks.set_defaults(func=cmd_list_tasks)

    prompts = subparsers.add_parser("write-prompts", help="Write resolved prompts for each task.")
    prompts.add_argument("--output-dir", type=Path, required=True)
    prompts.set_defaults(func=cmd_write_prompts)

    generate_cmd = subparsers.add_parser("generate", help="Generate outputs for one API-backed model.")
    generate_cmd.add_argument("--model", required=True)
    generate_cmd.add_argument("--task", action="append")
    generate_cmd.add_argument("--parallel", type=int, default=1)
    generate_cmd.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUTS_DIR)
    generate_cmd.add_argument("--provider", choices=PROVIDERS, default="auto")
    generate_cmd.add_argument("--force", action="store_true")
    generate_cmd.add_argument("--smoke", action="store_true")
    generate_cmd.add_argument("--run-id")
    generate_cmd.set_defaults(func=cmd_generate)

    batch_cmd = subparsers.add_parser("generate-batch", help="Generate outputs for multiple API-backed models.")
    batch_cmd.add_argument("--models", required=True, help="Comma-separated model IDs.")
    batch_cmd.add_argument("--task", action="append")
    batch_cmd.add_argument("--dry-run", action="store_true")
    batch_cmd.add_argument("--parallel", type=int, default=1)
    batch_cmd.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUTS_DIR)
    batch_cmd.add_argument("--provider", choices=PROVIDERS, default="auto")
    batch_cmd.add_argument("--force", action="store_true")
    batch_cmd.add_argument("--smoke", action="store_true")
    batch_cmd.add_argument("--run-id")
    batch_cmd.set_defaults(func=cmd_generate_batch)

    run = subparsers.add_parser("run", help="Run a benchmark for one file-backed model.")
    run.add_argument("--model", required=True)
    run.add_argument("--provider", choices=["file"], default="file")
    run.add_argument("--outputs-dir", type=Path, required=True)
    _add_render_args(run)
    run.set_defaults(func=cmd_run)

    matrix = subparsers.add_parser("run-file-matrix", help="Run identical tasks for multiple file-backed models.")
    matrix.add_argument("--model-output", action="append", required=True, metavar="MODEL=DIR")
    _add_render_args(matrix)
    matrix.set_defaults(func=cmd_run_file_matrix)

    render = subparsers.add_parser("render", help="Render and score one ManimCE solution file.")
    render.add_argument("--solution", type=Path, required=True)
    render.add_argument("--task-id", required=True)
    render.add_argument("--model", default="manual")
    _add_render_args(render, include_tasks=False, default_sandbox="local")
    render.set_defaults(func=cmd_render)

    score = subparsers.add_parser("score", help="Aggregate existing result JSON files into a score summary.")
    score.add_argument("--run-dir", type=Path, required=True)
    score.set_defaults(func=cmd_score)

    rerun = subparsers.add_parser("rerun-failed", help="Rerun failed tasks from a previous run.")
    rerun.add_argument("--previous-run-dir", type=Path, required=True)
    rerun.add_argument("--model", required=True)
    rerun.add_argument("--provider", choices=["file"], default="file")
    rerun.add_argument("--outputs-dir", type=Path, required=True)
    _add_render_args(rerun)
    rerun.set_defaults(func=cmd_rerun_failed)

    report_cmd = subparsers.add_parser("report", help="Generate a static report for a run directory.")
    report_cmd.add_argument("--run-dir", type=Path, required=True)
    report_cmd.add_argument("--output-dir", type=Path)
    report_cmd.set_defaults(func=cmd_report)

    publish_cmd = subparsers.add_parser("publish", help="Publish report data and videos to the site repository.")
    publish_cmd.add_argument("--run-dir", type=Path, required=True)
    publish_cmd.add_argument("--target", choices=["draft", "live"], required=True)
    publish_cmd.add_argument("--site-repo", type=Path)
    publish_cmd.add_argument("--allow-partial", action="store_true")
    publish_cmd.set_defaults(func=cmd_publish)

    return parser


def _add_render_args(parser: argparse.ArgumentParser, include_tasks: bool = True, default_sandbox: str = "container") -> None:
    if include_tasks:
        parser.add_argument("--task", action="append", help="Task ID to run. Repeat to run multiple tasks.")
    parser.add_argument("--sandbox", choices=["container", "local"], default=default_sandbox)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--run-id")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--container-image", default="manimbench-manimce:latest")
    parser.add_argument("--allow-stale", action="store_true")
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--manim-executable", default="python")


def cmd_start(args: argparse.Namespace) -> int:
    from manimbench.wizard import start_wizard

    return start_wizard(args)


def cmd_list_models(args: argparse.Namespace) -> int:
    for row in list_models(public=True):
        print(f"{row['id']}\t{row['display_name']}\t{row.get('default_provider') or ''}\t{row.get('openrouter_slug') or ''}")
    return 0


def cmd_create_workspaces(args: argparse.Namespace) -> int:
    from manimbench.workspaces import create_model_workspaces

    return create_model_workspaces(args)


def cmd_compare_ready(args: argparse.Namespace) -> int:
    from manimbench.comparison import run_auto_comparison

    return run_auto_comparison(args)


def cmd_usage_start(args: argparse.Namespace) -> int:
    from manimbench.usage import start_usage

    return start_usage(args)


def cmd_usage_finish(args: argparse.Namespace) -> int:
    from manimbench.usage import finish_usage

    return finish_usage(args)


def cmd_usage_collect(args: argparse.Namespace) -> int:
    from manimbench.usage import collect_all_usage

    return collect_all_usage(args)


def cmd_share_video(args: argparse.Namespace) -> int:
    from manimbench.share_video import build_share_videos

    return build_share_videos(args)


def cmd_review(args: argparse.Namespace) -> int:
    from manimbench.visual_review import init_reviews, set_review, summarize_reviews

    if args.review_command == "init":
        return init_reviews(args)
    if args.review_command == "set":
        return set_review(args)
    if args.review_command == "summarize":
        return summarize_reviews(args)
    raise ValueError(f"Unknown review command: {args.review_command}")


def cmd_list_tasks(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    for task in suite.tasks:
        domains = ", ".join(task.domains)
        print(f"{task.id}\t{task.difficulty}\t{domains}\t{task.title}")
    return 0


def cmd_write_prompts(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    master_prompt = load_master_prompt(args.prompt)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for task in suite.tasks:
        (args.output_dir / f"{task.id}.md").write_text(build_task_prompt(master_prompt, task), encoding="utf-8")
    print(f"Wrote {len(suite.tasks)} prompts to {args.output_dir}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    result = generate(
        GenerateRequest(
            model=args.model,
            suite_path=args.suite,
            prompt_path=args.prompt,
            task_ids=args.task,
            output_dir=args.output_dir,
            provider=args.provider,
            force=args.force,
            smoke=args.smoke,
            parallel=args.parallel,
            run_id=args.run_id,
        )
    )
    _print_generation_result(result)
    return 0 if result.ok else 1


def cmd_generate_batch(args: argparse.Namespace) -> int:
    result = generate_batch(
        GenerateBatchRequest(
            models=[item.strip() for item in args.models.split(",") if item.strip()],
            suite_path=args.suite,
            prompt_path=args.prompt,
            task_ids=args.task,
            output_dir=args.output_dir,
            provider=args.provider,
            force=args.force,
            smoke=args.smoke,
            dry_run=args.dry_run,
            parallel=args.parallel,
            run_id=args.run_id,
        )
    )
    _print_generation_result(result)
    return 0 if result.ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    request = _render_request(args, [RenderInput(args.model, args.outputs_dir)])
    result = render_matrix(request)
    print(f"Run artifacts: {result.run_dir}")
    return 0 if result.ok else 1


def cmd_run_file_matrix(args: argparse.Namespace) -> int:
    request = _render_request(args, [_parse_model_output(value) for value in args.model_output])
    result = render_matrix(request)
    print(f"Run artifacts: {result.run_dir}")
    return 0 if result.ok else 1


def cmd_render(args: argparse.Namespace) -> int:
    result = render_one_file(
        solution_path=args.solution,
        task_id=args.task_id,
        model=args.model,
        suite_path=args.suite,
        prompt_path=args.prompt,
        sandbox_name=args.sandbox,
        runs_dir=args.runs_dir,
        run_id=args.run_id,
        timeout_seconds=args.timeout_seconds,
        container_image=args.container_image,
        manim_executable=args.manim_executable,
    )
    print(f"Run artifacts: {result.run_dir}")
    return 0 if result.ok else 1


def cmd_score(args: argparse.Namespace) -> int:
    results = load_results(args.run_dir)
    summaries = summarize_models(results)
    output_path = args.run_dir / "score-summary.json"
    import json

    output_path.write_text(json.dumps({"models": summaries}, indent=2), encoding="utf-8")
    print(f"Wrote score summary: {output_path}")
    for summary in summaries:
        print(f"{summary['model']}\t{summary['avg_score']:.1f}\t{summary['pass_rate']:.1f}%")
    return 0


def cmd_rerun_failed(args: argparse.Namespace) -> int:
    failed = [
        result["task"]["id"]
        for result in load_results(args.previous_run_dir)
        if result.get("model") == args.model and not result.get("score", {}).get("passed")
    ]
    if not failed:
        print(f"No failed tasks found for {args.model} in {args.previous_run_dir}")
        return 0
    args.task = sorted(set(failed))
    return cmd_run(args)


def cmd_report(args: argparse.Namespace) -> int:
    result = report(ReportRequest(run_dir=args.run_dir, output_dir=args.output_dir))
    print(f"Wrote report: {result.index_path}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    request = PublishRequest(
        run_dir=args.run_dir,
        target=args.target,
        site_repo=args.site_repo if args.site_repo else DEFAULT_SITE_REPO,
        allow_partial=args.allow_partial,
    )
    result = publish(request)
    pushed = "pushed" if result.pushed else "committed locally"
    print(f"Published {result.target} bundle to {result.site_repo} on {result.branch} ({pushed}).")
    if result.target == "draft":
        print("Expected preview target: Cloudflare Pages draft branch preview for branch 'draft'.")
    return 0


def _render_request(args: argparse.Namespace, model_outputs: list[RenderInput]) -> RenderMatrixRequest:
    return RenderMatrixRequest(
        model_outputs=model_outputs,
        suite_path=args.suite,
        prompt_path=args.prompt,
        task_ids=getattr(args, "task", None),
        sandbox=args.sandbox,
        runs_dir=args.runs_dir,
        run_id=args.run_id,
        timeout_seconds=args.timeout_seconds,
        container_image=args.container_image,
        manim_executable=args.manim_executable,
        allow_stale=args.allow_stale,
        parallel=args.parallel,
    )


def _parse_model_output(value: str) -> RenderInput:
    if "=" not in value:
        raise ValueError("--model-output must be in MODEL=DIR format")
    model, directory = value.split("=", 1)
    if not model.strip() or not directory.strip():
        raise ValueError("--model-output must include a non-empty model and directory")
    return RenderInput(model.strip(), Path(directory).expanduser())


def _print_generation_result(result) -> None:
    if result.dry_run:
        for item in result.dry_run:
            print(f"{item['model']}/{item['task_id']}\t{item['status']}\t{item['path']}")
    for path in result.skipped:
        print(f"skipped complete: {path}")
    for path in result.generated:
        print(f"generated: {path}")
    for error in result.failed:
        print(f"failed: {error['model']}/{error['task_id']}: {error['error']}", file=sys.stderr)
    print(f"Generation state: {result.state_path}")
    print(f"API log: {result.api_log_path}")


if __name__ == "__main__":
    raise SystemExit(main())
