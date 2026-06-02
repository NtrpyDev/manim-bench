# Public Model Policy

Public leaderboard models live in `models/public.yaml`.

Rules for v0.6:

- Public API models should be routable through OpenRouter when OpenRouter
  publishes an official slug.
- `composer-2-5` is routed through Cursor Agent CLI because OpenRouter does not
  currently publish a Cursor Composer slug.
- Models marked `tier: pro`, `tier: enterprise`, `access: pro`,
  `access: enterprise`, or `access: private` are excluded from public listing.
- OpenRouter slugs live in `models/openrouter.yaml`.
- Provider defaults and model-specific overrides live in `models/providers.yaml`.
- Direct provider routes are optional bypasses for debugging or special runs.

The public list is CLI-visible:

```bash
manimbench list-models --public
```

Generation skips complete outputs unless `--force` is passed, so rerunning a
public batch does not pay again for already completed model/task outputs.
