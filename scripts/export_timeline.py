#!/usr/bin/env python3
"""Export a 3D-replay timeline: both controllers on the same arrival stream.

Writes viz/timeline.js (a `const TIMELINE = {...}` script, not JSON, so the
viewer works from file:// with no web server). For each scenario it records
every vehicle's arrival/departure time and every signal change-point.

Usage: .venv/bin/python scripts/export_timeline.py \
    [events.json] [duration] [config] [tracks.json] [timeline.js]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from theiatron.config import load_config
from theiatron.artifacts import POINT_QUEUE_BACKEND, build_artifact, load_artifact, validate_inputs
from theiatron.controller import AdaptiveController, FixedController
from theiatron.engine import IntersectionEngine
from theiatron.events import load_events

events_path = sys.argv[1] if len(sys.argv) > 1 else "out/events.json"
duration = float(sys.argv[2]) if len(sys.argv) > 2 else 180.0
events, _meta = load_events(events_path)
app = load_config(sys.argv[3] if len(sys.argv) > 3 else "configs/approaches.yaml")
tracks_path = Path(sys.argv[4]) if len(sys.argv) > 4 else Path(events_path).with_name("tracks.json")
timeline_path = Path(sys.argv[5]) if len(sys.argv) > 5 else Path("viz/timeline.js")
names = [a.name for a in app.approaches]

artifact_path = Path(events_path).with_name("simulation.json")
if artifact_path.exists():
    simulation = load_artifact(artifact_path)
    validate_inputs(simulation, events, app, duration)
    if simulation["backend"] != POINT_QUEUE_BACKEND:
        raise ValueError("this illustrative exporter does not support that simulation backend")
    evidence_source = "canonical-simulation"
else:
    if _meta.get("simulation_artifact"):
        raise ValueError("canonical simulation.json is missing; restore the complete run directory")
    # Compatibility for historic runs only. Do not claim exact live replay:
    # these events predate recorded ticks and may have rounded timestamps.
    print("legacy events: recomputing with supplied config at nominal 0.1s cadence")
    engines = [IntersectionEngine(cls(app.signal), app.signal, app.approaches, app.queue)
               for cls in (AdaptiveController, FixedController)]
    for engine in engines:
        engine.run_replay(events, duration)
    simulation = build_artifact(app, *engines, duration, _meta)
    evidence_source = "legacy-recomputed"

OPP = {"north": "south", "south": "north", "east": "west", "west": "east"}


def _norm(v):
    import math
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n > 1e-6 else (0.0, 0.0)


# Inbound direction of each approach in IMAGE space: the count line's unit
# normal, signed to point from the approach side across the line. (Count
# lines are perpendicular to travel by construction; using the line normal
# is robust even when the line's midpoint sits off the corridor axis.)
IMG_DIR = {}
for a in app.approaches:
    (x1, y1), (x2, y2) = a.count_line
    n = _norm((y2 - y1, -(x2 - x1)))
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    toward = (mx - a.approach_side[0], my - a.approach_side[1])
    if n[0] * toward[0] + n[1] * toward[1] < 0:
        n = (-n[0], -n[1])
    IMG_DIR[a.name] = n


EXTRA_MOTIONS: list = []


def load_motions():
    """Per-car real motion: spawn lead, crossing duration, exit arm (turn)."""
    path = tracks_path
    if not path.exists():
        print(f"no {path} - illustrative straight-through motion only where an opposite arm exists")
        return {}
    raw = json.loads(path.read_text())
    counted = raw["counted"] if isinstance(raw, dict) else raw
    if isinstance(raw, dict):
        EXTRA_MOTIONS.extend(raw.get("extras", []))
    aux = {}
    for m in counted:
        tail = m.get("tail", [])
        opposite = OPP.get(m["a"])
        exit_arm = opposite if opposite in names else None
        exit_source = "assumed-straight" if exit_arm else "unknown"
        if len(tail) >= 2:
            h = _norm((tail[-1][0] - tail[0][0], tail[-1][1] - tail[0][1]))
            moved = abs(tail[-1][0] - tail[0][0]) + abs(tail[-1][1] - tail[0][1])
            if moved > 25:  # enough motion for a reliable heading
                # Exit arm whose OUTBOUND image direction best matches the
                # final heading (outbound of X = -inbound of X).
                best = max(
                    (n for n in names if n != m["a"]),
                    key=lambda n: -(h[0] * IMG_DIR[n][0] + h[1] * IMG_DIR[n][1]),
                )
                exit_arm = best
                exit_source = "inferred-heading"
        cross = m["t_end"] - m["t0"]
        cross = round(min(max(cross, 2.0), 8.0), 2) if cross > 0.5 else 4.0
        aux[(m["a"], m["n"])] = {
            "ts": min(m["ts"], m["t0"] - 0.5),
            "exit": exit_arm,
            "exit_source": exit_source,
            "cross": cross,
            "pw": world_path(m),
            "tw": twin_path(m),
        }
    return aux


# ---------------------------------------------------------------------------
# Image -> world mapping, so the 3D replay follows the footage exactly.
# The affine basis comes from the calibrated corridor directions: the north
# inbound image direction maps to world (0,1) and east inbound to (-1,0),
# matching the viewer's lane layout. Each car is anchored at its lane's
# stop-line point at the moment it crossed the count line.

STOP_WORLD = 10.0
LANE_ANCHOR = {  # world (x, z) stop points + travel dirs; mirrors viz lanes
    "north": ((-3.5, -STOP_WORLD), (0, 1)),
    "south": ((3.5, STOP_WORLD), (0, -1)),
    "east": ((STOP_WORLD, -3.5), (-1, 0)),
    "west": ((-STOP_WORLD, 3.5), (1, 0)),
}


def build_world_map():
    # Use the best-conditioned pair across the learned signal phases.  Camera
    # perspective can make the specifically named north/east directions look
    # nearly parallel even when another NS/EW pair spans the image cleanly.
    ns = [IMG_DIR[a.name] for a in app.approaches if a.phase == "NS"]
    ew = [IMG_DIR[a.name] for a in app.approaches if a.phase == "EW"]
    candidates = [
        (abs(d_ns[0] * d_ew[1] - d_ew[0] * d_ns[1]), d_ns, d_ew)
        for d_ns in ns for d_ew in ew
    ]
    if not candidates:
        return None
    _span, d_n, d_e = max(candidates, key=lambda item: item[0])
    det = d_n[0] * d_e[1] - d_e[0] * d_n[1]
    if abs(det) < 0.2:  # degenerate camera geometry
        return None
    # M solves M@d_n=(0,1), M@d_e=(-1,0)
    m = ((d_n[1] / det, -d_n[0] / det), (d_e[1] / det, -d_e[0] / det))
    # scale: median count-line distance from junction center -> STOP_WORLD
    mids = []
    for a in app.approaches:
        mids.append(((a.count_line[0][0] + a.count_line[1][0]) / 2,
                     (a.count_line[0][1] + a.count_line[1][1]) / 2))
    cx = sum(x for x, _ in mids) / len(mids)
    cy = sum(y for _, y in mids) / len(mids)
    dists = sorted(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in mids)
    med = dists[len(dists) // 2] or 100.0
    k = max(0.04, min(0.3, (STOP_WORLD * 1.6) / med))
    return m, k, (cx, cy)


WORLD_MAP = build_world_map()


def twin_path(m_rec: dict):
    """GLOBAL-frame world path: one shared transform for every car, so all
    relative positions between vehicles are preserved exactly as filmed.
    This is the digital-twin frame (no per-lane anchoring)."""
    if WORLD_MAP is None or "pts" not in m_rec or len(m_rec["pts"]) < 5:
        return None
    m, k, (cx, cy) = WORLD_MAP
    return [
        [round(t, 2),
         round((m[0][0] * (x - cx) + m[0][1] * (y - cy)) * k, 2),
         round((m[1][0] * (x - cx) + m[1][1] * (y - cy)) * k, 2)]
        for t, x, y in m_rec["pts"]
    ]


def twin_affine():
    """Image px -> twin world (x, z) affine, for warping the footage onto
    the 3D ground plane: wx = a*px + b*py + c ; wz = d*px + e*py + f."""
    if WORLD_MAP is None:
        return None
    m, k, (cx, cy) = WORLD_MAP
    a, b = m[0][0] * k, m[0][1] * k
    d, e = m[1][0] * k, m[1][1] * k
    return [a, b, -(a * cx + b * cy), d, e, -(d * cx + e * cy)]


def count_lines_tw():
    """Per-approach count line endpoints + inbound unit dir in twin coords,
    so the viewer can place stop bars and signal heads on the real geometry."""
    af = twin_affine()
    if af is None:
        return None
    a_, b_, c_, d_, e_, f_ = af
    out = {}
    for ap in app.approaches:
        seg = [[round(a_ * x + b_ * y + c_, 2), round(d_ * x + e_ * y + f_, 2)]
               for x, y in ap.count_line]
        dx, dy = IMG_DIR[ap.name]
        vx, vy = a_ * dx + b_ * dy, d_ * dx + e_ * dy  # linear part only
        n = (vx ** 2 + vy ** 2) ** 0.5 or 1.0
        out[ap.name] = {"line": seg, "dir": [round(vx / n, 4), round(vy / n, 4)]}
    return out


def world_path(m_rec: dict):
    """Map a car's real pixel trajectory to a world-space timed polyline."""
    if WORLD_MAP is None or "pts" not in m_rec or len(m_rec["pts"]) < 5:
        return None
    (m, k, _c) = WORLD_MAP
    pts = m_rec["pts"]
    t0 = m_rec["t0"]
    # exact crossing position (interpolated at t0)
    ci = max(0, max((i for i, p in enumerate(pts) if p[0] <= t0), default=0))
    if ci + 1 < len(pts) and pts[ci + 1][0] > pts[ci][0]:
        u = (t0 - pts[ci][0]) / (pts[ci + 1][0] - pts[ci][0])
        u = max(0.0, min(1.0, u))
        cxp = pts[ci][1] + (pts[ci + 1][1] - pts[ci][1]) * u
        cyp = pts[ci][2] + (pts[ci + 1][2] - pts[ci][2]) * u
    else:
        cxp, cyp = pts[ci][1], pts[ci][2]
    (ax, az), _ = LANE_ANCHOR[m_rec["a"]]
    out = []
    for t, x, y in pts:
        rx, ry = x - cxp, y - cyp
        wx = (m[0][0] * rx + m[0][1] * ry) * k + ax
        wz = (m[1][0] * rx + m[1][1] * ry) * k + az
        out.append([round(t, 2), round(wx, 2), round(wz, 2)])
    return out


MOTIONS = load_motions()


def decorate_scenario(key):
    # Copy results without recomputing physics or rounding event times.
    scenario = json.loads(json.dumps(simulation["scenarios"][key]))
    vehicles = scenario["vehicles"]
    # Per-approach sequential number == the tag painted in the footage (N7...).
    seq = {n: 0 for n in names}
    for v in vehicles:
        seq[v["a"]] += 1
        v["label"] = v["a"][0].upper() + str(seq[v["a"]])
        aux = MOTIONS.get((v["a"], seq[v["a"]]))
        v["ts"] = aux["ts"] if aux else round(v["t0"] - 6.0, 2)
        opposite = OPP.get(v["a"])
        v["exit"] = aux["exit"] if aux else (opposite if opposite in names else None)
        v["exit_source"] = aux["exit_source"] if aux else (
            "assumed-straight" if v["exit"] else "unknown"
        )
        v["cross"] = aux["cross"] if aux else 4.0
        if aux and aux.get("pw"):
            v["pw"] = aux["pw"]
        if aux and aux.get("tw"):
            v["tw"] = aux["tw"]
    return scenario


timeline = {
    "duration": duration,
    "arrivals": simulation["report"]["adaptive"]["arrivals"],
    "sample_status": simulation["report"]["sample_status"],
    "comparison": simulation["report"],
    "artifact_id": simulation["artifact_id"],
    "backend": simulation["backend"],
    "evidence_source": evidence_source,
    "phase_of": {a.name: a.phase for a in app.approaches},
    "source": _meta.get("source"),
    "approaches": names,
    # One shared elevated camera -> footage is a single wide view;
    # otherwise it's the 2x2 grid of per-approach tiles.
    "footage_layout": "single" if len({a.video for a in app.approaches}) == 1 else "grid",
    "twin_affine": twin_affine(),
    "count_lines_tw": count_lines_tw(),
    # Uncounted-but-tracked vehicles (parked, outbound, cross traffic):
    # rendered by the digital twin so every boxed car has a 3D counterpart.
    "extras": [p for p in ({"tw": twin_path(m)} for m in EXTRA_MOTIONS)
               if p["tw"]],
    "theiatron": decorate_scenario("theiatron"),
    "fixed": decorate_scenario("fixed"),
}
out = timeline_path
out.parent.mkdir(exist_ok=True)
out.write_text("const TIMELINE = " + json.dumps(timeline) + ";\n")
verdict = simulation["report"]["headline"]
print(f"wrote {out}: {len(timeline['theiatron']['vehicles'])} vehicles, "
      f"theiatron {timeline['theiatron']['avg_wait']}s vs fixed {timeline['fixed']['avg_wait']}s "
      f"({verdict})")
