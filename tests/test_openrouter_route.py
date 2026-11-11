"""OpenRouter route: request shape, parsing, retries, and the transport's error mapping."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from email.message import Message

import pytest

from manimbench.providers.base import LiveCallForbiddenError, ProviderError, Request, TransientProviderError
from manimbench.providers.openrouter import HttpJsonClient, OpenRouterRoute

TARGET = {"model": "anthropic/claude-opus-5.5", "provider": "anthropic"}


class FakeClient:
    """Returns or raises from a scripted list, and records every call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def post_json(self, url, headers, payload, timeout):
        self.calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get_json(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def body(text="hello", *, finish="stop", cost=0.05, model="anthropic/claude-opus-5.5", ident="gen-1"):
    data = {
        "id": ident,
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40, "completion_tokens_details": {"reasoning_tokens": 15}},
    }
    if cost is not None:
        data["usage"]["cost"] = cost
    return data


def make(script, **kwargs):
    client = FakeClient(script)
    delays = []
    route = OpenRouterRoute(api_key="sk-test", client=client, sleep=delays.append, **kwargs)
    return route, client, delays


def test_text_payload_has_model_messages_and_token_limit():
    route, client, _ = make([body()])
    route.complete(TARGET, Request(system="SYS", prompt="USER", max_output_tokens=1234))
    payload = client.calls[0]["payload"]
    assert payload["model"] == "anthropic/claude-opus-5.5"
    assert payload["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert payload["max_completion_tokens"] == 1234
    assert "max_tokens" not in payload
    assert "temperature" not in payload
    assert client.calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"


def test_payload_omits_optional_keys_when_unset():
    route, client, _ = make([body()])
    route.complete({"model": "x/y"}, Request(system="S", prompt="P"))
    assert set(client.calls[0]["payload"]) == {"model", "messages"}


def test_reasoning_and_provider_only_when_set():
    route, client, _ = make([body()])
    route.complete(TARGET, Request(system="S", prompt="P", reasoning_effort="high"))
    payload = client.calls[0]["payload"]
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["provider"] == {"order": ["anthropic"], "allow_fallbacks": False}


def test_image_request_sends_text_part_then_one_data_url_per_image(tmp_path):
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    first.write_bytes(b"AAA")
    second.write_bytes(b"BBBB")
    route, client, _ = make([body()])
    route.complete(TARGET, Request(system="S", prompt="look", images=[first, second]))
    content = client.calls[0]["payload"]["messages"][1]["content"]
    assert content == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b"AAA").decode()}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b"BBBB").decode()}},
    ]


def test_headers_carry_key_referer_and_title():
    route, client, _ = make([body()])
    route.complete(TARGET, Request(system="S", prompt="P"))
    headers = client.calls[0]["headers"]
    assert headers["Authorization"] == "Bearer sk-test"
    assert headers["HTTP-Referer"] == "https://manimbench.site"
    assert headers["X-OpenRouter-Title"] == "ManimBench"
    assert headers["Content-Type"] == "application/json"


def test_success_parses_every_field():
    route, _, delays = make([body("print(1)", finish="stop", cost=0.05)])
    completion = route.complete(TARGET, Request(system="S", prompt="P"))
    assert completion.text == "print(1)"
    assert completion.finish_reason == "stop"
    assert completion.input_tokens == 120
    assert completion.output_tokens == 40
    assert completion.reasoning_tokens == 15
    assert completion.response_model == "anthropic/claude-opus-5.5"
    assert completion.request_id == "gen-1"
    assert completion.cost_usd == 0.05
    assert completion.cost_basis == "openrouter_reported"
    assert completion.route == "openrouter"
    assert completion.requested_model == "anthropic/claude-opus-5.5"
    assert completion.attempts == 1
    assert delays == []


def test_missing_cost_gives_no_cost_and_no_basis():
    route, _, _ = make([body(cost=None)])
    completion = route.complete(TARGET, Request(system="S", prompt="P"))
    assert completion.cost_usd is None
    assert completion.cost_basis is None


def test_list_content_parts_are_joined():
    data = body()
    data["choices"][0]["message"]["content"] = [{"type": "text", "text": "ab"}, {"type": "text", "text": "cd"}, "skip"]
    route, _, _ = make([data])
    assert route.complete(TARGET, Request(system="S", prompt="P")).text == "abcd"


def test_transient_errors_retry_with_exponential_delays():
    errors = [TransientProviderError("a"), TransientProviderError("b"), TransientProviderError("c")]
    route, client, delays = make([*errors, body("ok")], max_retries=3)
    completion = route.complete(TARGET, Request(system="S", prompt="P"))
    assert completion.text == "ok"
    assert completion.attempts == 4
    assert delays == [2.0, 4.0, 8.0]
    assert len(client.calls) == 4


def test_retry_after_is_honored():
    route, _, delays = make([TransientProviderError("slow down", retry_after=7.5), body()])
    route.complete(TARGET, Request(system="S", prompt="P"))
    assert delays == [7.5]


def test_gives_up_after_max_retries_with_provider_error():
    route, client, delays = make([TransientProviderError("x")] * 3, max_retries=2)
    with pytest.raises(ProviderError, match="gave up after 3 attempts"):
        route.complete(TARGET, Request(system="S", prompt="P"))
    assert len(client.calls) == 3
    assert delays == [2.0, 4.0]


def test_permanent_provider_error_is_not_retried():
    route, client, delays = make([ProviderError("HTTP 401: no"), body()])
    with pytest.raises(ProviderError, match="HTTP 401"):
        route.complete(TARGET, Request(system="S", prompt="P"))
    assert len(client.calls) == 1
    assert delays == []


def test_cost_is_summed_across_attempts_when_earlier_one_was_empty():
    route, client, delays = make([body("", finish="stop", cost=0.01), body("real", cost=0.02)])
    completion = route.complete(TARGET, Request(system="S", prompt="P"))
    assert completion.text == "real"
    assert completion.cost_usd == 0.03
    assert completion.attempts == 2
    assert len(client.calls) == 2
    assert delays == [2.0]


def test_empty_text_with_length_finish_is_returned_not_retried():
    route, client, _ = make([body("", finish="length", cost=0.04)])
    completion = route.complete(TARGET, Request(system="S", prompt="P"))
    assert completion.text == ""
    assert completion.finish_reason == "length"
    assert completion.cost_usd == 0.04
    assert len(client.calls) == 1


def test_error_body_with_429_is_transient_and_retried():
    error_body = {"error": {"code": 429, "message": "rate limited"}}
    route, client, delays = make([error_body, body("fine")])
    assert route.complete(TARGET, Request(system="S", prompt="P")).text == "fine"
    assert len(client.calls) == 2
    assert delays == [2.0]


def test_error_body_with_400_is_permanent():
    route, client, delays = make([{"error": {"code": 400, "message": "bad request"}}, body()])
    with pytest.raises(ProviderError, match="OpenRouter error 400: bad request") as info:
        route.complete(TARGET, Request(system="S", prompt="P"))
    assert not isinstance(info.value, TransientProviderError)
    assert len(client.calls) == 1
    assert delays == []


def test_body_without_choices_is_retried_as_transient():
    route, client, _ = make([{"id": "x"}, body("ok")])
    assert route.complete(TARGET, Request(system="S", prompt="P")).text == "ok"
    assert len(client.calls) == 2


def test_missing_api_key_raises_before_any_request(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = FakeClient([body()])
    route = OpenRouterRoute(client=client, sleep=lambda _d: None)
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY is not set"):
        route.complete(TARGET, Request(system="S", prompt="P"))
    assert client.calls == []


def test_catalog_uses_get_json_on_models_url():
    route, client, _ = make([{"data": []}])
    assert route.catalog() == {"data": []}
    assert client.calls[0]["url"] == "https://openrouter.ai/api/v1/models"


# --- the real transport, with urlopen replaced ---------------------------------------------


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def open_with(monkeypatch, outcome):
    def fake_urlopen(_request, timeout=None):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return HttpJsonClient._open(urllib.request.Request("http://example.invalid/x"), 5)


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("t"), ConnectionResetError("r"), urllib.error.URLError("dns")],
    ids=["timeout", "connection_reset", "urlerror"],
)
def test_transit_failures_map_to_transient(monkeypatch, failure):
    with pytest.raises(TransientProviderError):
        open_with(monkeypatch, failure)


def http_error(code, retry_after=None, text=b'{"error":"x"}'):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://example.invalid/x", code, "msg", headers, io.BytesIO(text))


def test_http_429_with_retry_after_is_transient_with_delay(monkeypatch):
    with pytest.raises(TransientProviderError) as info:
        open_with(monkeypatch, http_error(429, "12"))
    assert info.value.retry_after == 12.0
    assert "HTTP 429" in str(info.value)


def test_http_503_without_retry_after_is_transient_with_no_delay(monkeypatch):
    with pytest.raises(TransientProviderError) as info:
        open_with(monkeypatch, http_error(503))
    assert info.value.retry_after is None


def test_http_400_is_plain_provider_error(monkeypatch):
    with pytest.raises(ProviderError) as info:
        open_with(monkeypatch, http_error(400))
    assert not isinstance(info.value, TransientProviderError)
    assert "HTTP 400" in str(info.value)


def test_invalid_json_body_is_transient(monkeypatch):
    with pytest.raises(TransientProviderError, match="not valid JSON"):
        open_with(monkeypatch, FakeResponse(b"<html>nope"))


def test_json_array_body_is_transient(monkeypatch):
    with pytest.raises(TransientProviderError, match="not a JSON object"):
        open_with(monkeypatch, FakeResponse(b"[1]"))


def test_valid_json_object_is_returned(monkeypatch):
    assert open_with(monkeypatch, FakeResponse(json.dumps({"a": 1}).encode())) == {"a": 1}


def test_real_client_refuses_live_calls_without_touching_network(monkeypatch):
    def boom(*_a, **_k):
        pytest.fail("urlopen must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(LiveCallForbiddenError):
        HttpJsonClient().post_json("http://example.invalid", {}, {}, 1)
    with pytest.raises(LiveCallForbiddenError):
        HttpJsonClient().get_json("http://example.invalid", {}, 1)
