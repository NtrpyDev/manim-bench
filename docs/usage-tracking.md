# Usage Tracking

ManimBench tracks:

- Wall-clock generation time.
- Prompt/input tokens from the active suite's `tasks/*.md`.
- Output tokens from the active suite's generated `outputs/*.py`.
- Estimated USD cost from configured per-model rates in `models/public.yaml`.
- Real provider token and cost fields when returned by API-backed generation.

For model workspace runs:

```bash
./start_usage.sh
# generate outputs with the selected model
./run_benchmark.sh
```

Generated model workspaces use explicit shell scripts so the timing contract is
the same across coding agents.

`run_benchmark.sh` automatically writes:

```text
usage.json
```

For already-finished model workspaces, backfill usage with:

```bash
cd manimbench
python collect_usage.py
```

The default is V0.6 suite-scoped accounting, so it counts the six default
`tasks/<task_id>.md` prompts and matching `outputs/<task_id>.py` files. To
backfill earlier suite folders, pass the suite explicitly:

```bash
python collect_usage.py --suite benchmarks/v0.4/suite.yaml
python collect_usage.py --suite benchmarks/v0.3/suite.yaml
```

Token counts use ManimBench's deterministic tokenizer over the benchmark-visible
prompt and generated source files. USD is computed from the pricing table, so
every model has a comparable estimated cost number.
