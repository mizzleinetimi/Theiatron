#!/usr/bin/env python3
"""Theiatron demo runner.

Live demo (adaptive drives the lights; fixed-timer shadow runs on the same
vision-derived arrivals so the dashboard shows the live wait-time gap):

    python run_demo.py --config configs/approaches.yaml --duration 120 \
        --record out/annotated.mp4 --record-arrivals out/events.json

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
from theiatron.metrics import comparison_report, summarize, write_report

PHASE_LABEL = {"NS": "North-South", "EW": "East-West"}


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


def run_replay(args):
    cfg = load_config(args.config)
    events, meta = load_events(args.replay)
    duration = args.duration or (events[-1][0] + 30.0 if events else 60.0)
    adaptive, fixed = build_engines(cfg)
    adaptive.run_replay(events, duration)
    fixed.run_replay(events, duration)
    print(f"replayed {len(events)} arrivals over {duration:.0f}s (meta: {meta})")
    finish(cfg, adaptive, fixed, duration, args.out)


def run_calibrate(args):
    import cv2

    cfg = load_config(args.config)
    approach = next((a for a in cfg.approaches if a.name == args.calibrate), None)
    if approach is None:
        sys.exit(f"no approach named {args.calibrate!r} in {args.config}")
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
            save_config(cfg, args.config)
            print(f"saved count line for {approach.name} -> {args.config}")
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

    cfg = load_config(args.config)
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

    backup = str(args.config) + ".bak"
    shutil.copyfile(args.config, backup)
    cfg.approaches = autocal.to_approach_configs(corridors, video)
    save_config(cfg, args.config)

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

    print(f"\nauto-calibrated {len(corridors)} approaches -> {args.config} "
          f"(previous config: {backup})")
    for c in corridors:
        print(f"  {c.name:<6} phase={c.phase} tracks={len(c.tracks):>3} "
              f"line={c.count_line}")
    print(f"review overlay: {overlay}")


def run_live(args):
    import cv2  # noqa: F401  (fail fast if OpenCV is missing)

    import json

    from theiatron.approach import ArrivalExtractor, TrackRecorder
    from theiatron.dashboard import Dashboard, annotate_frame, annotate_intersection
    from theiatron.detection import VehicleDetector
    from theiatron.feeds import VideoFeed

    cfg = load_config(args.config)
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
    now = 0.0
    all_events: list[tuple[float, str]] = []
    t_wall = time.time()
    frames_done = 0
    try:
        while now < args.duration:
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
                    meta={"config": str(args.config), "duration": now,
                          "model": cfg.vision.model})
        print(f"arrivals: {out_dir / args.record_arrivals}")
    finish(cfg, adaptive, fixed, now, out_dir)


def main():
    ap = argparse.ArgumentParser(description="Theiatron demo")
    ap.add_argument("--config", default="configs/approaches.yaml")
    ap.add_argument("--duration", type=float, default=120.0,
                    help="seconds of video time to simulate")
    ap.add_argument("--replay", help="arrival-events JSON; skips vision entirely")
    ap.add_argument("--calibrate", metavar="APPROACH",
                    help="interactively set the count line for one approach")
    ap.add_argument("--auto-calibrate", action="store_true",
                    help="learn approaches automatically by watching traffic")
    ap.add_argument("--observe", type=float, default=90.0,
                    help="seconds of traffic to watch during --auto-calibrate")
    ap.add_argument("--road-model", choices=("auto", "motion", "segformer"),
                    default="auto", help="road-surface mask backend")
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
    elif args.auto_calibrate:
        run_autocal(args)
    elif args.calibrate:
        run_calibrate(args)
    else:
        run_live(args)


if __name__ == "__main__":
    main()
