from __future__ import annotations

from manimbench.models import ModelOutput, Task


class ApiProviderStub:
    """Placeholder for future hosted model integrations.

    This intentionally raises until a real provider is implemented. Keeping the
    stub in the package documents the adapter boundary without adding an
    untested dependency on any one model API.
    """

    def generate(self, task: Task, prompt: str) -> ModelOutput:
        del task, prompt
        raise NotImplementedError("API-backed providers are not implemented yet.")
