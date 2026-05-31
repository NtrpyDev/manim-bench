from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from manimbench.paths import (
    DEFAULT_MODEL_TESTS_DIR,
    DEFAULT_PROMPT_PATH,
    DEFAULT_REPORTS_DIR,
    DEFAULT_RUNS_DIR,
    DEFAULT_SUITE_PATH,
)
from manimbench.prompting import build_task_prompt, load_master_prompt
from manimbench.providers import FileProvider
from manimbench.reporting import summarize_models, write_report, load_results
from manimbench.runtime import ManimCERuntime
from manimbench.sandbox import ContainerSandbox, LocalSandbox
from manimbench.scoring import result_payload, score_task, source_metadata_with_hash
from manimbench.tasks import filter_tasks, load_suite, suite_hashes


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

    workspaces = subparsers.add_parser(
        "create-workspaces",
        help="Create file-backed model workspaces for AI coding agents.",
    )
    workspaces.add_argument("--task", action="append", help="Task ID to include. Repeat to include multiple tasks.")
    workspaces.add_argument("--force", action="store_true", help="Overwrite generated instructions and prompts.")
    workspaces.set_defaults(func=cmd_create_workspaces)

    compare_ready = subparsers.add_parser(
        "compare-ready",
        help="Auto-discover model_tests outputs and run a comparison for ready models.",
    )
    compare_ready.add_argument("--task", action="append", help="Task ID to compare. Repeat to include multiple tasks.")
    compare_ready.add_argument("--include-partial", action="store_true", help="Include models that have only some selected task outputs.")
    compare_ready.add_argument("--min-tasks", type=int, default=1, help="Minimum matching outputs when --include-partial is used.")
    compare_ready.add_argument("--sandbox", choices=["container", "local"], default="container")
    compare_ready.add_argument("--run-id")
    compare_ready.add_argument("--timeout-seconds", type=int, default=180)
    compare_ready.add_argument("--container-image", default="manimbench-manimce:latest")
    compare_ready.add_argument(
        "--manim-executable",
        default="python",
        help="Local sandbox renderer. Use 'python' for python -m manim, or pass a manim executable path.",
    )
    compare_ready.add_argument(
        "--strict-exit-code",
        action="store_true",
        help="Exit nonzero when any compared benchmark task fails.",
    )
    compare_ready.set_defaults(func=cmd_compare_ready)

    usage_start = subparsers.add_parser("usage-start", help="Start timing model workspace generation.")
    usage_start.add_argument("--model-dir", type=Path, default=Path.cwd())
    usage_start.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH)
    usage_start.add_argument("--force", action="store_true", help="Restart an existing usage timer.")
    usage_start.set_defaults(func=cmd_usage_start)

    usage_finish = subparsers.add_parser("usage-finish", help="Finish timing and write usage.json for a model workspace.")
    usage_finish.add_argument("--model-dir", type=Path, default=Path.cwd())
    usage_finish.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH)
    usage_finish.set_defaults(func=cmd_usage_finish)

    usage_collect = subparsers.add_parser("usage-collect", help="Collect usage.json for all model_tests folders.")
    usage_collect.add_argument("--root", type=Path, default=DEFAULT_MODEL_TESTS_DIR)
    usage_collect.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH)
    usage_collect.add_argument("--include-empty", action="store_true", help="Include model workspaces with no generated outputs.")
    usage_collect.set_defaults(func=cmd_usage_collect)

    share_video = subparsers.add_parser("share-video", help="Build final shareable MP4 videos from a run directory.")
    share_video.add_argument("--run-dir", type=Path, required=True)
    share_video.add_argument("--output-dir", type=Path, required=True)
    share_video.add_argument("--model", help="Limit the video build to one model.")
    share_video.add_argument("--max-seconds", type=int, default=120)
    share_video.set_defaults(func=cmd_share_video)

    review = subparsers.add_parser("review", help="Create and update visual review files.")
    review_subparsers = review.add_subparsers(dest="review_command", required=True)
    review_init = review_subparsers.add_parser("init", help="Initialize review.json and sample frames.")
    review_init.add_argument("--run-dir", type=Path, required=True)
    review_init.add_argument("--frames", type=int, default=6)
    review_init.add_argument("--force", action="store_true")
    review_init.set_defaults(func=cmd_review)
    review_set = review_subparsers.add_parser("set", help="Set a review status.")
    review_set.add_argument("--run-dir", type=Path, required=True)
    review_set.add_argument("--model")
    review_set.add_argument("--task")
    review_set.add_argument("--field", required=True)
    review_set.add_argument("--status", required=True, choices=["pass", "partial", "fail", "pending"])
    review_set.add_argument("--notes", default="")
    review_set.set_defaults(func=cmd_review)
    review_summary = review_subparsers.add_parser("summarize", help="Summarize visual reviews.")
    review_summary.add_argument("--run-dir", type=Path, required=True)
    review_summary.set_defaults(func=cmd_review)

    list_tasks = subparsers.add_parser("list-tasks", help="List benchmark tasks.")
    list_tasks.set_defaults(func=cmd_list_tasks)

    prompts = subparsers.add_parser("write-prompts", help="Write resolved prompts for each task.")
    prompts.add_argument("--output-dir", type=Path, required=True)
    prompts.set_defaults(func=cmd_write_prompts)

    run = subparsers.add_parser("run", help="Run a benchmark for one model.")
    run.add_argument("--model", required=True)
    run.add_argument("--provider", choices=["file"], default="file")
    run.add_argument("--outputs-dir", type=Path, required=True)
    run.add_argument("--task", action="append", help="Task ID to run. Repeat to run multiple tasks.")
    run.add_argument("--sandbox", choices=["container", "local"], default="container")
    run.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    run.add_argument("--run-id")
    run.add_argument("--timeout-seconds", type=int, default=180)
    run.add_argument("--container-image", default="manimbench-manimce:latest")
    run.add_argument("--allow-stale", action="store_true", help="Allow outputs that predate usage-start.")
    run.add_argument(
        "--manim-executable",
        default="python",
        help="Local sandbox renderer. Use 'python' for python -m manim, or pass a manim executable path.",
    )
    run.set_defaults(func=cmd_run)

    matrix = subparsers.add_parser("run-file-matrix", help="Run identical tasks for multiple file-backed models.")
    matrix.add_argument(
        "--model-output",
        action="append",
        required=True,
        metavar="MODEL=DIR",
        help="Model name and output directory. Repeat for multiple models.",
    )
    matrix.add_argument("--task", action="append", help="Task ID to run. Repeat to run multiple tasks.")
    matrix.add_argument("--sandbox", choices=["container", "local"], default="container")
    matrix.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    matrix.add_argument("--run-id")
    matrix.add_argument("--timeout-seconds", type=int, default=180)
    matrix.add_argument("--container-image", default="manimbench-manimce:latest")
    matrix.add_argument("--allow-stale", action="store_true", help="Allow outputs that predate usage-start.")
    matrix.add_argument(
        "--manim-executable",
        default="python",
        help="Local sandbox renderer. Use 'python' for python -m manim, or pass a manim executable path.",
    )
    matrix.set_defaults(func=cmd_run_file_matrix)

    render = subparsers.add_parser("render", help="Render and score one ManimCE solution file.")
    render.add_argument("--solution", type=Path, required=True)
    render.add_argument("--task-id", required=True)
    render.add_argument("--model", default="manual")
    render.add_argument("--sandbox", choices=["container", "local"], default="local")
    render.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    render.add_argument("--run-id")
    render.add_argument("--timeout-seconds", type=int, default=180)
    render.add_argument("--container-image", default="manimbench-manimce:latest")
    render.add_argument(
        "--manim-executable",
        default="python",
        help="Local sandbox renderer. Use 'python' for python -m manim, or pass a manim executable path.",
    )
    render.set_defaults(func=cmd_render)

    score = subparsers.add_parser("score", help="Aggregate existing result JSON files into a score summary.")
    score.add_argument("--run-dir", type=Path, required=True)
    score.set_defaults(func=cmd_score)

    rerun = subparsers.add_parser("rerun-failed", help="Rerun failed tasks from a previous run.")
    rerun.add_argument("--previous-run-dir", type=Path, required=True)
    rerun.add_argument("--model", required=True)
    rerun.add_argument("--provider", choices=["file"], default="file")
    rerun.add_argument("--outputs-dir", type=Path, required=True)
    rerun.add_argument("--sandbox", choices=["container", "local"], default="container")
    rerun.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    rerun.add_argument("--run-id")
    rerun.add_argument("--timeout-seconds", type=int, default=180)
    rerun.add_argument("--container-image", default="manimbench-manimce:latest")
    rerun.add_argument("--allow-stale", action="store_true", help="Allow outputs that predate usage-start.")
    rerun.add_argument(
        "--manim-executable",
        default="python",
        help="Local sandbox renderer. Use 'python' for python -m manim, or pass a manim executable path.",
    )
    rerun.set_defaults(func=cmd_rerun_failed)

    report = subparsers.add_parser("report", help="Generate a static report for a run directory.")
    report.add_argument("--run-dir", type=Path, required=True)
    report.add_argument("--output-dir", type=Path)
    report.set_defaults(func=cmd_report)

    build_site = subparsers.add_parser("build-site", help="Build a deployable static site bundle from a report.")
    build_site.add_argument("--report-dir", type=Path, required=True)
    build_site.add_argument("--output-dir", type=Path, required=True)
    build_site.add_argument("--template-dir", type=Path, help="Website template directory. Defaults to website/.")
    build_site.set_defaults(func=cmd_build_site)

    return parser


def cmd_start(args: argparse.Namespace) -> int:
    from manimbench.wizard import start_wizard

    return start_wizard(args)


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
        (args.output_dir / f"{task.id}.md").write_text(
            build_task_prompt(master_prompt, task),
            encoding="utf-8",
        )
    print(f"Wrote {len(suite.tasks)} prompts to {args.output_dir}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    master_prompt = load_master_prompt(args.prompt)
    tasks = filter_tasks(suite, args.task)
    provider = FileProvider(args.outputs_dir, args.model, allow_stale=args.allow_stale)
    sandbox = _make_sandbox(args)
    runtime = ManimCERuntime(executable=args.manim_executable)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_manifest(run_dir, run_id, suite, tasks, args, sandbox, runtime)

    failures = 0
    for task in tasks:
        task_prompt = build_task_prompt(master_prompt, task)
        try:
            output = provider.generate(task, task_prompt)
        except Exception as error:
            failures += 1
            task_run_dir = run_dir / args.model / task.id
            task_run_dir.mkdir(parents=True, exist_ok=True)
            _write_generation_error(task_run_dir, args.model, task.id, error)
            print(f"{task.id}: generation failed: {error}", file=sys.stderr)
            continue

        score = _run_one_task(
            run_dir=run_dir,
            suite=suite,
            task=task,
            model=args.model,
            source=output.source,
            source_metadata=output.metadata,
            task_prompt=task_prompt,
            sandbox=sandbox,
            runtime=runtime,
            timeout_seconds=args.timeout_seconds,
        )
        print(f"{task.id}: {'PASS' if score.passed else 'FAIL'} ({score.automated_score:.1f})")
        if not score.passed:
            failures += 1

    print(f"Run artifacts: {run_dir}")
    return 1 if failures else 0


def cmd_run_file_matrix(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    master_prompt = load_master_prompt(args.prompt)
    tasks = filter_tasks(suite, args.task)
    sandbox = _make_sandbox(args)
    runtime = ManimCERuntime(executable=args.manim_executable)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    model_outputs = [_parse_model_output(value) for value in args.model_output]
    _write_manifest(
        run_dir,
        run_id,
        suite,
        tasks,
        args,
        sandbox,
        runtime,
        models=[model for model, _ in model_outputs],
        provider="file",
    )

    failures = 0
    for model, outputs_dir in model_outputs:
        provider = FileProvider(outputs_dir, model, allow_stale=args.allow_stale)
        for task in tasks:
            task_prompt = build_task_prompt(master_prompt, task)
            try:
                output = provider.generate(task, task_prompt)
            except Exception as error:
                failures += 1
                task_run_dir = run_dir / model / task.id
                task_run_dir.mkdir(parents=True, exist_ok=True)
                _write_generation_error(task_run_dir, model, task.id, error)
                print(f"{model}/{task.id}: generation failed: {error}", file=sys.stderr)
                continue

            score = _run_one_task(
                run_dir=run_dir,
                suite=suite,
                task=task,
                model=model,
                source=output.source,
                source_metadata=output.metadata,
                task_prompt=task_prompt,
                sandbox=sandbox,
                runtime=runtime,
                timeout_seconds=args.timeout_seconds,
            )
            print(f"{model}/{task.id}: {'PASS' if score.passed else 'FAIL'} ({score.automated_score:.1f})")
            if not score.passed:
                failures += 1

    print(f"Run artifacts: {run_dir}")
    return 1 if failures else 0


def cmd_render(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    master_prompt = load_master_prompt(args.prompt)
    tasks = filter_tasks(suite, [args.task_id])
    task = tasks[0]
    sandbox = _make_sandbox(args)
    runtime = ManimCERuntime(executable=args.manim_executable)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(run_dir, run_id, suite, tasks, args, sandbox, runtime)

    source = args.solution.read_text(encoding="utf-8")
    score = _run_one_task(
        run_dir=run_dir,
        suite=suite,
        task=task,
        model=args.model,
        source=source,
        source_metadata={"provider": "manual", "source_path": str(args.solution)},
        task_prompt=build_task_prompt(master_prompt, task),
        sandbox=sandbox,
        runtime=runtime,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"{task.id}: {'PASS' if score.passed else 'FAIL'} ({score.automated_score:.1f})")
    print(f"Run artifacts: {run_dir}")
    return 0 if score.passed else 1


def cmd_score(args: argparse.Namespace) -> int:
    results = load_results(args.run_dir)
    summaries = summarize_models(results)
    output_path = args.run_dir / "score-summary.json"
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
    output_dir = args.output_dir or (DEFAULT_REPORTS_DIR / args.run_dir.name)
    index = write_report(args.run_dir, output_dir)
    print(f"Wrote report: {index}")
    return 0


def cmd_build_site(args: argparse.Namespace) -> int:
    from manimbench.site import build_site

    return build_site(args)


def _make_sandbox(args: argparse.Namespace):
    if args.sandbox == "local":
        return LocalSandbox()
    return ContainerSandbox(image=args.container_image)


def _write_manifest(
    run_dir: Path,
    run_id: str,
    suite,
    tasks,
    args: argparse.Namespace,
    sandbox,
    runtime: ManimCERuntime,
    models: list[str] | None = None,
    provider: str | None = None,
) -> None:
    manifest = {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite": {
            "id": suite.id,
            "version": suite.version,
            "title": suite.title,
            "task_count": len(tasks),
            "task_ids": [task.id for task in tasks],
        },
        "hashes": suite_hashes(suite, args.prompt),
        "model": getattr(args, "model", None),
        "models": models or ([getattr(args, "model")] if getattr(args, "model", None) else []),
        "provider": provider or getattr(args, "provider", "manual"),
        "runtime": runtime.metadata(),
        "sandbox": {"name": sandbox.name, "official": sandbox.official},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _parse_model_output(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("--model-output must be in MODEL=DIR format")
    model, directory = value.split("=", 1)
    if not model.strip() or not directory.strip():
        raise ValueError("--model-output must include a non-empty model and directory")
    return model.strip(), Path(directory).expanduser()


def _run_one_task(
    run_dir: Path,
    suite,
    task,
    model: str,
    source: str,
    source_metadata: dict,
    task_prompt: str,
    sandbox,
    runtime: ManimCERuntime,
    timeout_seconds: int,
):
    task_run_dir = run_dir / model / task.id
    task_run_dir.mkdir(parents=True, exist_ok=True)
    (task_run_dir / "prompt.md").write_text(task_prompt, encoding="utf-8")
    solution_path = task_run_dir / "solution.py"
    solution_path.write_text(source, encoding="utf-8")
    render = sandbox.render(
        run_dir=task_run_dir,
        solution_path=solution_path,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        fps=int(suite.runtime.get("fps", 60)),
        scene_class=str(suite.runtime.get("scene_class", "MainScene")),
    )
    score = score_task(task, model, source, render, task_run_dir)
    payload = result_payload(task, model, source_metadata_with_hash(source_metadata, source), render, score)
    (task_run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return score


def _write_generation_error(run_dir: Path, model: str, task_id: str, error: Exception) -> None:
    payload = {
        "schema_version": "0.1.0",
        "model": model,
        "task": {"id": task_id},
        "error": repr(error),
        "score": {
            "task_id": task_id,
            "model": model,
            "passed": False,
            "automated_score": 0,
            "checks": {"generation": False},
            "rubric": {},
            "artifacts": {},
        },
    }
    (run_dir / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
