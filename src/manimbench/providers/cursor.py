from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from manimbench.model_registry import provider_config
from manimbench.models import ModelOutput, Task
from manimbench.providers.common import ProviderError, cleanup_generated_source, metadata_payload, validate_main_scene


Runner = Callable[..., subprocess.CompletedProcess[str]]


class CursorProvider:
    """Run generation through Cursor Agent CLI.

    Cursor does not expose Composer as an OpenRouter/chat-completions model.
    The supported automation path is Cursor's authenticated local/headless
    agent CLI, which can use models included in the operator's Cursor plan.
    """

    provider_name = "cursor"
    route = "cursor-agent"

    def __init__(
        self,
        model_id: str,
        *,
        model_slug: str | None = None,
        api_key: str | None = None,
        runner: Runner | None = None,
        timeout_seconds: int = 900,
        command: str | None = None,
        cwd: Path | None = None,
    ):
        config = provider_config("cursor")
        model_names = config.get("model_names", {})
        if not isinstance(model_names, dict):
            model_names = {}
        self.model_id = model_id
        self.model_slug = model_slug or str(model_names.get(model_id, model_id))
        self.api_key_env = str(config.get("env_key", "CURSOR_API_KEY"))
        self.api_key = api_key or os.getenv(self.api_key_env)
        self.command = command or os.getenv("MANIMBENCH_CURSOR_AGENT") or str(config.get("command", "cursor-agent"))
        self.timeout_seconds = timeout_seconds
        self.runner = runner or subprocess.run
        self.cwd = cwd

    def generate(self, task: Task, prompt: str) -> ModelOutput:
        started = time.monotonic()
        request_id = f"cursor-{uuid.uuid4()}"
        command = [
            self.command,
            "-p",
            "--trust",
            "--output-format",
            "text",
            "--model",
            self.model_slug,
            self._prompt(prompt),
        ]
        env = os.environ.copy()
        if self.api_key:
            env[self.api_key_env] = self.api_key
        try:
            completed = self.runner(
                command,
                cwd=str(self.cwd) if self.cwd else None,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as error:
            raise ProviderError(
                f"Cursor Agent CLI not found: {self.command}. Install it with `curl https://cursor.com/install -fsSL | bash`."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ProviderError(f"Cursor Agent timed out after {self.timeout_seconds}s") from error

        elapsed = time.monotonic() - started
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode != 0:
            detail = (stderr or stdout).strip()
            raise ProviderError(f"Cursor Agent failed with exit code {completed.returncode}: {detail}")

        source = cleanup_generated_source(stdout)
        metadata = metadata_payload(
            provider=self.provider_name,
            route=self.route,
            model_id=self.model_id,
            model_slug=self.model_slug,
            task_id=task.id,
            request_id=request_id,
            response_model=self.model_slug,
            finish_reason="stop",
            elapsed_seconds=elapsed,
            usage={
                "exit_code": completed.returncode,
                "stderr": stderr.strip(),
                "auth": "api_key" if self.api_key else "cursor_login",
            },
        )
        validate_main_scene(source, metadata=metadata)
        return ModelOutput(model=self.model_id, task_id=task.id, source=source, metadata=metadata)

    @staticmethod
    def _prompt(prompt: str) -> str:
        return (
            "Generate exactly one ManimBench solution for the task below.\n"
            "Print only complete Python source code to stdout. Do not edit files, run shell commands, or explain.\n"
            "The source must import `from manim import *` and define `class MainScene(Scene)`.\n\n"
            f"{prompt}"
        )
