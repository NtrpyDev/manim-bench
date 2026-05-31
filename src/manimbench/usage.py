from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from manimbench.paths import PROJECT_ROOT
from manimbench.tasks import load_suite


MODEL_REGISTRY = PROJECT_ROOT / "models" / "models.yaml"
MODEL_TESTS_ROOT = PROJECT_ROOT / "model_tests"


def start_usage(args: argparse.Namespace) -> int:
    model_dir = Path(args.model_dir).resolve()
    state_dir = model_dir / ".manimbench"
    state_dir.mkdir(parents=True, exist_ok=True)
    start_path = state_dir / "usage_start.json"
    if start_path.exists() and not args.force:
        print(f"Usage timer already exists for {model_dir.name}")
        return 0
    suite_path = Path(args.suite).resolve() if getattr(args, "suite", None) else None
    expected_outputs = _suite_files(model_dir / "outputs", ".py", suite_path) if suite_path else sorted((model_dir / "outputs").glob("*.py"))
    payload = {
        "schema_version": "0.1.0",
        "model_id": model_dir.name,
        "started_at": _now_iso(),
        "started_at_epoch": time.time(),
        "suite_path": str(suite_path) if suite_path else None,
        "output_baseline": {
            str(path): path.stat().st_mtime for path in expected_outputs if path.exists()
        },
        "note": "Generation timer started before model output generation.",
    }
    start_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Started usage timer for {model_dir.name}")
    return 0


def finish_usage(args: argparse.Namespace) -> int:
    model_dir = Path(args.model_dir).resolve()
    payload = build_usage_payload(model_dir, suite_path=args.suite)
    output_path = model_dir / "usage.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote usage: {output_path}")
    print(
        f"{payload['model_id']}: input={payload['tokens']['input_tokens']} "
        f"output={payload['tokens']['output_tokens']} total={payload['tokens']['total_tokens']} "
        f"cost=${payload['cost']['estimated_usd']:.6f} time={payload['time']['elapsed_seconds']:.1f}s"
    )
    return 0


def collect_all_usage(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    rows = []
    suite_path = Path(args.suite).resolve() if args.suite else None
    for model_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if not (model_dir / "outputs").exists():
            continue
        output_files = _suite_files(model_dir / "outputs", ".py", suite_path)
        if not args.include_empty and not output_files:
            continue
        payload = build_usage_payload(model_dir, suite_path=suite_path)
        (model_dir / "usage.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        rows.append(payload)

    out_dir = PROJECT_ROOT / "usage"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"usage-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    output_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote aggregate usage: {output_path}")
    for payload in rows:
        print(
            f"{payload['model_id']}\t{payload['tokens']['total_tokens']}\t"
            f"${payload['cost']['estimated_usd']:.6f}\t{payload['time']['elapsed_seconds']:.1f}s"
        )
    return 0


def build_usage_payload(model_dir: Path, suite_path: Path | None = None) -> dict[str, Any]:
    model_id = model_dir.name
    registry = _load_model_registry()
    model = registry.get(model_id, {"id": model_id, "display_name": model_id})
    pricing = _pricing_for(model)
    tokenizer = _tokenizer_for(model)
    suite = load_suite(suite_path) if suite_path else None
    prompt_files = _suite_files(model_dir / "tasks", ".md", suite_path)
    output_files = _suite_files(model_dir / "outputs", ".py", suite_path)

    input_tokens = sum(count_tokens(path.read_text(encoding="utf-8", errors="ignore"), tokenizer) for path in prompt_files)
    output_tokens = sum(count_tokens(path.read_text(encoding="utf-8", errors="ignore"), tokenizer) for path in output_files)
    cost = estimate_cost(input_tokens, output_tokens, pricing)
    time_payload = _time_payload(model_dir, output_files)

    return {
        "schema_version": "0.4.0",
        "model_id": model_id,
        "display_name": model.get("display_name", model_id),
        "suite": {
            "id": suite.id if suite else None,
            "version": suite.version if suite else None,
            "path": str(suite_path) if suite_path else None,
        },
        "pricing": pricing,
        "tokens": {
            "tokenizer": tokenizer["id"],
            "tokenizer_method": tokenizer["method"],
            "input_files": len(prompt_files),
            "output_files": len(output_files),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        "cost": cost,
        "time": time_payload,
        "generated_at": _now_iso(),
    }


def _suite_files(root: Path, suffix: str, suite_path: Path | None) -> list[Path]:
    if not suite_path:
        return sorted(root.glob(f"*{suffix}"))
    suite = load_suite(suite_path)
    return sorted(path for task in suite.tasks if (path := root / f"{task.id}{suffix}").exists())


def count_tokens(text: str, tokenizer: dict[str, Any] | str | None = None) -> int:
    """Deterministic token estimator for benchmark accounting.

    This is not a provider billing counter. It is a reproducible benchmark token
    counter over exactly what the model saw in task prompts and wrote in source.
    """

    tokenizer_id = tokenizer["id"] if isinstance(tokenizer, dict) else tokenizer
    if tokenizer_id in {"openai_estimate_v1", "anthropic_estimate_v1", "gemini_estimate_v1", "xai_estimate_v1"}:
        return _char_token_estimate(text, chars_per_token=4.0)
    return _regex_token_estimate(text)


def _regex_token_estimate(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


def _char_token_estimate(text: str, chars_per_token: float) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / chars_per_token))


def estimate_cost(input_tokens: int, output_tokens: int, pricing: dict[str, Any]) -> dict[str, Any]:
    input_rate = float(pricing["input_usd_per_1m_tokens"])
    output_rate = float(pricing["output_usd_per_1m_tokens"])
    input_cost = input_tokens * input_rate / 1_000_000
    output_cost = output_tokens * output_rate / 1_000_000
    return {
        "currency": "USD",
        "method": pricing["method"],
        "pricing_source": pricing.get("source", pricing["method"]),
        "input_usd": round(input_cost, 6),
        "output_usd": round(output_cost, 6),
        "estimated_usd": round(input_cost + output_cost, 6),
    }


def _time_payload(model_dir: Path, output_files: list[Path]) -> dict[str, Any]:
    start_path = model_dir / ".manimbench" / "usage_start.json"
    finished_at = time.time()
    if start_path.exists():
        start = json.loads(start_path.read_text(encoding="utf-8"))
        started_at_epoch = float(start["started_at_epoch"])
        method = "explicit_start_finish"
    elif output_files:
        started_at_epoch = min(path.stat().st_mtime for path in output_files)
        finished_at = max(path.stat().st_mtime for path in output_files)
        method = "output_file_timestamp_window"
    else:
        started_at_epoch = finished_at
        method = "no_outputs"

    return {
        "method": method,
        "started_at": datetime.fromtimestamp(started_at_epoch, timezone.utc).isoformat(),
        "finished_at": datetime.fromtimestamp(finished_at, timezone.utc).isoformat(),
        "elapsed_seconds": max(0.0, finished_at - started_at_epoch),
    }


def _load_model_registry() -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(MODEL_REGISTRY.read_text(encoding="utf-8")) or {}
    return {item["id"]: item for item in data.get("models", [])}


def _pricing_for(model: dict[str, Any]) -> dict[str, Any]:
    pricing = dict(model.get("pricing", {}))
    if pricing:
        return {
            "method": pricing.get("method", "configured_model_rate"),
            "source": pricing.get("source", "models/models.yaml"),
            "input_usd_per_1m_tokens": float(pricing["input_usd_per_1m_tokens"]),
            "output_usd_per_1m_tokens": float(pricing["output_usd_per_1m_tokens"]),
        }
    return {
        "method": "default_benchmark_estimate_rate",
        "source": "manimbench_default",
        "input_usd_per_1m_tokens": 3.0,
        "output_usd_per_1m_tokens": 15.0,
    }


def _tokenizer_for(model: dict[str, Any]) -> dict[str, str]:
    if model.get("tokenizer"):
        return {"id": str(model["tokenizer"]), "method": "configured_model_tokenizer"}
    model_id = str(model.get("id", "")).lower()
    display = str(model.get("display_name", "")).lower()
    name = f"{model_id} {display}"
    if any(marker in name for marker in ["gpt", "codex"]):
        return {"id": "openai_estimate_v1", "method": "provider_family_estimate"}
    if any(marker in name for marker in ["opus", "sonnet", "haiku", "claude"]):
        return {"id": "anthropic_estimate_v1", "method": "provider_family_estimate"}
    if "gemini" in name:
        return {"id": "gemini_estimate_v1", "method": "provider_family_estimate"}
    if "grok" in name or "xai" in name:
        return {"id": "xai_estimate_v1", "method": "provider_family_estimate"}
    return {"id": "manimbench_regex_estimator_v1", "method": "deterministic_fallback"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
