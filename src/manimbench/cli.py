"""The ``manimbench`` command line."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from manimbench.paths import (
    DEFAULT_OUTPUTS_DIR,
    DEFAULT_PROMPT_PATH,
    DEFAULT_REPORTS_DIR,
    DEFAULT_RUNS_DIR,
    DEFAULT_SITE_REPO,
    DEFAULT_SUITE_PATH,
)

QUALITIES = ["l", "m", "h", "p", "k"]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as error:
        message = error.args[0] if isinstance(error, KeyError) and error.args else error
        print(f"error: {message}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manimbench", description="Benchmark how well AI models teach mathematics with Manim."
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE_PATH, help="Suite file to use.")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT_PATH, help="Shared prompt file.")
    commands = parser.add_subparsers(title="commands")

    run = commands.add_parser("run", help="Generate, render, judge and report in one go.")
    _models_argument(run)
    _selection_arguments(run)
    run.add_argument("--route", help="Route for generation. Default: the default route in models/routes.yaml.")
    run.add_argument("--run-id")
    run.add_argument("--parallel", type=int, default=1)
    run.add_argument("--force", action="store_true", help="Ask and render again even where results exist.")
    run.add_argument("--skip-generate", action="store_true", help="Use the answers already in the outputs folder.")
    run.add_argument("--skip-judge", action="store_true")
    _render_arguments(run)
    _folder_arguments(run)
    run.set_defaults(func=cmd_run)

    generate = commands.add_parser("generate", help="Ask models for answers and save them.")
    _models_argument(generate)
    _selection_arguments(generate)
    generate.add_argument("--route")
    generate.add_argument("--parallel", type=int, default=1)
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--dry-run", action="store_true", help="Show what would be asked without asking.")
    generate.add_argument("--outputs-dir", type=Path, default=DEFAULT_OUTPUTS_DIR)
    generate.set_defaults(func=cmd_generate)

    render = commands.add_parser("render", help="Render saved answers in the sandbox and measure them.")
    _models_argument(render)
    _selection_arguments(render)
    render.add_argument("--run-id")
    render.add_argument("--parallel", type=int, default=1)
    render.add_argument("--force", action="store_true")
    render.add_argument("--allow-stale", action="store_true", help="Render answers written for an older prompt.")
    _render_arguments(render)
    render.add_argument("--outputs-dir", type=Path, default=DEFAULT_OUTPUTS_DIR)
    render.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    render.set_defaults(func=cmd_render)

    judge = commands.add_parser("judge", help="Send a rendered run to the judge panel.")
    judge.add_argument("--run-dir", type=Path, required=True)
    judge.add_argument("--parallel", type=int, default=1)
    judge.add_argument("--force", action="store_true")
    judge.set_defaults(func=cmd_judge)

    report = commands.add_parser("report", help="Write the report for a run.")
    report.add_argument("--run-dir", type=Path, required=True)
    report.add_argument("--output-dir", type=Path)
    report.set_defaults(func=cmd_report)

    check = commands.add_parser("check", help="Render and measure one scene file. No model is called.")
    check.add_argument("file", type=Path)
    check.add_argument("--task", required=True)
    check.add_argument("--out", type=Path, help="Folder to keep the render in. Default: a temporary folder.")
    _render_arguments(check)
    check.set_defaults(func=cmd_check)

    tasks = commands.add_parser("tasks", help="List the tasks in the suite.")
    tasks.set_defaults(func=cmd_tasks)

    prompt = commands.add_parser("prompt", help="Print the exact prompt a model gets for a task.")
    prompt.add_argument("--task", required=True)
    prompt.set_defaults(func=cmd_prompt)

    models = commands.add_parser("models", help="List models, or check them against OpenRouter's catalog.")
    models.add_argument("action", nargs="?", choices=["list", "check"], default="list")
    models.set_defaults(func=cmd_models)

    sandbox = commands.add_parser("sandbox", help="Show, pull or update the pinned Manim image.")
    sandbox.add_argument("action", choices=["info", "pull", "update"])
    sandbox.add_argument("version", nargs="?", help="Manim version for update, like 0.22.1.")
    sandbox.set_defaults(func=cmd_sandbox)

    review = commands.add_parser("review", help="Check the judge against a person's ratings.")
    review.add_argument("action", choices=["export", "agreement"])
    review.add_argument("--run-dir", type=Path, required=True)
    review.add_argument("--sheet", type=Path, required=True, help="CSV file to write or read.")
    review.add_argument("--limit", type=int, default=30)
    review.set_defaults(func=cmd_review)

    publish = commands.add_parser("publish", help="Copy a report into the site repository.")
    publish.add_argument("--run-dir", type=Path, required=True)
    publish.add_argument("--target", choices=["draft", "live"], required=True)
    publish.add_argument("--site-repo", type=Path, default=DEFAULT_SITE_REPO)
    publish.add_argument("--allow-incomplete", action="store_true")
    publish.set_defaults(func=cmd_publish)
    return parser


def _models_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--models", required=True, help="Comma-separated model ids from models/models.yaml.")


def _selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task", action="append", help="Task id. Repeat for several. Default: all tasks.")
    parser.add_argument("--samples", type=int, help="Samples per task. Default: the suite's setting.")


def _render_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--quality", choices=QUALITIES, help="Render quality. Anything but the suite's is not official.")
    parser.add_argument("--fps", type=int, help="Frame rate. Anything but the suite's is not official.")
    parser.add_argument("--timeout-seconds", type=int, help="Render time limit. Anything but the suite's is not official.")


def _folder_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--outputs-dir", type=Path, default=DEFAULT_OUTPUTS_DIR)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)


def _model_list(value: str) -> list[str]:
    models = [item.strip() for item in value.split(",") if item.strip()]
    if not models:
        raise ValueError("--models needs at least one model id")
    return models


def cmd_run(args: argparse.Namespace) -> int:
    from manimbench.pipeline import PipelineRequest, run_all

    result = run_all(
        PipelineRequest(
            models=_model_list(args.models),
            suite_path=args.suite,
            prompt_path=args.prompt,
            task_ids=args.task,
            outputs_dir=args.outputs_dir,
            runs_dir=args.runs_dir,
            reports_dir=args.reports_dir,
            run_id=args.run_id,
            route=args.route,
            samples=args.samples,
            parallel=args.parallel,
            force=args.force,
            skip_generate=args.skip_generate,
            skip_judge=args.skip_judge,
            quality=args.quality,
            fps=args.fps,
            timeout_seconds=args.timeout_seconds,
            on_event=print,
        )
    )
    if result.generation:
        _print_generation(result.generation)
    _print_render(result.render)
    if result.judge:
        _print_judge(result.judge)
    else:
        print(f"Not judged: {result.judge_skipped_reason}")
    print(f"Report: {result.report_index}")
    return 0 if result.ok else 1


def cmd_generate(args: argparse.Namespace) -> int:
    from manimbench.generation import GenerateRequest, generate

    result = generate(
        GenerateRequest(
            models=_model_list(args.models),
            suite_path=args.suite,
            prompt_path=args.prompt,
            task_ids=args.task,
            output_dir=args.outputs_dir,
            route=args.route,
            samples=args.samples,
            force=args.force,
            dry_run=args.dry_run,
            parallel=args.parallel,
            on_event=print,
        )
    )
    if args.dry_run:
        for item in result.planned:
            print(f"{item['model']}/{item['task_id']}/sample-{item['sample']}\t{item['status']}")
        return 0
    _print_generation(result)
    return 0 if result.ok else 1


def cmd_render(args: argparse.Namespace) -> int:
    from manimbench.rendering import RenderRequest, render

    outcome = render(
        RenderRequest(
            models=_model_list(args.models),
            suite_path=args.suite,
            prompt_path=args.prompt,
            task_ids=args.task,
            outputs_dir=args.outputs_dir,
            runs_dir=args.runs_dir,
            run_id=args.run_id,
            samples=args.samples,
            parallel=args.parallel,
            force=args.force,
            allow_stale=args.allow_stale,
            quality=args.quality,
            fps=args.fps,
            timeout_seconds=args.timeout_seconds,
            on_event=print,
        )
    )
    _print_render(outcome)
    return 0 if outcome.ok else 1


def cmd_judge(args: argparse.Namespace) -> int:
    from manimbench.judging import JudgeRequest, judge_run

    outcome = judge_run(
        JudgeRequest(run_dir=args.run_dir, suite_path=args.suite, parallel=args.parallel, force=args.force, on_event=print)
    )
    _print_judge(outcome)
    return 0 if outcome.ok else 1


def cmd_report(args: argparse.Namespace) -> int:
    from manimbench.reporting import write_report

    output_dir = args.output_dir or DEFAULT_REPORTS_DIR / args.run_dir.resolve().name
    print(f"Report: {write_report(args.run_dir, output_dir, args.suite)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from manimbench.rendering import render_sample
    from manimbench.sandbox import ContainerSandbox
    from manimbench.tasks import filter_tasks, load_suite

    suite = load_suite(args.suite)
    task = filter_tasks(suite, [args.task])[0]
    sandbox = ContainerSandbox()
    sandbox.ensure_image()
    source = args.file.read_text(encoding="utf-8")

    def run(target: Path) -> dict:
        return render_sample(
            target,
            suite,
            task,
            "check",
            1,
            source,
            None,
            sandbox,
            quality=args.quality or suite.runtime.quality,
            fps=args.fps or suite.runtime.fps,
            timeout_seconds=args.timeout_seconds or suite.runtime.render_timeout_seconds,
        )

    if args.out:
        result = run(args.out.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="manimbench-check-") as folder:
            result = run(Path(folder) / "sample")
    summary = {key: result[key] for key in ["gates", "layout", "pacing", "score"]}
    print(json.dumps(summary, indent=2))
    if not result["gates"]["passed"] and args.out:
        print(f"Render log: {args.out.resolve() / 'logs' / 'stderr.log'}", file=sys.stderr)
    return 0 if result["gates"]["passed"] else 1


def cmd_tasks(args: argparse.Namespace) -> int:
    from manimbench.tasks import load_suite

    suite = load_suite(args.suite)
    print(f"{suite.title} ({suite.id}), {suite.samples_per_task} samples per task")
    for task in suite.tasks:
        print(f"{task.id}\t{', '.join(task.domains)}\t{task.title}")
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    from manimbench.generation import task_prompts
    from manimbench.sandbox import load_sandbox_settings
    from manimbench.tasks import filter_tasks, load_suite

    suite = load_suite(args.suite)
    tasks = filter_tasks(suite, [args.task])
    print(task_prompts(suite, args.prompt, tasks, load_sandbox_settings())[args.task])
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from manimbench.registry import load_models, load_routes

    models = load_models()
    routes = load_routes()
    if args.action == "list":
        for name, config in routes["routes"].items():
            state = "on" if config.get("enabled") else "off"
            default = " (default)" if name == routes["default_route"] else ""
            print(f"route {name}: {state}{default}")
        for entry in models.values():
            print(f"{entry.id}\t{entry.name}\t{entry.vendor}\t{', '.join(sorted(entry.routes))}")
        return 0
    from manimbench.providers.openrouter import OpenRouterRoute

    catalog = {item["id"]: item for item in OpenRouterRoute().catalog().get("data", [])}
    problems = 0
    for entry in models.values():
        target = entry.routes.get("openrouter")
        if not target:
            print(f"{entry.id}\tno OpenRouter route")
            continue
        listed = catalog.get(target["model"])
        if not listed:
            problems += 1
            print(f"{entry.id}\tNOT IN CATALOG: {target['model']}")
            continue
        pricing = listed.get("pricing", {})
        rate = lambda key: float(pricing.get(key, 0)) * 1_000_000  # noqa: E731
        reasoning = listed.get("reasoning") or {}
        efforts = reasoning.get("supported_efforts") or []
        note = ""
        if entry.reasoning_effort and entry.reasoning_effort not in efforts:
            problems += 1
            note = f"\tEFFORT {entry.reasoning_effort!r} NOT SUPPORTED ({', '.join(efforts)})"
        images = "image" in ((listed.get("architecture") or {}).get("input_modalities") or [])
        print(
            f"{entry.id}\t{target['model']}\t${rate('prompt'):g} in / ${rate('completion'):g} out per million"
            f"\tdefault effort {reasoning.get('default_effort')}\t{'sees images' if images else 'text only'}{note}"
        )
    return 1 if problems else 0


def cmd_sandbox(args: argparse.Namespace) -> int:
    from manimbench.sandbox import ContainerSandbox, load_sandbox_settings
    from manimbench.sandbox.settings import update_sandbox

    if args.action == "update":
        if not args.version:
            raise ValueError("sandbox update needs a version, for example: manimbench sandbox update 0.22.1")
        settings = update_sandbox(args.version)
        print(f"Pinned Manim {settings.manim_version} at {settings.reference}")
        return 0
    settings = load_sandbox_settings()
    if args.action == "pull":
        ContainerSandbox(settings).pull()
        print(f"Pulled {settings.reference}")
        return 0
    print(f"Manim {settings.manim_version}, Python {settings.python_version}")
    print(settings.reference)
    try:
        ContainerSandbox(settings).ensure_image()
        print("Image is present on this machine.")
    except RuntimeError as error:
        print(error)
        return 1
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from manimbench import review
    from manimbench.tasks import load_suite

    suite = load_suite(args.suite)
    if args.action == "export":
        count = review.export_sheet(args.run_dir, suite, args.sheet, limit=args.limit)
        print(f"Wrote {count} samples to rate: {args.sheet}")
        print(f"Videos are numbered in {args.sheet.with_name(args.sheet.stem + '-videos')}. Do not open {review.key_path(args.sheet).name} while rating.")
        return 0
    report = review.agreement(args.run_dir, suite, review.read_sheet(args.sheet, suite))
    for criterion, row in report.items():
        print(
            f"{criterion}\tsamples {row['samples']}\trank correlation {row['spearman']}"
            f"\tmean gap {row['mean_absolute_gap']}\tjudge minus human {row['judge_minus_human']}"
        )
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from manimbench.publish import PublishRequest, publish

    result = publish(
        PublishRequest(
            run_dir=args.run_dir, target=args.target, site_repo=args.site_repo, allow_incomplete=args.allow_incomplete
        )
    )
    state = "pushed" if result.pushed else "committed locally, not pushed"
    print(f"Published {result.files} files to {result.site_repo} on branch {result.branch} ({state}).")
    return 0


def _print_generation(result) -> None:
    print(
        f"Generation via {result.route}: {len(result.generated)} new, {len(result.skipped)} already done, "
        f"{len(result.no_code)} with no code, {len(result.stale)} stale, {len(result.failed)} failed. "
        f"Reported cost ${result.cost_usd:.4f}."
    )
    for path in result.stale:
        print(f"  stale (written for a different prompt, use --force to replace): {path}")
    for item in result.failed:
        print(f"  failed: {item['model']}/{item['task_id']}/sample-{item['sample']}: {item['error']}", file=sys.stderr)


def _print_render(outcome) -> None:
    print(
        f"Run {outcome.run_id}: {len(outcome.rendered)} rendered, {len(outcome.reused)} already done, "
        f"{len(outcome.missing)} missing, {len(outcome.stale)} stale. Folder: {outcome.run_dir}"
    )
    for item in outcome.missing + outcome.stale:
        print(f"  {item['reason']}: {item['model']}/{item['task_id']}/sample-{item['sample']}")


def _print_judge(outcome) -> None:
    print(
        f"Judging: {outcome.judged} new, {outcome.reused} already done, {len(outcome.failed)} failed, "
        f"{outcome.skipped_failed_gate} samples skipped for failing a gate. Reported cost ${outcome.cost_usd:.4f}."
    )
    for item in outcome.failed:
        print(f"  failed: {item['sample']} by {item['judge']}: {item['error']}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
