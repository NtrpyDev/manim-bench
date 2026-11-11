"""The vision judge: what it is asked, and how its reply becomes a score.

The judge never sees which model made the video or the code behind it. It
sees frames from the rendered video in time order, the text that was on
screen at each frame, the task, and reference facts for checking the maths.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from manimbench.models import Suite, Task

MAX_SCORE = 4
VERDICT_VALUES = {"yes": 1.0, "partial": 0.5, "no": 0.0}
DEFAULT_MAX_FRAMES = 12
FRAME_LEAD_SECONDS = 0.05

JUDGE_SYSTEM_PROMPT = """\
You are grading a silent mathematics animation for a benchmark of teaching quality.

You are shown still frames from the video in time order. For each frame you also get the text that was on screen, read directly from the renderer, so you can trust it even when the frame is small.

Rules:
- Grade only what the frames and on-screen text show. Do not give credit for anything you cannot see.
- A student is the audience. They have not seen this idea before and there is no narration.
- Be strict and consistent. Most real videos have problems; say what they are.
- Wrong mathematics on screen is serious even when the video looks polished.
- Do not reward length, decoration, or the amount of text.
- Reply with one JSON object and nothing else."""

SCALE_TEXT = """\
0 = absent, or wrong throughout
1 = serious problems; fails more than it succeeds
2 = mixed; real strengths and real problems
3 = good; only minor problems
4 = excellent; nothing of substance to fix"""


class JudgeReplyError(ValueError):
    """The judge's reply could not be used."""


def select_frame_times(snapshot_times: list[float], duration: float, max_frames: int = DEFAULT_MAX_FRAMES) -> list[float]:
    """Pick moments to show the judge: the settled state after animations, spread over the video."""
    if duration <= 0 or max_frames < 1:
        return []
    last = max(0.0, duration - FRAME_LEAD_SECONDS)
    candidates = sorted({round(min(last, max(0.0, moment - FRAME_LEAD_SECONDS)), 3) for moment in snapshot_times if moment > 0})
    if len(candidates) < 4:
        count = min(max_frames, 8)
        candidates = [round(duration * (index + 1) / (count + 1), 3) for index in range(count)]
    candidates = sorted(set(candidates) | {round(last, 3)})
    if len(candidates) <= max_frames:
        return candidates
    chosen: list[float] = []
    for index in range(max_frames):
        target = duration * (index + 1) / max_frames
        best = min(candidates, key=lambda moment: abs(moment - target))
        if best not in chosen:
            chosen.append(best)
    if candidates[-1] not in chosen:
        chosen[-1] = candidates[-1]
    return sorted(chosen)


def build_judge_prompt(suite: Suite, task: Task, frames: list[dict[str, Any]], duration: float) -> str:
    """The text part of the judge request. ``frames`` is ``[{"time", "text": [...]}]`` in order."""
    judged = [item for item in suite.criteria if item.id != suite.scoring.must_show_criterion]
    lines = [
        f"# Task given to the model: {task.title}",
        "",
        task.prompt,
        "",
        "## Things the video had to show",
        "",
        *[f"- `{item.id}`: {item.text}" for item in task.must_show],
        "",
        "## Reference facts for checking the mathematics",
        "",
        task.judge_notes or "(none)",
        "",
        "These facts are for checking correctness only. Do not mark a video down for leaving out a fact that the task did not ask for.",
        "",
        f"## The video: {duration:.1f} seconds, {len(frames)} frames attached in this order",
        "",
    ]
    for number, frame in enumerate(frames, start=1):
        text = "; ".join(_clip(value) for value in frame.get("text", [])) or "(no text on screen)"
        lines.append(f"- Frame {number} at {frame['time']:.1f} s. On-screen text: {text}")
    lines += [
        "",
        "## What to return",
        "",
        "For every item in the list of things the video had to show, give a verdict:",
        "`yes` (clearly shown), `partial` (attempted but incomplete, unclear, or unlabeled), or `no` (not shown).",
        "",
        "Then rate each of these from 0 to 4:",
        "",
        *[f"- `{item.id}`: {item.question}" for item in judged],
        "",
        "Scale:",
        SCALE_TEXT,
        "",
        "Return exactly this JSON shape, with one short sentence of evidence each, naming the frame you relied on:",
        "",
        "```json",
        json.dumps(_reply_template(task, [item.id for item in judged]), indent=2),
        "```",
    ]
    return "\n".join(lines)


def _reply_template(task: Task, criterion_ids: list[str]) -> dict[str, Any]:
    return {
        "must_show": {item.id: {"verdict": "yes | partial | no", "evidence": "..."} for item in task.must_show},
        "criteria": {name: {"score": 0, "evidence": "..."} for name in criterion_ids},
        "math_errors": ["each mathematical error seen on screen, or an empty list"],
        "summary": "one or two sentences",
    }


def prompt_sha256(system: str, prompt: str) -> str:
    return hashlib.sha256((system + "\n\n" + prompt).encode("utf-8")).hexdigest()


def parse_judge_reply(text: str, suite: Suite, task: Task) -> dict[str, Any]:
    """Validate the reply strictly. Anything missing or out of range is an error, never a guess."""
    data = _extract_json(text)
    must_show_raw = data.get("must_show")
    criteria_raw = data.get("criteria")
    if not isinstance(must_show_raw, dict) or not isinstance(criteria_raw, dict):
        raise JudgeReplyError("The reply needs both a must_show object and a criteria object")

    must_show: dict[str, dict[str, Any]] = {}
    for item in task.must_show:
        entry = must_show_raw.get(item.id)
        verdict = str(entry.get("verdict", "")).strip().lower() if isinstance(entry, dict) else ""
        if verdict not in VERDICT_VALUES:
            raise JudgeReplyError(f"Missing or invalid verdict for must_show item {item.id!r}")
        must_show[item.id] = {"verdict": verdict, "evidence": _clip(str(entry.get("evidence", "")), 400)}

    criteria: dict[str, dict[str, Any]] = {}
    for criterion in suite.criteria:
        if criterion.id == suite.scoring.must_show_criterion:
            continue
        entry = criteria_raw.get(criterion.id)
        score = entry.get("score") if isinstance(entry, dict) else None
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= MAX_SCORE:
            raise JudgeReplyError(f"Missing or out-of-range score for criterion {criterion.id!r}")
        criteria[criterion.id] = {"score": float(score), "evidence": _clip(str(entry.get("evidence", "")), 400)}

    errors = data.get("math_errors", [])
    return {
        "must_show": must_show,
        "criteria": criteria,
        "math_errors": [_clip(str(value), 300) for value in errors][:20] if isinstance(errors, list) else [],
        "summary": _clip(str(data.get("summary", "")), 600),
    }


def judge_score(parsed: dict[str, Any], suite: Suite) -> dict[str, Any]:
    """Turn one judge's validated reply into criterion scores and a 0 to 100 total."""
    verdicts = [VERDICT_VALUES[item["verdict"]] for item in parsed["must_show"].values()]
    coverage = MAX_SCORE * sum(verdicts) / len(verdicts)
    by_criterion: dict[str, float] = {}
    for criterion in suite.criteria:
        if criterion.id == suite.scoring.must_show_criterion:
            by_criterion[criterion.id] = round(coverage, 4)
        else:
            by_criterion[criterion.id] = parsed["criteria"][criterion.id]["score"]
    total_weight = sum(item.weight for item in suite.criteria)
    weighted = sum(item.weight * by_criterion[item.id] / MAX_SCORE for item in suite.criteria)
    return {"criteria": by_criterion, "score": round(100.0 * weighted / total_weight, 2)}


def combine_judges(records: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    """Average the judges that answered. ``status`` says whether the panel is complete."""
    done = [item for item in records if item.get("status") == "complete"]
    failed = [item for item in records if item.get("status") == "failed"]
    if not done:
        return {
            "status": "failed" if failed and len(failed) >= expected else "pending",
            "score": None,
            "judges": len(done),
            "expected": expected,
        }
    scores = [item["score"] for item in done]
    criterion_ids = list(done[0]["criteria"])
    return {
        "status": "complete" if len(done) >= expected else "partial",
        "score": round(sum(scores) / len(scores), 2),
        "spread": round(max(scores) - min(scores), 2),
        "criteria": {
            name: round(sum(item["criteria"][name] for item in done) / len(done), 3) for name in criterion_ids
        },
        "judges": len(done),
        "expected": expected,
        "judge_ids": [item["judge_id"] for item in done],
    }


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise JudgeReplyError("The reply contains no JSON object")
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise JudgeReplyError(f"The reply is not valid JSON: {error.msg}") from error
    if not isinstance(data, dict):
        raise JudgeReplyError("The reply is not a JSON object")
    return data


def _clip(value: str, limit: int = 120) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"
