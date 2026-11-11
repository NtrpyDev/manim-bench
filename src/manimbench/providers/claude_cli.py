"""Claude through the Claude Code command line, on a Claude subscription.

The CLI is an agent by default. Here it is stripped down to a plain model
call: no tools, no project files, no user settings, no memory, and our own
system prompt in place of the built-in one. It runs from an empty folder.

The flags used are from `claude --help` (Claude Code 2.1.322) and the headless
docs at https://code.claude.com/docs/en/headless.md. The shape of the JSON
result is from https://code.claude.com/docs/en/agent-sdk/typescript.md. No live
call has been made yet, so the parsing of a real reply is unverified.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import subprocess
import tempfile
import time
from typing import Any, Callable

from manimbench.providers.base import Completion, ProviderError, Request, assert_live_calls_allowed

Runner = Callable[..., subprocess.CompletedProcess]


class ClaudeCliRoute:
    name = "claude-cli"

    def __init__(self, *, command: str = "claude", runner: Runner | None = None, timeout_seconds: float = 1800.0):
        self.command = command
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def argv(self, target: dict[str, Any], request: Request) -> list[str]:
        argv = [
            self.command,
            "--print",
            "--model",
            str(target["model"]),
            "--system-prompt",
            request.system,
            "--tools",
            "",
            "--safe-mode",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]
        if request.reasoning_effort:
            argv += ["--effort", request.reasoning_effort]
        if request.images:
            # Images can only be sent as streamed input; the result is then the last streamed line.
            argv += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        else:
            argv += ["--output-format", "json"]
        return argv

    def stdin(self, request: Request) -> str:
        if not request.images:
            return request.prompt
        content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
        for path in request.images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mimetypes.guess_type(str(path))[0] or "image/jpeg",
                        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                    },
                }
            )
        return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"

    def complete(self, target: dict[str, Any], request: Request) -> Completion:
        argv = self.argv(target, request)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="manimbench-claude-") as empty_dir:
            try:
                completed = self._run(argv, input=self.stdin(request), cwd=empty_dir)
            except FileNotFoundError as error:
                raise ProviderError(f"Claude Code CLI not found: {self.command}") from error
            except subprocess.TimeoutExpired as error:
                raise ProviderError(f"Claude Code CLI timed out after {self.timeout_seconds:g} s") from error
        result = _result_object(completed.stdout or "")
        if result is None:
            detail = (completed.stderr or completed.stdout or "").strip()[-800:]
            raise ProviderError(f"Claude Code CLI returned no result (exit {completed.returncode}): {detail}")
        if result.get("is_error") or result.get("subtype") not in (None, "success"):
            detail = result.get("result") or result.get("errors") or result.get("subtype")
            raise ProviderError(f"Claude Code CLI reported an error: {detail}")
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        models = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}
        cost = result.get("total_cost_usd")
        return Completion(
            text=str(result.get("result") or ""),
            route=self.name,
            requested_model=str(target["model"]),
            response_model=", ".join(sorted(models)) or None,
            request_id=str(result["session_id"]) if result.get("session_id") else None,
            finish_reason=str(result["stop_reason"]) if result.get("stop_reason") else None,
            input_tokens=_input_tokens(usage),
            output_tokens=_integer(usage.get("output_tokens")),
            # On a subscription this is what the tokens would cost at API prices, not money spent.
            cost_usd=float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
            cost_basis="claude_cli_api_equivalent",
            elapsed_seconds=time.monotonic() - started,
        )

    def _run(self, argv: list[str], *, input: str, cwd: str) -> subprocess.CompletedProcess:
        kwargs = {"input": input, "cwd": cwd, "text": True, "capture_output": True, "timeout": self.timeout_seconds, "check": False}
        if self.runner is not None:
            return self.runner(argv, **kwargs)
        assert_live_calls_allowed("Claude Code CLI call")
        return subprocess.run(argv, **kwargs)


def _result_object(stdout: str) -> dict[str, Any] | None:
    """The result message: the whole output in json mode, the last result line in stream mode."""
    text = stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and data.get("type") == "result":
        return data
    if isinstance(data, list):
        lines: list[Any] = data
    else:
        lines = []
        for line in text.splitlines():
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for item in reversed(lines):
        if isinstance(item, dict) and item.get("type") == "result":
            return item
    return None


def _input_tokens(usage: dict[str, Any]) -> int | None:
    parts = [usage.get("input_tokens"), usage.get("cache_creation_input_tokens"), usage.get("cache_read_input_tokens")]
    numbers = [int(value) for value in parts if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return sum(numbers) if numbers else None


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
