import pytest

from manimbench.providers.common import GenerationValidationError, TransientProviderError, validate_main_scene
from manimbench.providers.anthropic import AnthropicProvider
from manimbench.providers.cursor import CursorProvider
from manimbench.providers.google import GoogleProvider
from manimbench.providers.openai import OpenAIProvider
from manimbench.providers.openrouter import OpenRouterProvider
from manimbench.providers.xai import XAIProvider
from manimbench.tasks import load_suite
from manimbench.paths import DEFAULT_SUITE_PATH


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def post_json(self, url, headers, payload, timeout):
        self.requests.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return self.response


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post_json(self, url, headers, payload, timeout):
        self.requests.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        if not self.responses:
            raise AssertionError("No fake response available")
        return self.responses.pop(0)


class ErrorThenResponseClient:
    def __init__(self, error, response):
        self.error = error
        self.response = response
        self.requests = []

    def post_json(self, url, headers, payload, timeout):
        self.requests.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        if len(self.requests) == 1:
            raise self.error
        return self.response


def _response(content, finish_reason="stop"):
    return {
        "id": "gen-test",
        "model": "openai/gpt-5.5",
        "choices": [{"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "cost": 0.0012},
    }


def _provider_choice_error(code=502, message="Upstream idle timeout exceeded", error_type="provider_unavailable"):
    return {
        "id": "gen-error",
        "model": "google/gemini-3.1-pro-preview",
        "choices": [
            {
                "error": {
                    "code": code,
                    "message": message,
                    "metadata": {"error_type": error_type},
                }
            }
        ],
    }


def test_openrouter_request_cleanup_validation_and_usage():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "```python\nfrom manim import *\n\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n```"
    client = FakeClient(_response(source))
    provider = OpenRouterProvider("gpt-5-5", api_key="test-key", client=client)

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["url"].endswith("/chat/completions")
    assert client.requests[0]["headers"]["Authorization"] == "Bearer test-key"
    assert client.requests[0]["payload"]["model"] == "openai/gpt-5.5"
    assert client.requests[0]["payload"]["messages"][-1]["content"] == "Task prompt"
    assert output.source.startswith("from manim import *")
    assert "```" not in output.source
    assert output.metadata["request_id"] == "gen-test"
    assert output.metadata["input_tokens"] == 10
    assert output.metadata["output_tokens"] == 20
    assert output.metadata["total_tokens"] == 30
    assert output.metadata["cost_usd"] == 0.0012


def test_openrouter_retries_transient_choice_error_before_failing_task():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = SequenceClient([_provider_choice_error(), _response(source)])
    provider = OpenRouterProvider(
        "gemini-3-1-pro",
        api_key="test-key",
        client=client,
        reasoning_effort="max",
        max_retries=2,
        retry_backoff_seconds=0,
    )

    output = provider.generate(task, "Task prompt")

    assert len(client.requests) == 2
    assert output.source.startswith("from manim import *")
    assert output.metadata["provider_retries"] == 1


def test_openrouter_retries_malformed_json_provider_response():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = ErrorThenResponseClient(
        TransientProviderError("Provider returned malformed JSON at line 879 column 1 (char 4829); body preview: '<html>'"),
        _response(source),
    )
    provider = OpenRouterProvider(
        "codex-5-2",
        api_key="test-key",
        client=client,
        reasoning_effort="max",
        max_retries=2,
        retry_backoff_seconds=0,
    )

    output = provider.generate(task, "Task prompt")

    assert len(client.requests) == 2
    assert output.metadata["provider_retries"] == 1
    assert output.source.startswith("from manim import *")


def test_openrouter_retries_empty_text_response():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    empty_response = _response("", finish_reason="stop")
    client = SequenceClient([empty_response, _response(source)])
    provider = OpenRouterProvider(
        "gpt-5-4",
        api_key="test-key",
        client=client,
        max_retries=2,
        retry_backoff_seconds=0,
    )

    output = provider.generate(task, "Task prompt")

    assert len(client.requests) == 2
    assert output.metadata["provider_retries"] == 1
    assert output.source.startswith("from manim import *")


def test_openrouter_accepts_content_text_blocks():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(
        {
            "id": "gen-test",
            "model": "openai/gpt-5.4",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": source}],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "cost": 0.0012},
        }
    )
    provider = OpenRouterProvider("gpt-5-4", api_key="test-key", client=client)

    output = provider.generate(task, "Task prompt")

    assert output.source.startswith("from manim import *")


def test_openrouter_request_includes_reasoning_effort():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = OpenRouterProvider("gpt-5-5", api_key="test-key", client=client, reasoning_effort="xhigh")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["reasoning"] == {"effort": "xhigh"}
    assert output.metadata["reasoning_effort"] == "xhigh"


def test_openrouter_request_includes_completion_budget():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = OpenRouterProvider(
        "gpt-5-2",
        api_key="test-key",
        client=client,
        max_completion_tokens=32768,
    )

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["max_tokens"] == 32768
    assert output.metadata["max_completion_tokens"] == 32768


def test_openrouter_retries_length_finish_with_lower_reasoning_effort():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    truncated = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text("
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = SequenceClient([_response(truncated, finish_reason="length"), _response(source)])
    provider = OpenRouterProvider(
        "gpt-5-2",
        api_key="test-key",
        client=client,
        reasoning_effort="max",
        max_retries=0,
        retry_backoff_seconds=0,
    )

    output = provider.generate(task, "Task prompt")

    assert len(client.requests) == 2
    assert client.requests[0]["payload"]["max_tokens"] == 65536
    assert client.requests[1]["payload"]["max_tokens"] == 65536
    assert client.requests[0]["payload"]["reasoning"] == {"effort": "xhigh"}
    assert client.requests[1]["payload"]["reasoning"] == {"effort": "high"}
    assert output.metadata["reasoning_effort"] == "max"
    assert output.metadata["effective_reasoning_effort"] == "high"
    assert output.metadata["length_retries"] == 1
    assert output.source.startswith("from manim import *")


def test_openrouter_anthropic_max_uses_highest_reasoning_and_verbosity():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = OpenRouterProvider("opus-4-8", api_key="test-key", client=client, reasoning_effort="max")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["model"] == "anthropic/claude-opus-4.8"
    assert client.requests[0]["payload"]["reasoning"] == {"effort": "xhigh"}
    assert client.requests[0]["payload"]["verbosity"] == "max"
    assert output.metadata["reasoning_effort"] == "max"


def test_openrouter_gemini_max_uses_highest_supported_reasoning_level():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = OpenRouterProvider("gemini-3-1-pro", api_key="test-key", client=client, reasoning_effort="max")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["model"] == "google/gemini-3.1-pro-preview"
    assert client.requests[0]["payload"]["reasoning"] == {"effort": "high"}
    assert "max_tokens" not in client.requests[0]["payload"]
    assert output.metadata["reasoning_effort"] == "max"


def test_openrouter_anthropic_xhigh_caps_verbosity_when_model_lacks_xhigh():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = OpenRouterProvider("sonnet-4-6", api_key="test-key", client=client, reasoning_effort="xhigh")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["reasoning"] == {"effort": "xhigh"}
    assert client.requests[0]["payload"]["verbosity"] == "high"
    assert output.metadata["reasoning_effort"] == "xhigh"


def test_openrouter_rejects_missing_main_scene():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    provider = OpenRouterProvider("gpt-5-5", api_key="test-key", client=FakeClient(_response("print('no scene')")))

    with pytest.raises(GenerationValidationError, match="MainScene"):
        provider.generate(task, "Task prompt")


def test_validate_main_scene_rejects_invalid_escape_warning():
    source = 'from manim import *\nclass MainScene(Scene):\n    label = "\\D"\n'

    with pytest.raises(GenerationValidationError, match="not valid Python line 3"):
        validate_main_scene(source)


def test_openai_direct_request_shape():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = OpenAIProvider("gpt-5-test", api_key="openai-key", client=client)

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert client.requests[0]["headers"]["Authorization"] == "Bearer openai-key"
    assert "HTTP-Referer" not in client.requests[0]["headers"]
    assert client.requests[0]["payload"]["model"] == "gpt-5-test"
    assert output.metadata["provider"] == "openai"


def test_openai_direct_request_includes_reasoning_effort():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = OpenAIProvider("gpt-5-test", api_key="openai-key", client=client, reasoning_effort="high")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["reasoning_effort"] == "high"
    assert output.metadata["reasoning_effort"] == "high"


def test_openai_direct_max_reasoning_effort_uses_highest_supported_effort():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = OpenAIProvider("gpt-5-test", api_key="openai-key", client=client, reasoning_effort="max")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["reasoning_effort"] == "xhigh"
    assert output.metadata["reasoning_effort"] == "max"


def test_xai_direct_request_shape():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = XAIProvider("grok-test", api_key="xai-key", client=client)

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["url"] == "https://api.x.ai/v1/chat/completions"
    assert client.requests[0]["headers"]["Authorization"] == "Bearer xai-key"
    assert client.requests[0]["payload"]["messages"][-1]["content"] == "Task prompt"
    assert output.metadata["provider"] == "xai"


def test_xai_direct_max_reasoning_effort_uses_highest_supported_effort():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(_response(source))
    provider = XAIProvider("grok-test", api_key="xai-key", client=client, reasoning_effort="max")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["reasoning_effort"] == "high"
    assert output.metadata["reasoning_effort"] == "max"


def test_anthropic_direct_request_shape_and_usage():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(
        {
            "id": "msg-test",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": source}],
            "usage": {"input_tokens": 11, "output_tokens": 22},
        }
    )
    provider = AnthropicProvider("claude-test", api_key="anthropic-key", client=client)

    output = provider.generate(task, "Task prompt")

    request = client.requests[0]
    assert request["url"] == "https://api.anthropic.com/v1/messages"
    assert request["headers"]["x-api-key"] == "anthropic-key"
    assert request["headers"]["anthropic-version"] == "2023-06-01"
    assert request["payload"]["system"].startswith("Return only")
    assert request["payload"]["messages"] == [{"role": "user", "content": "Task prompt"}]
    assert output.metadata["input_tokens"] == 11
    assert output.metadata["output_tokens"] == 22
    assert output.metadata["total_tokens"] == 33


def test_anthropic_direct_request_includes_reasoning_effort():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(
        {
            "id": "msg-test",
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": source}],
            "usage": {"input_tokens": 11, "output_tokens": 22},
        }
    )
    provider = AnthropicProvider("claude-test", api_key="anthropic-key", client=client, reasoning_effort="max")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["output_config"] == {"effort": "max"}
    assert output.metadata["reasoning_effort"] == "max"


def test_anthropic_direct_adds_adaptive_thinking_for_supported_models():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(
        {
            "id": "msg-test",
            "model": "claude-opus-4-8",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": source}],
            "usage": {"input_tokens": 11, "output_tokens": 22},
        }
    )
    provider = AnthropicProvider("opus-4-8", model_slug="claude-opus-4-8", api_key="anthropic-key", client=client, reasoning_effort="max")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["output_config"] == {"effort": "max"}
    assert client.requests[0]["payload"]["thinking"] == {"type": "adaptive"}
    assert output.metadata["reasoning_effort"] == "max"


def test_google_direct_request_shape_and_usage():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(
        {
            "responseId": "google-test",
            "modelVersion": "gemini-test",
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": source}]},
                }
            ],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 8, "totalTokenCount": 15},
        }
    )
    provider = GoogleProvider("gemini-test", api_key="google-key", client=client)

    output = provider.generate(task, "Task prompt")

    request = client.requests[0]
    assert request["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent?key=google-key"
    assert request["payload"]["systemInstruction"]["parts"][0]["text"].startswith("Return only")
    assert request["payload"]["contents"][0]["parts"][0]["text"] == "Task prompt"
    assert output.metadata["input_tokens"] == 7
    assert output.metadata["output_tokens"] == 8
    assert output.metadata["total_tokens"] == 15


def test_google_direct_max_reasoning_effort_uses_highest_thinking_level():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(
        {
            "responseId": "google-test",
            "modelVersion": "gemini-3.1-pro-preview",
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": source}]}}],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 8, "totalTokenCount": 15},
        }
    )
    provider = GoogleProvider("gemini-3-1-pro", model_slug="gemini-3.1-pro-preview", api_key="google-key", client=client, reasoning_effort="max")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "high"}
    assert output.metadata["reasoning_effort"] == "max"


def test_google_direct_25_max_reasoning_effort_uses_highest_thinking_budget():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "from manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n"
    client = FakeClient(
        {
            "responseId": "google-test",
            "modelVersion": "gemini-2.5-flash",
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": source}]}}],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 8, "totalTokenCount": 15},
        }
    )
    provider = GoogleProvider("gemini-2-5-flash", model_slug="gemini-2.5-flash", api_key="google-key", client=client, reasoning_effort="max")

    output = provider.generate(task, "Task prompt")

    assert client.requests[0]["payload"]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 24576}
    assert output.metadata["reasoning_effort"] == "max"


def test_cursor_provider_invokes_cursor_agent_and_cleans_output(tmp_path):
    import subprocess

    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    source = "Here is the solution:\n```python\nfrom manim import *\nclass MainScene(Scene):\n    def construct(self):\n        self.add(Text('ok'))\n```"
    calls = []

    def runner(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        return subprocess.CompletedProcess(command, 0, stdout=source, stderr="")

    provider = CursorProvider(
        "composer-2-5",
        api_key="cursor-key",
        runner=runner,
        command="cursor-agent",
        cwd=tmp_path,
    )

    output = provider.generate(task, "Task prompt")
    call = calls[0]

    assert call["command"][:7] == ["cursor-agent", "-p", "--trust", "--output-format", "text", "--model", "Composer 2.5"]
    assert "Task prompt" in call["command"][-1]
    assert call["kwargs"]["env"]["CURSOR_API_KEY"] == "cursor-key"
    assert call["kwargs"]["cwd"] == str(tmp_path)
    assert output.source.startswith("from manim import *")
    assert output.metadata["provider"] == "cursor"
    assert output.metadata["provider_route"] == "cursor-agent"
