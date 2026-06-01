from __future__ import annotations

from typing import Any

from manimbench.model_registry import provider_config
from manimbench.providers.common import ChatCompletionProvider


class OpenAIProvider(ChatCompletionProvider):
    def __init__(self, model_id: str, model_slug: str | None = None, *, api_key: str | None = None, client: Any | None = None):
        config = provider_config("openai")
        super().__init__(
            provider_name="openai",
            route="direct",
            model_id=model_id,
            model_slug=model_slug or model_id,
            api_key_env=str(config.get("env_key", "OPENAI_API_KEY")),
            base_url=str(config.get("base_url", "https://api.openai.com/v1")),
            api_key=api_key,
            client=client,
        )
