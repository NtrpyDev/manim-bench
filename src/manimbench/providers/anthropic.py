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


class AnthropicProvider:
    def __init__(
        self,
        model_id: str,
        model_slug: str | None = None,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        timeout_seconds: int = 240,
        max_tokens: int = 8192,
    ):
        config = provider_config("anthropic")
        self.provider_name = "anthropic"
        self.route = "direct"
        self.model_id = model_id
        self.model_slug = model_slug or model_id
        self.base_url = str(config.get("base_url", "https://api.anthropic.com/v1")).rstrip("/")
        self.api_key_env = str(config.get("env_key", "ANTHROPIC_API_KEY"))
        self.api_key = api_key or os.getenv(self.api_key_env)
        self.client = client or HttpJsonClient()
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        if not self.api_key:
            raise ProviderError(f"{self.api_key_env} is required for provider {self.provider_name}")

    def generate(self, task: Task, prompt: str) -> ModelOutput:
        started = time.monotonic()
        response = self.client.post_json(
            f"{self.base_url}/messages",
            headers={
                "x-api-key": str(self.api_key),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload={
                "model": self.model_slug,
                "max_tokens": self.max_tokens,
                "system": system_prompt(),
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout_seconds,
        )
        elapsed = time.monotonic() - started
        content = _anthropic_text(response)
        finish_reason = response.get("stop_reason")
        usage = response.get("usage", {}) if isinstance(response.get("usage"), dict) else {}
        metadata = metadata_payload(
            provider=self.provider_name,
            route=self.route,
            model_id=self.model_id,
            model_slug=self.model_slug,
            task_id=task.id,
            request_id=response.get("id"),
            response_model=response.get("model"),
            finish_reason=finish_reason,
            elapsed_seconds=elapsed,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=_sum_tokens(usage.get("input_tokens"), usage.get("output_tokens")),
            usage=usage,
        )
        if finish_reason and finish_reason not in {"end_turn", "stop_sequence"}:
            raise GenerationValidationError(f"Incomplete provider response: stop_reason={finish_reason}", content, metadata)
        source = cleanup_generated_source(content)
        validate_main_scene(source, metadata=metadata)
        return ModelOutput(model=self.model_id, task_id=task.id, source=source, metadata=metadata)


def _anthropic_text(response: dict[str, Any]) -> str:
    blocks = response.get("content")
    if not isinstance(blocks, list):
        raise ProviderError("Anthropic response did not include content blocks")
    parts = [str(block.get("text", "")) for block in blocks if isinstance(block, dict) and block.get("type") == "text"]
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        raise GenerationValidationError("Anthropic response did not include text content")
    return text


def _sum_tokens(input_tokens: Any, output_tokens: Any) -> int | None:
    if input_tokens is None and output_tokens is None:
        return None
    return int(input_tokens or 0) + int(output_tokens or 0)
