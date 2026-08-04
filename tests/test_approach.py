import pytest

from theiatron.approach import ArrivalExtractor
from theiatron.config import ApproachConfig


def make_extractor(min_age=3, roi=None):
    # Horizontal count line at y=100; vehicles approach from above (y < 100).
    cfg = ApproachConfig(
        name="north",
        video="",
        phase="NS",
        count_line=[[0, 100], [200, 100]],
        approach_side=[100, 0],
        roi=roi,
    )
    return ArrivalExtractor(cfg, min_track_age=min_age)


def drive_across(ex, tid, ys, t0=0.0):
    events = []
    for i, y in enumerate(ys):
        events += ex.update(t0 + i * 0.1, [(tid, 100.0, y)])
    return events


def test_track_counted_once():
    ex = make_extractor()
    # Cross, jitter back, cross again: still one arrival.
    events = drive_across(ex, 1, [60, 80, 95, 105, 98, 110, 120])
    assert len(events) == 1
    assert ex.total == 1


def test_min_age_filters_ghost_tracks():
    ex = make_extractor(min_age=3)
    # A 2-frame-old track jumping over the line (typical ID-switch ghost).
    events = drive_across(ex, 7, [95, 105])
    assert events == []
    # A mature track counts fine.
    events = drive_across(ex, 8, [60, 70, 80, 95, 105])
    assert len(events) == 1


def test_direction_gating_rejects_wrongway():
    ex = make_extractor()
    # Moving far-side -> approach-side (opposite lane / wrong way).
    events = drive_across(ex, 2, [140, 120, 105, 95, 80, 60])
    assert events == []


def test_roi_excludes_outside_tracks():
    ex = make_extractor(roi=[[0, 0], [200, 0], [200, 200], [0, 200]])
    outside = drive_across(ex, 3, [60, 80, 95, 105, 120])  # x=100 inside
    assert len(outside) == 1
    ex2 = make_extractor(roi=[[0, 0], [50, 0], [50, 200], [0, 200]])
    events = drive_across(ex2, 4, [60, 80, 95, 105, 120])  # x=100 outside ROI
    assert events == []


def test_loop_reset_clears_seen_ids():
    ex = make_extractor()
    assert len(drive_across(ex, 5, [60, 80, 95, 105, 120])) == 1
    ex.reset()
    # Same ID reused after wraparound is a NEW vehicle and may count again.
    assert len(drive_across(ex, 5, [60, 80, 95, 105, 120])) == 1
    assert ex.total == 2


def test_two_events_from_two_vehicles():
    ex = make_extractor()
    events = []
    for i, (ya, yb) in enumerate([(60, 40), (80, 60), (95, 80), (105, 95), (120, 105)]):
        events += ex.update(i * 0.1, [(10, 100.0, ya), (11, 50.0, yb)])
    assert len(events) == 2


def test_crossing_beyond_segment_end_not_counted():
    # Track crosses the infinite extension of the line (x=300 > line end 200)
    # but never the drawn segment itself: must NOT count.
    ex = make_extractor()
    events = []
    for i, y in enumerate([60, 80, 95, 105, 120]):
        events += ex.update(i * 0.1, [(9, 300.0, y)])
    assert events == []


def test_sample_exactly_on_line_still_counts_crossing():
    ex = make_extractor(min_age=1)
    events = drive_across(ex, 12, [80, 100, 105])
    assert events == [(0.2, "north")]


def test_sample_on_infinite_extension_still_does_not_count():
    ex = make_extractor(min_age=1)
    events = []
    for i, y in enumerate([80, 100, 105]):
        events += ex.update(i * 0.1, [(13, 300.0, y)])
    assert events == []


def test_missing_calibration_raises():
    cfg = ApproachConfig(name="x", video="", phase="NS")
    with pytest.raises(ValueError):
        ArrivalExtractor(cfg)
