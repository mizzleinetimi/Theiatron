from types import SimpleNamespace

import numpy as np

import json

import pytest

from run_demo import (
    _calibration_quality,
    _export_3d_timeline,
    _new_run_dir,
    _normalize_frame,
)
from theiatron.config import AppConfig, ApproachConfig, save_config
from theiatron.events import save_events


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


def test_live_run_directory_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        _new_run_dir(tmp_path, "../outside")


def test_run_specific_3d_timeline_export(tmp_path):
    approaches = []
    for name in ("north", "south", "east", "west"):
        phase = "NS" if name in ("north", "south") else "EW"
        approaches.append(ApproachConfig(
            name=name,
            video="clip.mp4",
            phase=phase,
            count_line=(
                [[100, 120], [180, 120]] if phase == "NS"
                else [[220, 80], [220, 160]]
            ),
            approach_side=([140, 60] if phase == "NS" else [280, 120]),
        ))
    config = tmp_path / "config.yaml"
    events = tmp_path / "events.json"
    tracks = tmp_path / "tracks.json"
    timeline = tmp_path / "timeline.js"
    save_config(AppConfig(approaches=approaches), config)
    save_events([(5.0, "north"), (12.0, "east")], events,
                meta={"source": "/tmp/clip.mp4"})
    tracks.write_text(json.dumps({"counted": [], "extras": []}))

    ok, message = _export_3d_timeline(events, 30.0, config, tracks, timeline)

    assert ok, message
    payload = json.loads(
        timeline.read_text().removeprefix("const TIMELINE = ").removesuffix(";\n")
    )
    assert payload["arrivals"] == 2
    assert payload["sample_status"] == "inconclusive"
    assert payload["source"] == "/tmp/clip.mp4"
    assert len(payload["twin_affine"]) == 6
    assert set(payload["count_lines_tw"]) == {"north", "south", "east", "west"}
