from __future__ import annotations

import ast
import json
import os
import re
import time
import urllib.error
import urllib.request
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from manimbench.models import ModelOutput, Task
from manimbench.reasoning import normalize_reasoning_effort


class ProviderError(RuntimeError):
    pass


class TransientProviderError(ProviderError):
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
            message = f"Provider HTTP {error.code}: {detail}"
            if _is_transient_error(code=error.code, message=detail):
                raise TransientProviderError(message) from error
            raise ProviderError(message) from error
        except urllib.error.URLError as error:
            raise TransientProviderError(f"Provider request failed: {error}") from error
        try:
            data = json.loads(body)
        except json.JSONDecodeError as error:
            preview = body[:500].replace("\n", "\\n")
            raise TransientProviderError(
                f"Provider returned malformed JSON at line {error.lineno} column {error.colno} "
                f"(char {error.pos}); body preview: {preview!r}"
            ) from error
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
    reasoning_effort: str | None = None
    max_completion_tokens: int | None = None
    max_retries: int = 2
    retry_backoff_seconds: float = 2.0
    max_length_retries: int = 1

    def __post_init__(self) -> None:
        self.client = self.client or HttpJsonClient()
        self.api_key = self.api_key or os.getenv(self.api_key_env)
        self.reasoning_effort = normalize_reasoning_effort(self.reasoning_effort)
        if self.max_completion_tokens is not None and self.max_completion_tokens <= 0:
            self.max_completion_tokens = None
        if not self.api_key:
            raise ProviderError(f"{self.api_key_env} is required for provider {self.provider_name}")

    def generate(self, task: Task, prompt: str) -> ModelOutput:
        started = time.monotonic()
        retries = 0
        length_retries = 0
        original_reasoning_effort = self.reasoning_effort
        active_reasoning_effort = original_reasoning_effort
        response: dict[str, Any] = {}
        content = ""
        finish_reason: str | None = None
        try:
            while True:
                self.reasoning_effort = active_reasoning_effort
                payload = self._request_payload(prompt)
                while True:
                    try:
                        response = self.client.post_json(
                            self._chat_url(),
                            headers=self._headers(),
                            payload=payload,
                            timeout=self.timeout_seconds,
                        )
                        content, finish_reason = extract_chat_content(response)
                        break
                    except TransientProviderError:
                        if retries >= max(0, self.max_retries):
                            raise
                        retries += 1
                        delay = min(self.retry_backoff_seconds * (2 ** (retries - 1)), 30.0)
                        if delay > 0:
                            time.sleep(delay)
                next_effort = self._length_retry_reasoning_effort(active_reasoning_effort)
                if (
                    not _is_length_finish_reason(finish_reason)
                    or length_retries >= max(0, self.max_length_retries)
                    or next_effort == active_reasoning_effort
                ):
                    break
                length_retries += 1
                active_reasoning_effort = next_effort
        finally:
            self.reasoning_effort = original_reasoning_effort
        elapsed = time.monotonic() - started
        metadata = self._metadata(response, task.id, finish_reason, elapsed)
        if retries:
            metadata["provider_retries"] = retries
        if length_retries:
            metadata["length_retries"] = length_retries
            metadata["effective_reasoning_effort"] = active_reasoning_effort
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
        payload = {
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
        self._apply_completion_budget(payload)
        self._apply_reasoning_effort(payload)
        return payload

    def _apply_completion_budget(self, payload: dict[str, Any]) -> None:
        if self.max_completion_tokens:
            payload["max_completion_tokens"] = self.max_completion_tokens

    def _apply_reasoning_effort(self, payload: dict[str, Any]) -> None:
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

    def _length_retry_reasoning_effort(self, effort: str | None) -> str | None:
        if effort in {"max", "xhigh"}:
            return "high"
        if effort == "high":
            return "medium"
        if effort == "medium":
            return "low"
        if effort == "low":
            return "minimal"
        return effort

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
            "reasoning_effort": self.reasoning_effort,
            "max_completion_tokens": self.max_completion_tokens,
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
        error = choice["error"]
        message = f"Provider choice error: {error}"
        if isinstance(error, dict) and _is_transient_error(
            code=error.get("code"),
            message=error.get("message"),
            metadata=error.get("metadata") if isinstance(error.get("metadata"), dict) else None,
        ):
            raise TransientProviderError(message)
        raise ProviderError(message)
    message = choice.get("message")
    if isinstance(message, dict):
        content = _content_text(message.get("content"))
        refusal = message.get("refusal")
    else:
        content = _content_text(choice.get("text"))
        refusal = choice.get("refusal")
    if not content.strip() and isinstance(refusal, str) and refusal.strip():
        raise GenerationValidationError(f"Provider refused to generate text: {refusal.strip()}")
    if not isinstance(content, str) or not content.strip():
        raise TransientProviderError("Provider response did not include text content")
    return content, choice.get("finish_reason")


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if not isinstance(text, str):
                    text = item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return ""


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
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            tree = ast.parse(source)
    except SyntaxError as error:
        location = f" line {error.lineno}" if error.lineno else ""
        raise GenerationValidationError(f"Generated output is not valid Python{location}: {error.msg}", source, metadata) from error
    if not any(isinstance(node, ast.ClassDef) and node.name == "MainScene" for node in ast.walk(tree)):
        raise GenerationValidationError("Generated output does not define class MainScene", source, metadata)


def system_prompt() -> str:
    return "Return only complete Manim Community Edition Python source code."


def _is_transient_error(code: Any = None, message: Any = None, metadata: dict[str, Any] | None = None) -> bool:
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = None
    if numeric_code in {408, 409, 425, 429, 500, 502, 503, 504, 529}:
        return True
    error_type = str((metadata or {}).get("error_type") or "").lower()
    if error_type in {"provider_unavailable", "rate_limited", "timeout", "server_error"}:
        return True
    text = str(message or "").lower()
    return any(
        marker in text
        for marker in [
            "upstream idle timeout",
            "timeout exceeded",
            "provider unavailable",
            "temporarily unavailable",
            "rate limit",
        ]
    )


def _is_length_finish_reason(finish_reason: str | None) -> bool:
    return str(finish_reason or "").strip().lower() in {"length", "max_tokens"}


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
