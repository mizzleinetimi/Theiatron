#!/usr/bin/env python3
"""Theiatron demo runner.

Live demo (adaptive drives the lights; fixed-timer shadow runs on the same
vision-derived arrivals so the dashboard shows the live wait-time gap):

    python run_demo.py --config configs/approaches.yaml --duration 120 \
        --record out/annotated.mp4 --record-arrivals out/events.json

Learn and analyze a new single-camera intersection video end to end:

    python run_demo.py --live-demo --video path/to/intersection.mp4

Deterministic offline replay of a recorded arrival stream (no vision):

    python run_demo.py --replay out/events.json --duration 120

Calibration (click 2 count-line points, then 1 point on the side vehicles
approach from; press s to save, r to restart, q to abort):

    python run_demo.py --config configs/approaches.yaml --calibrate north
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from theiatron.config import AppConfig, load_config, save_config
from theiatron.controller import AdaptiveController, FixedController, SignalState
from theiatron.engine import IntersectionEngine
from theiatron.events import load_events, save_events
from theiatron.metrics import (
    MIN_COMPARISON_ARRIVALS,
    comparison_report,
    summarize,
    total_censored_wait,
    write_report,
)

PHASE_LABEL = {"NS": "North-South", "EW": "East-West"}
DEFAULT_CONFIG = "configs/approaches.yaml"


def config_path(args, default: str = DEFAULT_CONFIG) -> str:
    """Resolve an optional CLI config without hiding replay metadata."""
    return args.config or default


def narrate(engine) -> str:
    """One plain-language line: what the signal is doing and why."""
    sm = engine.sm
    active_label = PHASE_LABEL[sm.active.value]
    other_label = PHASE_LABEL[sm.active.other.value]
    by_phase = engine.queues_by_phase()
    active_q = sum(len(q.queue) for q in by_phase[sm.active])
    other_q = sum(len(q.queue) for q in by_phase[sm.active.other])
    if sm.state is SignalState.GREEN:
        if active_q > 0:
            return f"Green for {active_label}: clearing {active_q} waiting cars"
        if other_q > 0:
            return f"{active_label} is clear - {other_q} now waiting on {other_label}"
        return "All clear - cameras watching for the next queue"
    if sm.state is SignalState.YELLOW:
        cause = sm.green_end_cause
        reason = getattr(engine.controller, "last_reason", None)
        if cause == "max_green":
            return f"Fairness cap reached - giving {other_label} a turn"
        if reason == "pressure":
            return f"Long queue on {other_label} - switching over"
        return f"{active_label} all clear - switching to {other_label}"
    return "Safety pause: all directions red for 1 second"


def build_engines(cfg: AppConfig):
    adaptive = IntersectionEngine(
        AdaptiveController(cfg.signal), cfg.signal, cfg.approaches, cfg.queue
    )
    fixed = IntersectionEngine(
        FixedController(cfg.signal), cfg.signal, cfg.approaches, cfg.queue
    )
    return adaptive, fixed


def finish(cfg, adaptive, fixed, end_time, out_dir):
    a_sum = summarize(adaptive, end_time)
    f_sum = summarize(fixed, end_time)
    md, data = comparison_report(a_sum, f_sum)
    md_path, json_path = write_report(md, data, out_dir)
    print(md)
    print(f"report: {md_path}  |  {json_path}")
    return data


def run_replay(args):
    events, meta = load_events(args.replay)
    cfg_path = args.config or meta.get("config") or DEFAULT_CONFIG
    if not Path(cfg_path).exists():
        sys.exit(f"replay config does not exist: {cfg_path}")
    cfg = load_config(cfg_path)
    duration = (
        args.duration
        if args.duration is not None
        else float(meta.get("duration") or (events[-1][0] + 30.0 if events else 60.0))
    )
    adaptive, fixed = build_engines(cfg)
    adaptive.run_replay(events, duration)
    fixed.run_replay(events, duration)
    print(f"replayed {len(events)} arrivals over {duration:.0f}s (meta: {meta})")
    finish(cfg, adaptive, fixed, duration, args.out)


def run_calibrate(args):
    import cv2

    cfg_path = config_path(args)
    cfg = load_config(cfg_path)
    approach = next((a for a in cfg.approaches if a.name == args.calibrate), None)
    if approach is None:
        sys.exit(f"no approach named {args.calibrate!r} in {cfg_path}")
    cap = cv2.VideoCapture(approach.video)
    if not cap.isOpened():
        sys.exit(f"cannot open {approach.video}")
    # Grab a mid-video frame: usually has traffic in a representative state.
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit("cannot read frame")

    clicks: list[tuple[int, int]] = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 3:
            clicks.append((x, y))

    win = f"calibrate: {approach.name} (2 line pts, 1 approach-side pt; s=save r=reset q=quit)"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    while True:
        vis = frame.copy()
        for i, pt in enumerate(clicks):
            color = (60, 60, 230) if i < 2 else (80, 220, 80)
            cv2.circle(vis, pt, 6, color, -1)
        if len(clicks) >= 2:
            cv2.line(vis, clicks[0], clicks[1], (60, 60, 230), 2)
        if len(clicks) == 3:
            cv2.putText(vis, "press s to save", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 220, 80), 2)
        cv2.imshow(win, vis)
        key = cv2.waitKey(30) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            clicks.clear()
        if key == ord("s") and len(clicks) == 3:
            approach.count_line = [list(clicks[0]), list(clicks[1])]
            approach.approach_side = list(clicks[2])
            save_config(cfg, cfg_path)
            print(f"saved count line for {approach.name} -> {cfg_path}")
            break
    cv2.destroyAllWindows()


def run_autocal(args):
    """Learn the intersection from traffic: watch, cluster, place lines."""
    import shutil
    from collections import defaultdict

    import cv2
    import numpy as np

    from theiatron import autocal
    from theiatron.dashboard import APPROACH_COLORS
    from theiatron.detection import VehicleDetector
    from theiatron.feeds import VideoFeed

    cfg_path = config_path(args)
    cfg = load_config(cfg_path)
    if not cfg.approaches:
        sys.exit("config needs at least one approach entry to know which video to watch")
    video = cfg.approaches[0].video

    print(f"observing {video} for {args.observe:.0f}s of traffic...")
    fps = cfg.vision.process_fps
    feed = VideoFeed(video, fps, loop=False)
    det = VehicleDetector(cfg.vision)
    paths = defaultdict(list)
    frame0 = None
    seg_early = None
    writer = None
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    process_path = out_dir / "autocal_process_raw.mp4"
    AMBER, WHITE = (36, 183, 255), (255, 255, 255)

    def hud(vis, text, sub=""):
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 58 if sub else 40), (14, 13, 10), -1)
        cv2.putText(vis, text, (16, 28), cv2.FONT_HERSHEY_DUPLEX, 0.8, AMBER, 2)
        if sub:
            cv2.putText(vis, sub, (16, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

    ticks = int(args.observe * fps)
    for k in range(ticks):
        frame, _ = feed.read()
        if frame is None:
            break
        if frame0 is None:
            frame0 = frame.copy()
            writer = cv2.VideoWriter(str(process_path), cv2.VideoWriter_fourcc(*"mp4v"),
                                     fps, (frame0.shape[1], frame0.shape[0]))
            if args.road_model in ("auto", "segformer"):
                print("segmenting road surface on first frame...")
                seg_early, _why = autocal.road_mask_segformer(frame0)
        now = k / fps
        dets = det.track(frame)
        for d in dets:
            paths[d.track_id].append((now, d.x, d.y))
        # -- render the observation process --
        vis = frame.copy()
        if seg_early is not None:
            tint = np.zeros_like(vis)
            tint[seg_early > 0] = (60, 38, 12)
            vis = cv2.add(vis, tint)
        for pts_ in paths.values():
            if len(pts_) >= 2:
                poly = np.array([[int(x), int(y)] for _, x, y in pts_], np.int32)
                cv2.polylines(vis, [poly], False, (50, 160, 220), 2)
        for d in dets:
            x1, y1, x2, y2 = map(int, d.box)
            cv2.rectangle(vis, (x1 - 1, y1 - 1), (x2 + 1, y2 + 1), (0, 0, 0), 4)
            cv2.rectangle(vis, (x1, y1), (x2, y2), WHITE, 2)
            cv2.putText(vis, str(d.track_id), (x1, max(14, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
        moving_n = len(autocal.moving_tracks(list(paths.values())))
        hud(vis, f"AUTO-CALIBRATION  |  observing {now:5.1f}s / {args.observe:.0f}s"
                 f"   tracks {len(paths)}   moving {moving_n}",
            "tinted = drivable surface (segmentation model) - trails = vehicle paths the system remembers")
        writer.write(vis)
        if not args.headless:
            cv2.imshow("Theiatron auto-calibration", vis)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
    feed.release()
    if not args.headless:
        cv2.destroyAllWindows()
    tracks = list(paths.values())
    h, w = frame0.shape[:2]
    print(f"{len(tracks)} raw tracks ({len(autocal.moving_tracks(tracks))} moving)")

    corridors = autocal.calibrate(tracks, (w, h))

    # Road mask. Motion evidence (where traffic provably drove) is always
    # trusted; the segmentation model's visible-asphalt mask is UNIONED in
    # when plausible, so clipping only removes ground that neither backend
    # calls road. Segmentation alone tends to lose tree-shadowed stretches
    # on elevated views.
    mask = autocal.road_mask_motion(tracks, (w, h))
    used = "motion"
    if args.road_model in ("auto", "segformer"):
        seg_mask = seg_early  # already computed on the first frame
        if seg_mask is None:
            print("segformer backend unavailable (transformers missing or no road found)")
        else:
            pts = [p for t in autocal.moving_tracks(tracks) for p in t]
            on = sum(
                1 for _, x, y in pts
                if seg_mask[min(h - 1, max(0, int(y))), min(w - 1, max(0, int(x)))] > 0
            )
            agree = on / max(len(pts), 1)
            frac = float((seg_mask > 0).mean())
            print(f"segformer road mask: {frac:.0%} of frame, "
                  f"agrees with {agree:.0%} of observed traffic")
            if 0.05 <= frac <= 0.6:
                mask = np.maximum(mask, seg_mask)
                used = "motion + segformer"
    print(f"road mask backend: {used}")

    for c in corridors:
        c.count_line = list(autocal.clip_line_to_mask(*c.count_line, mask))

    backup = str(cfg_path) + ".bak"
    shutil.copyfile(cfg_path, backup)
    cfg.approaches = autocal.to_approach_configs(corridors, video)
    save_config(cfg, cfg_path)

    # Overlay for human review.
    vis = (frame0 * 0.55).astype(np.uint8)
    tint = np.zeros_like(vis)
    tint[mask > 0] = (60, 45, 20)
    vis = cv2.add(vis, tint)
    for pts in autocal.moving_tracks(tracks):
        poly = np.array([[int(x), int(y)] for _, x, y in pts], dtype=np.int32)
        cv2.polylines(vis, [poly], False, (90, 90, 90), 1)
    for c in corridors:
        col = APPROACH_COLORS.get(c.name, (255, 255, 255))
        p1, p2 = tuple(c.count_line[0]), tuple(c.count_line[1])
        cv2.line(vis, p1, p2, col, 3)
        cv2.circle(vis, tuple(c.approach_side), 5, col, -1)
        cv2.putText(vis, f"{c.name} ({c.phase}) {len(c.tracks)} trk",
                    (p1[0] + 6, p1[1] - 10), cv2.FONT_HERSHEY_DUPLEX, 0.8, col, 2)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay = out_dir / "autocal_overlay.png"
    cv2.imwrite(str(overlay), vis)

    # Finale for the process video: corridors light up, then lines land.
    if writer is not None:
        center = autocal.junction_center(corridors)
        color_of = {}
        for c in corridors:
            col = APPROACH_COLORS.get(c.name, (255, 255, 255))
            for pts_ in c.tracks:
                color_of[id(pts_)] = col
        base = (frame0 * 0.55).astype(np.uint8)
        tint = np.zeros_like(base)
        tint[mask > 0] = (55, 42, 18)
        base = cv2.add(base, tint)
        for pts_ in autocal.moving_tracks(tracks):
            col = color_of.get(id(pts_), (90, 90, 90))
            poly = np.array([[int(x), int(y)] for _, x, y in pts_], np.int32)
            cv2.polylines(base, [poly], False, col, 2)
        cv2.drawMarker(base, (int(center[0]), int(center[1])), (255, 255, 255),
                       cv2.MARKER_CROSS, 26, 2)
        s1 = base.copy()
        hud(s1, f"CORRIDORS CLUSTERED  |  {len(corridors)} approaches from "
                f"{len(autocal.moving_tracks(tracks))} vehicle paths",
            "each color = one inbound corridor - cross = computed junction center")
        for _ in range(int(fps * 2.5)):
            writer.write(s1)
        s2 = base.copy()
        for c in corridors:
            col = APPROACH_COLORS.get(c.name, (255, 255, 255))
            p1, p2 = tuple(c.count_line[0]), tuple(c.count_line[1])
            cv2.line(s2, p1, p2, col, 4)
            cv2.circle(s2, tuple(c.approach_side), 6, col, -1)
            cv2.putText(s2, f"{c.name} ({c.phase})", (p1[0] + 6, p1[1] - 10),
                        cv2.FONT_HERSHEY_DUPLEX, 0.85, col, 2)
        hud(s2, "COUNT LINES PLACED  |  calibration complete",
            "lines sit upstream of the junction, clipped to drivable surface - config written")
        for _ in range(int(fps * 4)):
            writer.write(s2)
        writer.release()
        print(f"process video (raw): {process_path}")

    print(f"\nauto-calibrated {len(corridors)} approaches -> {cfg_path} "
          f"(previous config: {backup})")
    for c in corridors:
        print(f"  {c.name:<6} phase={c.phase} tracks={len(c.tracks):>3} "
              f"line={c.count_line}")
    print(f"review overlay: {overlay}")


def _normalize_frame(frame, width: int = 1280, height: int = 720):
    """Normalize arbitrary footage to the calibration coordinate system."""
    import cv2

    if frame.shape[1] == width and frame.shape[0] == height:
        return frame
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def _temporal_median_frame(frames):
    """Clean-ish scene plate from sparse frames of one static camera."""
    import numpy as np

    if not frames:
        raise ValueError("at least one frame is required")
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def _scene_plate(frames, max_median_delta: float = 15.0):
    """Use a clean temporal median only when the camera is sufficiently still.

    A moving camera turns a pixel-wise median into a blurred composite.  In
    that case, choose the sharp observed frame closest to the median scene.
    """
    import cv2
    import numpy as np

    plate = _temporal_median_frame(frames)
    deltas = [float(np.mean(cv2.absdiff(frame, plate))) for frame in frames]
    variation = float(np.median(deltas))
    if variation <= max_median_delta:
        return plate, "temporal-median", variation
    best = min(range(len(frames)), key=deltas.__getitem__)
    return frames[best].copy(), "representative-frame", variation


def _calibration_quality(corridors, moving_count: int) -> dict:
    """Small, explainable quality gate for an automatically learned layout."""
    import math

    members = sum(len(c.tracks) for c in corridors)
    min_members = min((len(c.tracks) for c in corridors), default=0)
    coverage = members / max(moving_count, 1)
    phases = {c.phase for c in corridors if c.phase}
    line_lengths = [
        math.hypot(c.count_line[1][0] - c.count_line[0][0],
                   c.count_line[1][1] - c.count_line[0][1])
        for c in corridors if len(c.count_line) == 2
    ]
    min_line_length = min(line_lengths, default=0.0)
    geometry_valid = (
        len(line_lengths) == len(corridors)
        and min_line_length >= 24.0
        and all(c.name and c.phase and c.approach_side for c in corridors)
    )
    score = (
        0.35 * min(len(corridors) / 4.0, 1.0)
        + 0.35 * min(moving_count / 20.0, 1.0)
        + 0.30 * min(coverage, 1.0)
    )
    if (geometry_valid and len(phases) == 2 and len(corridors) >= 3
            and min_members >= 3 and score >= 0.62):
        label = "good"
    elif (geometry_valid and len(phases) == 2 and len(corridors) >= 3
          and min_members >= 3):
        label = "usable"
    else:
        label = "low"
    return {
        "label": label,
        "score": round(score, 3),
        "corridors": len(corridors),
        "moving_tracks": moving_count,
        "clustered_tracks": members,
        "coverage": round(coverage, 3),
        "minimum_tracks_per_corridor": min_members,
        "phases_found": sorted(phases),
        "minimum_line_length_px": round(min_line_length, 1),
        "geometry_valid": geometry_valid,
    }


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _new_run_dir(root: str | Path, requested_name: str | None = None) -> Path:
    from datetime import datetime
    import re

    base = Path(root)
    name = requested_name or datetime.now().strftime("live-%Y%m%d-%H%M%S")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError(
            "--run-name must contain only letters, numbers, '.', '_' or '-'"
        )
    out = base / name
    if out.exists():
        raise FileExistsError(f"run output already exists: {out}")
    out.mkdir(parents=True)
    return out


def _export_3d_timeline(event_path: Path, duration: float, config_path_: Path,
                        tracks_path: Path, timeline_path: Path) -> tuple[bool, str]:
    """Build the run-specific timeline consumed by the browser 3D viewer."""
    import json
    import subprocess

    exporter = Path(__file__).resolve().parent / "scripts" / "export_timeline.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(exporter),
            str(event_path),
            str(duration),
            str(config_path_),
            str(tracks_path),
            str(timeline_path),
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return False, (proc.stderr.strip() or proc.stdout.strip() or "unknown export error")
    try:
        payload = json.loads(
            timeline_path.read_text().removeprefix("const TIMELINE = ").removesuffix(";\n")
        )
    except (OSError, json.JSONDecodeError) as e:
        return False, f"timeline validation failed: {e}"
    if not payload.get("twin_affine") or not payload.get("count_lines_tw"):
        return False, "camera geometry cannot produce a valid 3D projection"
    return True, proc.stdout.strip()


def _transcode_3d_footage(raw_path: Path, output_path: Path) -> tuple[bool, str]:
    """Convert OpenCV's staging video to browser-compatible H.264."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg is required to create the browser 3D footage"
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(raw_path),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",
            str(output_path),
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return False, (proc.stderr.strip() or "unknown ffmpeg error")
    raw_path.unlink()
    return True, str(output_path)


def _draw_calibration_observation(frame, detections, paths, elapsed, target):
    """Live proof that calibration is learning from current detector tracks."""
    import cv2
    import numpy as np

    vis = frame.copy()
    for pts in paths.values():
        if len(pts) >= 2:
            # Only the recent tail is needed on screen; the full path remains
            # available to the calibration algorithm.
            poly = np.array([[int(x), int(y)] for _, x, y in pts[-80:]], np.int32)
            cv2.polylines(vis, [poly], False, (50, 160, 220), 2)
    for d in detections:
        x1, y1, x2, y2 = map(int, d.box)
        cv2.rectangle(vis, (x1 - 1, y1 - 1), (x2 + 1, y2 + 1), (0, 0, 0), 4)
        cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 255, 255), 2)
        cv2.putText(vis, str(d.track_id), (x1, max(18, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.rectangle(vis, (0, 0), (vis.shape[1], 66), (14, 13, 10), -1)
    cv2.putText(vis, "LIVE SETUP  |  learning intersection from vehicle motion",
                (16, 28), cv2.FONT_HERSHEY_DUPLEX, 0.76, (36, 183, 255), 2)
    cv2.putText(vis, f"observed {elapsed:5.1f}s / {target:.0f}s   "
                f"tracks {len(paths)}   active detections {len(detections)}",
                (16, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (220, 220, 220), 1)
    return vis


def _draw_calibration_result(frame, mask, tracks, corridors, quality):
    import cv2
    import numpy as np

    from theiatron.dashboard import APPROACH_COLORS

    vis = (frame * 0.55).astype(np.uint8)
    tint = np.zeros_like(vis)
    tint[mask > 0] = (60, 45, 20)
    vis = cv2.add(vis, tint)
    for pts in tracks:
        if len(pts) >= 2:
            poly = np.array([[int(x), int(y)] for _, x, y in pts], np.int32)
            cv2.polylines(vis, [poly], False, (100, 100, 100), 1)
    for c in corridors:
        color = APPROACH_COLORS.get(c.name, (255, 255, 255))
        p1, p2 = tuple(c.count_line[0]), tuple(c.count_line[1])
        cv2.line(vis, p1, p2, color, 4)
        cv2.circle(vis, tuple(c.approach_side), 6, color, -1)
        cv2.putText(vis, f"{c.name.upper()}  {c.phase}  {len(c.tracks)} tracks",
                    (p1[0] + 7, max(28, p1[1] - 10)),
                    cv2.FONT_HERSHEY_DUPLEX, 0.72, color, 2)
    cv2.rectangle(vis, (0, 0), (vis.shape[1], 64), (14, 13, 10), -1)
    cv2.putText(vis, f"CALIBRATION {quality['label'].upper()}  |  "
                f"{quality['corridors']} approaches learned",
                (16, 28), cv2.FONT_HERSHEY_DUPLEX, 0.78, (36, 183, 255), 2)
    cv2.putText(vis, f"{quality['moving_tracks']} moving tracks observed  |  "
                f"{quality['coverage']:.0%} assigned to traffic corridors",
                (16, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (220, 220, 220), 1)
    return vis


def _harvest_track_artifacts(extractors, recorder) -> dict:
    """Timeline-compatible motion artifacts for one single-camera session."""
    counted = []
    counted_tids = set()
    for ex in extractors.values():
        counted.extend(ex.harvest_motions(recorder))
        counted_tids |= set(ex.count_num)
    extras = []
    for tid, rec in recorder.live.items():
        pts = rec["pts"]
        if tid in counted_tids or len(pts) < 8:
            continue
        (t_a, xa, ya), (t_b, xb, yb) = pts[0], pts[-1]
        displacement = ((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5
        if displacement < 25 and (t_b - t_a) < 8.0:
            continue
        kept = []
        for t, x, y in pts:
            if (not kept or abs(x - kept[-1][1]) + abs(y - kept[-1][2]) > 2.0
                    or t - kept[-1][0] >= 3.0):
                kept.append([round(t, 2), round(x, 1), round(y, 1)])
        if kept[-1][0] != round(t_b, 2):
            kept.append([round(t_b, 2), round(xb, 1), round(yb, 1)])
        extras.append({"ts": round(t_a, 2), "t_end": round(t_b, 2), "pts": kept})
    return {"counted": counted, "extras": extras}


def run_live_demo(args):
    """Learn a new video, then run fresh perception + A/B control live."""
    import json
    from collections import defaultdict

    import cv2
    import numpy as np

    from theiatron import autocal
    from theiatron.approach import ArrivalExtractor, TrackRecorder
    from theiatron.dashboard import Dashboard, annotate_intersection
    from theiatron.detection import VehicleDetector
    from theiatron.feeds import VideoFeed

    cfg_path = config_path(args, "configs/intersection.yaml")
    if not Path(cfg_path).exists():
        sys.exit(f"base config does not exist: {cfg_path}")
    cfg = load_config(cfg_path)
    if args.model:
        cfg.vision.model = args.model
    if args.device:
        cfg.vision.device = args.device

    video = args.video or (cfg.approaches[0].video if cfg.approaches else None)
    if not video:
        sys.exit("--live-demo needs --video or a config containing one video")
    source = Path(video).expanduser()
    if not source.is_file():
        sys.exit(f"video does not exist: {source}")
    if args.observe <= 0:
        sys.exit("--observe must be greater than zero")
    if args.duration is not None and args.duration <= 0:
        sys.exit("--duration must be greater than zero")

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        sys.exit(f"cannot open video: {source}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    total_duration = frame_count / native_fps if frame_count else 0.0
    if width < 320 or height < 240:
        sys.exit(f"video resolution is too small for reliable tracking: {width}x{height}")
    if total_duration and total_duration < 15.0:
        sys.exit(f"video is only {total_duration:.1f}s; use at least 15s, preferably 90s+")

    try:
        run_dir = _new_run_dir(args.out, args.run_name)
    except (FileExistsError, ValueError) as e:
        sys.exit(str(e))
    source_hash = _sha256(source)
    observe_target = min(args.observe, total_duration) if total_duration else args.observe
    eval_target = (
        args.duration
        if args.duration is not None
        else (total_duration if args.evaluation_scope == "full" and total_duration else 120.0)
    )
    print("\n=== THEIATRON LIVE DEMO ===")
    print(f"source: {source}  ({width}x{height}, {native_fps:.2f} FPS, "
          f"{total_duration:.1f}s)")
    print(f"run artifacts: {run_dir}")
    print(f"stage 1/3: observing up to {observe_target:.0f}s for automatic calibration")

    feed = VideoFeed(str(source), cfg.vision.process_fps, loop=False)
    detector = VehicleDetector(cfg.vision)
    paths = defaultdict(list)
    plate_samples = []
    plate_interval = max(observe_target / 17.0, feed.dt)
    next_plate_sample = 0.0
    first_frame = last_frame = None
    obs_time = 0.0
    setup_aborted = False
    try:
        while obs_time < observe_target:
            frame, _ = feed.read()
            if frame is None:
                break
            frame = _normalize_frame(frame)
            if first_frame is None:
                first_frame = frame.copy()
            last_frame = frame.copy()
            obs_time = round(obs_time + feed.dt, 6)
            if obs_time + 1e-9 >= next_plate_sample:
                plate_samples.append(frame.copy())
                next_plate_sample += plate_interval
            detections = detector.track(frame)
            for d in detections:
                paths[d.track_id].append((obs_time, d.x, d.y))
            if not args.headless:
                vis = _draw_calibration_observation(
                    frame, detections, paths, obs_time, observe_target
                )
                cv2.imshow("Theiatron - learning this intersection", vis)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    setup_aborted = True
                    break
        if setup_aborted:
            sys.exit("live setup cancelled")
        if first_frame is None or last_frame is None:
            sys.exit("no readable video frames")

        tracks = list(paths.values())
        moving = autocal.moving_tracks(tracks)
        print(f"observed {len(tracks)} tracks; {len(moving)} moved far enough to calibrate")
        try:
            corridors = autocal.calibrate(tracks, (1280, 720))
        except ValueError as e:
            sys.exit(
                f"automatic calibration failed: {e}. Use a longer/static elevated clip "
                "or run --calibrate with a prepared config."
            )

        mask = autocal.road_mask_motion(tracks, (1280, 720))
        road_backend = "motion"
        if args.road_model in ("auto", "segformer"):
            print("optional road segmentation requested; checking local model/cache...")
            seg_mask, why = autocal.road_mask_segformer(first_frame)
            if seg_mask is None:
                print(f"segmentation unavailable; continuing with motion evidence ({why})")
            else:
                fraction = float((seg_mask > 0).mean())
                if 0.05 <= fraction <= 0.6:
                    mask = np.maximum(mask, seg_mask)
                    road_backend = "motion + segformer"
                else:
                    print(f"segmentation rejected: implausible road coverage {fraction:.0%}")
        for corridor in corridors:
            corridor.count_line = list(
                autocal.clip_line_to_mask(*corridor.count_line, mask)
            )

        quality = _calibration_quality(corridors, len(moving))
        if quality["label"] == "low":
            sys.exit(f"calibration confidence is too low: {quality}")
        cfg.approaches = autocal.to_approach_configs(corridors, str(source.resolve()))
        session_config = run_dir / "config.yaml"
        save_config(cfg, session_config)
        plate_path = run_dir / "plate.jpg"
        plate, plate_mode, plate_variation = _scene_plate(plate_samples)
        if not cv2.imwrite(
            str(plate_path), plate, [cv2.IMWRITE_JPEG_QUALITY, 90]
        ):
            sys.exit(f"cannot create run-specific 3D ground plate: {plate_path}")
        cv2.imwrite(str(run_dir / "road_mask.png"), mask)
        overlay = _draw_calibration_result(last_frame, mask, moving, corridors, quality)
        overlay_path = run_dir / "calibration.png"
        cv2.imwrite(str(overlay_path), overlay)
        print(f"stage 2/3: learned {len(corridors)} approaches "
              f"(quality={quality['label']}, backend={road_backend})")
        for c in corridors:
            print(f"  {c.name:<6} phase={c.phase} tracks={len(c.tracks):>3} "
                  f"line={c.count_line}")
        print(f"review overlay: {overlay_path}")

        if not args.headless:
            cv2.imshow("Theiatron - learned intersection", overlay)
            deadline = time.monotonic() + max(0.0, args.review_seconds)
            while time.monotonic() < deadline:
                key = cv2.waitKey(30) & 0xFF
                if key in (ord("q"), 13, 32):
                    break
            cv2.destroyWindow("Theiatron - learned intersection")
            cv2.destroyWindow("Theiatron - learning this intersection")

        remaining = max(0.0, total_duration - obs_time) if total_duration else 0.0
        minimum_fresh = min(20.0, eval_target * 0.25)
        rewound = args.evaluation_scope == "full" or remaining < minimum_fresh
        if rewound:
            if args.evaluation_scope == "full":
                print("rewinding for a fresh full-clip inference and comparison pass")
            else:
                print("clip has little unseen footage after calibration; rewinding for fresh inference")
            feed.release()
            feed = VideoFeed(str(source), cfg.vision.process_fps, loop=False)
            # A truly new detector matters here. Ultralytics registers tracker
            # callbacks on the model object; clearing only its predictor and
            # reusing it can retain callbacks and recycle track IDs during the
            # second pass, merging many vehicles into a handful of tracks.
            detector = VehicleDetector(cfg.vision)
            available_eval = total_duration or eval_target
        else:
            print(f"continuing into {remaining:.1f}s of footage not used for calibration")
            available_eval = remaining
        if available_eval and eval_target > available_eval:
            print(f"evaluation shortened from {eval_target:.1f}s to available "
                  f"{available_eval:.1f}s")
            eval_target = available_eval

        print(f"stage 3/3: live detection + controller comparison for up to "
              f"{eval_target:.1f}s")
        extractors = {
            a.name: ArrivalExtractor(a, cfg.vision.min_track_age) for a in cfg.approaches
        }
        recorder = TrackRecorder()
        claimed = set()
        adaptive, fixed = build_engines(cfg)
        names = [a.name for a in cfg.approaches]
        record_path = run_dir / args.record if args.record else None
        footage_raw_path = run_dir / "footage-raw.mp4"
        footage_path = run_dir / "footage.mp4"
        footage_writer = cv2.VideoWriter(
            str(footage_raw_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            1.0 / feed.dt,
            (1280, 720),
        )
        if not footage_writer.isOpened():
            sys.exit(f"cannot create 3D footage asset: {footage_raw_path}")
        dashboard = Dashboard(
            names, record_path, fps=1.0 / feed.dt, show=not args.headless
        )
        now = 0.0
        frames_done = 0
        all_events: list[tuple[float, str]] = []
        wall_start = time.perf_counter()
        last_annotated = None
        try:
            while now < eval_target:
                frame, _ = feed.read()
                if frame is None:
                    break
                frame = _normalize_frame(frame)
                now = round(now + feed.dt, 6)
                detections = detector.track(frame)
                points = [(d.track_id, d.x, d.y) for d in detections]
                recorder.update(now, points)
                tick_events = []
                for a in cfg.approaches:
                    tick_events += extractors[a.name].update(now, points, claimed)
                adaptive.tick(now, tick_events)
                fixed.tick(now, tick_events)
                all_events.extend(tick_events)

                a_sum = summarize(adaptive, now)
                f_sum = summarize(fixed, now)
                a_waiting = sum(len(q.queue) for q in adaptive.queues.values())
                f_waiting = sum(len(q.queue) for q in fixed.queues.values())
                saved = total_censored_wait(fixed, now) - total_censored_wait(adaptive, now)
                annotated = annotate_intersection(
                    frame,
                    detections,
                    extractors,
                    {name: adaptive.light_for(name) for name in names},
                    {name: len(adaptive.queues[name].queue) for name in names},
                )
                last_annotated = annotated
                footage_writer.write(annotated)
                canvas = dashboard.render(
                    [annotated],
                    {name: adaptive.light_for(name) for name in names},
                    {name: len(adaptive.queues[name].queue) for name in names},
                    {
                        "theia_wait": a_sum["avg_wait_s"],
                        "fixed_wait": f_sum["avg_wait_s"],
                        "theia_waiting": a_waiting,
                        "fixed_waiting": f_waiting,
                        "time_saved_s": saved,
                        "fixed_label": f"FIXED {cfg.signal.fixed_split:.0f}s",
                        "ready": (
                            now > 30.0
                            and a_sum["arrivals"] >= MIN_COMPARISON_ARRIVALS
                        ),
                    },
                    narrate(adaptive),
                )
                if not dashboard.display(canvas):
                    break
                frames_done += 1

            # Hold a clean result card on screen and append it to the recorded
            # dashboard. This gives a presenter time to talk through the
            # measured outcome without racing the final video frame.
            if last_annotated is not None and args.result_seconds > 0:
                a_final = summarize(adaptive, now)
                f_final = summarize(fixed, now)
                saved_final = (
                    total_censored_wait(fixed, now)
                    - total_censored_wait(adaptive, now)
                )
                sample_ready = a_final["arrivals"] >= MIN_COMPARISON_ARRIVALS
                if not sample_ready:
                    result_text = (
                        f"Inconclusive: {a_final['arrivals']} arrivals counted; "
                        f"need {MIN_COMPARISON_ARRIVALS}"
                    )
                elif f_final["avg_wait_s"] > 0:
                    reduction = 100.0 * (
                        f_final["avg_wait_s"] - a_final["avg_wait_s"]
                    ) / f_final["avg_wait_s"]
                    result_text = (
                        f"Result on this footage: {reduction:.0f}% less modeled "
                        "average waiting"
                        if reduction >= 0
                        else f"Result on this footage: {-reduction:.0f}% more modeled waiting"
                    )
                else:
                    result_text = "Result: no modeled queue formed in this footage segment"
                final_stats = {
                    "theia_wait": a_final["avg_wait_s"],
                    "fixed_wait": f_final["avg_wait_s"],
                    "theia_waiting": sum(len(q.queue) for q in adaptive.queues.values()),
                    "fixed_waiting": sum(len(q.queue) for q in fixed.queues.values()),
                    "time_saved_s": saved_final,
                    "fixed_label": f"FIXED {cfg.signal.fixed_split:.0f}s",
                    "ready": sample_ready,
                }
                hold_frames = max(1, round(args.result_seconds / feed.dt))
                for _ in range(hold_frames):
                    final_canvas = dashboard.render(
                        [last_annotated],
                        {name: adaptive.light_for(name) for name in names},
                        {name: len(adaptive.queues[name].queue) for name in names},
                        final_stats,
                        result_text,
                    )
                    if not dashboard.display(final_canvas):
                        break
                    if not args.headless:
                        time.sleep(feed.dt)
        finally:
            dashboard.close()
            footage_writer.release()

        wall_time = max(time.perf_counter() - wall_start, 1e-9)
        footage_ok, footage_message = _transcode_3d_footage(
            footage_raw_path, footage_path
        )
        if not footage_ok:
            print(f"warning: 3D footage conversion failed: {footage_message}")
        artifacts = _harvest_track_artifacts(extractors, recorder)
        tracks_path = run_dir / "tracks.json"
        tracks_path.write_text(json.dumps(artifacts))
        event_name = args.record_arrivals or "events.json"
        event_path = run_dir / event_name
        event_meta = {
            "kind": "live-video-analysis",
            "config": str(session_config.resolve()),
            "duration": now,
            "model": cfg.vision.model,
            "source": str(source.resolve()),
            "source_sha256": source_hash,
            "calibration_observe_s": round(obs_time, 3),
            "calibration_quality": quality,
            "evaluation_scope": "unseen" if not rewound else "full-fresh-pass",
        }
        save_events(all_events, event_path, meta=event_meta)
        report = finish(cfg, adaptive, fixed, now, run_dir)
        timeline_path = run_dir / "timeline.js"
        timeline_ok, timeline_message = _export_3d_timeline(
            event_path, now, session_config, tracks_path, timeline_path
        )
        if timeline_ok:
            print(timeline_message)
        else:
            print(f"warning: 3D timeline export failed: {timeline_message}")
        repo_root = Path(__file__).resolve().parent
        default_out = (repo_root / "out").resolve()
        viewer_run = (
            f"out/{run_dir.name}" if run_dir.parent.resolve() == default_out else None
        )
        viewer_path = (
            f"viz/index.html?run={viewer_run}" if viewer_run else None
        )
        three_d_ready = timeline_ok and footage_ok and plate_path.is_file()
        manifest = {
            "source": event_meta["source"],
            "source_sha256": source_hash,
            "source_width": width,
            "source_height": height,
            "source_fps": native_fps,
            "source_duration_s": round(total_duration, 3),
            "process_fps": round(1.0 / feed.dt, 3),
            "model": cfg.vision.model,
            "device": cfg.vision.device,
            "calibration": quality,
            "road_mask_backend": road_backend,
            "evaluation_duration_s": round(now, 3),
            "evaluation_scope": event_meta["evaluation_scope"],
            "events": len(all_events),
            "processing_ticks_per_wall_second": round(frames_done / wall_time, 2),
            "results": {
                "sample_status": report["sample_status"],
                "avg_wait_reduction_pct": report["avg_wait_reduction_pct"],
                "p95_wait_reduction_pct": report["p95_wait_reduction_pct"],
            },
            "three_d": {
                "ready": three_d_ready,
                "timeline": str(timeline_path.resolve()) if timeline_ok else None,
                "footage": str(footage_path.resolve()) if footage_ok else None,
                "plate": str(plate_path.resolve()) if plate_path.is_file() else None,
                "plate_mode": plate_mode,
                "plate_variation": round(plate_variation, 2),
                "viewer": viewer_path if three_d_ready else None,
            },
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"processed {frames_done} fresh inference ticks in {wall_time:.1f}s wall "
              f"({frames_done / wall_time:.1f} ticks/s)")
        print(f"live run complete: {run_dir}")
        print(f"replay: python run_demo.py --replay {event_path}")
        if viewer_path and three_d_ready:
            print(f"3D viewer: {viewer_path}")
    finally:
        feed.release()
        if not args.headless:
            cv2.destroyAllWindows()


def run_live(args):
    import cv2  # noqa: F401  (fail fast if OpenCV is missing)

    import json

    from theiatron.approach import ArrivalExtractor, TrackRecorder
    from theiatron.dashboard import Dashboard, annotate_frame, annotate_intersection
    from theiatron.detection import VehicleDetector
    from theiatron.feeds import VideoFeed

    cfg_path = config_path(args)
    cfg = load_config(cfg_path)
    if args.model:
        cfg.vision.model = args.model
    if args.device:
        cfg.vision.device = args.device
    if not cfg.approaches:
        sys.exit("config has no approaches; run scripts/get_videos.sh and calibrate first")
    for a in cfg.approaches:
        if not a.count_line:
            sys.exit(f"approach {a.name!r} is not calibrated; run --calibrate {a.name}")

    names = [a.name for a in cfg.approaches]
    # Approaches may share one elevated camera: one feed + one detector per
    # unique video, every sharing approach reads the same detections.
    by_video: dict[str, list] = {}
    for a in cfg.approaches:
        by_video.setdefault(a.video, []).append(a)
    feeds = {v: VideoFeed(v, cfg.vision.process_fps) for v in by_video}
    detectors = {v: VehicleDetector(cfg.vision) for v in by_video}
    recorders = {v: TrackRecorder() for v in by_video}
    extractors = {
        a.name: ArrivalExtractor(a, cfg.vision.min_track_age) for a in cfg.approaches
    }
    adaptive, fixed = build_engines(cfg)
    motions: list[dict] = []
    extras: list[dict] = []  # tracked-but-uncounted vehicles (parked, outbound...)
    # One physical vehicle = one arrival, across all zones of one camera.
    claimed = {v: set() for v in by_video}

    def harvest(vid):
        counted_tids = set()
        for a in by_video[vid]:
            motions.extend(extractors[a.name].harvest_motions(recorders[vid]))
            counted_tids |= set(extractors[a.name].count_num)
        # The digital twin renders every vehicle the camera tracked, not
        # just counted arrivals: moving ones (any direction) and long-lived
        # parked ones. Short flickers are dropped.
        for tid, rec in recorders[vid].live.items():
            pts = rec["pts"]
            if tid in counted_tids or len(pts) < 8:
                continue
            (t_a, xa, ya), (t_b, xb, yb) = pts[0], pts[-1]
            disp = ((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5
            if disp < 25 and (t_b - t_a) < 8.0:
                continue
            # Decimate stationary stretches: keep a point only after real
            # movement or a 3s gap (a parked car needs 2 points, not 1800).
            kept = []
            for t, x, y in pts:
                if (not kept or abs(x - kept[-1][1]) + abs(y - kept[-1][2]) > 2.0
                        or t - kept[-1][0] >= 3.0):
                    kept.append([round(t, 2), round(x, 1), round(y, 1)])
            kept.append([round(t_b, 2), round(xb, 1), round(yb, 1)])
            extras.append({"ts": round(t_a, 2), "t_end": round(t_b, 2), "pts": kept})

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / args.record if args.record else None
    dash = Dashboard(names, record_path, cfg.vision.process_fps, show=not args.headless)

    dt = 1.0 / cfg.vision.process_fps
    duration = args.duration if args.duration is not None else 120.0
    now = 0.0
    all_events: list[tuple[float, str]] = []
    t_wall = time.time()
    frames_done = 0
    try:
        while now < duration:
            now = round(now + dt, 6)
            tick_events: list[tuple[float, str]] = []
            tile_frames = []
            for vid, group in by_video.items():
                frame, wrapped = feeds[vid].read()
                if wrapped:
                    harvest(vid)  # pair counted IDs with motion BEFORE resets
                    detectors[vid].reset()
                    recorders[vid].reset()
                    claimed[vid].clear()
                    for a in group:
                        extractors[a.name].reset()
                if frame is None:
                    tile_frames.append(None)
                    continue
                dets = detectors[vid].track(frame)
                pts = [(d.track_id, d.x, d.y) for d in dets]
                recorders[vid].update(now, pts)
                for a in group:
                    tick_events += extractors[a.name].update(now, pts, claimed[vid])
                if len(group) == 1:
                    a = group[0]
                    tile_frames.append(annotate_frame(
                        frame, dets, extractors[a.name],
                        extractors[a.name].last_counted, adaptive.light_for(a.name),
                        a.name, len(adaptive.queues[a.name].queue),
                    ))
                else:
                    tile_frames.append(annotate_intersection(
                        frame, dets,
                        {a.name: extractors[a.name] for a in group},
                        {a.name: adaptive.light_for(a.name) for a in group},
                        {a.name: len(adaptive.queues[a.name].queue) for a in group},
                    ))
            adaptive.tick(now, tick_events)
            fixed.tick(now, tick_events)
            all_events += tick_events

            a_sum = summarize(adaptive, now)
            f_sum = summarize(fixed, now)
            stats = {
                "theia_wait": a_sum["avg_wait_s"],
                "fixed_wait": f_sum["avg_wait_s"],
                "theia_waiting": sum(len(q.queue) for q in adaptive.queues.values()),
                "fixed_waiting": sum(len(q.queue) for q in fixed.queues.values()),
                "time_saved_s": (
                    total_censored_wait(fixed, now)
                    - total_censored_wait(adaptive, now)
                ),
                "fixed_label": f"FIXED {cfg.signal.fixed_split:.0f}s",
                # Early numbers are startup noise; hold the verdict back
                # until both controllers have served a fair sample.
                "ready": now > 60.0 and f_sum["served"] >= 15,
            }
            canvas = dash.render(
                tile_frames,
                {n: adaptive.light_for(n) for n in names},
                {n: len(adaptive.queues[n].queue) for n in names},
                stats,
                narrate(adaptive),
            )
            if not dash.display(canvas):
                break
            frames_done += 1
    finally:
        dash.close()
        for f in feeds.values():
            f.release()

    for vid in by_video:
        harvest(vid)
    (out_dir / "tracks.json").write_text(
        json.dumps({"counted": motions, "extras": extras}))
    wall = time.time() - t_wall
    print(f"processed {frames_done} ticks of {dt:.2f}s video-time in {wall:.1f}s wall "
          f"({frames_done / wall:.1f} ticks/s incl. detection + GUI); "
          f"{len(motions)} counted + {len(extras)} extra motions -> "
          f"{out_dir / 'tracks.json'}")
    if args.record_arrivals:
        save_events(all_events, out_dir / args.record_arrivals,
                    meta={"config": str(cfg_path), "duration": now,
                          "model": cfg.vision.model})
        print(f"arrivals: {out_dir / args.record_arrivals}")
    finish(cfg, adaptive, fixed, now, out_dir)


def main():
    ap = argparse.ArgumentParser(description="Theiatron demo")
    ap.add_argument("--config", help=f"configuration YAML (default: {DEFAULT_CONFIG}; "
                    "live-video mode defaults to configs/intersection.yaml)")
    ap.add_argument("--duration", type=float,
                    help="seconds of video time to evaluate (default: 120; replay uses metadata)")
    ap.add_argument("--replay", help="arrival-events JSON; skips vision entirely")
    ap.add_argument("--video", help="new intersection footage to analyze with fresh inference")
    ap.add_argument("--live-demo", action="store_true",
                    help="learn --video, then run live detection and A/B control")
    ap.add_argument("--calibrate", metavar="APPROACH",
                    help="interactively set the count line for one approach")
    ap.add_argument("--auto-calibrate", action="store_true",
                    help="learn approaches automatically by watching traffic")
    ap.add_argument("--observe", type=float, default=180.0,
                    help="maximum seconds of traffic to watch during calibration")
    ap.add_argument("--road-model", choices=("auto", "motion", "segformer"),
                    default="motion", help="road-surface mask backend (motion is offline/reliable)")
    ap.add_argument("--review-seconds", type=float, default=3.0,
                    help="seconds to show the learned layout before live evaluation")
    ap.add_argument("--result-seconds", type=float, default=8.0,
                    help="seconds to hold the final result card")
    ap.add_argument("--evaluation-scope", choices=("full", "unseen"), default="full",
                    help="fresh full-clip pass (stage default) or only footage after calibration")
    ap.add_argument("--run-name",
                    help="live run directory name under --out (default: timestamped)")
    ap.add_argument("--record", default="annotated.mp4",
                    help="dashboard MP4 filename (in --out dir); '' disables")
    ap.add_argument("--record-arrivals", default="events.json",
                    help="arrival stream JSON filename (in --out dir); '' disables")
    ap.add_argument("--out", default="out")
    ap.add_argument("--model", help="override detector weights (e.g. yolo11n.pt)")
    ap.add_argument("--device", help="cpu | mps")
    ap.add_argument("--headless", action="store_true", help="no live window")
    args = ap.parse_args()

    if args.replay:
        run_replay(args)
    elif args.live_demo or args.video:
        run_live_demo(args)
    elif args.auto_calibrate:
        run_autocal(args)
    elif args.calibrate:
        run_calibrate(args)
    else:
        run_live(args)


if __name__ == "__main__":
    main()
