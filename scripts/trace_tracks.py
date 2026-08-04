#!/usr/bin/env python3
"""Debug helper: overlay real track trajectories on a frame to place count lines.

Usage: .venv/bin/python scripts/trace_tracks.py videos/east.mp4 20
Writes videos/frames/<name>_tracks.png with each track's bottom-center path
(green start -> red end) so a good count line placement is obvious.
"""
import sys
from collections import defaultdict
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from theiatron.config import load_config
from theiatron.detection import VehicleDetector
from theiatron.feeds import VideoFeed

video = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
config_path = sys.argv[3] if len(sys.argv) > 3 else "configs/approaches.yaml"
name = Path(video).stem

cfg = load_config(config_path)
det = VehicleDetector(cfg.vision)
feed = VideoFeed(video, cfg.vision.process_fps, loop=False)

paths = defaultdict(list)
bg = None
ticks = int(seconds * cfg.vision.process_fps)
for _ in range(ticks):
    frame, _ = feed.read()
    if frame is None:
        break
    if bg is None:
        bg = frame.copy()
    for d in det.track(frame):
        paths[d.track_id].append((int(d.x), int(d.y)))
feed.release()

long_paths = {t: p for t, p in paths.items() if len(p) >= 5}
print(f"{name}: {len(paths)} tracks, {len(long_paths)} with >=5 points")
for tid, p in sorted(long_paths.items()):
    (x0, y0), (x1, y1) = p[0], p[-1]
    print(f"  track {tid:>3}: ({x0},{y0}) -> ({x1},{y1})  len={len(p)}")

for p in long_paths.values():
    for a, b in zip(p, p[1:]):
        cv2.line(bg, a, b, (0, 200, 255), 2)
    cv2.circle(bg, p[0], 5, (0, 220, 0), -1)   # start: green
    cv2.circle(bg, p[-1], 5, (0, 0, 230), -1)  # end: red
out = f"videos/frames/{name}_tracks.png"
cv2.imwrite(out, bg)
print(f"wrote {out}")
