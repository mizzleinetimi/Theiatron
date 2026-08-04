import math
import random

from theiatron import autocal

W, H = 1280, 720
CX, CY = 640, 360


def synth_track(entry_dir, exit_dir=None, n=30, noise=3.0, start_d=350, rng=None):
    """A track entering along entry_dir (unit vector toward center) and
    leaving along exit_dir (defaults to straight through)."""
    rng = rng or random.Random(0)
    exit_dir = exit_dir or entry_dir
    pts = []
    lat = rng.uniform(-14, 14)
    px, py = -entry_dir[1], entry_dir[0]
    for i in range(n):
        u = i / (n - 1)
        d = start_d * (1 - u)  # distance to center along entry
        if u < 0.5:
            x = CX - entry_dir[0] * d + px * lat
            y = CY - entry_dir[1] * d + py * lat
        else:
            d_out = start_d * (u - 0.5) * 2
            x = CX + exit_dir[0] * d_out + px * lat
            y = CY + exit_dir[1] * d_out + py * lat
        pts.append((i * 0.1, x + rng.gauss(0, noise), y + rng.gauss(0, noise)))
    return pts


DIRS = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}


def four_way(rng):
    tracks = []
    for d, count in (("down", 8), ("up", 7), ("right", 4), ("left", 4)):
        for _ in range(count):
            tracks.append(synth_track(DIRS[d], rng=rng))
    # a couple of turners and some parked-car jitter
    tracks.append(synth_track(DIRS["down"], exit_dir=DIRS["right"], rng=rng))
    for _ in range(5):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        tracks.append([(i * 0.1, x + rng.gauss(0, 2), y + rng.gauss(0, 2)) for i in range(20)])
    return tracks


def test_four_way_calibration():
    rng = random.Random(7)
    corridors = autocal.calibrate(four_way(rng), (W, H))
    assert len(corridors) == 4
    names = {c.name for c in corridors}
    assert names == {"north", "south", "east", "west"}
    phases = {c.name: c.phase for c in corridors}
    assert phases["north"] == phases["south"] == "NS"
    assert phases["east"] == phases["west"] == "EW"


def test_lines_upstream_and_crossable():
    rng = random.Random(3)
    corridors = autocal.calibrate(four_way(rng), (W, H))
    for c in corridors:
        (x1, y1), (x2, y2) = c.count_line
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        # line sits upstream of center along the inbound direction
        s = (mx - CX) * c.direction[0] + (my - CY) * c.direction[1]
        assert s <= -autocal.MIN_LINE_DIST + 6
        # most member tracks would actually cross it (span both sides)
        crossing = 0
        for pts in c.tracks:
            ss = [((x - CX) * c.direction[0] + (y - CY) * c.direction[1]) for _, x, y in pts]
            if min(ss) < s < max(ss):
                crossing += 1
        assert crossing / len(c.tracks) >= 0.6


def test_parked_cars_ignored():
    rng = random.Random(1)
    tracks = four_way(rng)
    total_member = sum(
        len(c.tracks) for c in autocal.calibrate(tracks, (W, H))
    )
    # 24 movers + 1 turner; the 5 jitter tracks must not appear
    assert total_member <= 25


def test_t_junction():
    rng = random.Random(11)
    tracks = []
    for d, count in (("down", 8), ("up", 7), ("right", 5)):
        for _ in range(count):
            tracks.append(synth_track(DIRS[d], rng=rng))
    corridors = autocal.calibrate(tracks, (W, H))
    assert len(corridors) == 3
    phases = {c.name: c.phase for c in corridors}
    assert sorted(phases.values()).count("NS") == 2


def test_junction_center_recovery():
    rng = random.Random(5)
    corridors = autocal.cluster_by_heading(autocal.moving_tracks(four_way(rng)))
    cx, cy = autocal.junction_center(corridors)
    assert math.hypot(cx - CX, cy - CY) < 40


def test_clip_line_to_mask():
    import numpy as np
    mask = np.zeros((100, 200), dtype=np.uint8)
    mask[:, 50:150] = 255  # road is the middle band
    p1, p2 = autocal.clip_line_to_mask([0, 50], [199, 50], mask)
    assert 40 <= p1[0] <= 60 and 140 <= p2[0] <= 160
