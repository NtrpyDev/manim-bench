# Cursor Composer 2.5

Composer 2.5 is not currently available as an OpenRouter chat-completions model.
ManimBench therefore treats it as a Cursor Agent CLI provider.

## Setup

Install and authenticate Cursor Agent CLI:

```bash
curl https://cursor.com/install -fsSL | bash
cursor-agent login
cursor-agent status
```

For headless automation, create a Cursor user API key in the Cursor dashboard
and export it instead:

```bash
export CURSOR_API_KEY=...
```

## Generate

Use the engine provider directly:

```bash
manimbench generate \
  --model composer-2-5 \
  --provider cursor \
  --output-dir outputs \
  --smoke

manimbench generate \
  --model composer-2-5 \
  --provider cursor \
  --output-dir outputs
```

`--provider auto` also resolves `composer-2-5` to `cursor`.

The provider runs Cursor Agent in print mode:

```text
cursor-agent -p --output-format text --model "Composer 2.5" <task prompt>
```

The engine writes one generated file per task under:

```text
outputs/composer-2-5/<task_id>.py
```

It still applies normal v0.6 safety behavior: completed files are skipped
unless `--force` is passed, checkpoint state is stored under
`.manimbench/runs/<run_id>/state.json`, and call records are appended to
`.manimbench/runs/<run_id>/generation.log`.

Cursor Agent CLI does not return token counts or cost fields, so ManimBench
cannot fill those values in `usage.json`; use the Cursor dashboard for exact
Composer spend.

## Render And Report

```bash
manimbench run-file-matrix \
  --model-output composer-2-5=outputs/composer-2-5 \
  --sandbox container \
  --parallel 4 \
  --run-id v05-composer-2-5

manimbench report --run-dir runs/v05-composer-2-5
```

## Workspace Fallback

If you prefer using the Cursor editor instead of headless CLI:

```bash
manimbench create-workspaces --model composer-2-5 --force
cursor model_tests/composer-2-5
```

In Cursor, select Composer 2.5 and ask it to read `AGENTS.md` and `tasks/*.md`,
then write the solutions to `outputs/*.py`. Run `./run_benchmark.sh` from that
workspace when generation is complete.
