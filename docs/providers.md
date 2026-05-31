# Adding Model Providers

The initial provider is file-based: generate model outputs elsewhere, save each
task as `<task_id>.py`, and run ManimBench against that directory.

Future API providers should:

- Preserve `prompt.md` exactly.
- Append task payloads through `manimbench.prompting.build_task_prompt`.
- Record model name, provider, effort level, cost, elapsed time, and output token
  metadata when available.
- Store the raw generated source as `solution.py` for reproducibility.

The provider boundary is defined by `ModelProvider` in
`src/manimbench/providers/base.py`. The package includes `ApiProviderStub` as a
placeholder for future hosted model integrations.

For multiple manually generated models, use:

```bash
manimbench run-file-matrix \
  --model-output model-a=outputs/model-a \
  --model-output model-b=outputs/model-b
```
