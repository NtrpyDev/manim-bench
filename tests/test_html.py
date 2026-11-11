"""The static report pages: what they show, that they escape data, and that their links resolve."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from conftest import GOOD_SOURCE, FakeRoute, FakeSandbox, good_judge_reply

from manimbench.html import render_pages
from manimbench.pipeline import PipelineRequest, run_all
from manimbench.registry import JudgePanel

ATTACK = "<script>alert(1)</script>"
NOT_OFFICIAL = "Not an official run"
INCOMPLETE = "Incomplete: some samples are missing or not judged"


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src"} and value is not None:
                self.links.append(value)
            if name == "id" and value:
                self.ids.add(value)


def _parse(text: str) -> _Links:
    parser = _Links()
    parser.feed(text)
    return parser


def broken_links(root: Path) -> list[str]:
    """Every href and src in every page must point at a file inside ``root``, and fragments at an id."""
    root = root.resolve()
    pages = sorted(root.rglob("*.html"))
    ids = {page.resolve(): _parse(page.read_text(encoding="utf-8")).ids for page in pages}
    problems = []
    for page in pages:
        for link in _parse(page.read_text(encoding="utf-8")).links:
            parts = urlsplit(link)
            if parts.scheme or parts.netloc:
                problems.append(f"{page.name}: external {link}")
                continue
            target = (page.parent / unquote(parts.path)).resolve() if parts.path else page.resolve()
            if root not in target.parents:
                problems.append(f"{page.name}: outside the report {link}")
            elif not target.is_file():
                problems.append(f"{page.name}: missing {link}")
            elif parts.fragment and parts.fragment not in ids.get(target, set()):
                problems.append(f"{page.name}: no anchor {link}")
    return problems


def write_pages(root: Path, pages: dict[str, str]) -> None:
    for relative, text in pages.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


# A small hand-built report --------------------------------------------------


def _result(model, task, sample, *, status="scored", quality=80.0, evidence="Frame 2."):
    base = f"{model}/{task}/sample-{sample}"
    passed = status != "failed_gate"
    judged = status == "scored"
    return {
        "model": model,
        "task": {"id": task, "version": "1", "title": task},
        "sample": sample,
        "score": {
            "status": status,
            "quality": quality if judged else (0.0 if not passed else None),
            "automated": 90.0 if passed else 0.0,
            "components": {"layout": 90.0, "pacing": 90.0, **({"judge": 70.0} if judged else {})} if passed else {},
            "weights": {},
        },
        "gates": {
            "passed": passed,
            "failure": None if passed else "render_error",
            "checks": {"renders": {"passed": passed, **({} if passed else {"detail": "Render exited with code 1."})}},
            "not_run": [] if passed else ["video"],
        },
        "layout": {"available": True, "score": 90.0, "problem_seconds": {"clipping": 1.0}, "issues": [{"kind": "clipping", "text": "x", "seconds": 1.0}], "reason": None} if passed else None,
        "pacing": {"available": True, "score": 90.0, "active_share": 0.8, "longest_still_seconds": 2.0, "dead_seconds": 0.0, "blank_share": 0.0} if passed else None,
        "judge": {"status": "complete", "score": 70.0, "spread": 0.0, "criteria": {"correctness": 3.0}, "judges": 1, "expected": 1, "judge_ids": ["judge-a"]}
        if judged
        else {"status": "pending", "score": None, "judges": 0, "expected": 1},
        "judgements": [
            {
                "judge_id": "judge-a",
                "status": "complete",
                "score": 70.0,
                "criteria": {"correctness": 3.0, "task_coverage": 4.0},
                "reply": {
                    "must_show": {"axes": {"verdict": "yes", "evidence": evidence}},
                    "criteria": {"correctness": {"score": 3, "evidence": evidence}},
                    "math_errors": [evidence],
                    "summary": evidence,
                },
                "cost_usd": 0.01,
            }
        ]
        if judged
        else [],
        "video": f"videos/{base}.mp4" if passed else None,
        "source": f"sources/{base}.py",
        "source_sha256": "0" * 64,
        "generation": {"route": "fake", "response_model": "m", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01, "cost_basis": "fake"},
        "render": {"exit_code": 0, "timed_out": False, "elapsed_seconds": 1.0, "duration_seconds": 20.0, "fps": 15.0, "width": 854, "height": 480}
        if passed
        else None,
    }


def _row(model, name, *, rank, complete):
    return {
        "model": model,
        "name": name,
        "vendor": "Vendor",
        "complete": complete,
        "quality": 60.0 if complete else None,
        "quality_interval": [40.0, 80.0] if complete else None,
        "automated": 90.0,
        "samples": {
            "expected": 2,
            "present": 2 if complete else 1,
            "missing": 0 if complete else 1,
            "scored": 2 if complete else 0,
            "awaiting_judge": 0 if complete else 1,
            "failed_gate": 1 if complete else 0,
        },
        "gate_pass_rate": 50.0 if complete else 100.0,
        "failures": {"render_error": 1} if complete else {},
        "tasks": {
            "task_a": {"samples": 1, "expected_samples": 1, "complete": complete, "quality": 80.0 if complete else None, "automated": 90.0, "passed_gates": 1},
            "task_b": {"samples": 1 if complete else 0, "expected_samples": 1, "complete": complete, "quality": 0.0 if complete else None, "automated": 0.0, "passed_gates": 0},
        },
        "components": {"judge": 70.0, "layout": 90.0, "pacing": 90.0},
        "cost": {"generation_usd": 0.02, "judging_usd": 0.01, "samples_without_cost": 0 if complete else 1, "basis": ["fake"]},
        "rank": rank,
    }


def hand_data(*, official: bool, complete: bool) -> dict:
    rows = [_row("model-a", f"Alpha {ATTACK}", rank=1, complete=True)]
    results = [
        _result("model-a", "task_a", 1, evidence=f"Saw {ATTACK} here"),
        _result("model-a", "task_b", 1, status="failed_gate"),
    ]
    if not complete:
        rows.append(_row("model-b", "Beta", rank=None, complete=False))
        results.append(_result("model-b", "task_a", 1, status="awaiting_judge"))
    return {
        "leaderboard": {
            "run_id": "hand",
            "generated_at": "2026-11-10T00:00:00+00:00",
            "suite": {"id": "s", "version": "1", "title": "Bench", "task_ids": ["task_a", "task_b"]},
            "manim_version": "0.22.1",
            "samples_per_task": 1,
            "official": official,
            "complete": complete,
            "weights": {"judge": 65.0, "layout": 25.0, "pacing": 10.0},
            "criteria": [{"id": "correctness", "weight": 50.0, "question": "Correct?"}, {"id": "task_coverage", "weight": 50.0, "question": "Covered?"}],
            "judges": ["judge-a"],
            "models": rows,
        },
        "results": results,
        "models": [{"id": row["model"], "name": row["name"], "vendor": row["vendor"]} for row in rows],
        "tasks": [
            {"id": "task_a", "title": "Task A", "domains": ["algebra"], "prompt": "Teach A.", "must_show": [{"id": "axes", "text": "Axes."}]},
            {"id": "task_b", "title": "Task B", "domains": [], "prompt": "Teach B.", "must_show": []},
        ],
        "manifest": {},
    }


def _touch_assets(root: Path, data: dict) -> None:
    for result in data["results"]:
        for key in ("video", "source"):
            if result[key]:
                (root / result[key]).parent.mkdir(parents=True, exist_ok=True)
                (root / result[key]).write_text("x", encoding="utf-8")


def test_pages_cover_every_model_and_task():
    data = hand_data(official=False, complete=False)
    pages = render_pages(data)
    assert set(pages) == {"index.html", "models/model-a.html", "models/model-b.html", "tasks/task_a.html", "tasks/task_b.html"}
    index = pages["index.html"]
    for href in ["models/model-a.html", "models/model-b.html", "tasks/task_a.html", "tasks/task_b.html"]:
        assert f'href="{href}"' in index
    for name in ["Beta", "Task A", "Task B"]:
        assert name in index
    for text in pages.values():
        assert text.startswith("<!doctype html>")


def test_data_is_escaped():
    pages = render_pages(hand_data(official=True, complete=True))
    for text in pages.values():
        assert ATTACK not in text
        assert "<script" not in text
    assert "Alpha &lt;script&gt;alert(1)&lt;/script&gt;" in pages["index.html"]
    assert "Saw &lt;script&gt;alert(1)&lt;/script&gt; here" in pages["models/model-a.html"]


def test_pages_are_self_contained():
    for text in render_pages(hand_data(official=False, complete=False)).values():
        assert "http://" not in text and "https://" not in text
        assert "<script" not in text
        assert "<link" not in text
        assert "@import" not in text and "url(" not in text
        assert " style=" not in text
        assert chr(0x2014) not in text  # no em dash


def test_status_banners_only_when_needed():
    clean = render_pages(hand_data(official=True, complete=True))["index.html"]
    assert NOT_OFFICIAL not in clean and INCOMPLETE not in clean
    unofficial = render_pages(hand_data(official=False, complete=True))["index.html"]
    assert NOT_OFFICIAL in unofficial and INCOMPLETE not in unofficial
    partial = render_pages(hand_data(official=True, complete=False))["index.html"]
    assert INCOMPLETE in partial and NOT_OFFICIAL not in partial


def test_unranked_models_are_labeled():
    pages = render_pages(hand_data(official=True, complete=False))
    index = pages["index.html"]
    beta_row = next(row for row in index.split("<tr>") if 'href="models/model-b.html"' in row and "rank" in row)
    assert "not ranked" in beta_row and "provisional" in beta_row
    assert "1 missing" in beta_row and "1 awaiting judge" in beta_row
    assert "not ranked" in pages["models/model-b.html"]
    alpha_row = next(row for row in index.split("<tr>") if 'href="models/model-a.html"' in row and "rank" in row)
    assert "not ranked" not in alpha_row


def test_failures_and_numbers_are_readable():
    pages = render_pages(hand_data(official=True, complete=False))
    assert "render error" in pages["index.html"]
    assert "render_error" not in pages["index.html"]
    assert "Failed gate: render error" in pages["models/model-a.html"]
    assert "60.0" in pages["index.html"] and "40.0 to 80.0" in pages["index.html"]
    assert "$0.0300" in pages["index.html"]
    assert "1 sample without cost" in pages["index.html"]


def test_hand_built_links_resolve(tmp_path):
    data = hand_data(official=False, complete=False)
    _touch_assets(tmp_path, data)
    write_pages(tmp_path, render_pages(data))
    assert broken_links(tmp_path) == []
    model_page = (tmp_path / "models" / "model-a.html").read_text(encoding="utf-8")
    assert '<video controls preload="none" src="../videos/model-a/task_a/sample-1.mp4">' in model_page


def test_link_check_catches_a_missing_file(tmp_path):
    write_pages(tmp_path, {"index.html": '<a href="models/nope.html">x</a><a href="../outside.html">y</a>'})
    assert len(broken_links(tmp_path)) == 2


def test_real_pipeline_report(tmp_path, suite, monkeypatch):
    tasks = {task.title: task for task in suite.tasks}

    def judge_reply(_target, request):
        title = next(title for title in tasks if title in request.prompt)
        return good_judge_reply(tasks[title])

    monkeypatch.setattr(
        "manimbench.judging.load_judges",
        lambda: JudgePanel(route="openrouter", judges=["claude-opus-5-5", "gpt-6-1-sol"], max_frames=6, max_output_tokens=None),
    )
    count = {"n": 0}

    def generate(_target, _request):
        count["n"] += 1
        return ("# fake:crash\n" if count["n"] % 4 == 0 else "") + GOOD_SOURCE

    result = run_all(
        PipelineRequest(
            models=["claude-opus-5-5", "gpt-6-1-sol"],
            outputs_dir=tmp_path / "outputs",
            runs_dir=tmp_path / "runs",
            reports_dir=tmp_path / "reports",
            run_id="html",
            samples=1,
            generate_route_factory=lambda _name: FakeRoute(generate),
            judge_route_factory=lambda _name: FakeRoute(judge_reply),
            sandbox=FakeSandbox(),
        )
    )
    assert result.ok
    root = tmp_path / "reports" / "html"
    data = {name: json.loads((root / "data" / f"{name}.json").read_text()) for name in ["leaderboard", "results", "models", "tasks"]}
    leaderboard = data["leaderboard"]
    assert (root / "index.html").is_file()
    for model in data["models"]:
        assert (root / "models" / f"{model['id']}.html").is_file()
    for task in data["tasks"]:
        assert (root / "tasks" / f"{task['id']}.html").is_file()
    index = (root / "index.html").read_text(encoding="utf-8")
    assert (NOT_OFFICIAL in index) == (not leaderboard["official"])
    assert (INCOMPLETE in index) == (not leaderboard["complete"])
    for model in data["models"]:
        assert model["name"] in index
    assert broken_links(root) == []
    videos = [item["video"] for item in data["results"] if item["video"]]
    assert videos and all((root / video).is_file() for video in videos)
    pages = "".join(page.read_text(encoding="utf-8") for page in root.rglob("*.html"))
    assert all(f'src="../{video}"' in pages for video in videos)
    assert all(f'href="../{item["source"]}"' in pages for item in data["results"])
    assert not re.search(r"https?://", pages)
