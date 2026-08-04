from types import SimpleNamespace

import numpy as np

from run_demo import _calibration_quality, _new_run_dir, _normalize_frame


def corridor(name, phase, n=4, line=None):
    return SimpleNamespace(
        name=name,
        phase=phase,
        tracks=[object()] * n,
        count_line=line or [[100, 100], [180, 100]],
        approach_side=[140, 20],
    )


def test_calibration_quality_accepts_complete_two_phase_layout():
    corridors = [
        corridor("north", "NS"),
        corridor("south", "NS"),
        corridor("east", "EW"),
        corridor("west", "EW"),
    ]
    quality = _calibration_quality(corridors, moving_count=20)
    assert quality["label"] == "good"
    assert quality["geometry_valid"] is True
    assert quality["phases_found"] == ["EW", "NS"]


def test_calibration_quality_rejects_one_axis_and_collapsed_line():
    corridors = [
        corridor("north", "NS", line=[[2, 2], [2, 2]]),
        corridor("south", "NS"),
    ]
    quality = _calibration_quality(corridors, moving_count=20)
    assert quality["label"] == "low"
    assert quality["geometry_valid"] is False
    assert quality["phases_found"] == ["NS"]


def test_calibration_quality_rejects_two_track_spurious_corridor():
    corridors = [
        corridor("north", "NS", n=5),
        corridor("south", "NS", n=2),
        corridor("east", "EW", n=10),
        corridor("west", "EW", n=13),
    ]
    quality = _calibration_quality(corridors, moving_count=31)
    assert quality["label"] == "low"
    assert quality["minimum_tracks_per_corridor"] == 2


def test_frame_normalization_uses_calibration_resolution():
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    normalized = _normalize_frame(frame)
    assert normalized.shape == (720, 1280, 3)


def test_live_run_directory_never_overwrites(tmp_path):
    run = _new_run_dir(tmp_path, "demo")
    assert run.is_dir()
    try:
        _new_run_dir(tmp_path, "demo")
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing live run directory was overwritten")
