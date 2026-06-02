from __future__ import annotations


REASONING_EFFORT_CHOICES = ("default", "minimal", "low", "medium", "high", "xhigh", "max")
PROVIDER_REASONING_EFFORTS = set(REASONING_EFFORT_CHOICES) - {"default"}
ANTHROPIC_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
OPENAI_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}
OPENROUTER_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}
XAI_REASONING_EFFORTS = {"low", "medium", "high"}

_EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max")

_ANTHROPIC_XHIGH_MODELS = {"claude-opus-4-8", "claude-opus-4-7"}
_ANTHROPIC_MAX_MODELS = {
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
}
_ANTHROPIC_HIGH_EFFORT_MODELS = {
    *_ANTHROPIC_MAX_MODELS,
    "claude-opus-4-5",
}


def normalize_reasoning_effort(value: str | None, *, allowed_efforts: set[str] | None = None) -> str | None:
    effort = str(value or "").strip().lower()
    if not effort or effort == "default":
        return None
    if effort not in (allowed_efforts or PROVIDER_REASONING_EFFORTS):
        return None
    return effort


def normalize_anthropic_reasoning_effort(value: str | None) -> str | None:
    effort = normalize_reasoning_effort(value)
    if effort == "minimal":
        return "low"
    return normalize_reasoning_effort(effort, allowed_efforts=ANTHROPIC_REASONING_EFFORTS)


def anthropic_reasoning_effort_for_model(model_slug: str, value: str | None) -> str | None:
    effort = normalize_anthropic_reasoning_effort(value)
    if not effort:
        return None
    allowed = _anthropic_efforts_for_model(model_slug)
    if not allowed:
        return effort
    return _cap_effort(effort, allowed)


def anthropic_adaptive_thinking_supported(model_slug: str) -> bool:
    return _canonical_anthropic_slug(model_slug) in {
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
    }


def google_thinking_config_for_model(model_slug: str, value: str | None) -> dict[str, int | str] | None:
    effort = normalize_reasoning_effort(value)
    if not effort:
        return None
    slug = model_slug.lower()
    if "gemini-3" in slug:
        if effort in {"xhigh", "max"}:
            level = "high"
        elif effort == "minimal" and "gemini-3.1-pro" in slug:
            level = "low"
        else:
            level = effort
        return {"thinkingLevel": level}
    if "gemini-2.5" in slug:
        budgets = {
            "minimal": 0,
            "low": 1024,
            "medium": -1,
            "high": 24576,
            "xhigh": 24576,
            "max": 24576,
        }
        return {"thinkingBudget": budgets[effort]}
    return None


def openrouter_reasoning_effort_for_model(model_slug: str, value: str | None) -> str | None:
    effort = normalize_reasoning_effort(value)
    if not effort:
        return None
    slug = model_slug.lower()
    if effort == "max":
        if slug.startswith("google/") and "gemini-3" in slug:
            return "high"
        return "xhigh"
    if slug.startswith("google/") and "gemini-3" in slug and effort == "xhigh":
        return "high"
    return normalize_reasoning_effort(effort, allowed_efforts=OPENROUTER_REASONING_EFFORTS)


def openrouter_verbosity_for_model(model_slug: str, value: str | None) -> str | None:
    if not model_slug.lower().startswith("anthropic/"):
        return None
    effort = normalize_anthropic_reasoning_effort(value)
    if not effort:
        return None
    allowed = _anthropic_efforts_for_model(model_slug)
    if not allowed:
        return None
    return _cap_effort(effort, allowed)


def xai_reasoning_effort_for_model(value: str | None) -> str | None:
    effort = normalize_reasoning_effort(value)
    if effort in {"max", "xhigh"}:
        return "high"
    return normalize_reasoning_effort(effort, allowed_efforts=XAI_REASONING_EFFORTS)


def stored_reasoning_effort(value: str | None) -> str:
    return normalize_reasoning_effort(value) or "default"


def display_reasoning_effort(value: str | None) -> str:
    return stored_reasoning_effort(value)


def _anthropic_efforts_for_model(model_slug: str) -> set[str]:
    slug = _canonical_anthropic_slug(model_slug)
    if slug in _ANTHROPIC_XHIGH_MODELS:
        return {"low", "medium", "high", "xhigh", "max"}
    if slug in _ANTHROPIC_MAX_MODELS:
        return {"low", "medium", "high", "max"}
    if slug in _ANTHROPIC_HIGH_EFFORT_MODELS:
        return {"low", "medium", "high"}
    return set()


def _canonical_anthropic_slug(model_slug: str) -> str:
    slug = model_slug.strip().lower().replace("_", "-").replace(".", "-")
    if "/" in slug:
        slug = slug.split("/", 1)[1]
    if not slug.startswith("claude-") and slug.startswith(("opus-", "sonnet-", "haiku-")):
        slug = f"claude-{slug}"
    return slug


def _cap_effort(effort: str, allowed: set[str]) -> str:
    if effort in allowed:
        return effort
    requested_index = _EFFORT_ORDER.index(effort)
    for candidate in reversed(_EFFORT_ORDER[: requested_index + 1]):
        if candidate in allowed:
            return candidate
    return min(allowed, key=_EFFORT_ORDER.index)
