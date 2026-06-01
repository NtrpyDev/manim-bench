from __future__ import annotations

import os
import time
from typing import Any

from manimbench.model_registry import provider_config
from manimbench.models import ModelOutput, Task
from manimbench.providers.common import (
    GenerationValidationError,
    HttpJsonClient,
    ProviderError,
    cleanup_generated_source,
    metadata_payload,
    system_prompt,
    validate_main_scene,
)


class GoogleProvider:
    def __init__(
        self,
        model_id: str,
        model_slug: str | None = None,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        timeout_seconds: int = 240,
    ):
        config = provider_config("google")
        self.provider_name = "google"
        self.route = "direct"
        self.model_id = model_id
        self.model_slug = model_slug or model_id
        self.base_url = str(config.get("base_url", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
        self.api_key_env = str(config.get("env_key", "GOOGLE_API_KEY"))
        self.api_key = api_key or os.getenv(self.api_key_env)
        self.client = client or HttpJsonClient()
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise ProviderError(f"{self.api_key_env} is required for provider {self.provider_name}")

    def generate(self, task: Task, prompt: str) -> ModelOutput:
        started = time.monotonic()
        response = self.client.post_json(
            f"{self.base_url}/models/{self.model_slug}:generateContent?key={self.api_key}",
            headers={"Content-Type": "application/json"},
            payload={
                "systemInstruction": {"parts": [{"text": system_prompt()}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            },
            timeout=self.timeout_seconds,
        )
        elapsed = time.monotonic() - started
        content, finish_reason = _google_text(response)
        usage = response.get("usageMetadata", {}) if isinstance(response.get("usageMetadata"), dict) else {}
        metadata = metadata_payload(
            provider=self.provider_name,
            route=self.route,
            model_id=self.model_id,
            model_slug=self.model_slug,
            task_id=task.id,
            request_id=response.get("responseId"),
            response_model=response.get("modelVersion"),
            finish_reason=finish_reason,
            elapsed_seconds=elapsed,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            total_tokens=usage.get("totalTokenCount"),
            usage=usage,
        )
        if finish_reason and finish_reason not in {"STOP", "FINISH_REASON_UNSPECIFIED"}:
            raise GenerationValidationError(f"Incomplete provider response: finish_reason={finish_reason}", content, metadata)
        source = cleanup_generated_source(content)
        validate_main_scene(source, metadata=metadata)
        return ModelOutput(model=self.model_id, task_id=task.id, source=source, metadata=metadata)


def _google_text(response: dict[str, Any]) -> tuple[str, str | None]:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ProviderError("Google response did not include candidates")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ProviderError("Google candidate was not an object")
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ProviderError("Google candidate did not include content parts")
    text = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict) and part.get("text")).strip()
    if not text:
        raise GenerationValidationError("Google response did not include text content")
    return text, candidate.get("finishReason")
