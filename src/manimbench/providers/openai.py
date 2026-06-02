from __future__ import annotations

from typing import Any

from manimbench.model_registry import provider_config
from manimbench.providers.common import ChatCompletionProvider
from manimbench.reasoning import OPENAI_REASONING_EFFORTS, normalize_reasoning_effort


class OpenAIProvider(ChatCompletionProvider):
    def __init__(
        self,
        model_id: str,
        model_slug: str | None = None,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        reasoning_effort: str | None = None,
    ):
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
            reasoning_effort=reasoning_effort,
        )

    def _apply_reasoning_effort(self, payload: dict[str, Any]) -> None:
        effort = normalize_reasoning_effort(self.reasoning_effort, allowed_efforts=OPENAI_REASONING_EFFORTS)
        if effort is None and normalize_reasoning_effort(self.reasoning_effort) == "max":
            effort = "xhigh"
        if effort:
            payload["reasoning_effort"] = effort
