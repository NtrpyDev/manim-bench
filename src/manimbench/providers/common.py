from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from manimbench.models import ModelOutput, Task


class ProviderError(RuntimeError):
    pass


class GenerationValidationError(ProviderError):
    def __init__(self, message: str, source: str = "", metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.source = source
        self.metadata = metadata or {}


class HttpJsonClient:
    def get_json(self, url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=headers, method="GET")
        return self._open_json(request, timeout)

    def post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        return self._open_json(request, timeout)

    def _open_json(self, request: urllib.request.Request, timeout: int) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Provider HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise ProviderError(f"Provider request failed: {error}") from error
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ProviderError("Provider returned a non-object JSON response")
        return data


@dataclass
class ChatCompletionProvider:
    provider_name: str
    route: str
    model_id: str
    model_slug: str
    api_key_env: str
    base_url: str
    api_key: str | None = None
    timeout_seconds: int = 240
    client: Any | None = None
    temperature: float = 0.2

    def __post_init__(self) -> None:
        self.client = self.client or HttpJsonClient()
        self.api_key = self.api_key or os.getenv(self.api_key_env)
        if not self.api_key:
            raise ProviderError(f"{self.api_key_env} is required for provider {self.provider_name}")

    def generate(self, task: Task, prompt: str) -> ModelOutput:
        started = time.monotonic()
        payload = self._request_payload(prompt)
        response = self.client.post_json(
            self._chat_url(),
            headers=self._headers(),
            payload=payload,
            timeout=self.timeout_seconds,
        )
        elapsed = time.monotonic() - started
        content, finish_reason = extract_chat_content(response)
        metadata = self._metadata(response, task.id, finish_reason, elapsed)
        if finish_reason and finish_reason not in {"stop", "end_turn"}:
            raise GenerationValidationError(
                f"Incomplete provider response: finish_reason={finish_reason}",
                content,
                metadata,
            )
        source = cleanup_generated_source(content)
        validate_main_scene(source, metadata=metadata)
        return ModelOutput(model=self.model_id, task_id=task.id, source=source, metadata=metadata)

    def _request_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model_slug,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only complete Manim Community Edition Python source code.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def _metadata(self, response: dict[str, Any], task_id: str, finish_reason: str | None, elapsed: float) -> dict[str, Any]:
        usage = response.get("usage", {}) if isinstance(response.get("usage"), dict) else {}
        return {
            "provider": self.provider_name,
            "provider_route": self.route,
            "model_id": self.model_id,
            "model_slug": self.model_slug,
            "task_id": task_id,
            "request_id": response.get("id"),
            "response_model": response.get("model"),
            "finish_reason": finish_reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cost_usd": usage.get("cost"),
            "usage": usage,
        }


def extract_chat_content(response: dict[str, Any]) -> tuple[str, str | None]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("Provider response did not include choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderError("Provider choice was not an object")
    if choice.get("error"):
        raise ProviderError(f"Provider choice error: {choice['error']}")
    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = choice.get("text")
    if not isinstance(content, str) or not content.strip():
        raise GenerationValidationError("Provider response did not include text content")
    return content, choice.get("finish_reason")


def cleanup_generated_source(content: str) -> str:
    text = content.strip()
    fenced = re.fullmatch(r"```(?:python|py)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    else:
        fenced_block = re.search(r"```(?:python|py)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced_block:
            text = fenced_block.group(1).strip()
        else:
            text = re.sub(r"^```(?:python|py)?\s*", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"\s*```$", "", text).strip()
    return text.rstrip() + "\n"


def validate_main_scene(source: str, metadata: dict[str, Any] | None = None) -> None:
    if not re.search(r"^\s*class\s+MainScene\s*\(", source, flags=re.MULTILINE):
        raise GenerationValidationError("Generated output does not define class MainScene", source, metadata)


def system_prompt() -> str:
    return "Return only complete Manim Community Edition Python source code."


def metadata_payload(
    *,
    provider: str,
    route: str,
    model_id: str,
    model_slug: str,
    task_id: str,
    request_id: str | None,
    response_model: str | None,
    finish_reason: str | None,
    elapsed_seconds: float,
    input_tokens: Any = None,
    output_tokens: Any = None,
    total_tokens: Any = None,
    cost_usd: Any = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "provider_route": route,
        "model_id": model_id,
        "model_slug": model_slug,
        "task_id": task_id,
        "request_id": request_id,
        "response_model": response_model,
        "finish_reason": finish_reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed_seconds,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
        "usage": usage or {},
    }
