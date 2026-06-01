# Providers

ManimBench v0.5a has two provider paths:

- `auto` is the default. It routes most public models through OpenRouter and
  routes `composer-2-5` through Cursor Agent CLI.
- `openrouter` is the default API gateway for public models that OpenRouter
  actually publishes.
- `cursor` is the local/headless Cursor Agent CLI route for Composer 2.5.
- Direct providers are optional bypasses for debugging or special runs.

Provider configuration lives in:

- `models/public.yaml` for public model IDs, display names, tokenizers, and rates.
- `models/openrouter.yaml` for public model ID to OpenRouter slug mapping.
- `models/providers.yaml` for provider base URLs, CLI commands, API key
  environment names, and model-specific provider overrides.

## OpenRouter

Use OpenRouter for public API models:

```bash
export OPENROUTER_API_KEY=...
manimbench generate --model gpt-5-5 --provider openrouter
```

OpenRouter uses `POST https://openrouter.ai/api/v1/chat/completions` and
`GET https://openrouter.ai/api/v1/models`.

## Cursor Composer

Cursor does not currently publish Composer 2.5 through OpenRouter. To benchmark
actual Composer 2.5, use Cursor Agent CLI with a Cursor account that has
Composer access:

```bash
curl https://cursor.com/install -fsSL | bash
cursor-agent login
cursor-agent status

manimbench generate \
  --model composer-2-5 \
  --provider cursor \
  --output-dir outputs \
  --smoke
```

For automation, create a Cursor user API key in the Cursor dashboard and export
it before running the benchmark:

```bash
export CURSOR_API_KEY=...
manimbench generate --model composer-2-5 --provider cursor
```

The Cursor provider invokes:

```text
cursor-agent -p --output-format text --model "Composer 2.5" <prompt>
```

The engine captures stdout, strips code fences, validates `class MainScene`,
writes `outputs/composer-2-5/<task_id>.py`, and logs the call under
`.manimbench/runs/<run_id>/generation.log`. Cursor CLI does not return token or
cost fields, so spend accounting comes from the Cursor dashboard.

## Direct Bypasses

Direct routes are selected explicitly:

```bash
manimbench generate --model gpt-5-test --provider openai
manimbench generate --model claude-test --provider anthropic
manimbench generate --model gemini-test --provider google
manimbench generate --model grok-test --provider xai
```

Environment variables:

| Provider | Env var |
| --- | --- |
| OpenRouter | `OPENROUTER_API_KEY` |
| Cursor | `CURSOR_API_KEY` optional; browser login also works |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google | `GOOGLE_API_KEY` |
| xAI | `XAI_API_KEY` |

All provider adapters strip Markdown code fences, require `class MainScene`,
and return provider usage metadata when the API response includes token or cost
fields.

## File Provider

File-backed runs remain supported for reproduction and review:

```bash
manimbench run-file-matrix \
  --model-output model-a=outputs/model-a \
  --model-output model-b=outputs/model-b
```
