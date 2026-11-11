"""Tests for the layout score. Defaults: clipping 40, overlap 40, small text 20, saturation 0.25, tallest character 0.09, overlap ratio 0.15."""

from __future__ import annotations

import json

import pytest
from conftest import clean_layout, snapshot, text_item

from manimbench.models import LayoutSettings
from manimbench.scoring import layout as layout_module
from manimbench.scoring.layout import load_layout, on_screen_text, score_layout, snapshot_times

SETTINGS = LayoutSettings()
GOOD = text_item("ok", [-1.0, -1.0, 1.0, 1.0], ident=1)
# Frame is 14.2222 wide, so the right limit is 7.1111 + 0.05. This box sticks out of it.
CLIPPED = text_item("cut", [6.5, 0.0, 8.0, 1.0], ident=2)
OFFSCREEN = text_item("gone", [8.0, 0.0, 9.0, 1.0], ident=3)


def _wrap(snaps):
    return {"snapshots": snaps}


def _steady(items, seconds=10.0):
    """The same text for the whole time: 2 snapshots, so measured time is `seconds`."""
    return _wrap([snapshot(0.0, items), snapshot(seconds, items)])


def test_clean_layout_scores_100():
    result = score_layout(clean_layout(), SETTINGS)
    assert result["available"] is True
    assert result["score"] == 100.0
    # Snapshots at 4, 8, 12, 16, 20: four gaps of 4 s.
    assert result["measured_seconds"] == 16.0


def test_label_partly_outside_frame_all_the_time_scores_60():
    # Clipping share = min(1, 1 / 0.25) = 1, loses 40 of 100 points.
    assert score_layout(_steady([GOOD, CLIPPED]), SETTINGS)["score"] == 60.0


def test_label_fully_outside_frame_is_ignored():
    assert score_layout(_steady([GOOD, OFFSCREEN]), SETTINGS)["score"] == 100.0


def test_label_inside_tolerance_is_not_clipped():
    inside = text_item("edge", [6.0, 0.0, 7.15, 1.0], ident=4)  # 7.15 < 7.1611
    assert score_layout(_steady([inside]), SETTINGS)["score"] == 100.0


def test_overlapping_labels_lose_overlap_points():
    a = text_item("a", [0.0, 0.0, 2.0, 1.0], ident=5)
    b = text_item("b", [1.0, 0.0, 3.0, 1.0], ident=6)  # shares half of each
    assert score_layout(_steady([a, b]), SETTINGS)["score"] == 60.0


def test_overlap_just_under_ratio_is_fine():
    a = text_item("a", [0.0, 0.0, 2.0, 1.0], ident=5)
    b = text_item("b", [1.72, 0.0, 3.72, 1.0], ident=6)  # overlap 0.28 / 2 = 0.14
    assert score_layout(_steady([a, b]), SETTINGS)["score"] == 100.0


def test_overlap_just_over_ratio_is_penalized():
    a = text_item("a", [0.0, 0.0, 2.0, 1.0], ident=5)
    b = text_item("b", [1.68, 0.0, 3.68, 1.0], ident=6)  # overlap 0.32 / 2 = 0.16
    assert score_layout(_steady([a, b]), SETTINGS)["score"] == 60.0


def test_overlap_ratio_uses_the_smaller_box():
    big = text_item("big", [0.0, 0.0, 10.0, 10.0], ident=5)
    small = text_item("small", [1.0, 1.0, 2.0, 2.0], ident=6)  # fully inside: ratio 1
    assert score_layout(_steady([big, small]), SETTINGS)["problem_shares"]["overlap"] == 1.0


def test_low_opacity_overlapping_label_is_ignored():
    a = text_item("a", [0.0, 0.0, 2.0, 1.0], ident=5)
    ghost = text_item("b", [0.0, 0.0, 2.0, 1.0], opacity=0.2, ident=6)
    assert score_layout(_steady([a, ghost]), SETTINGS)["score"] == 100.0


def test_small_text_loses_20_points():
    tiny = text_item("tiny", [-1.0, -1.0, 1.0, 1.0], glyph_height=0.06, ident=7)
    assert score_layout(_steady([tiny]), SETTINGS)["score"] == 80.0


def test_text_exactly_at_the_height_limit_is_not_small():
    assert score_layout(_steady([text_item("x", [-1, -1, 1, 1], glyph_height=0.09, ident=8)]), SETTINGS)["score"] == 100.0


def test_zoomed_in_camera_makes_small_text_not_small():
    frame = {"cx": 0.0, "cy": 0.0, "width": 7.1111, "height": 4.0}  # zoom 8 / 4 = 2
    ok = text_item("x", [-1, -1, 1, 1], glyph_height=0.06, ident=9)  # 0.06 * 2 = 0.12 >= 0.09
    snaps = _wrap([snapshot(0.0, [ok], frame=frame), snapshot(10.0, [ok], frame=frame)])
    assert score_layout(snaps, SETTINGS)["score"] == 100.0


def test_zoomed_in_camera_still_flags_text_that_is_too_small():
    frame = {"cx": 0.0, "cy": 0.0, "width": 7.1111, "height": 4.0}
    tiny = text_item("x", [-1, -1, 1, 1], glyph_height=0.04, ident=9)  # 0.04 * 2 = 0.08 < 0.09
    snaps = _wrap([snapshot(0.0, [tiny], frame=frame), snapshot(10.0, [tiny], frame=frame)])
    assert score_layout(snaps, SETTINGS)["score"] == 80.0


def test_problem_for_ten_percent_of_time_loses_40_percent_of_that_part():
    # Problem from t=0 to 1 of 10 s measured: 0.1 / 0.25 = 0.4 of the part is lost.
    # Clipping: 40 * 0.4 = 16 lost of 100 -> 84.
    clean = [GOOD]
    snaps = _wrap([snapshot(0.0, [GOOD, CLIPPED]), snapshot(1.0, clean), snapshot(10.0, clean)])
    result = score_layout(snaps, SETTINGS)
    assert result["score"] == 84.0
    assert result["problem_shares"]["clipping"] == 0.4


def test_small_text_for_ten_percent_of_time_loses_8_points():
    tiny = text_item("tiny", [-1, -1, 1, 1], glyph_height=0.06, ident=7)
    snaps = _wrap([snapshot(0.0, [tiny]), snapshot(1.0, [GOOD]), snapshot(10.0, [GOOD])])
    assert score_layout(snaps, SETTINGS)["score"] == 92.0  # 20 * 0.4 = 8 lost


def test_problem_share_saturates_at_one():
    # 30% of the time is above the 25% saturation point, so the share is capped at 1.
    snaps = _wrap([snapshot(0.0, [GOOD, CLIPPED]), snapshot(3.0, [GOOD]), snapshot(10.0, [GOOD])])
    assert score_layout(snaps, SETTINGS)["score"] == 60.0


def test_all_three_problems_at_once_scores_zero():
    both = text_item("both", [6.5, 0.0, 8.0, 1.0], glyph_height=0.06, ident=10)  # clipped and small
    other = text_item("other", [6.5, 0.0, 8.0, 1.0], ident=11)  # overlaps it
    assert score_layout(_steady([both, other]), SETTINGS)["score"] == 0.0


def test_3d_snapshots_are_skipped():
    # The 3d snapshot holds a clipped label but is not measured: 5 s measured, clean.
    snaps = _wrap([snapshot(0.0, [GOOD]), snapshot(5.0, [GOOD, CLIPPED], projection="3d"), snapshot(10.0, [GOOD])])
    result = score_layout(snaps, SETTINGS)
    assert result["score"] == 100.0
    assert result["measured_seconds"] == 5.0


def test_all_3d_layout_is_unavailable():
    snaps = _wrap([snapshot(0.0, [GOOD], projection="3d"), snapshot(5.0, [GOOD], projection="3d")])
    result = score_layout(snaps, SETTINGS)
    assert result["available"] is False
    assert result["score"] is None
    assert result["reason"] == "not_enough_2d_snapshots"


def test_single_snapshot_is_unavailable():
    result = score_layout(_wrap([snapshot(1.0, [GOOD])]), SETTINGS)
    assert result["available"] is False
    assert result["snapshots"] == 1


def test_no_snapshots_is_unavailable():
    result = score_layout(_wrap([]), SETTINGS)
    assert result["available"] is False
    assert result["reason"] == "no_snapshots"


def test_none_layout_is_unavailable():
    assert score_layout(None, SETTINGS)["available"] is False


def test_same_time_snapshots_have_no_measured_time():
    result = score_layout(_wrap([snapshot(2.0, [GOOD]), snapshot(2.0, [GOOD])]), SETTINGS)
    assert result["available"] is False
    assert result["reason"] == "no_measured_time"


def test_issues_name_the_problem_text():
    result = score_layout(_steady([GOOD, CLIPPED]), SETTINGS)
    assert result["issues"] == [{"kind": "clipping", "text": "cut", "seconds": 10.0}]


def test_load_layout_reads_valid_file(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(clean_layout()), encoding="utf-8")
    assert load_layout(path)["scene_class"] == "MainScene"


def test_load_layout_missing_file_is_none(tmp_path):
    assert load_layout(tmp_path / "nope.json") is None


def test_load_layout_invalid_json_is_none(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_layout(path) is None


def test_load_layout_json_list_is_none(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_layout(path) is None


def test_load_layout_without_snapshot_list_is_none(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text('{"snapshots": 3}', encoding="utf-8")
    assert load_layout(path) is None


def test_load_layout_oversized_file_is_none(tmp_path, monkeypatch):
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(clean_layout()), encoding="utf-8")
    monkeypatch.setattr(layout_module, "MAX_LAYOUT_BYTES", 10)
    assert load_layout(path) is None


def test_malformed_text_items_are_skipped():
    bad = [
        {"string": "no box"},
        {"string": "short box", "box": [0, 0, 1]},
        {"string": "zero size", "box": [1, 1, 1, 1]},
        {"string": "text box", "box": ["a", 0, 1, 1]},
        "not a dict",
        GOOD,
    ]
    result = score_layout(_steady(bad), SETTINGS)
    assert result["score"] == 100.0
    assert result["text_seen"] == 1


def test_malformed_snapshots_are_skipped_not_fatal():
    snaps = _wrap([{"time": 1.0}, "junk", {"time": "x", "frame": {}}, snapshot(0.0, [GOOD]), snapshot(10.0, [GOOD])])
    result = score_layout(snaps, SETTINGS)
    assert result["available"] is True
    assert result["snapshots"] == 2


def test_snapshot_with_non_list_text_is_kept_with_no_text():
    raw = snapshot(0.0, [])
    raw["text"] = "oops"
    assert score_layout(_wrap([raw, snapshot(10.0, [])]), SETTINGS)["available"] is True


def test_on_screen_text_uses_latest_snapshot_at_or_before_time():
    layout = _wrap(
        [
            snapshot(1.0, [text_item("A", [0, 0, 1, 1], ident=1)]),
            snapshot(5.0, [text_item("B", [0, 0, 1, 1], ident=2), text_item("B", [2, 0, 3, 1], ident=3), text_item("C", [4, 0, 5, 1], ident=4)]),
        ]
    )
    assert on_screen_text(layout, 0.5) == []
    assert on_screen_text(layout, 1.0) == ["A"]
    assert on_screen_text(layout, 4.9) == ["A"]
    assert on_screen_text(layout, 5.0) == ["B", "C"]
    assert on_screen_text(layout, 99.0) == ["B", "C"]


def test_on_screen_text_of_none_is_empty():
    assert on_screen_text(None, 1.0) == []


def test_snapshot_times_are_sorted():
    layout = _wrap([snapshot(5.0, []), snapshot(1.0, []), snapshot(3.0, [])])
    assert snapshot_times(layout) == [1.0, 3.0, 5.0]


def test_snapshot_times_of_none_is_empty():
    assert snapshot_times(None) == []


@pytest.mark.parametrize(
    ("name", "box"),
    [
        ("past the top edge", [-1.0, 3.6, 1.0, 4.4]),
        ("past the bottom edge", [-1.0, -4.4, 1.0, -3.6]),
        ("past the left edge", [-7.6, 0.0, -6.0, 0.5]),
        ("past the right edge", [6.0, 0.0, 7.6, 0.5]),
    ],
)
def test_text_cut_off_by_any_of_the_four_edges_is_clipped(name, box):
    """The frame is 14.2222 wide and 8 tall, centered: x within 7.11, y within 4."""
    from manimbench.models import LayoutSettings
    from manimbench.scoring.layout import score_layout

    layout = {"snapshots": [snapshot(0.0, [text_item(name, box)]), snapshot(10.0, [text_item(name, box)])]}
    result = score_layout(layout, LayoutSettings())
    # Clipped for the whole measured time: all 40 clipping points lost, nothing else.
    assert result["score"] == 60.0, name
    assert result["problem_seconds"] == {"clipping": 10.0, "overlap": 0.0, "small_text": 0.0}


def test_issue_seconds_never_exceed_the_time_measured():
    """Two labels with the same text, both cut off, are one issue for that stretch, not two."""
    from manimbench.models import LayoutSettings
    from manimbench.scoring.layout import score_layout

    twins = [text_item("same words", [6.0, 0.0, 7.6, 0.5], ident=1), text_item("same words", [6.0, 2.0, 7.6, 2.5], ident=2)]
    result = score_layout({"snapshots": [snapshot(0.0, twins), snapshot(10.0, twins)]}, LayoutSettings())
    assert result["measured_seconds"] == 10.0
    assert result["issues"] == [{"kind": "clipping", "text": "same words", "seconds": 10.0}]
