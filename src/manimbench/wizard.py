from __future__ import annotations

import argparse
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from manimbench.cli import cmd_report, cmd_run_file_matrix
from manimbench.paths import DEFAULT_PROMPT_PATH, DEFAULT_REPORTS_DIR, DEFAULT_RUNS_DIR, DEFAULT_SUITE_PATH, PROJECT_ROOT
from manimbench.tasks import load_suite


SMOKE_SUITE_PATH = PROJECT_ROOT / "benchmarks" / "v0" / "suite.yaml"


def start_wizard(args: argparse.Namespace) -> int:
    print("\nManimBench Launcher")
    print("===================")
    print("This guided launcher runs saved ManimCE model outputs through ManimBench.\n")

    suite_path, task_ids = _choose_suite_and_tasks()
    suite = load_suite(suite_path)
    model_outputs = _choose_model_outputs()
    sandbox = _choose_sandbox()
    manim_executable = _choose_manim_executable(sandbox)
    container_image = "manimbench-manimce:latest"

    if sandbox == "container" and not _container_image_exists(container_image):
        if _confirm(f"Container image `{container_image}` is missing. Build it now?", default=True):
            if _build_container_image(container_image) != 0:
                print("Container image build failed. Re-run after fixing Docker.")
                return 1
        else:
            print("Cannot run official container benchmark without the sandbox image.")
            return 1

    default_run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    run_id = _prompt("Run ID", default_run_id)
    timeout_seconds = int(_prompt("Per-task timeout seconds", "180"))

    run_args = argparse.Namespace(
        suite=suite_path,
        prompt=DEFAULT_PROMPT_PATH,
        model_output=[f"{model}={path}" for model, path in model_outputs],
        task=task_ids,
        sandbox=sandbox,
        runs_dir=DEFAULT_RUNS_DIR,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        container_image=container_image,
        manim_executable=str(manim_executable),
    )

    print("\nStarting benchmark...")
    print(f"Suite: {suite.title} ({len(suite.tasks)} task definitions)")
    print(f"Selected tasks: {'all' if not task_ids else ', '.join(task_ids)}")
    print(f"Models: {', '.join(model for model, _ in model_outputs)}")
    print(f"Sandbox: {sandbox}\n")

    run_exit = cmd_run_file_matrix(run_args)
    run_dir = DEFAULT_RUNS_DIR / run_id
    report_args = argparse.Namespace(run_dir=run_dir, output_dir=DEFAULT_REPORTS_DIR / run_id)
    cmd_report(report_args)

    print("\nDone.")
    print(f"Run artifacts: {run_dir}")
    print(f"Report: {report_args.output_dir / 'index.html'}")
    if run_exit:
        print("Some tasks failed. The report still includes errors and logs.")
    return run_exit


def _choose_suite_and_tasks() -> tuple[Path, list[str] | None]:
    print("Benchmark size:")
    print("  1. Public suite (v0.4, six focused tasks)")
    print("  2. Smoke test (v0, one quick task)")
    print("  3. Public suite, choose task IDs")
    choice = _prompt("Select option", "1")
    if choice == "2":
        return SMOKE_SUITE_PATH, ["easy_pythagorean_theorem"]
    if choice == "3":
        suite = load_suite(DEFAULT_SUITE_PATH)
        print("\nAvailable public tasks:")
        for task in suite.tasks:
            print(f"  - {task.id} ({task.difficulty})")
        raw = _prompt("Task IDs, comma-separated", suite.tasks[0].id)
        return DEFAULT_SUITE_PATH, [item.strip() for item in raw.split(",") if item.strip()]
    return DEFAULT_SUITE_PATH, None


def _choose_model_outputs() -> list[tuple[str, Path]]:
    discovered = _discover_model_output_dirs()
    print("\nModel outputs:")
    if discovered:
        for index, (model, path) in enumerate(discovered, start=1):
            print(f"  {index}. {model} ({path})")
        print("  C. Custom path")
        raw = _prompt("Select model number(s), comma-separated", "1")
        if raw.strip().lower() != "c":
            selected: list[tuple[str, Path]] = []
            for item in raw.split(","):
                if not item.strip():
                    continue
                index = int(item.strip()) - 1
                selected.append(discovered[index])
            if selected:
                return selected

    model = _prompt("Model name", "my-model")
    path = Path(_prompt("Output directory path", f"sample_outputs/{model}")).expanduser()
    return [(model, path)]


def _discover_model_output_dirs() -> list[tuple[str, Path]]:
    roots = [PROJECT_ROOT / "outputs", PROJECT_ROOT / "sample_outputs", PROJECT_ROOT / "model_outputs"]
    discovered: list[tuple[str, Path]] = []
    for root in roots:
        if not root.exists():
            continue
        for child in sorted(path for path in root.iterdir() if path.is_dir()):
            if any(child.glob("*.py")):
                discovered.append((child.name, child))
    return discovered


def _choose_sandbox() -> str:
    print("\nSandbox:")
    print("  1. Container sandbox (official, Docker/Podman, network disabled)")
    print("  2. Local subprocess sandbox (development only)")
    choice = _prompt("Select option", "1")
    return "local" if choice == "2" else "container"


def _choose_manim_executable(sandbox: str) -> str:
    if sandbox == "container":
        return "python"
    return _prompt("Local Manim executable", "python")


def _container_image_exists(image: str) -> bool:
    engine = shutil.which("docker") or shutil.which("podman")
    if not engine:
        return False
    completed = subprocess.run(
        [engine, "image", "inspect", image],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _build_container_image(image: str) -> int:
    engine = shutil.which("docker") or shutil.which("podman")
    if not engine:
        print("Docker or Podman is required for the official sandbox.")
        return 1
    command = [engine, "build", "-t", image, "-f", "sandbox/Dockerfile", "."]
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def _prompt(label: str, default: str) -> str:
    try:
        value = input(f"{label} [{default}]: ").strip()
    except EOFError:
        print()
        return default
    return value or default


def _confirm(label: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    try:
        value = input(f"{label} [{suffix}]: ").strip().lower()
    except EOFError:
        print()
        return default
    if not value:
        return default
    return value in {"y", "yes"}
