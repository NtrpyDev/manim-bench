"""Check the judge against a person.

A vision judge is only worth trusting where it agrees with a human. This
writes a sheet of samples for a person to rate on the same 0 to 4 scale the
judge uses, then measures how closely the judge's scores follow theirs.
"""

from __future__ import annotations

import csv
import random
import shutil
from pathlib import Path
from typing import Any

from manimbench.models import Suite
from manimbench.rendering import load_results

SHEET_SEED = 20261110


def key_path(sheet: Path) -> Path:
    """The file that says which sample each sheet row is. Not for the rater to open."""
    return sheet.with_name(sheet.stem + "-key.csv")


def export_sheet(run_dir: Path, suite: Suite, output: Path, *, limit: int = 30) -> int:
    """Write a rating sheet, blind.

    Each row gets a number instead of a name, and its video is copied to
    ``<sheet>-videos/<number>.mp4``, so nothing the rater sees says which model
    made it. The numbers are tied back to samples in ``<sheet>-key.csv``.
    """
    rows = [result for result in load_results(run_dir) if result["gates"]["passed"]]
    random.Random(SHEET_SEED).shuffle(rows)
    rows = rows[:limit]
    criteria = [criterion.id for criterion in suite.criteria]
    output.parent.mkdir(parents=True, exist_ok=True)
    videos = output.with_name(output.stem + "-videos")
    if videos.exists():
        shutil.rmtree(videos)
    videos.mkdir()
    with output.open("w", encoding="utf-8", newline="") as sheet, key_path(output).open("w", encoding="utf-8", newline="") as key:
        sheet_writer = csv.writer(sheet)
        key_writer = csv.writer(key)
        sheet_writer.writerow(["id", "task", "video", *criteria, "notes"])
        key_writer.writerow(["id", "sample"])
        for number, result in enumerate(rows, start=1):
            row_id = f"s{number:03d}"
            sample = f"{result['model']}/{result['task']['id']}/sample-{result['sample']}"
            shutil.copy2(run_dir / sample / str(result["render"]["video"]), videos / f"{row_id}.mp4")
            sheet_writer.writerow([row_id, result["task"]["title"], f"{videos.name}/{row_id}.mp4", *["" for _ in criteria], ""])
            key_writer.writerow([row_id, sample])
    return len(rows)


def read_sheet(path: Path, suite: Suite) -> dict[str, dict[str, float]]:
    """Read a filled-in sheet and return ratings by sample.

    Rows with no ratings are skipped. A rating outside 0 to 4 is an error.
    """
    with key_path(path).open("r", encoding="utf-8", newline="") as handle:
        samples = {row["id"]: row["sample"] for row in csv.DictReader(handle)}
    ratings: dict[str, dict[str, float]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["id"] not in samples:
                raise ValueError(f"Row {row['id']} is not in the key file {key_path(path).name}")
            scores: dict[str, float] = {}
            for criterion in suite.criteria:
                value = (row.get(criterion.id) or "").strip()
                if not value:
                    continue
                number = float(value)
                if not 0 <= number <= 4:
                    raise ValueError(f"{row['id']}: {criterion.id} must be between 0 and 4, got {value}")
                scores[criterion.id] = number
            if scores:
                ratings[samples[row["id"]]] = scores
    return ratings


def agreement(run_dir: Path, suite: Suite, ratings: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Per criterion: how many samples were compared, the rank correlation, and the mean gap."""
    judged: dict[str, dict[str, float]] = {}
    for result in load_results(run_dir):
        if result["judge"].get("criteria"):
            sample = f"{result['model']}/{result['task']['id']}/sample-{result['sample']}"
            judged[sample] = result["judge"]["criteria"]
    report: dict[str, Any] = {}
    for criterion in suite.criteria:
        pairs = [
            (scores[criterion.id], judged[sample][criterion.id])
            for sample, scores in ratings.items()
            if criterion.id in scores and sample in judged and criterion.id in judged[sample]
        ]
        human = [pair[0] for pair in pairs]
        judge = [pair[1] for pair in pairs]
        report[criterion.id] = {
            "samples": len(pairs),
            "spearman": spearman(human, judge),
            "mean_absolute_gap": round(sum(abs(a - b) for a, b in pairs) / len(pairs), 3) if pairs else None,
            "judge_minus_human": round(sum(b - a for a, b in pairs) / len(pairs), 3) if pairs else None,
        }
    return report


def spearman(first: list[float], second: list[float]) -> float | None:
    """Spearman rank correlation, with ties given their average rank. None if undefined."""
    if len(first) != len(second) or len(first) < 3:
        return None
    a, b = _ranks(first), _ranks(second)
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    spread_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
    spread_b = sum((y - mean_b) ** 2 for y in b) ** 0.5
    if spread_a == 0 or spread_b == 0:
        return None
    return round(covariance / (spread_a * spread_b), 4)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2 + 1
        for index in order[position : end + 1]:
            ranks[index] = average
        position = end + 1
    return ranks
