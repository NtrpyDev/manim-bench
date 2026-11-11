"""OpenRouter: one HTTP request per completion, with the real cost returned."""

from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from manimbench.providers.base import (
    Completion,
    ProviderError,
    Request,
    TransientProviderError,
    assert_live_calls_allowed,
)

TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
MAX_BACKOFF_SECONDS = 60.0


class HttpJsonClient:
    """A small JSON-over-HTTPS client. Every way a request can fail in transit is retryable."""

    def post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        assert_live_calls_allowed("OpenRouter request")
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        return self._open(request, timeout)

    def get_json(self, url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
        assert_live_calls_allowed("OpenRouter request")
        return self._open(urllib.request.Request(url, headers=headers, method="GET"), timeout)

    @staticmethod
    def _open(request: urllib.request.Request, timeout: float) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:2000]
            message = f"HTTP {error.code}: {detail}"
            if error.code in TRANSIENT_STATUS:
                raise TransientProviderError(message, retry_after=_retry_after(error.headers.get("Retry-After"))) from error
            raise ProviderError(message) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, http.client.HTTPException) as error:
            raise TransientProviderError(f"Request failed in transit: {error!r}") from error
        try:
            data = json.loads(body)
        except json.JSONDecodeError as error:
            raise TransientProviderError("The response was not valid JSON") from error
        if not isinstance(data, dict):
            raise TransientProviderError("The response was not a JSON object")
        return data


def _retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


class OpenRouterRoute:
    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str = "OPENROUTER_API_KEY",
        base_url: str = "https://openrouter.ai/api/v1",
        client: Any | None = None,
        timeout_seconds: float = 900.0,
        max_retries: int = 4,
        backoff_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        referer: str = "https://manimbench.site",
        title: str = "ManimBench",
    ):
        self.api_key = api_key if api_key is not None else os.environ.get(api_key_env)
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.client = client or HttpJsonClient()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep
        self.referer = referer
        self.title = title

    def payload(self, target: dict[str, Any], request: Request) -> dict[str, Any]:
        if request.images:
            content: Any = [{"type": "text", "text": request.prompt}]
            content += [{"type": "image_url", "image_url": {"url": _data_url(path)}} for path in request.images]
        else:
            content = request.prompt
        payload: dict[str, Any] = {
            "model": str(target["model"]),
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": content}],
        }
        if request.max_output_tokens:
            payload["max_completion_tokens"] = int(request.max_output_tokens)
        if request.reasoning_effort:
            payload["reasoning"] = {"effort": request.reasoning_effort}
        if target.get("provider"):
            # Always the same upstream for a model, so every sample is served the same way.
            payload["provider"] = {"order": [str(target["provider"])], "allow_fallbacks": False}
        return payload

    def complete(self, target: dict[str, Any], request: Request) -> Completion:
        if not self.api_key:
            raise ProviderError(f"{self.api_key_env} is not set")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.referer,
            "X-OpenRouter-Title": self.title,
        }
        payload = self.payload(target, request)
        started = time.monotonic()
        spent = 0.0
        spent_known = False
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                data = self.client.post_json(f"{self.base_url}/chat/completions", headers, payload, self.timeout_seconds)
                error = data.get("error")
                if isinstance(error, dict):
                    code = error.get("code")
                    message = f"OpenRouter error {code}: {error.get('message')}"
                    if code in TRANSIENT_STATUS:
                        raise TransientProviderError(message)
                    raise ProviderError(message)
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                cost = _number(usage.get("cost"))
                if cost is not None:
                    spent += cost
                    spent_known = True
                text, finish_reason = _choice(data)
                if not text.strip() and finish_reason != "length":
                    # Paid for, but nothing came back. Try again; the cost stays counted.
                    raise TransientProviderError("The response had no text")
                details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
                return Completion(
                    text=text,
                    route=self.name,
                    requested_model=str(target["model"]),
                    response_model=str(data["model"]) if data.get("model") else None,
                    request_id=str(data["id"]) if data.get("id") else None,
                    finish_reason=finish_reason,
                    input_tokens=_integer(usage.get("prompt_tokens")),
                    output_tokens=_integer(usage.get("completion_tokens")),
                    reasoning_tokens=_integer(details.get("reasoning_tokens")),
                    cost_usd=round(spent, 8) if spent_known else None,
                    cost_basis="openrouter_reported" if spent_known else None,
                    elapsed_seconds=time.monotonic() - started,
                    attempts=attempt,
                )
            except TransientProviderError as error:
                last_error = error
                if attempt > self.max_retries:
                    break
                delay = error.retry_after if error.retry_after is not None else self.backoff_seconds * 2 ** (attempt - 1)
                self.sleep(min(MAX_BACKOFF_SECONDS, delay))
        raise ProviderError(f"OpenRouter gave up after {self.max_retries + 1} attempts: {last_error}")

    def catalog(self) -> dict[str, Any]:
        """The public model list. Free, and not a model call."""
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return self.client.get_json(f"{self.base_url}/models", headers, 60)


def _choice(data: dict[str, Any]) -> tuple[str, str | None]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise TransientProviderError("The response had no choices")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    finish = choice.get("finish_reason")
    return (content if isinstance(content, str) else ""), (str(finish) if finish else None)


def _data_url(path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
