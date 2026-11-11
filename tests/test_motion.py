"""Tests for motion analysis and video probing.

Synthetic videos are 20 s at 10 fps, 320x180. The analyzer samples 5 frames a
second, so the step is 0.2 s and a 20 s video has 100 samples.
"""

from __future__ import annotations

import pytest
from conftest import write_video

from manimbench.media import extract_frames, probe_video
from manimbench.models import PacingSettings
from manimbench.scoring.motion import analyze_motion

PACING = PacingSettings()  # still limit 8 s, active min 2 s or 10%, blank max 50%


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    root = tmp_path_factory.mktemp("videos")
    return {kind: write_video(root / f"{kind}.mp4", kind=kind) for kind in ["moving", "static", "blank", "stall"]}


def test_probe_video_reports_duration_fps_and_size(videos):
    info = probe_video(videos["moving"])
    assert info["duration_seconds"] == pytest.approx(20.0, abs=0.2)
    assert info["fps"] == pytest.approx(10.0)
    assert info["frames"] == 200
    assert (info["width"], info["height"]) == (320, 180)


def test_probe_video_missing_file_is_empty(tmp_path):
    assert probe_video(tmp_path / "nope.mp4") == {}


def test_probe_video_garbage_file_is_empty(tmp_path):
    path = tmp_path / "junk.mp4"
    path.write_bytes(b"this is not a video" * 100)
    assert probe_video(path) == {}


def test_moving_video_has_motion_is_not_blank_and_paces_perfectly(videos):
    result = analyze_motion(videos["moving"], PACING)
    assert result["available"] is True
    assert result["has_motion"] is True
    assert result["not_blank"] is True
    assert result["score"] == 100.0
    assert result["duration_seconds"] == pytest.approx(20.0, abs=0.3)


def test_static_video_has_no_motion(videos):
    result = analyze_motion(videos["static"], PACING)
    assert result["has_motion"] is False
    assert result["active_seconds"] == 0.0
    assert result["not_blank"] is True


def test_static_video_pacing_score_is_zero(videos):
    # One still run of about 19.8 s: dead = 19.8 - 8 = 11.8, over half of 20 s, so the loss is capped at 100%.
    assert analyze_motion(videos["static"], PACING)["score"] == 0.0


def test_blank_video_is_blank(videos):
    result = analyze_motion(videos["blank"], PACING)
    assert result["not_blank"] is False
    assert result["blank_share"] == 1.0


def test_stall_video_longest_still_run(videos):
    # Motion lasts for the first quarter (5 s, 25 of 99 sample gaps), so the still
    # run is about 74 gaps * 0.2 s = 14.8 s. Tolerance 1 s for codec effects.
    result = analyze_motion(videos["stall"], PACING)
    assert result["longest_still_seconds"] == pytest.approx(14.8, abs=1.0)


def test_stall_video_pacing_score_matches_formula(videos):
    # dead = longest still - 8 = 6.8 s; score = 100 * (1 - 6.8 / (0.5 * 20)) = 32. Tolerance 8 points.
    result = analyze_motion(videos["stall"], PACING)
    assert result["score"] == pytest.approx(32.0, abs=8.0)
    expected = 100.0 * (1.0 - result["dead_seconds"] / (0.5 * result["duration_seconds"]))
    assert result["score"] == pytest.approx(expected, abs=0.01)


def test_stall_video_still_counts_as_moving_overall(videos):
    assert analyze_motion(videos["stall"], PACING)["has_motion"] is True


def test_required_active_seconds_is_larger_of_floor_and_share(videos):
    # 10% of 20 s = 2 s, equal to the 2 s floor.
    assert analyze_motion(videos["moving"], PACING)["required_active_seconds"] == pytest.approx(2.0, abs=0.05)
    strict = PacingSettings(min_active_seconds=5.0)
    assert analyze_motion(videos["moving"], strict)["required_active_seconds"] == 5.0


def test_unreadable_video_is_unavailable(tmp_path):
    path = tmp_path / "junk.mp4"
    path.write_bytes(b"not a video")
    assert analyze_motion(path, PACING)["available"] is False


def test_missing_video_is_unavailable(tmp_path):
    assert analyze_motion(tmp_path / "nope.mp4", PACING)["available"] is False


def test_extract_frames_writes_requested_jpegs_with_times(videos, tmp_path):
    out = tmp_path / "frames"
    written = extract_frames(videos["moving"], [1.0, 5.0, 10.0], out)
    assert [item["file"] for item in written] == ["frame_01.jpg", "frame_02.jpg", "frame_03.jpg"]
    assert [item["time"] for item in written] == pytest.approx([1.0, 5.0, 10.0], abs=0.1)
    for item in written:
        assert (out / item["file"]).stat().st_size > 0


def test_extract_frames_clamps_time_past_the_end(videos, tmp_path):
    written = extract_frames(videos["moving"], [500.0], tmp_path / "f")
    assert len(written) == 1
    assert written[0]["time"] == pytest.approx(19.9, abs=0.05)


def test_extract_frames_resizes_wide_frames(videos, tmp_path):
    import cv2

    written = extract_frames(videos["moving"], [1.0], tmp_path / "f", width=160)
    image = cv2.imread(str(tmp_path / "f" / written[0]["file"]))
    assert image.shape[1] == 160


def test_extract_frames_of_missing_video_is_empty(tmp_path):
    assert extract_frames(tmp_path / "nope.mp4", [1.0], tmp_path / "f") == []
