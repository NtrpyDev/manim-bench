"""Tests for the human review sheet and judge agreement."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from manimbench.review import agreement, export_sheet, read_sheet, spearman


def test_spearman_perfect_agreement():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0


def test_spearman_reversed_order():
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0


def test_spearman_handles_ties_with_average_ranks():
    # Ranks 1, 2.5, 2.5, 4 against 1, 2, 3, 4. cov 4.5, spreads sqrt(4.5) and sqrt(5): 4.5 / sqrt(22.5) = 0.9487
    assert spearman([1, 2, 2, 3], [1, 2, 3, 4]) == 0.9487


def test_spearman_needs_three_points():
    assert spearman([1, 2], [1, 2]) is None


def test_spearman_constant_input_is_undefined():
    assert spearman([2, 2, 2], [1, 2, 3]) is None
    assert spearman([1, 2, 3], [5, 5, 5]) is None


def test_spearman_length_mismatch_is_none():
    assert spearman([1, 2, 3], [1, 2]) is None


def _make_result(run: Path, model: str, task, sample: int, *, passed=True, criteria=None):
    folder = run / model / task.id / f"sample-{sample}"
    folder.mkdir(parents=True)
    result = {
        "model": model,
        "sample": sample,
        "task": {"id": task.id, "title": task.title},
        "gates": {"passed": passed},
        "render": {"video": "media/result.mp4"},
        "judge": {"criteria": criteria} if criteria else {},
    }
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (folder / "media").mkdir()
    (folder / "media" / "result.mp4").write_bytes(f"video of {model} sample {sample}".encode())


@pytest.fixture
def run(tmp_path, suite):
    folder = tmp_path / "run"
    task = suite.tasks[0]
    _make_result(folder, "secret-model-a", task, 1)
    _make_result(folder, "secret-model-a", task, 2)
    _make_result(folder, "secret-model-b", task, 1)
    _make_result(folder, "secret-model-b", task, 2, passed=False)
    return folder


def _rows(path: Path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_export_sheet_skips_samples_that_failed_gates(run, suite, tmp_path):
    assert export_sheet(run, suite, tmp_path / "sheet.csv") == 3


def test_export_sheet_respects_limit(run, suite, tmp_path):
    assert export_sheet(run, suite, tmp_path / "sheet.csv", limit=2) == 2
    assert len(_rows(tmp_path / "sheet.csv")) == 3


def test_export_sheet_header_has_no_model_column(run, suite, tmp_path):
    export_sheet(run, suite, tmp_path / "sheet.csv")
    header = _rows(tmp_path / "sheet.csv")[0]
    assert header == ["id", "task", "video", "correctness", "explanation", "task_coverage", "clarity", "notes"]


def test_exported_sheet_and_videos_are_blind(run, suite, tmp_path):
    """Nothing the rater opens may say which model made a video."""
    export_sheet(run, suite, tmp_path / "sheet.csv")
    assert "secret-model" not in (tmp_path / "sheet.csv").read_text()
    videos = sorted((tmp_path / "sheet-videos").iterdir())
    assert [video.name for video in videos] == ["s001.mp4", "s002.mp4", "s003.mp4"]
    for row in _rows(tmp_path / "sheet.csv")[1:]:
        assert row[2] == f"sheet-videos/{row[0]}.mp4"
        assert (tmp_path / row[2]).exists()


def test_key_file_ties_each_row_to_its_sample_and_video(run, suite, tmp_path):
    export_sheet(run, suite, tmp_path / "sheet.csv")
    key = _rows(tmp_path / "sheet-key.csv")
    assert key[0] == ["id", "sample"]
    assert sorted(row[1] for row in key[1:]) == [
        f"secret-model-a/{suite.tasks[0].id}/sample-1",
        f"secret-model-a/{suite.tasks[0].id}/sample-2",
        f"secret-model-b/{suite.tasks[0].id}/sample-1",
    ]
    for row_id, sample in key[1:]:
        model, _task, number = sample.split("/")
        expected = f"video of {model} sample {number.removeprefix('sample-')}".encode()
        assert (tmp_path / "sheet-videos" / f"{row_id}.mp4").read_bytes() == expected


def test_exporting_again_replaces_old_videos(run, suite, tmp_path):
    export_sheet(run, suite, tmp_path / "sheet.csv")
    export_sheet(run, suite, tmp_path / "sheet.csv", limit=1)
    assert [video.name for video in (tmp_path / "sheet-videos").iterdir()] == ["s001.mp4"]


def test_export_is_deterministic(run, suite, tmp_path):
    export_sheet(run, suite, tmp_path / "one" / "sheet.csv")
    export_sheet(run, suite, tmp_path / "two" / "sheet.csv")
    assert (tmp_path / "one" / "sheet.csv").read_text() == (tmp_path / "two" / "sheet.csv").read_text()
    assert (tmp_path / "one" / "sheet-key.csv").read_text() == (tmp_path / "two" / "sheet-key.csv").read_text()


def _fill(path: Path, ratings: dict[str, dict[str, str]]):
    header, *rows = _rows(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            for column, value in ratings.get(row[0], {}).items():
                row[header.index(column)] = value
            writer.writerow(row)


def test_sheet_round_trip(run, suite, tmp_path):
    sheet = tmp_path / "sheet.csv"
    export_sheet(run, suite, sheet)
    ids = [row[0] for row in _rows(sheet)[1:]]
    samples = dict(_rows(tmp_path / "sheet-key.csv")[1:])
    _fill(sheet, {ids[0]: {"correctness": "3", "clarity": "2.5"}, ids[1]: {"explanation": "4"}})
    ratings = read_sheet(sheet, suite)
    assert ratings == {samples[ids[0]]: {"correctness": 3.0, "clarity": 2.5}, samples[ids[1]]: {"explanation": 4.0}}


def test_a_row_missing_from_the_key_file_is_an_error(run, suite, tmp_path):
    sheet = tmp_path / "sheet.csv"
    export_sheet(run, suite, sheet)
    (tmp_path / "sheet-key.csv").write_text("id,sample\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not in the key file"):
        read_sheet(sheet, suite)


def test_unrated_rows_are_skipped(run, suite, tmp_path):
    sheet = tmp_path / "sheet.csv"
    export_sheet(run, suite, sheet)
    assert read_sheet(sheet, suite) == {}


@pytest.mark.parametrize("value", ["5", "-1", "4.1"])
def test_out_of_range_rating_raises(run, suite, tmp_path, value):
    sheet = tmp_path / "sheet.csv"
    export_sheet(run, suite, sheet)
    first = _rows(sheet)[1][0]
    _fill(sheet, {first: {"correctness": value}})
    with pytest.raises(ValueError, match="between 0 and 4"):
        read_sheet(sheet, suite)


def test_agreement_exact_numbers(tmp_path, suite):
    task = suite.tasks[0]
    folder = tmp_path / "run"
    judge_scores = {1: 2.0, 2: 2.0, 3: 3.0}
    for sample, value in judge_scores.items():
        _make_result(folder, "m", task, sample, criteria={"correctness": value})
    human = {f"m/{task.id}/sample-{n}": {"correctness": h} for n, h in {1: 1.0, 2: 2.0, 3: 4.0}.items()}
    report = agreement(folder, suite, human)
    # Human ranks 1,2,3; judge 2,2,3 gives ranks 1.5,1.5,3. cov 1.5, spreads sqrt(2) and sqrt(1.5): 1.5 / sqrt(3) = 0.866
    # Gaps |1-2|, |2-2|, |4-3| = 1, 0, 1 -> mean 2/3. Judge minus human: +1, 0, -1 -> 0.
    assert report["correctness"] == {"samples": 3, "spearman": 0.866, "mean_absolute_gap": 0.667, "judge_minus_human": 0.0}
    assert report["clarity"] == {"samples": 0, "spearman": None, "mean_absolute_gap": None, "judge_minus_human": None}


def test_agreement_ignores_ratings_for_unknown_samples(tmp_path, suite):
    task = suite.tasks[0]
    folder = tmp_path / "run"
    _make_result(folder, "m", task, 1, criteria={"correctness": 3.0})
    report = agreement(folder, suite, {"other/x/sample-1": {"correctness": 3.0}})
    assert report["correctness"]["samples"] == 0
