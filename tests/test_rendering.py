"""Rendering: gates, result.json, manifest, reuse, and what counts as missing or stale."""

from __future__ import annotations

import json

import pytest

from conftest import GOOD_SOURCE, FakeRoute, FakeSandbox

from manimbench.generation import GenerateRequest, generate, sha256_text
from manimbench.providers.base import ProviderError
from manimbench.rendering import RenderRequest, load_manifest, load_results, render, sample_dir

TASK = "coordinate_system_animation"
OTHER_TASK = "fourier_series_decomposition"
MODEL = "claude-opus-5-5"
OTHER_MODEL = "claude-sonnet-5-5"


def write_sample(outputs, source, *, model=MODEL, task=TASK, sample=1):
    path = outputs / model / task / f"sample-{sample}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def do_render(tmp_path, sandbox, **overrides):
    values = dict(
        models=[MODEL],
        task_ids=[TASK],
        samples=1,
        outputs_dir=tmp_path / "outputs",
        runs_dir=tmp_path / "runs",
        run_id="r1",
        sandbox=sandbox,
    )
    values.update(overrides)
    return render(RenderRequest(**values))


def do_generate(tmp_path, reply, *, models=(MODEL,), tasks=(TASK,), samples=1, **overrides):
    route = FakeRoute(lambda _t, _r: reply)
    values = dict(
        models=list(models),
        task_ids=list(tasks),
        samples=samples,
        output_dir=tmp_path / "outputs",
        route="openrouter",
        route_factory=lambda _name: route,
    )
    values.update(overrides)
    generate(GenerateRequest(**values))
    return route


def result_of(tmp_path, *, model=MODEL, task=TASK, sample=1, run_id="r1"):
    path = sample_dir(tmp_path / "runs" / run_id, model, task, sample) / "result.json"
    return json.loads(path.read_text())


def test_passing_sample_result_fields(tmp_path):
    do_generate(tmp_path, GOOD_SOURCE)
    sandbox = FakeSandbox()
    outcome = do_render(tmp_path, sandbox)
    assert outcome.ok
    assert len(outcome.rendered) == 1 and outcome.reused == []
    result = result_of(tmp_path)
    assert result["model"] == MODEL
    assert result["sample"] == 1
    assert result["task"]["id"] == TASK
    assert result["gates"]["passed"] is True
    assert result["gates"]["failure"] is None
    assert result["gates"]["not_run"] == []
    assert result["layout"]["score"] == 100
    assert result["pacing"]["available"] is True
    assert result["pacing"]["score"] is not None
    assert result["score"]["status"] == "awaiting_judge"
    assert result["score"]["quality"] is None
    assert result["score"]["automated"] == 100.0
    assert result["judge"] == {"status": "pending", "score": None, "judges": 0, "expected": 0}
    assert result["judgements"] == []
    assert result["source"]["sha256"] == sha256_text(GOOD_SOURCE)
    generation = result["source"]["generation"]
    assert generation["status"] == "complete"
    assert generation["route"] == "openrouter"
    assert generation["requested_model"] == "anthropic/claude-opus-5.5"
    assert generation["cost_usd"] == 0.01
    assert generation["input_tokens"] == 1000
    assert generation["output_tokens"] == 500
    assert generation["attempts"] == 1
    assert result["render"]["exit_code"] == 0
    assert result["render"]["video"].endswith("result.mp4")
    folder = sample_dir(tmp_path / "runs" / "r1", MODEL, TASK, 1)
    assert (folder / "solution.py").read_text() == GOOD_SOURCE
    assert sandbox.rendered == [folder]


@pytest.mark.parametrize(
    "marker, failure",
    [
        ("crash", "render_error"),
        ("timeout", "render_timeout"),
        ("static", "static_video"),
        ("blank", "blank_video"),
        ("short", "too_short"),
    ],
)
def test_each_fake_sandbox_marker_gives_the_right_failure(tmp_path, marker, failure):
    write_sample(tmp_path / "outputs", GOOD_SOURCE + f"# fake:{marker}\n")
    sandbox = FakeSandbox()
    do_render(tmp_path, sandbox)
    result = result_of(tmp_path)
    assert result["gates"]["passed"] is False
    assert result["gates"]["failure"] == failure
    assert result["score"]["status"] == "failed_gate"
    assert result["score"]["quality"] == 0.0
    assert result["layout"] is None
    assert len(sandbox.rendered) == 1


@pytest.mark.parametrize(
    "source, failure",
    [
        ("def broken(:\n    pass\n", "syntax_error"),
        ("from manim import *\n\nclass Other(Scene):\n    pass\n", "missing_scene_class"),
    ],
)
def test_bad_source_fails_without_calling_the_sandbox(tmp_path, source, failure):
    write_sample(tmp_path / "outputs", source)
    sandbox = FakeSandbox()
    do_render(tmp_path, sandbox)
    result = result_of(tmp_path)
    assert result["gates"]["failure"] == failure
    assert result["score"]["quality"] == 0.0
    assert result["render"] is None
    assert sandbox.rendered == []


def test_no_code_record_gives_no_code_failure_without_calling_the_sandbox(tmp_path):
    do_generate(tmp_path, "   ")
    sandbox = FakeSandbox()
    outcome = do_render(tmp_path, sandbox)
    assert outcome.ok
    result = result_of(tmp_path)
    assert result["gates"]["failure"] == "no_code"
    assert result["score"]["quality"] == 0.0
    assert result["source"]["generation"]["status"] == "no_code"
    assert sandbox.rendered == []


def test_sample_never_generated_is_missing_and_writes_no_result(tmp_path):
    sandbox = FakeSandbox()
    outcome = do_render(tmp_path, sandbox)
    assert outcome.missing == [{"model": MODEL, "task_id": TASK, "sample": 1, "reason": "not_generated"}]
    assert not outcome.ok
    assert outcome.rendered == []
    assert not sample_dir(tmp_path / "runs" / "r1", MODEL, TASK, 1).exists()
    assert sandbox.rendered == []


def test_provider_error_record_is_missing_with_that_reason(tmp_path):
    route = FakeRoute(lambda _t, _r: ProviderError("down"))
    generate(
        GenerateRequest(
            models=[MODEL], task_ids=[TASK], samples=1, output_dir=tmp_path / "outputs", route="openrouter",
            route_factory=lambda _n: route,
        )
    )
    sandbox = FakeSandbox()
    outcome = do_render(tmp_path, sandbox)
    assert outcome.missing == [{"model": MODEL, "task_id": TASK, "sample": 1, "reason": "provider_error"}]
    assert not outcome.ok
    assert sandbox.rendered == []
    assert load_results(tmp_path / "runs" / "r1") == []


def changed_prompt(tmp_path):
    from manimbench.paths import DEFAULT_PROMPT_PATH

    path = tmp_path / "prompt2.md"
    path.write_text(DEFAULT_PROMPT_PATH.read_text(encoding="utf-8").replace("student", "pupil", 1), encoding="utf-8")
    return path


def test_stale_record_is_listed_and_not_rendered(tmp_path):
    do_generate(tmp_path, GOOD_SOURCE)
    sandbox = FakeSandbox()
    outcome = do_render(tmp_path, sandbox, prompt_path=changed_prompt(tmp_path))
    assert outcome.stale == [{"model": MODEL, "task_id": TASK, "sample": 1, "reason": "written_for_a_different_prompt"}]
    assert not outcome.ok
    assert outcome.rendered == []
    assert sandbox.rendered == []


def test_allow_stale_renders_the_stale_sample(tmp_path):
    do_generate(tmp_path, GOOD_SOURCE)
    sandbox = FakeSandbox()
    outcome = do_render(tmp_path, sandbox, prompt_path=changed_prompt(tmp_path), allow_stale=True)
    assert outcome.stale == []
    assert outcome.ok
    assert len(outcome.rendered) == 1
    assert result_of(tmp_path)["gates"]["passed"] is True


def test_hand_written_py_with_no_record_renders_as_manual(tmp_path):
    write_sample(tmp_path / "outputs", GOOD_SOURCE)
    outcome = do_render(tmp_path, FakeSandbox())
    assert outcome.ok
    assert result_of(tmp_path)["source"]["generation"] == {"status": "manual", "route": "manual"}
    assert result_of(tmp_path)["gates"]["passed"] is True


def test_rerun_reuses_results_and_force_renders_again(tmp_path):
    write_sample(tmp_path / "outputs", GOOD_SOURCE)
    sandbox = FakeSandbox()
    first = do_render(tmp_path, sandbox)
    assert len(first.rendered) == 1
    second = do_render(tmp_path, sandbox)
    assert second.rendered == []
    assert [path.name for path in second.reused] == ["result.json"]
    assert len(sandbox.rendered) == 1
    third = do_render(tmp_path, sandbox, force=True)
    assert len(third.rendered) == 1
    assert third.reused == []
    assert len(sandbox.rendered) == 2


def test_manifest_contents(tmp_path, suite):
    write_sample(tmp_path / "outputs", GOOD_SOURCE)
    sandbox = FakeSandbox()
    do_render(tmp_path, sandbox, task_ids=[TASK, OTHER_TASK], samples=2)
    manifest = load_manifest(tmp_path / "runs" / "r1")
    assert manifest["run_id"] == "r1"
    assert manifest["suite"] == {
        "id": suite.id,
        "version": suite.version,
        "title": suite.title,
        "task_ids": [TASK, OTHER_TASK],
    }
    assert manifest["models"] == [MODEL]
    assert manifest["samples_per_task"] == 2
    assert manifest["render"] == {"quality": "h", "fps": 60, "timeout_seconds": 900}
    assert manifest["official"] is False  # 2 samples, the suite asks for 3
    assert manifest["sandbox"]["image_digest"] == sandbox.settings.digest
    assert manifest["sandbox"]["manim_version"] == sandbox.settings.manim_version
    assert manifest["sandbox"] == sandbox.metadata()
    assert set(manifest["hashes"]) == {"prompt_sha256", "suite_sha256", "task_sha256"}
    assert set(manifest["hashes"]["task_sha256"]) == {task.id for task in suite.tasks}


def test_manifest_is_official_only_with_suite_settings_and_full_samples(tmp_path):
    do_render(tmp_path, FakeSandbox(), samples=3, run_id="full", task_ids=[TASK])
    do_render(tmp_path, FakeSandbox(), samples=3, run_id="low", task_ids=[TASK], quality="l")
    assert load_manifest(tmp_path / "runs" / "full")["official"] is True
    assert load_manifest(tmp_path / "runs" / "low")["official"] is False
    assert load_manifest(tmp_path / "runs" / "low")["render"]["quality"] == "l"


def test_continuing_a_run_with_different_quality_raises(tmp_path):
    do_render(tmp_path, FakeSandbox())
    with pytest.raises(ValueError, match="different settings.*render"):
        do_render(tmp_path, FakeSandbox(), quality="l")


def test_continuing_a_run_with_different_samples_raises(tmp_path):
    do_render(tmp_path, FakeSandbox())
    with pytest.raises(ValueError, match="samples_per_task"):
        do_render(tmp_path, FakeSandbox(), samples=2)


def test_adding_a_second_model_extends_the_manifest_models(tmp_path):
    write_sample(tmp_path / "outputs", GOOD_SOURCE)
    write_sample(tmp_path / "outputs", GOOD_SOURCE, model=OTHER_MODEL)
    sandbox = FakeSandbox()
    do_render(tmp_path, sandbox)
    do_render(tmp_path, sandbox, models=[OTHER_MODEL])
    assert load_manifest(tmp_path / "runs" / "r1")["models"] == [MODEL, OTHER_MODEL]
    do_render(tmp_path, sandbox, models=[MODEL, OTHER_MODEL])
    assert load_manifest(tmp_path / "runs" / "r1")["models"] == [MODEL, OTHER_MODEL]
    assert len(sandbox.rendered) == 2
    assert {result["model"] for result in load_results(tmp_path / "runs" / "r1")} == {MODEL, OTHER_MODEL}


def test_no_absolute_path_of_tmp_path_in_result_json(tmp_path):
    do_generate(tmp_path, GOOD_SOURCE)
    write_sample(tmp_path / "outputs", GOOD_SOURCE + "# fake:crash\n", sample=2)
    do_render(tmp_path, FakeSandbox(), samples=2)
    files = list((tmp_path / "runs").rglob("result.json"))
    assert len(files) == 2
    for path in files:
        assert str(tmp_path) not in path.read_text(encoding="utf-8")


def test_parallel_render_gives_the_same_results(tmp_path):
    for task in (TASK, OTHER_TASK):
        write_sample(tmp_path / "outputs", GOOD_SOURCE, task=task)
    do_render(tmp_path, FakeSandbox(), task_ids=[TASK, OTHER_TASK], run_id="serial")
    do_render(tmp_path, FakeSandbox(), task_ids=[TASK, OTHER_TASK], run_id="par", parallel=4)

    def digest(run_id):
        rows = load_results(tmp_path / "runs" / run_id)
        return [(row["task"]["id"], row["gates"], row["score"]) for row in rows]

    assert digest("serial") == digest("par")
    assert len(digest("par")) == 2


def test_on_event_reports_passed_or_failure(tmp_path):
    write_sample(tmp_path / "outputs", GOOD_SOURCE)
    write_sample(tmp_path / "outputs", GOOD_SOURCE + "# fake:crash\n", sample=2)
    events = []
    do_render(tmp_path, FakeSandbox(), samples=2, on_event=events.append)
    assert events == [f"{MODEL}/{TASK}/sample-1: passed gates", f"{MODEL}/{TASK}/sample-2: render_error"]


@pytest.mark.parametrize(
    ("override", "official"),
    [({}, True), ({"quality": "l"}, False), ({"fps": 15}, False), ({"timeout_seconds": 30}, False), ({"samples": 1}, False)],
)
def test_a_run_is_official_only_with_the_suites_own_settings(tmp_path, override, official):
    import json

    from manimbench.rendering import RenderRequest, render

    outcome = render(
        RenderRequest(
            models=["nobody"],
            task_ids=["fourier_series_decomposition"],
            outputs_dir=tmp_path / "outputs",
            runs_dir=tmp_path / "runs",
            run_id="r",
            sandbox=FakeSandbox(),
            **override,
        )
    )
    manifest = json.loads((outcome.run_dir / "manifest.json").read_text())
    assert manifest["official"] is official
