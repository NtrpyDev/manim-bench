"""What every model route takes and returns."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

FORBID_LIVE_CALLS_ENV = "MANIMBENCH_FORBID_LIVE_CALLS"


class ProviderError(RuntimeError):
    """The call failed for a reason that says nothing about the model's answer."""


class TransientProviderError(ProviderError):
    """Worth retrying: rate limit, timeout, server error."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class RouteDisabledError(ProviderError):
    """The route is switched off in models/routes.yaml."""


class LiveCallForbiddenError(ProviderError):
    """A real model call was attempted where none is allowed (the test suite)."""


def assert_live_calls_allowed(what: str) -> None:
    if os.environ.get(FORBID_LIVE_CALLS_ENV):
        raise LiveCallForbiddenError(f"{what}: live model calls are forbidden while {FORBID_LIVE_CALLS_ENV} is set")


@dataclass(frozen=True)
class Request:
    system: str
    prompt: str
    images: list[Path] = field(default_factory=list)
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class Completion:
    text: str
    route: str
    requested_model: str
    response_model: str | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None
    cost_basis: str | None = None
    elapsed_seconds: float = 0.0
    attempts: int = 1

    def metadata(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "requested_model": self.requested_model,
            "response_model": self.response_model,
            "request_id": self.request_id,
            "finish_reason": self.finish_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": self.cost_usd,
            "cost_basis": self.cost_basis,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "attempts": self.attempts,
        }


class Route(Protocol):
    name: str

    def complete(self, target: dict[str, Any], request: Request) -> Completion:
        """Send one request to the model described by ``target`` (this route's entry for a model)."""
        ...
