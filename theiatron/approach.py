"""Arrival extraction: tracked vehicle positions -> per-approach arrival events.

A vehicle registers exactly one arrival when its track crosses the count
line from the approach side to the far side. Robustness measures:
- one count per track ID (per-feed seen set),
- minimum track age before a track may count (kills ghost tracks born
  from ID switches, which mostly die young),
- crossing must go approach-side -> far-side, which inherently rejects
  wrong-way / opposite-lane traffic,
- optional ROI polygon to exclude irrelevant image regions,
- reset() for video loop wraparound (track IDs restart and would collide).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import ApproachConfig

# Track is dropped after this many consecutive updates without a detection.
STALE_AFTER = 30


class TrackRecorder:
    """Per-camera motion log so the 3D replay can mirror real car movement:
    when it first appeared, how fast it approached, how long the crossing
    took, and (from the trajectory tail) which arm it exited toward."""

    # Full paths: the 3D replay mirrors each car's exact motion, so keep
    # every processed-frame sample (1800 = 3 min at 10 FPS; cap is a
    # runaway guard, not a design limit).
    MAX_PTS = 4000

    def __init__(self):
        self.live: dict[int, dict] = {}

    def update(self, now: float, pts: list[tuple[int, float, float]]) -> None:
        for tid, x, y in pts:
            rec = self.live.setdefault(tid, {"pts": []})
            rec["pts"].append((now, float(x), float(y)))
            if len(rec["pts"]) > self.MAX_PTS:
                del rec["pts"][0]

    def reset(self) -> None:
        self.live.clear()


@dataclass
class _TrackState:
    pos: tuple[float, float]
    age: int = 1
    missed: int = 0
    # Last known non-zero side of the count line. A detector sample can land
    # exactly on the line; retaining the prior side prevents that sample from
    # swallowing an otherwise valid approach -> far-side crossing.
    side: int = 0


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _orient(a, b, c) -> int:
    return _sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _segments_cross(p, q, a, b) -> bool:
    """True when segment p-q properly crosses segment a-b. Using the actual
    count-line SEGMENT (not its infinite extension) matters once several
    approaches share one camera frame: other corridors may cross the
    infinite line far away from the drawn stop line."""
    return (
        _orient(a, b, p) * _orient(a, b, q) < 0
        and _orient(p, q, a) * _orient(p, q, b) < 0
    )


def _point_on_segment(p, a, b, eps: float = 1e-6) -> bool:
    """Whether p lies on the finite segment a-b (within floating tolerance)."""
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    return (
        abs(cross) <= eps
        and min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
    )


def _point_in_polygon(pt: tuple[float, float], poly: list) -> bool:
    """Ray casting; poly is [[x, y], ...]."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


class ArrivalExtractor:
    def __init__(self, cfg: ApproachConfig, min_track_age: int = 3):
        if not cfg.count_line or not cfg.approach_side:
            raise ValueError(f"approach '{cfg.name}' missing count_line/approach_side")
        self.name = cfg.name
        self.p1 = tuple(map(float, cfg.count_line[0]))
        self.p2 = tuple(map(float, cfg.count_line[1]))
        self.roi = cfg.roi
        self.min_track_age = min_track_age
        self.approach_sign = _sign(self._side(tuple(map(float, cfg.approach_side))))
        if self.approach_sign == 0:
            raise ValueError(f"approach '{cfg.name}': approach_side lies on the count line")
        self.tracks: dict[int, _TrackState] = {}
        self.counted: set[int] = set()
        self.last_counted: set[int] = set()  # IDs counted in the latest update (for UI flash)
        # track id -> sequential arrival number (1-based); lets the UI paint a
        # stable per-approach car number that the 3D replay reuses verbatim.
        self.count_num: dict[int, int] = {}
        self.count_time: dict[int, float] = {}
        self.total = 0

    def _side(self, pt: tuple[float, float]) -> float:
        """Signed area cross product: which side of the count line pt is on."""
        (x1, y1), (x2, y2) = self.p1, self.p2
        return (x2 - x1) * (pt[1] - y1) - (y2 - y1) * (pt[0] - x1)

    def update(
        self, now: float, detections: list[tuple[int, float, float]],
        claimed: set | None = None,
    ) -> list[tuple[float, str]]:
        """Feed one processed frame's tracks [(track_id, x, y), ...].

        Returns arrival events [(now, approach_name), ...] and remembers
        which IDs already counted. `x, y` should be the bottom-center of
        the vehicle box (closest point to the road plane).

        `claimed` is shared across every approach watching the same camera:
        one physical vehicle is one arrival, even if its (turning) path
        crosses a second approach's count line in a countable direction.
        """
        events: list[tuple[float, str]] = []
        seen: set[int] = set()
        self.last_counted = set()
        for tid, x, y in detections:
            pt = (float(x), float(y))
            if self.roi and not _point_in_polygon(pt, self.roi):
                continue
            seen.add(tid)
            state = self.tracks.get(tid)
            if state is None:
                self.tracks[tid] = _TrackState(pt, side=_sign(self._side(pt)))
                continue
            prev = state.pos
            prev_side = state.side
            current_side = _sign(self._side(pt))
            state.pos = pt
            state.age += 1
            state.missed = 0
            if current_side != 0:
                state.side = current_side
            if tid in self.counted or state.age < self.min_track_age:
                continue
            if claimed is not None and tid in claimed:
                continue
            # Count only approach-side -> far-side transitions that physically
            # cross the drawn line segment; a wrong-way vehicle transitions
            # far -> approach and never matches, and traffic in other parts
            # of the frame never touches the segment itself.
            if (
                prev_side == self.approach_sign
                and current_side == -self.approach_sign
                # If the immediately previous sample was exactly on the line,
                # the two-frame segment merely touches its endpoint. The
                # retained non-zero side still establishes a valid crossing.
                and (
                    _segments_cross(prev, pt, self.p1, self.p2)
                    or _point_on_segment(prev, self.p1, self.p2)
                )
            ):
                self.counted.add(tid)
                self.last_counted.add(tid)
                if claimed is not None:
                    claimed.add(tid)
                self.total += 1
                self.count_num[tid] = self.total
                self.count_time[tid] = now
                events.append((now, self.name))
        # Age out tracks that vanished (occlusion, exit, ID retired).
        for tid in list(self.tracks):
            if tid not in seen:
                self.tracks[tid].missed += 1
                if self.tracks[tid].missed > STALE_AFTER:
                    del self.tracks[tid]
        return events

    def harvest_motions(self, recorder: "TrackRecorder") -> list[dict]:
        """Pair this approach's counted IDs with their recorded motion."""
        out = []
        for tid, num in self.count_num.items():
            rec = recorder.live.get(tid)
            if not rec or len(rec["pts"]) < 2:
                continue
            out.append({
                "a": self.name,
                "n": num,
                "ts": round(rec["pts"][0][0], 2),
                "t0": round(self.count_time[tid], 2),
                "t_end": round(rec["pts"][-1][0], 2),
                "tail": [[round(x), round(y)] for _, x, y in rec["pts"][-6:]],
                "pts": [[round(t, 2), round(x, 1), round(y, 1)]
                        for t, x, y in rec["pts"]],
            })
        return out

    def reset(self) -> None:
        """Call on video loop wraparound: tracker IDs restart and collide."""
        self.tracks.clear()
        self.counted.clear()
        self.count_num.clear()  # numbering (self.total) continues across loops
        self.count_time.clear()
