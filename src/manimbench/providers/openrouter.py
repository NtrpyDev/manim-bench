from __future__ import annotations

from typing import Any

from manimbench.model_registry import openrouter_slug, provider_config
from manimbench.providers.common import ChatCompletionProvider, HttpJsonClient, ProviderError


class OpenRouterProvider(ChatCompletionProvider):
    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        timeout_seconds: int = 240,
        base_url: str | None = None,
    ):
        config = provider_config("openrouter")
        super().__init__(
            provider_name="openrouter",
            route="openrouter",
            model_id=model_id,
            model_slug=openrouter_slug(model_id),
            api_key_env=str(config.get("env_key", "OPENROUTER_API_KEY")),
            base_url=base_url or str(config.get("base_url", "https://openrouter.ai/api/v1")),
            api_key=api_key,
            client=client,
            timeout_seconds=timeout_seconds,
        )

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
