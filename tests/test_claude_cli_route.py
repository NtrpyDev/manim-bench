"""Claude Code CLI route: the stripped-down command line, the stdin payload, and result parsing."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import pytest

from conftest import REPO_ROOT

from manimbench.providers.base import LiveCallForbiddenError, ProviderError, Request
from manimbench.providers.claude_cli import ClaudeCliRoute

TARGET = {"model": "claude-opus-5-5"}

RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "print('hi')",
    "total_cost_usd": 0.12,
    "usage": {"input_tokens": 10, "cache_creation_input_tokens": 200, "cache_read_input_tokens": 3000, "output_tokens": 77},
    "modelUsage": {"claude-opus-5-5": {}},
    "session_id": "s",
    "stop_reason": "end_turn",
}


class Runner:
    def __init__(self, stdout="", returncode=0, stderr="", raises=None):
        self.stdout, self.returncode, self.stderr, self.raises = stdout, returncode, stderr, raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr=self.stderr)


def run(request, runner=None, **kwargs):
    runner = runner or Runner(json.dumps(RESULT))
    completion = ClaudeCliRoute(runner=runner, **kwargs).complete(TARGET, request)
    return completion, runner


def value_after(argv, flag):
    return argv[argv.index(flag) + 1]


def test_text_argv_has_the_stripped_down_flags():
    _, runner = run(Request(system="SYS", prompt="PROMPT"))
    argv = runner.calls[0][0]
    assert argv[0] == "claude"
    assert "--print" in argv
    assert value_after(argv, "--model") == "claude-opus-5-5"
    assert value_after(argv, "--system-prompt") == "SYS"
    assert value_after(argv, "--tools") == ""
    assert "--safe-mode" in argv
    assert value_after(argv, "--setting-sources") == ""
    assert "--strict-mcp-config" in argv
    assert "--disable-slash-commands" in argv
    assert "--no-session-persistence" in argv
    assert value_after(argv, "--output-format") == "json"
    assert "--input-format" not in argv
    assert "--verbose" not in argv


def test_argv_never_contains_unsafe_flags():
    _, runner = run(Request(system="SYS", prompt="PROMPT", reasoning_effort="high"))
    argv = runner.calls[0][0]
    for flag in ["--bare", "--dangerously-skip-permissions", "--allowedTools"]:
        assert flag not in argv


def test_effort_flag_only_when_set():
    _, without = run(Request(system="S", prompt="P"))
    assert "--effort" not in without.calls[0][0]
    _, with_effort = run(Request(system="S", prompt="P", reasoning_effort="high"))
    assert value_after(with_effort.calls[0][0], "--effort") == "high"


def test_prompt_goes_on_stdin_not_argv():
    _, runner = run(Request(system="S", prompt="THE-PROMPT-TEXT"))
    argv, kwargs = runner.calls[0]
    assert kwargs["input"] == "THE-PROMPT-TEXT"
    assert "THE-PROMPT-TEXT" not in argv
    assert kwargs["text"] is True
    assert kwargs["check"] is False


def test_runs_from_an_empty_temporary_folder_outside_the_repo():
    seen = {}

    def runner(argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        seen["cwd"] = cwd
        seen["entries"] = list(cwd.iterdir())
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(RESULT), stderr="")

    ClaudeCliRoute(runner=runner).complete(TARGET, Request(system="S", prompt="P"))
    cwd = seen["cwd"]
    assert seen["entries"] == []
    assert cwd != REPO_ROOT
    assert REPO_ROOT not in cwd.parents
    assert not cwd.exists()  # cleaned up afterwards


def test_timeout_kwarg_comes_from_route_setting():
    _, runner = run(Request(system="S", prompt="P"), timeout_seconds=42.0)
    assert runner.calls[0][1]["timeout"] == 42.0


def test_image_request_uses_stream_json_and_sends_one_json_line(tmp_path):
    png = tmp_path / "f.png"
    jpg = tmp_path / "g.jpg"
    png.write_bytes(b"PNGDATA")
    jpg.write_bytes(b"JPGDATA")
    stream = "\n".join([json.dumps({"type": "system"}), json.dumps(RESULT)])
    _, runner = run(Request(system="S", prompt="look", images=[png, jpg]), Runner(stream))
    argv, kwargs = runner.calls[0]
    assert value_after(argv, "--input-format") == "stream-json"
    assert value_after(argv, "--output-format") == "stream-json"
    assert "--verbose" in argv
    stdin = kwargs["input"]
    assert stdin.endswith("\n") and stdin.count("\n") == 1
    message = json.loads(stdin)
    assert message["type"] == "user"
    assert message["message"]["role"] == "user"
    content = message["message"]["content"]
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(b"PNGDATA").decode()},
    }
    assert content[2]["source"]["media_type"] == "image/jpeg"
    assert content[2]["source"]["data"] == base64.b64encode(b"JPGDATA").decode()
    assert len(content) == 3


def test_json_reply_is_parsed_into_a_completion():
    completion, _ = run(Request(system="S", prompt="P"))
    assert completion.text == "print('hi')"
    assert completion.cost_usd == 0.12
    assert completion.cost_basis == "claude_cli_api_equivalent"
    assert completion.input_tokens == 3210
    assert completion.output_tokens == 77
    assert completion.response_model == "claude-opus-5-5"
    assert completion.request_id == "s"
    assert completion.finish_reason == "end_turn"
    assert completion.route == "claude-cli"
    assert completion.requested_model == "claude-opus-5-5"


def test_stream_output_with_result_last_is_parsed_the_same():
    lines = [
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": []}}),
        "not json at all",
        json.dumps(RESULT),
    ]
    completion, _ = run(Request(system="S", prompt="P"), Runner("\n".join(lines) + "\n"))
    assert completion.text == "print('hi')"
    assert completion.input_tokens == 3210
    assert completion.cost_usd == 0.12


def test_json_array_output_is_parsed():
    completion, _ = run(Request(system="S", prompt="P"), Runner(json.dumps([{"type": "system"}, RESULT])))
    assert completion.text == "print('hi')"


def test_missing_usage_gives_no_token_counts():
    data = {"type": "result", "subtype": "success", "is_error": False, "result": "x"}
    completion, _ = run(Request(system="S", prompt="P"), Runner(json.dumps(data)))
    assert completion.input_tokens is None
    assert completion.output_tokens is None
    assert completion.cost_usd is None
    assert completion.response_model is None
    assert completion.request_id is None


@pytest.mark.parametrize(
    "stdout",
    [
        json.dumps({**RESULT, "is_error": True, "result": "overloaded"}),
        json.dumps({**RESULT, "subtype": "error_max_turns"}),
        "",
        "   \n",
        "this is not json",
        json.dumps({"type": "assistant"}),
    ],
    ids=["is_error", "bad_subtype", "empty", "whitespace", "not_json", "no_result_message"],
)
def test_unusable_output_raises_provider_error(stdout):
    with pytest.raises(ProviderError):
        run(Request(system="S", prompt="P"), Runner(stdout))


def test_missing_cli_raises_provider_error():
    with pytest.raises(ProviderError, match="not found"):
        run(Request(system="S", prompt="P"), Runner(raises=FileNotFoundError("claude")))


def test_cli_timeout_raises_provider_error():
    with pytest.raises(ProviderError, match="timed out"):
        run(Request(system="S", prompt="P"), Runner(raises=subprocess.TimeoutExpired("claude", 1)))


def test_without_a_runner_live_calls_are_forbidden_and_no_process_starts(monkeypatch):
    def boom(*_a, **_k):
        pytest.fail("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(LiveCallForbiddenError):
        ClaudeCliRoute().complete(TARGET, Request(system="S", prompt="P"))
