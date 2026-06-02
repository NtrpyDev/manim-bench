from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from manimbench.paths import PROJECT_ROOT
from manimbench.visual_review import merge_review

REPORT_SCHEMA_VERSION = "0.6.0"
SCORING_POLICY_SUMMARY = (
    "v0.6 ranks models by capability score while publishing pass rate, coverage, render success, "
    "and failure buckets separately. Required source terms are advisory score evidence, not a hard pass gate."
)


def load_results(run_dir: Path) -> list[dict[str, Any]]:
    return sorted(
        (_with_usage_metadata(merge_review(json.loads(path.read_text(encoding="utf-8")), path)) for path in run_dir.rglob("result.json")),
        key=lambda item: (item["model"], item["task"]["id"]),
    )


def summarize_models(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["model"]].append(result)

    summaries = []
    for model, model_results in grouped.items():
        scores = [_rank_score(item) for item in model_results]
        automated_scores = [float(item["score"]["automated_score"]) for item in model_results]
        adjusted_scores = [
            float(item["score"]["adjusted_visual_score"])
            for item in model_results
            if item.get("score", {}).get("adjusted_visual_score") is not None
        ]
        passed = [bool(item["score"]["passed"]) for item in model_results]
        failure_buckets = _failure_buckets(model_results)
        times = [_metadata_number(item, "elapsed_seconds") for item in model_results]
        costs = [_metadata_number(item, "cost_usd") for item in model_results]
        input_tokens = [_metadata_number(item, "input_tokens") for item in model_results]
        output_tokens = [_metadata_number(item, "output_tokens") for item in model_results]
        total_tokens = [_metadata_number(item, "total_tokens") for item in model_results]
        render_success = [
            bool(item["score"]["checks"].get("render_exit_code"))
            and bool(item["score"]["checks"].get("media_generated"))
            for item in model_results
        ]
        avg_score = sum(scores) / max(len(scores), 1)
        avg_automated_score = sum(automated_scores) / max(len(automated_scores), 1)
        avg_cost = _average([value for value in costs if value is not None])
        avg_time = _average([value for value in times if value is not None])
        avg_input_tokens = _average([value for value in input_tokens if value is not None])
        avg_output_tokens = _average([value for value in output_tokens if value is not None])
        avg_total_tokens = _average([value for value in total_tokens if value is not None])
        summaries.append(
            {
                "model": model,
                "tasks": len(model_results),
                "pass_rate": 100.0 * sum(passed) / max(len(passed), 1),
                "render_success_rate": 100.0 * sum(render_success) / max(len(render_success), 1),
                "coverage_rate": 100.0 * (len(model_results) - failure_buckets.get("missing_source", 0)) / max(len(model_results), 1),
                "avg_score": avg_score,
                "avg_automated_score": avg_automated_score,
                "avg_adjusted_visual_score": _average(adjusted_scores),
                "failure_buckets": dict(sorted(failure_buckets.items())),
                "review_status": _model_review_status(model_results),
                "avg_cost_usd": avg_cost,
                "avg_time_seconds": avg_time,
                "avg_input_tokens": avg_input_tokens,
                "avg_output_tokens": avg_output_tokens,
                "avg_total_tokens": avg_total_tokens,
            }
        )

    summaries.sort(key=lambda item: item["avg_score"], reverse=True)
    max_cost = max((item["avg_cost_usd"] or 0 for item in summaries), default=0)
    max_time = max((item["avg_time_seconds"] or 0 for item in summaries), default=0)
    for summary in summaries:
        cost_penalty = (summary["avg_cost_usd"] or 0) / max(max_cost, 1)
        time_penalty = (summary["avg_time_seconds"] or 0) / max(max_time, 1)
        penalty = 1 + 0.35 * cost_penalty + 0.35 * time_penalty
        summary["efficiency_score"] = summary["avg_score"] / penalty
    summaries.sort(key=lambda item: item["avg_score"], reverse=True)
    return summaries


def _model_review_status(results: list[dict[str, Any]]) -> str:
    statuses = [
        str(
            item.get("visual_review", item.get("score", {}).get("rubric", {}).get("visual_review", {})).get(
                "overall", "pending"
            )
        )
        for item in results
    ]
    if not statuses:
        return "pending"
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status == "partial" for status in statuses):
        return "partial"
    if all(status == "pass" for status in statuses):
        return "pass"
    return "pending"


def _rank_score(result: dict[str, Any]) -> float:
    score = result.get("score", {}) if isinstance(result.get("score"), dict) else {}
    value = score.get("rank_score", score.get("automated_score", 0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _failure_buckets(results: list[dict[str, Any]]) -> Counter[str]:
    buckets: Counter[str] = Counter()
    for result in results:
        category = _result_failure_category(result)
        if category != "pass":
            buckets[category] += 1
    return buckets


def _result_failure_category(result: dict[str, Any]) -> str:
    score = result.get("score", {}) if isinstance(result.get("score"), dict) else {}
    if score.get("passed"):
        return "pass"
    category = score.get("failure_category")
    if isinstance(category, str) and category:
        return category
    error = str(result.get("error") or "")
    if "Missing file-provider output" in error:
        return "missing_source"
    checks = score.get("checks", {}) if isinstance(score.get("checks"), dict) else {}
    if checks.get("generation") is False:
        return "missing_source"
    if checks.get("render_not_timed_out") is False:
        return "render_timeout"
    if checks.get("render_exit_code") is False:
        return "render_crash"
    if checks.get("media_generated") is False:
        return "no_media"
    if _passed_field_failed(checks.get("required_source_terms")):
        return "source_terms"
    if _passed_field_failed(checks.get("minimum_required_labels")):
        return "missing_required_labels"
    if _passed_field_failed(checks.get("required_sections")):
        return "missing_required_sections"
    if _passed_field_failed(checks.get("visual_sanity")):
        return "visual_sanity"
    if _passed_field_failed(checks.get("suspicious_source_patterns")):
        return "suspicious_source"
    return "score_gate"


def _passed_field_failed(value: Any) -> bool:
    return isinstance(value, dict) and value.get("passed") is False


def summarize_tasks(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["task"]["id"]].append(result)

    summaries = []
    for task_id, task_results in grouped.items():
        scores = [_rank_score(item) for item in task_results]
        passed = [bool(item["score"]["passed"]) for item in task_results]
        task = task_results[0].get("task", {})
        failure_buckets = _failure_buckets(task_results)
        summaries.append(
            {
                "task_id": task_id,
                "title": task.get("title", task_id),
                "difficulty": task.get("difficulty", "unknown"),
                "domains": task.get("domains", []),
                "models": len(task_results),
                "avg_score": sum(scores) / max(len(scores), 1),
                "pass_rate": 100.0 * sum(passed) / max(len(passed), 1),
                "failure_buckets": dict(sorted(failure_buckets.items())),
            }
        )
    return sorted(summaries, key=lambda item: (item["difficulty"], item["task_id"]))


def write_report(run_dir: Path, output_dir: Path) -> Path:
    results = load_results(run_dir)
    summaries = summarize_models(results)
    task_summaries = summarize_tasks(results)
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (data_dir / "models.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    (data_dir / "tasks.json").write_text(json.dumps(task_summaries, indent=2), encoding="utf-8")
    manifest_path = run_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (data_dir / "leaderboard.json").write_text(
        json.dumps(_leaderboard_payload(run_dir, output_dir, summaries, manifest), indent=2),
        encoding="utf-8",
    )
    _write_detail_pages(output_dir, results, summaries, task_summaries)
    (output_dir / "report.md").write_text(_render_markdown(run_dir, summaries, task_summaries), encoding="utf-8")
    index = output_dir / "index.html"
    index.write_text(_render_html(run_dir, output_dir, results, summaries), encoding="utf-8")
    return index


def _leaderboard_payload(
    run_dir: Path,
    output_dir: Path,
    summaries: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    video_manifest = _load_share_video_manifest(output_dir)
    video_by_model = {item.get("model"): item for item in video_manifest}
    entries = []
    for rank, summary in enumerate(summaries, start=1):
        video = video_by_model.get(summary["model"], {})
        entries.append(
            {
                "rank": rank,
                "model": summary["model"],
                "score": summary["avg_score"],
                "automated_score": summary.get("avg_automated_score"),
                "adjusted_visual_score": summary.get("avg_adjusted_visual_score"),
                "pass_rate": summary.get("pass_rate"),
                "coverage_rate": summary.get("coverage_rate"),
                "render_success_rate": summary.get("render_success_rate"),
                "failure_buckets": summary.get("failure_buckets", {}),
                "review_status": summary.get("review_status", "pending"),
                "video_path": video.get("relative_output"),
                "thumbnail_path": video.get("relative_thumbnail"),
                "cost_usd": summary.get("avg_cost_usd"),
                "elapsed_seconds": summary.get("avg_time_seconds"),
                "input_tokens": summary.get("avg_input_tokens"),
                "output_tokens": summary.get("avg_output_tokens"),
                "total_tokens": summary.get("avg_total_tokens"),
                "suite": manifest.get("suite", {}),
                "sandbox": manifest.get("sandbox", {}),
                "run_id": manifest.get("run_id", run_dir.name),
            }
        )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": manifest.get("run_id", run_dir.name),
        "suite": manifest.get("suite", {}),
        "scoring_policy": {
            "version": REPORT_SCHEMA_VERSION,
            "summary": SCORING_POLICY_SUMMARY,
            "primary_rank_field": "score",
            "separate_fields": ["pass_rate", "coverage_rate", "render_success_rate", "failure_buckets"],
        },
        "models": entries,
    }


def _load_share_video_manifest(output_dir: Path) -> list[dict[str, Any]]:
    manifest_path = output_dir / "videos" / "share_videos.json"
    if not manifest_path.exists():
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _render_html(run_dir: Path, output_dir: Path, results: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> str:
    model_count = len(summaries)
    task_count = len({item["task"]["id"] for item in results})
    best_score = max((item["avg_score"] for item in summaries), default=0)
    overall_chart = _ranking_chart(summaries, "avg_score", "Capability score", "%")
    efficiency_chart = _ranking_chart(
        sorted(summaries, key=lambda item: item["efficiency_score"], reverse=True),
        "efficiency_score",
        "Efficiency ranking",
        "",
    )
    table = _model_table(summaries)
    final_videos = _final_video_grid(output_dir, summaries)
    tasks = _task_cards(results)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ManimBench Report</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f8f7f4;
      --panel: #ffffff;
      --text: #171717;
      --muted: #6b6b6b;
      --line: #dfddd7;
      --accent: #111111;
      --green: #188a5a;
      --orange: #c66a2b;
      --blue: #3769c8;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #11110f;
        --panel: #191917;
        --text: #f3f0e8;
        --muted: #aaa59b;
        --line: #33312b;
        --accent: #f3f0e8;
      }}
    }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    .shell {{ max-width: 1120px; margin: 0 auto; padding: 28px 20px 64px; }}
    nav {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--line); padding-bottom: 14px; }}
    .brand {{ font-weight: 800; letter-spacing: -0.03em; font-size: 20px; }}
    .navlinks {{ color: var(--muted); font-size: 13px; display: flex; gap: 18px; }}
    .hero {{ text-align: center; padding: 64px 0 34px; }}
    .hero h1 {{ font-size: clamp(46px, 8vw, 88px); line-height: 0.95; margin: 0; letter-spacing: -0.075em; }}
    .hero p {{ color: var(--muted); max-width: 720px; margin: 18px auto 0; font-size: 17px; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 26px auto 0; max-width: 760px; }}
    .stat {{ background: var(--panel); border: 1px solid var(--line); padding: 14px; border-radius: 14px; text-align: left; }}
    .stat strong {{ display: block; font-size: 22px; }}
    .stat span {{ color: var(--muted); font-size: 12px; }}
    .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 34px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 18px; box-shadow: 0 20px 40px rgba(0,0,0,0.04); }}
    .panel h2 {{ margin: 0 0 14px; font-size: 17px; }}
    .bar-row {{ display: grid; grid-template-columns: 160px 1fr 58px; gap: 10px; align-items: center; font-size: 12px; margin: 9px 0; }}
    .bar-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }}
    .bar-track {{ height: 10px; background: color-mix(in srgb, var(--line) 78%, transparent); border-radius: 999px; overflow: hidden; }}
    .bar-fill {{ height: 100%; background: linear-gradient(90deg, var(--green), var(--blue)); border-radius: inherit; }}
    .bar-value {{ color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 11px 8px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .section {{ margin-top: 22px; }}
    .cards {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
    .card {{ border: 1px solid var(--line); border-radius: 14px; padding: 14px; background: color-mix(in srgb, var(--panel) 90%, transparent); }}
    .card h3 {{ margin: 0 0 6px; font-size: 14px; }}
    .card p {{ margin: 0; color: var(--muted); font-size: 12px; }}
    .video-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }}
    .video-card video {{ width: 100%; border-radius: 14px; background: #000; border: 1px solid var(--line); }}
    .video-card h3 {{ margin: 10px 0 4px; font-size: 14px; }}
    .video-card p {{ margin: 0; color: var(--muted); font-size: 12px; }}
    @media (max-width: 820px) {{ .charts, .cards, .stats, .video-grid {{ grid-template-columns: 1fr; }} .bar-row {{ grid-template-columns: 110px 1fr 48px; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <nav>
      <div class="brand">ManimBench</div>
      <div class="navlinks"><span>Overview</span><span>Models</span><span>Tasks</span><span>Data</span></div>
    </nav>
    <section class="hero">
      <h1>ManimBench</h1>
      <p>Ranking AI models on ManimCE animation generation with v0.6 scoring: capability score is primary, while coverage, render success, pass rate, and failure buckets stay visible as separate evidence.</p>
      <div class="stats">
        <div class="stat"><strong>{model_count}</strong><span>models</span></div>
        <div class="stat"><strong>{task_count}</strong><span>tasks</span></div>
        <div class="stat"><strong>{best_score:.1f}%</strong><span>top capability score</span></div>
        <div class="stat"><strong>{html.escape(run_dir.name)}</strong><span>run id</span></div>
      </div>
    </section>
    <section class="charts">
      {overall_chart}
      {efficiency_chart}
    </section>
    <section class="panel section">
      <h2>Final Share Videos</h2>
      {final_videos}
    </section>
    <section class="panel section">
      <h2>Model Comparison</h2>
      {table}
    </section>
    <section class="panel section">
      <h2>Task Results</h2>
      <div class="cards">{tasks}</div>
    </section>
  </main>
</body>
</html>"""


def _write_detail_pages(
    output_dir: Path,
    results: list[dict[str, Any]],
    model_summaries: list[dict[str, Any]],
    task_summaries: list[dict[str, Any]],
) -> None:
    models_dir = output_dir / "models"
    tasks_dir = output_dir / "tasks"
    models_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    results_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    results_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        results_by_model[result["model"]].append(result)
        results_by_task[result["task"]["id"]].append(result)

    for summary in model_summaries:
        model = summary["model"]
        (models_dir / f"{_slug(model)}.html").write_text(
            _render_detail_html(
                title=f"{model} Results",
                subtitle=f"Average score {summary['avg_score']:.1f}% across {summary['tasks']} task(s).",
                rows=results_by_model.get(model, []),
            ),
            encoding="utf-8",
        )

    for summary in task_summaries:
        task_id = summary["task_id"]
        (tasks_dir / f"{_slug(task_id)}.html").write_text(
            _render_detail_html(
                title=f"{summary['title']}",
                subtitle=f"{summary['difficulty']} task · pass rate {summary['pass_rate']:.1f}%",
                rows=results_by_task.get(task_id, []),
            ),
            encoding="utf-8",
        )


def _render_detail_html(title: str, subtitle: str, rows: list[dict[str, Any]]) -> str:
    cards = _task_cards(rows)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - ManimBench</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #f8f7f4; color: #171717; }}
    main {{ max-width: 960px; margin: 0 auto; padding: 40px 20px; }}
    a {{ color: inherit; }}
    .panel {{ background: #fff; border: 1px solid #dfddd7; border-radius: 18px; padding: 18px; }}
    .cards {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
    .card {{ border: 1px solid #dfddd7; border-radius: 14px; padding: 14px; }}
    .card h3 {{ margin: 0 0 6px; font-size: 14px; }}
    .card p {{ margin: 0; color: #6b6b6b; font-size: 12px; }}
    @media (max-width: 820px) {{ .cards {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <p><a href="../index.html">Back to overview</a></p>
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(subtitle)}</p>
    <section class="panel"><div class="cards">{cards}</div></section>
  </main>
</body>
</html>"""


def _render_markdown(run_dir: Path, summaries: list[dict[str, Any]], task_summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# ManimBench Report",
        "",
        f"Run: `{run_dir.name}`",
        "",
        f"Scoring policy: {SCORING_POLICY_SUMMARY}",
        "",
        "## Model Ranking",
        "",
        "| Rank | Model | Score | Pass@1 | Coverage | Render | Failures | Avg cost | Avg time |",
        "|---:|---|---:|---:|---:|---:|---|---:|---:|",
    ]
    for rank, item in enumerate(summaries, start=1):
        lines.append(
            f"| {rank} | {item['model']} | {item['avg_score']:.1f}% | {item['pass_rate']:.1f}% | "
            f"{item['coverage_rate']:.1f}% | {item['render_success_rate']:.1f}% | "
            f"{_format_failure_mix(item.get('failure_buckets', {}))} | {_format_money(item['avg_cost_usd'])} | "
            f"{_format_seconds(item['avg_time_seconds'])} |"
        )

    lines.extend(
        [
            "",
            "## Task Summary",
            "",
            "| Task | Difficulty | Models | Score | Pass rate | Failures |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for item in task_summaries:
        lines.append(
            f"| {item['task_id']} | {item['difficulty']} | {item['models']} | "
            f"{item['avg_score']:.1f}% | {item['pass_rate']:.1f}% | {_format_failure_mix(item.get('failure_buckets', {}))} |"
        )
    lines.append("")
    return "\n".join(lines)


def _ranking_chart(summaries: list[dict[str, Any]], key: str, title: str, suffix: str) -> str:
    max_value = max((float(item[key]) for item in summaries), default=1) or 1
    rows = []
    for rank, item in enumerate(summaries, start=1):
        value = float(item[key])
        width = max(2, 100 * value / max_value)
        rows.append(
            f"""<div class="bar-row">
  <div class="bar-name">{rank}. {html.escape(item["model"])}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{width:.2f}%"></div></div>
  <div class="bar-value">{value:.1f}{suffix}</div>
</div>"""
        )
    return f"""<div class="panel"><h2>{html.escape(title)}</h2>{''.join(rows) or '<p>No model results yet.</p>'}</div>"""


def _model_table(summaries: list[dict[str, Any]]) -> str:
    rows = []
    for rank, item in enumerate(summaries, start=1):
        rows.append(
            "<tr>"
            f"<td>{rank}. {html.escape(item['model'])}</td>"
            f"<td>{item['avg_score']:.1f}%</td>"
            f"<td>{item['pass_rate']:.1f}%</td>"
            f"<td>{item['coverage_rate']:.1f}%</td>"
            f"<td>{item['render_success_rate']:.1f}%</td>"
            f"<td>{html.escape(_format_failure_mix(item.get('failure_buckets', {})))}</td>"
            f"<td>{_format_money(item['avg_cost_usd'])}</td>"
            f"<td>{_format_seconds(item['avg_time_seconds'])}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Model</th><th>Score</th><th>Pass@1</th><th>Coverage</th><th>Render</th>"
        "<th>Failure mix</th><th>Avg cost</th><th>Avg time</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _final_video_grid(output_dir: Path, summaries: list[dict[str, Any]]) -> str:
    videos_dir = output_dir / "videos"
    cards = []
    for item in summaries:
        video_path = videos_dir / f"{_slug(item['model'])}.mp4"
        thumbnail_path = videos_dir / f"{_slug(item['model'])}.jpg"
        if not video_path.exists():
            continue
        relative = video_path.relative_to(output_dir)
        poster = f' poster="{html.escape(str(thumbnail_path.relative_to(output_dir)))}"' if thumbnail_path.exists() else ""
        cards.append(
            f"""<div class="video-card">
  <video controls preload="metadata" src="{html.escape(str(relative))}"{poster}></video>
  <h3>{html.escape(item['model'])}</h3>
  <p>Score {item['avg_score']:.1f}% · Pass {item['pass_rate']:.1f}% · Review {html.escape(str(item.get('review_status', 'pending')))} · Cost {_format_money(item['avg_cost_usd'])} · Time {_format_seconds(item['avg_time_seconds'])}</p>
</div>"""
        )
    if not cards:
        return "<p>No final videos have been built for this report yet.</p>"
    return f"<div class=\"video-grid\">{''.join(cards)}</div>"


def _task_cards(results: list[dict[str, Any]]) -> str:
    cards = []
    for result in results:
        status = "pass" if result["score"]["passed"] else _result_failure_category(result)
        task = result.get("task", {})
        cards.append(
            f"""<div class="card">
  <h3>{html.escape(task.get('title') or task.get('id') or 'Unknown task')}</h3>
  <p>{html.escape(result.get('model', 'unknown'))} · {html.escape(task.get('difficulty', 'unknown'))} · {html.escape(status)} · visual {_result_visual_status(result)} · {_rank_score(result):.1f}%</p>
</div>"""
        )
    return "".join(cards) or "<p>No task results yet.</p>"


def _result_visual_status(result: dict[str, Any]) -> str:
    review = result.get("score", {}).get("rubric", {}).get("visual_review", {})
    return html.escape(str(review.get("overall", "pending")))


def _metadata_number(result: dict[str, Any], key: str) -> float | None:
    value = result.get("source_metadata", {}).get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _with_usage_metadata(result: dict[str, Any]) -> dict[str, Any]:
    model = result.get("model")
    if not model:
        return result
    metadata = result.setdefault("source_metadata", {})
    if metadata.get("total_tokens") is not None:
        return result
    usage_path = PROJECT_ROOT / "model_tests" / model / "usage.json"
    if not usage_path.exists():
        return result
    try:
        usage = json.loads(usage_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return result
    metadata.update(
        {
            "usage_path": str(usage_path),
            "cost_usd": usage.get("cost", {}).get("estimated_usd"),
            "elapsed_seconds": usage.get("time", {}).get("elapsed_seconds"),
            "input_tokens": usage.get("tokens", {}).get("input_tokens"),
            "output_tokens": usage.get("tokens", {}).get("output_tokens"),
            "total_tokens": usage.get("tokens", {}).get("total_tokens"),
            "tokenizer": usage.get("tokens", {}).get("tokenizer"),
            "cost_method": usage.get("cost", {}).get("method"),
        }
    )
    return result


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _format_money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.2f}"


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 60:
        return f"{value / 60:.1f}m"
    return f"{value:.1f}s"


def _format_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return f"{value:.0f}"


def _format_failure_mix(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "-"
    ranked = sorted(((str(key), int(count)) for key, count in value.items()), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{key} {count}" for key, count in ranked[:3])


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "item"
