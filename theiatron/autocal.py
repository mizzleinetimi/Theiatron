"""Auto-calibration: learn the intersection's approaches by watching traffic.

Point the camera at any junction, observe for a minute or two, and this
module turns the raw vehicle trajectories into a full approach config:

  1. filter to genuinely moving tracks,
  2. cluster their ENTRY headings (first part of each track, so turns
     don't blur the direction) into inbound corridors,
  3. locate the junction center as the least-squares intersection of the
     corridor axes,
  4. place each count line perpendicular to its corridor, as far upstream
     as track coverage allows (so most vehicles are already tracked when
     they reach it),
  5. constrain lines to the drivable surface (road mask), and
  6. name approaches by compass direction and pair opposite corridors
     into signal phases.

The geometry here is pure Python so it is unit-testable without video.
"""

from __future__ import annotations

import math
from itertools import combinations
from dataclasses import dataclass, field

from .config import ApproachConfig

MIN_TRACK_PTS = 8
MIN_DISPLACEMENT = 60.0  # px; anything less is parked / jitter
ENTRY_FRAC = 0.4         # heading from the first 40% of the track
CLUSTER_TOL_DEG = 35.0
# 2, not 3: a quiet side road may show only a couple of vehicles in the
# observation window, and the moving-displacement filter already rejects
# parked-car jitter.
MIN_CLUSTER_TRACKS = 2
MIN_LINE_DIST = 60.0     # px upstream of center; keeps lines out of the box
COVERAGE_TARGET = 0.7


@dataclass
class Corridor:
    tracks: list          # each: list[(t, x, y)]
    direction: tuple      # unit inbound heading (toward the junction)
    name: str = ""
    phase: str = ""
    count_line: list = field(default_factory=list)
    approach_side: list = field(default_factory=list)


def _norm(vx, vy):
    n = math.hypot(vx, vy)
    return (vx / n, vy / n) if n > 1e-9 else (0.0, 0.0)


def moving_tracks(tracks: list[list]) -> list[list]:
    out = []
    for pts in tracks:
        if len(pts) < MIN_TRACK_PTS:
            continue
        (_, x0, y0), (_, x1, y1) = pts[0], pts[-1]
        if math.hypot(x1 - x0, y1 - y0) >= MIN_DISPLACEMENT:
            out.append(pts)
    return out


def entry_heading(pts: list) -> tuple:
    k = max(2, int(len(pts) * ENTRY_FRAC))
    (_, x0, y0), (_, x1, y1) = pts[0], pts[k - 1]
    return _norm(x1 - x0, y1 - y0)


def cluster_by_heading(tracks: list[list]) -> list[Corridor]:
    """Greedy circular clustering of entry headings."""
    items = [(entry_heading(p), p) for p in tracks]
    items = [(h, p) for h, p in items if h != (0.0, 0.0)]
    clusters: list[list] = []
    tol = math.cos(math.radians(CLUSTER_TOL_DEG))
    for h, p in items:
        best, best_dot = None, tol
        for cl in clusters:
            ch = cl[0]
            d = h[0] * ch[0] + h[1] * ch[1]
            if d > best_dot:
                best, best_dot = cl, d
        if best is None:
            clusters.append([h, [p]])
        else:
            best[1].append(p)
            n = len(best[1])
            # running mean of the heading, renormalized
            best[0] = _norm(best[0][0] * (n - 1) / n + h[0] / n,
                            best[0][1] * (n - 1) / n + h[1] / n)
    out = []
    for h, plist in clusters:
        if len(plist) >= MIN_CLUSTER_TRACKS:
            out.append(Corridor(tracks=plist, direction=h))
    return out


def _entry_centroid(c: Corridor) -> tuple:
    xs, ys, n = 0.0, 0.0, 0
    for pts in c.tracks:
        k = max(2, int(len(pts) * ENTRY_FRAC))
        for _, x, y in pts[:k]:
            xs += x
            ys += y
            n += 1
    return (xs / n, ys / n)


def junction_center(corridors: list[Corridor]) -> tuple:
    """Least-squares point closest to every corridor's axis line."""
    # Each axis: point p_i (entry centroid), direction d_i. Minimize sum of
    # squared perpendicular distances -> 2x2 normal equations.
    a11 = a12 = a22 = b1 = b2 = 0.0
    for c in corridors:
        px, py = _entry_centroid(c)
        dx, dy = c.direction
        nx, ny = -dy, dx  # normal to the axis
        a11 += nx * nx
        a12 += nx * ny
        a22 += ny * ny
        dot = nx * px + ny * py
        b1 += nx * dot
        b2 += ny * dot
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-9:  # all corridors parallel; fall back to global centroid
        cs = [_entry_centroid(c) for c in corridors]
        return (sum(x for x, _ in cs) / len(cs), sum(y for _, y in cs) / len(cs))
    return ((a22 * b1 - a12 * b2) / det, (a11 * b2 - a12 * b1) / det)


def place_line(c: Corridor, center: tuple, frame_wh: tuple) -> None:
    """Count line perpendicular to the corridor, upstream of the center."""
    dx, dy = c.direction
    px, py = -dy, dx  # lateral axis
    spans = []
    for pts in c.tracks:
        ss = [((x - center[0]) * dx + (y - center[1]) * dy) for _, x, y in pts]
        spans.append((min(ss), max(ss)))
    # Never place the line upstream of where tracks are actually
    # established: cap the search at the 25th percentile of first-seen
    # positions (else the line drifts to the frame edge where vehicles
    # blink into existence).
    s_mins = sorted(s for s, _ in spans)
    lo = s_mins[len(s_mins) // 4] + 45.0
    candidates = []
    s = -MIN_LINE_DIST
    while s > lo:
        cov = sum(1 for smin, smax in spans if smin < s < smax) / len(spans)
        candidates.append((s, cov))
        s -= 5.0
    if not candidates:
        s_star = -MIN_LINE_DIST
    else:
        best_cov = max(cov for _, cov in candidates)
        target = min(COVERAGE_TARGET, best_cov)
        # farthest upstream position that still catches enough tracks
        s_star = min(s for s, cov in candidates if cov >= target - 1e-9)
    # lateral extent of the corridor near the chosen position
    lats = []
    for pts in c.tracks:
        for _, x, y in pts:
            s = (x - center[0]) * dx + (y - center[1]) * dy
            if abs(s - s_star) < 30.0:
                lats.append((x - center[0]) * px + (y - center[1]) * py)
    if not lats:
        lats = [-30.0, 30.0]
    # Percentile extent, not min/max: one mis-clustered track must not
    # drag the line across the map.
    lats.sort()
    l_lo = lats[max(0, int(len(lats) * 0.1))] - 14.0
    l_hi = lats[min(len(lats) - 1, int(len(lats) * 0.9))] + 14.0
    if l_hi - l_lo < 56.0:  # at least a car-width-and-a-half of line
        mid = (l_lo + l_hi) / 2.0
        l_lo, l_hi = mid - 28.0, mid + 28.0
    w, h = frame_wh

    def pt(l):
        x = center[0] + dx * s_star + px * l
        y = center[1] + dy * s_star + py * l
        return [int(max(2, min(w - 2, x))), int(max(2, min(h - 2, y)))]

    c.count_line = [pt(l_lo), pt(l_hi)]
    mx = center[0] + dx * (s_star - 70.0)
    my = center[1] + dy * (s_star - 70.0)
    c.approach_side = [int(max(2, min(w - 2, mx))), int(max(2, min(h - 2, my)))]


COMPASS = {"north": (0.0, -1.0), "south": (0.0, 1.0), "east": (1.0, 0.0), "west": (-1.0, 0.0)}


def name_and_phase(corridors: list[Corridor]) -> None:
    """Compass names from the upstream direction; opposite corridors pair
    into one phase; the more-vertical axis is NS."""
    # Pair every learned corridor into at most two signal axes.  A fixed
    # dot-product cutoff is brittle under perspective: two truly opposing
    # roads need not appear 180 degrees apart in image coordinates.  Preserve
    # the strongest opposite pair (normally the dominant through-road), then
    # put the remaining approaches on the other axis.  Optimizing the sum of
    # both pairs can incorrectly split one unmistakable road just to improve
    # a weak/turning-traffic pair.
    indices = list(range(len(corridors)))

    def opposition(i, j):
        return (corridors[i].direction[0] * corridors[j].direction[0]
                + corridors[i].direction[1] * corridors[j].direction[1])

    if len(indices) == 4:
        i, j = min(combinations(indices, 2), key=lambda pair: opposition(*pair))
        axes = [[i, j], [k for k in indices if k not in (i, j)]]
    elif len(indices) == 3:
        i, j = min(combinations(indices, 2), key=lambda pair: opposition(*pair))
        axes = [[i, j], [k for k in indices if k not in (i, j)]]
    else:
        axes = [indices]
    # more-vertical axis (by mean |dy| share) is NS
    def verticality(axis):
        return sum(abs(corridors[i].direction[1]) for i in axis) / len(axis)

    axes.sort(key=verticality, reverse=True)
    used = set()
    for ai, axis in enumerate(axes[:2]):
        phase = "NS" if ai == 0 else "EW"
        pool = ["north", "south"] if phase == "NS" else ["east", "west"]
        for i in axis:
            ux, uy = -corridors[i].direction[0], -corridors[i].direction[1]
            best = max((n for n in pool if n not in used),
                       key=lambda n: ux * COMPASS[n][0] + uy * COMPASS[n][1],
                       default=None)
            if best is None:  # >2 corridors on one axis; borrow other pool
                best = max((n for n in COMPASS if n not in used),
                           key=lambda n: ux * COMPASS[n][0] + uy * COMPASS[n][1])
            used.add(best)
            corridors[i].name = best
            corridors[i].phase = phase


def calibrate(tracks: list[list], frame_wh: tuple) -> list[Corridor]:
    """Full pipeline: raw trajectories -> named, phased, lined corridors."""
    moving = moving_tracks(tracks)
    corridors = cluster_by_heading(moving)
    if len(corridors) < 2:
        raise ValueError(
            f"only {len(corridors)} traffic corridor(s) found - observe longer "
            "or check the camera view"
        )
    corridors.sort(key=lambda c: -len(c.tracks))
    corridors = corridors[:4]
    center = junction_center(corridors)
    for c in corridors:
        place_line(c, center, frame_wh)
    name_and_phase(corridors)
    return corridors


def to_approach_configs(corridors: list[Corridor], video: str) -> list[ApproachConfig]:
    order = {"north": 0, "south": 1, "east": 2, "west": 3}
    out = [
        ApproachConfig(
            name=c.name, video=video, phase=c.phase,
            count_line=[list(c.count_line[0]), list(c.count_line[1])],
            approach_side=list(c.approach_side),
        )
        for c in corridors
    ]
    out.sort(key=lambda a: order.get(a.name, 9))
    return out


# ---------------------------------------------------------------------------
# Road mask backends


def road_mask_motion(tracks: list[list], frame_wh: tuple, width: int = 52):
    """Drivable surface = everywhere traffic actually drove, dilated.
    Viewpoint-agnostic and needs no extra model."""
    import cv2
    import numpy as np

    w, h = frame_wh
    mask = np.zeros((h, w), dtype=np.uint8)
    for pts in moving_tracks(tracks):
        poly = np.array([[int(x), int(y)] for _, x, y in pts], dtype=np.int32)
        cv2.polylines(mask, [poly], False, 255, width)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
    )
    return mask


def road_mask_segformer(frame):
    """Cityscapes-trained SegFormer 'road' class. Needs `transformers`.
    Returns None (with a reason) when unavailable or nothing found."""
    try:
        from transformers import (
            AutoImageProcessor,
            AutoModelForSemanticSegmentation,
            pipeline,
        )
    except ImportError:
        return None, "transformers not installed"
    import cv2
    import numpy as np
    from PIL import Image

    model_id = "nvidia/segformer-b0-finetuned-cityscapes-1024-1024"
    # Offline-first: load strictly from the local cache (no version-check
    # request to Hugging Face); fall back to a one-time download only when
    # the cache is empty.
    try:
        proc = AutoImageProcessor.from_pretrained(model_id, local_files_only=True)
        mdl = AutoModelForSemanticSegmentation.from_pretrained(model_id, local_files_only=True)
    except Exception:
        try:
            proc = AutoImageProcessor.from_pretrained(model_id)
            mdl = AutoModelForSemanticSegmentation.from_pretrained(model_id)
        except Exception as e:
            return None, f"model unavailable (first download needs internet): {e}"
    seg = pipeline("image-segmentation", model=mdl, image_processor=proc)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = seg(Image.fromarray(rgb))
    road = [r for r in results if r["label"] == "road"]
    if not road:
        return None, "no 'road' class in segmentation output"
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    for r in road:
        m = np.array(r["mask"])
        mask[m > 127] = 255
    return mask, "ok"


def clip_line_to_mask(p1, p2, mask):
    """Longest run of the segment that lies on drivable surface."""
    import numpy as np

    n = 60
    xs = np.linspace(p1[0], p2[0], n)
    ys = np.linspace(p1[1], p2[1], n)
    h, w = mask.shape
    inside = [
        mask[min(h - 1, max(0, int(y))), min(w - 1, max(0, int(x)))] > 0
        for x, y in zip(xs, ys)
    ]
    best_len, best_range, run_start = 0, None, None
    for i, ok in enumerate(inside + [False]):
        if ok and run_start is None:
            run_start = i
        elif not ok and run_start is not None:
            if i - run_start > best_len:
                best_len, best_range = i - run_start, (run_start, i - 1)
            run_start = None
    if best_range is None or best_len < n * 0.45:
        return p1, p2  # mask would gut the line; keep the geometric answer
    a, b = best_range
    return ([int(xs[a]), int(ys[a])], [int(xs[b]), int(ys[b])])
