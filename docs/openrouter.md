# OpenRouter

OpenRouter is the default API gateway for public v0.5a model generation when
the model is published in OpenRouter's catalog. `composer-2-5` is the exception:
OpenRouter does not currently publish a Cursor Composer slug, so ManimBench
routes actual Composer 2.5 generation through Cursor Agent CLI.

## Model Mapping

ManimBench model IDs are stable benchmark IDs. OpenRouter model slugs are kept
separately in `models/openrouter.yaml` so display names and routes can change
without changing result IDs.

Check the local mapping:

```bash
manimbench list-models --public
```

Fetch the OpenRouter catalog through the orchestrator API:

```python
from manimbench.orchestrator import fetch_openrouter_catalog

catalog = fetch_openrouter_catalog()
```

## Generate

```bash
export OPENROUTER_API_KEY=...
manimbench generate-batch \
  --models gpt-5-5,opus-4-8 \
  --provider auto \
  --smoke
```

The generation path uses the same prompt builder as file-backed runs:
`manimbench.prompting.build_task_prompt`.

## Accounting

Each provider call is logged as JSONL at:

```text
.manimbench/runs/<run_id>/generation.log
```

Each line includes request ID, provider route, model slug, task ID, token counts,
cost when returned by OpenRouter, elapsed seconds, timestamp, and status.

The per-model `usage.json` summary is written to:

```text
outputs/<model>/usage.json
```

For Composer 2.5, use:

```bash
cursor-agent login
manimbench generate --model composer-2-5 --provider cursor
```

See [providers.md](providers.md) for the Cursor route.
