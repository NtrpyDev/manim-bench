"""Tests for suite and task loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from manimbench.paths import DEFAULT_SUITE_PATH
from manimbench.tasks import filter_tasks, load_suite

SHIPPED = load_suite(DEFAULT_SUITE_PATH)


def _task(**over):
    data = {
        "id": "t_one",
        "version": "1",
        "title": "T",
        "prompt": "Do it.",
        "must_show": [{"id": "a", "text": "A thing"}],
    }
    data.update(over)
    return {key: value for key, value in data.items() if value is not None}


def _write(tmp_path: Path, tasks=None, **suite_over) -> Path:
    tasks = tasks if tasks is not None else [_task()]
    names = []
    for index, task in enumerate(tasks):
        name = f"task{index}.yaml"
        (tmp_path / name).write_text(yaml.safe_dump(task), encoding="utf-8")
        names.append(name)
    suite = {
        "id": "s",
        "version": "1",
        "title": "S",
        "tasks": names,
        "judge": {"criteria": [{"id": "task_coverage", "weight": 1, "question": "Q?"}]},
    }
    suite.update(suite_over)
    path = tmp_path / "suite.yaml"
    path.write_text(yaml.safe_dump(suite), encoding="utf-8")
    return path


def test_minimal_suite_loads(tmp_path):
    suite = load_suite(_write(tmp_path))
    assert [task.id for task in suite.tasks] == ["t_one"]
    assert suite.samples_per_task == 1


def test_shipped_suite_has_six_tasks(suite):
    assert len(suite.tasks) == 6


def test_shipped_suite_has_three_samples_per_task(suite):
    assert suite.samples_per_task == 3


def test_shipped_suite_has_four_criteria(suite):
    assert [item.id for item in suite.criteria] == ["correctness", "explanation", "task_coverage", "clarity"]


def test_every_shipped_task_has_must_show_and_judge_notes(suite):
    for task in suite.tasks:
        assert task.must_show, task.id
        assert task.judge_notes, task.id


def test_filter_tasks_without_ids_returns_all(suite):
    assert len(filter_tasks(suite, None)) == 6
    assert len(filter_tasks(suite, [])) == 6


def test_filter_tasks_selects_requested_in_suite_order(suite):
    ids = [suite.tasks[3].id, suite.tasks[1].id]
    assert [task.id for task in filter_tasks(suite, ids)] == [suite.tasks[1].id, suite.tasks[3].id]


def test_filter_tasks_rejects_unknown_id(suite):
    with pytest.raises(ValueError, match="nope"):
        filter_tasks(suite, [suite.tasks[0].id, "nope"])


def test_missing_required_task_key_raises(tmp_path):
    path = _write(tmp_path, [_task(prompt=None)])
    with pytest.raises(ValueError, match="prompt"):
        load_suite(path)


def test_bad_task_id_raises(tmp_path):
    with pytest.raises(ValueError, match="invalid id"):
        load_suite(_write(tmp_path, [_task(id="Bad-Id")]))


def test_duplicate_must_show_id_raises(tmp_path):
    items = [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]
    with pytest.raises(ValueError, match="duplicate must_show"):
        load_suite(_write(tmp_path, [_task(must_show=items)]))


def test_empty_must_show_raises(tmp_path):
    with pytest.raises(ValueError, match="at least one must_show"):
        load_suite(_write(tmp_path, [_task(must_show=[])]))


def test_unknown_layout_key_raises(tmp_path):
    path = _write(tmp_path, scoring={"layout": {"bogus": 1}})
    with pytest.raises(ValueError, match="bogus"):
        load_suite(path)


def test_must_show_criterion_not_in_criteria_raises(tmp_path):
    path = _write(tmp_path, scoring={"must_show_criterion": "nope"})
    with pytest.raises(ValueError, match="must_show_criterion"):
        load_suite(path)


def test_zero_samples_per_task_raises(tmp_path):
    with pytest.raises(ValueError, match="samples_per_task"):
        load_suite(_write(tmp_path, samples_per_task=0))


def test_duplicate_task_ids_in_suite_raise(tmp_path):
    with pytest.raises(ValueError, match="duplicate task ids"):
        load_suite(_write(tmp_path, [_task(), _task()]))
