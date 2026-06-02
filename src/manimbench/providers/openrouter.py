from __future__ import annotations

from typing import Any

from manimbench.model_registry import openrouter_slug, provider_config
from manimbench.providers.common import ChatCompletionProvider, HttpJsonClient, ProviderError
from manimbench.reasoning import openrouter_reasoning_effort_for_model, openrouter_verbosity_for_model


OPENROUTER_DEFAULT_MAX_COMPLETION_TOKENS = 65536
_AUTO_MAX_COMPLETION_TOKENS = object()


class OpenRouterProvider(ChatCompletionProvider):
    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        timeout_seconds: int = 240,
        base_url: str | None = None,
        model_slug: str | None = None,
        reasoning_effort: str | None = None,
        max_completion_tokens: int | None | object = _AUTO_MAX_COMPLETION_TOKENS,
        max_retries: int = 2,
        retry_backoff_seconds: float = 2.0,
        max_length_retries: int = 1,
    ):
        config = provider_config("openrouter")
        model_slug = model_slug or openrouter_slug(model_id)
        completion_budget = (
            _default_max_completion_tokens_for_model(model_slug)
            if max_completion_tokens is _AUTO_MAX_COMPLETION_TOKENS
            else max_completion_tokens
        )
        super().__init__(
            provider_name="openrouter",
            route="openrouter",
            model_id=model_id,
            model_slug=model_slug,
            api_key_env=str(config.get("env_key", "OPENROUTER_API_KEY")),
            base_url=base_url or str(config.get("base_url", "https://openrouter.ai/api/v1")),
            api_key=api_key,
            client=client,
            timeout_seconds=timeout_seconds,
            reasoning_effort=reasoning_effort,
            max_completion_tokens=completion_budget if isinstance(completion_budget, int) else None,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_length_retries=max_length_retries,
        )

    def _apply_completion_budget(self, payload: dict[str, Any]) -> None:
        if self.max_completion_tokens:
            payload["max_tokens"] = self.max_completion_tokens

    def _apply_reasoning_effort(self, payload: dict[str, Any]) -> None:
        effort = openrouter_reasoning_effort_for_model(self.model_slug, self.reasoning_effort)
        if effort:
            payload["reasoning"] = {"effort": effort}
        verbosity = openrouter_verbosity_for_model(self.model_slug, self.reasoning_effort)
        if verbosity:
            payload["verbosity"] = verbosity

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers.update(
            {
                "HTTP-Referer": "https://manimbench.site",
                "X-OpenRouter-Title": "ManimBench",
            }
        )
        return headers

    @staticmethod
    def fetch_model_metadata(*, api_key: str | None = None, client: Any | None = None, base_url: str | None = None) -> dict[str, Any]:
        config = provider_config("openrouter")
        key = api_key
        if key is None:
            import os

            key = os.getenv(str(config.get("env_key", "OPENROUTER_API_KEY")))
        http = client or HttpJsonClient()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return http.get_json(
            f"{(base_url or str(config.get('base_url', 'https://openrouter.ai/api/v1'))).rstrip('/')}/models",
            headers=headers,
            timeout=60,
        )


def _default_max_completion_tokens_for_model(model_slug: str) -> int | None:
    slug = model_slug.lower()
    if slug.startswith("openai/") and ("gpt-5" in slug or "codex" in slug):
        return OPENROUTER_DEFAULT_MAX_COMPLETION_TOKENS
    return None
