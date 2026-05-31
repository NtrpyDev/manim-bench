from __future__ import annotations

from typing import Protocol

from manimbench.models import ModelOutput, Task


class ModelProvider(Protocol):
    """Interface for model providers.

    API-backed providers should preserve the resolved benchmark prompt exactly,
    return raw Python source, and include reproducibility metadata such as model
    name, effort level, elapsed time, cost, and output tokens when available.
    """

    def generate(self, task: Task, prompt: str) -> ModelOutput:
        ...
