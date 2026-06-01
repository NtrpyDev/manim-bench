import pytest

from manimbench.providers.common import GenerationValidationError
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


def _response(content):
    return {
        "id": "gen-test",
        "model": "openai/gpt-5.5",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "cost": 0.0012},
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


def test_openrouter_rejects_missing_main_scene():
    task = load_suite(DEFAULT_SUITE_PATH).tasks[0]
    provider = OpenRouterProvider("gpt-5-5", api_key="test-key", client=FakeClient(_response("print('no scene')")))

    with pytest.raises(GenerationValidationError, match="MainScene"):
        provider.generate(task, "Task prompt")


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

    assert call["command"][:6] == ["cursor-agent", "-p", "--output-format", "text", "--model", "Composer 2.5"]
    assert "Task prompt" in call["command"][-1]
    assert call["kwargs"]["env"]["CURSOR_API_KEY"] == "cursor-key"
    assert call["kwargs"]["cwd"] == str(tmp_path)
    assert output.source.startswith("from manim import *")
    assert output.metadata["provider"] == "cursor"
    assert output.metadata["provider_route"] == "cursor-agent"
