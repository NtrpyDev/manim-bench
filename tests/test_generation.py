"""Generation: files per sample, caching, stale detection, failure handling."""

from __future__ import annotations

import json

import pytest

from conftest import GOOD_SOURCE, FakeRoute

from manimbench.generation import (
    GENERATION_SYSTEM_PROMPT,
    GenerateRequest,
    generate,
    generation_prompt_sha256,
    sample_paths,
    sha256_text,
    task_prompts,
)
from manimbench.paths import DEFAULT_PROMPT_PATH
from manimbench.providers.base import ProviderError
from manimbench.sandbox.settings import load_sandbox_settings
from manimbench.tasks import filter_tasks

TASKS = ["coordinate_system_animation", "fourier_series_decomposition"]
MODEL = "claude-opus-5-5"


def good(_target, _request):
    return GOOD_SOURCE


def request(tmp_path, fake_route, **overrides):
    values = dict(
        models=[MODEL],
        task_ids=TASKS,
        samples=2,
        output_dir=tmp_path / "out",
        route="openrouter",
        route_factory=lambda _name: fake_route,
    )
    values.update(overrides)
    return GenerateRequest(**values)


def all_files(folder):
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())


def test_files_are_written_per_sample_with_record_fields(tmp_path, suite):
    route = FakeRoute(good)
    result = generate(request(tmp_path, route))
    out = tmp_path / "out"
    assert len(route.calls) == 4
    assert len(result.generated) == 4
    assert result.ok
    expected = sorted(
        f"{MODEL}/{task}/sample-{n}{suffix}" for task in TASKS for n in (1, 2) for suffix in (".py", ".json", ".reply.txt")
    )
    assert all_files(out) == expected
    code, record_path, reply = sample_paths(out, MODEL, "fourier_series_decomposition", 2)
    assert code.read_text() == GOOD_SOURCE
    assert reply.read_text() == GOOD_SOURCE
    record = json.loads(record_path.read_text())
    prompts = task_prompts(suite, DEFAULT_PROMPT_PATH, filter_tasks(suite, TASKS), load_sandbox_settings())
    assert record["schema_version"] == "0.7.0"
    assert record["model"] == MODEL
    assert record["task_id"] == "fourier_series_decomposition"
    assert record["sample"] == 2
    assert record["route"] == "openrouter"
    assert record["status"] == "complete"
    assert record["prompt_sha256"] == generation_prompt_sha256(prompts["fourier_series_decomposition"])
    assert record["source_sha256"] == sha256_text(GOOD_SOURCE)
    assert record["max_output_tokens"] == 64000
    assert record["reasoning_effort"] is None
    assert record["completion"]["cost_usd"] == 0.01
    assert record["completion"]["input_tokens"] == 1000
    assert record["completion"]["output_tokens"] == 500
    assert record["completion"]["requested_model"] == "anthropic/claude-opus-5.5"


def test_route_receives_target_system_prompt_and_task_prompt(tmp_path, suite):
    route = FakeRoute(good)
    generate(request(tmp_path, route, task_ids=TASKS[:1], samples=1))
    target, sent = route.calls[0]
    assert target == {"model": "anthropic/claude-opus-5.5", "provider": "anthropic"}
    assert sent.system == GENERATION_SYSTEM_PROMPT
    assert sent.max_output_tokens == 64000
    assert sent.reasoning_effort is None
    assert "## Task: " + suite.tasks[0].title in sent.prompt or "## Task: " in sent.prompt


def test_fenced_reply_is_saved_unfenced_and_raw_reply_is_kept(tmp_path):
    fenced = "Sure, here it is:\n```python\n" + GOOD_SOURCE + "```\nHope that helps."
    route = FakeRoute(lambda _t, _r: fenced)
    generate(request(tmp_path, route, task_ids=TASKS[:1], samples=1))
    code, _record, reply = sample_paths(tmp_path / "out", MODEL, TASKS[0], 1)
    assert code.read_text() == GOOD_SOURCE
    assert reply.read_text() == fenced


def test_second_run_asks_nothing_and_reports_skipped(tmp_path):
    route = FakeRoute(good)
    generate(request(tmp_path, route))
    again = generate(request(tmp_path, route))
    assert len(route.calls) == 4
    assert len(again.skipped) == 4
    assert again.generated == []
    assert again.ok
    assert [item["status"] for item in again.planned] == ["complete"] * 4


def test_force_asks_again(tmp_path):
    route = FakeRoute(good)
    generate(request(tmp_path, route))
    forced = generate(request(tmp_path, route, force=True))
    assert len(route.calls) == 8
    assert len(forced.generated) == 4
    assert forced.skipped == []


def test_reply_with_no_code_is_no_code_and_is_not_asked_again(tmp_path):
    route = FakeRoute(lambda _t, _r: "   \n")
    first = generate(request(tmp_path, route, task_ids=TASKS[:1], samples=1))
    code, record_path, _reply = sample_paths(tmp_path / "out", MODEL, TASKS[0], 1)
    assert len(first.no_code) == 1
    assert first.generated == []
    assert not code.exists()
    assert json.loads(record_path.read_text())["status"] == "no_code"
    assert json.loads(record_path.read_text())["source_sha256"] is None
    second = generate(request(tmp_path, route, task_ids=TASKS[:1], samples=1))
    assert len(route.calls) == 1
    assert len(second.skipped) == 1
    assert second.ok


def test_provider_error_is_recorded_reported_and_asked_again(tmp_path):
    broken = FakeRoute(lambda _t, _r: ProviderError("boom"))
    first = generate(request(tmp_path, broken, task_ids=TASKS[:1], samples=1))
    _code, record_path, _reply = sample_paths(tmp_path / "out", MODEL, TASKS[0], 1)
    record = json.loads(record_path.read_text())
    assert record["status"] == "provider_error"
    assert record["error"] == "boom"
    assert first.failed == [{"model": MODEL, "task_id": TASKS[0], "sample": 1, "error": "boom"}]
    assert first.generated == []
    assert not first.ok

    working = FakeRoute(good)
    second = generate(request(tmp_path, working, task_ids=TASKS[:1], samples=1, dry_run=True))
    assert second.planned[0]["status"] == "provider_error"
    assert working.calls == []
    third = generate(request(tmp_path, working, task_ids=TASKS[:1], samples=1))
    assert len(working.calls) == 1
    assert len(third.generated) == 1
    assert third.ok
    assert json.loads(record_path.read_text())["status"] == "complete"


def test_provider_error_leaves_no_code_file_even_over_an_older_answer(tmp_path):
    route = FakeRoute(good)
    generate(request(tmp_path, route, task_ids=TASKS[:1], samples=1))
    broken = FakeRoute(lambda _t, _r: ProviderError("later failure"))
    generate(request(tmp_path, broken, task_ids=TASKS[:1], samples=1, force=True))
    code, _record, reply = sample_paths(tmp_path / "out", MODEL, TASKS[0], 1)
    assert not code.exists()
    assert not reply.exists()


def changed_prompt(tmp_path):
    text = DEFAULT_PROMPT_PATH.read_text(encoding="utf-8")
    assert "student" in text
    path = tmp_path / "prompt2.md"
    path.write_text(text.replace("student", "pupil", 1), encoding="utf-8")
    return path


def test_changed_prompt_makes_samples_stale_and_they_are_not_regenerated(tmp_path):
    route = FakeRoute(good)
    generate(request(tmp_path, route))
    stale = generate(request(tmp_path, route, prompt_path=changed_prompt(tmp_path)))
    assert len(route.calls) == 4
    assert len(stale.stale) == 4
    assert stale.generated == [] and stale.skipped == []
    assert not stale.ok
    assert [item["status"] for item in stale.planned] == ["stale"] * 4


def test_force_regenerates_stale_samples_and_clears_the_problem(tmp_path):
    route = FakeRoute(good)
    prompt = changed_prompt(tmp_path)
    generate(request(tmp_path, route))
    forced = generate(request(tmp_path, route, prompt_path=prompt, force=True))
    assert len(route.calls) == 8
    assert forced.ok
    after = generate(request(tmp_path, route, prompt_path=prompt))
    assert len(after.skipped) == 4
    assert len(route.calls) == 8


def test_editing_a_saved_py_by_hand_makes_it_stale(tmp_path):
    route = FakeRoute(good)
    generate(request(tmp_path, route, task_ids=TASKS[:1], samples=2))
    code, _record, _reply = sample_paths(tmp_path / "out", MODEL, TASKS[0], 1)
    code.write_text(GOOD_SOURCE + "# edited\n", encoding="utf-8")
    result = generate(request(tmp_path, route, task_ids=TASKS[:1], samples=2))
    assert len(route.calls) == 2
    assert result.stale == [code]
    assert len(result.skipped) == 1
    assert not result.ok
    assert [item["status"] for item in result.planned] == ["stale", "complete"]


def test_deleting_a_saved_py_makes_it_stale(tmp_path):
    route = FakeRoute(good)
    generate(request(tmp_path, route, task_ids=TASKS[:1], samples=1))
    code, _record, _reply = sample_paths(tmp_path / "out", MODEL, TASKS[0], 1)
    code.unlink()
    result = generate(request(tmp_path, route, task_ids=TASKS[:1], samples=1))
    assert result.stale == [code]


def test_dry_run_asks_nothing_and_lists_planned_statuses(tmp_path):
    def factory(_name):
        raise AssertionError("dry run must not build a route")

    result = generate(request(tmp_path, None, route_factory=factory, dry_run=True))
    assert len(result.planned) == 4
    assert {item["status"] for item in result.planned} == {"missing"}
    assert {(item["task_id"], item["sample"]) for item in result.planned} == {(t, n) for t in TASKS for n in (1, 2)}
    assert not (tmp_path / "out").exists()
    assert result.generated == []


def test_unknown_model_raises_key_error_before_any_call(tmp_path):
    route = FakeRoute(good)
    with pytest.raises(KeyError, match="no-such-model"):
        generate(request(tmp_path, route, models=[MODEL, "no-such-model"]))
    assert route.calls == []
    assert not (tmp_path / "out").exists()


def test_model_without_the_requested_route_raises_before_any_call(tmp_path):
    route = FakeRoute(good)
    with pytest.raises(KeyError, match="no claude-cli route"):
        generate(request(tmp_path, route, models=[MODEL, "gpt-6-1-sol"], route="claude-cli"))
    assert route.calls == []
    assert not (tmp_path / "out").exists()


def test_fully_cached_run_never_builds_a_route(tmp_path):
    generate(request(tmp_path, FakeRoute(good)))

    def factory(_name):
        raise AssertionError("a cached run must not build a route")

    result = generate(request(tmp_path, None, route_factory=factory))
    assert len(result.skipped) == 4


def test_route_is_built_once_with_the_route_name(tmp_path):
    names = []
    route = FakeRoute(good)

    def factory(name):
        names.append(name)
        return route

    generate(request(tmp_path, None, route_factory=factory))
    assert names == ["openrouter"]


def test_reported_cost_is_summed(tmp_path):
    result = generate(request(tmp_path, FakeRoute(good)))
    assert result.cost_usd == 0.04


def test_samples_argument_overrides_the_suite_default(tmp_path, suite):
    assert suite.samples_per_task == 3
    route = FakeRoute(good)
    generate(request(tmp_path, route, task_ids=TASKS[:1], samples=1))
    assert len(route.calls) == 1
    default_route = FakeRoute(good)
    generate(request(tmp_path, default_route, task_ids=TASKS[:1], samples=None, output_dir=tmp_path / "default"))
    assert len(default_route.calls) == 3
    names = sorted(p.name for p in (tmp_path / "default" / MODEL / TASKS[0]).glob("*.py"))
    assert names == ["sample-1.py", "sample-2.py", "sample-3.py"]


def test_parallel_produces_the_same_files(tmp_path):
    serial = generate(request(tmp_path, FakeRoute(good), output_dir=tmp_path / "serial"))
    parallel = generate(request(tmp_path, FakeRoute(good), output_dir=tmp_path / "parallel", parallel=4))
    assert all_files(tmp_path / "serial") == all_files(tmp_path / "parallel")
    assert len(parallel.generated) == len(serial.generated) == 4
    assert parallel.cost_usd == serial.cost_usd


def test_on_event_reports_each_sample(tmp_path):
    events = []
    generate(request(tmp_path, FakeRoute(good), task_ids=TASKS[:1], samples=1, on_event=events.append))
    assert events == [f"{MODEL}/{TASKS[0]}/sample-1: complete"]


@pytest.mark.parametrize("reply", ["I cannot help with that request.", "Here is my plan:\n1. Draw axes\n2. Plot the curve"])
def test_a_reply_with_no_class_in_it_is_recorded_as_no_code(tmp_path, reply):
    """A refusal or plain prose is an answer with no scene in it, not a syntax error."""
    from manimbench.generation import GenerateRequest, generate, read_record, sample_paths

    result = generate(
        GenerateRequest(
            models=["claude-opus-5-5"],
            task_ids=["fourier_series_decomposition"],
            output_dir=tmp_path / "outputs",
            samples=1,
            route_factory=lambda _name: FakeRoute(lambda _target, _request: reply),
        )
    )
    code_path, record_path, reply_path = sample_paths(tmp_path / "outputs", "claude-opus-5-5", "fourier_series_decomposition", 1)
    assert len(result.no_code) == 1 and not result.generated
    assert not code_path.exists()
    assert read_record(record_path)["status"] == "no_code"
    assert reply_path.read_text() == reply
