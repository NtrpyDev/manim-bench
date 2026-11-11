# Routes

A route is a way of reaching models. Two exist, and both ship switched off in
`models/routes.yaml`. A route that is off refuses every call.

## OpenRouter

The route for benchmarking many vendors' models with one key and one bill.

1. Put the key in the environment as `OPENROUTER_API_KEY`. Setting a credit
   limit on the key itself caps spending on OpenRouter's side.
2. Copy `models/routes.yaml` to `models/routes.local.yaml` and set
   `enabled: true` under `openrouter` there. Local files are ignored by git, so
   the repository keeps shipping with every route off.
3. `manimbench models check` compares `models/models.yaml` with OpenRouter's
   live catalog: slugs, prices, and whether each model accepts images.

Each model is pinned to one upstream provider with fallbacks off
(`provider` in `models/models.yaml`), so every sample from a model is served
the same way. Requests send no temperature and no reasoning setting unless
the model's entry sets `reasoning_effort`, so each model runs at its own
defaults. The cost recorded is the one OpenRouter reports, summed across
retries.

Unverified until the first live call: that OpenRouter accepts the provider
tags in `models/models.yaml` exactly as written.

## Claude subscription

Calls Claude through the Claude Code command line, on a Claude subscription
rather than an API key. It is for checking the pipeline end to end before
paying for API calls.

1. `claude` must be installed and logged in.
2. Set `enabled: true` under `claude-cli` in `models/routes.local.yaml`.
3. Pass `--route claude-cli` to `generate` or `run`. To judge through it,
   copy `models/judges.yaml` to `models/judges.local.yaml`, set
   `route: claude-cli` there, and list only Claude models.

The command line is an agent by default. This route turns that off: no tools,
no project files, no user settings or memory, the benchmark's own system
prompt, and an empty working folder. The cost it records is what the tokens
would cost at API prices, not money spent, and it is labeled that way.
Calls count against the subscription's usage limits.

Unverified until the first live call: the exact shape of the command line's
JSON reply, and sending images through streamed input.

## Adding a model

Add an entry to `models/models.yaml` with an `openrouter` route (slug and
provider tag from OpenRouter's catalog) and run `manimbench models check`.
