# Codex Job Usage

For every user message that receives a final assistant reply, track Codex token usage and estimated USD cost with `codex-job-usage`.

- Start a snapshot before doing the work for that user message: `codex-job-usage start "<short-task-label>"`.
- Finish the snapshot immediately before sending the final reply in that response chain: `codex-job-usage finish "<short-task-label>"`.
- Include the message/job delta tokens, message/job delta cost in USD, and today total from the command output in the final reply.
- Do not announce that usage tracking is running or that the final reply will include usage; just run the tool and report the numbers.
- The final reply must contain only raw numbers in this exact one-line format: `<delta_tokens> tokens, $<delta_cost>; today <today_tokens> tokens, $<today_cost>`. Do not add labels like "This message", status text, summaries, acknowledgements, explanations, bullets, or extra lines.
- Treat one completed user message as one tracked job. If the user explicitly splits work into multiple jobs, start and finish each one separately.
- If the command fails, say so briefly and continue the user task.

Known limitation: the final response tokens may not be included because the finish snapshot is taken before the final answer is sent.

# TLDR Responses

When the user asks for a TLDR, answer the actual question in the first sentence. Additional context may follow, but the first sentence must contain the decision, conclusion, or requested fact.

# Direct Capability Answers

When the user asks whether Codex can do something, answer the exact requested outcome first. If any required part of the requested outcome cannot be done, the answer is `no`; do not reframe a partial workaround as `yes`, and do not add excuse-like context before the direct answer.

# Release Version Labels

When an engine, scoring, report schema, or benchmark release changes the version number, all active user-facing labels, site data, docs, default suite metadata, and current-run examples must use the new release version only. Older version numbers may appear only in explicitly historical/archive/reproduction contexts, never in the current release title, suite label, leaderboard label, homepage status, or default workflow copy.
