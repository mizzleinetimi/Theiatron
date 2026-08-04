#!/usr/bin/env python3
"""Extract a clean background plate from traffic footage.

Samples frames across the clip, aligns each to the first frame with an
ORB-feature homography (the drone camera drifts), and takes a per-pixel
temporal median: moving vehicles vanish, parked vehicles and every road
marking survive. The result is the ground texture for the twin-frame A/B
viewer (viz/app.js), which projects it through the same image->world
affine as the digital twin.

Usage: .venv/bin/python scripts/make_plate.py [video] [out] [n_samples]
Defaults: videos/intersection.mp4 viz/plate.jpg 91
"""
import sys

import cv2
import numpy as np

video = sys.argv[1] if len(sys.argv) > 1 else "videos/intersection.mp4"
out = sys.argv[2] if len(sys.argv) > 2 else "viz/plate.jpg"
n_samples = int(sys.argv[3]) if len(sys.argv) > 3 else 91

cap = cv2.VideoCapture(video)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
frames = []
for i in np.linspace(0, total - 1, n_samples).astype(int):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
    ok, f = cap.read()
    if ok:
        frames.append(f)
cap.release()
if not frames:
    sys.exit(f"no frames read from {video}")

ref = frames[0]
refg = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
orb = cv2.ORB_create(4000)
kr, dr = orb.detectAndCompute(refg, None)
bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
aligned = [ref]
skipped = 0
for f in frames[1:]:
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    k, d = orb.detectAndCompute(g, None)
    if d is None:
        skipped += 1
        continue
    m = sorted(bf.match(d, dr), key=lambda x: x.distance)[:800]
    if len(m) < 40:
        skipped += 1
        continue
    src = np.float32([k[x.queryIdx].pt for x in m]).reshape(-1, 1, 2)
    dst = np.float32([kr[x.trainIdx].pt for x in m]).reshape(-1, 1, 2)
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None:
        skipped += 1
        continue
    aligned.append(cv2.warpPerspective(
        f, H, (ref.shape[1], ref.shape[0]), borderMode=cv2.BORDER_REPLICATE))

plate = np.median(np.stack(aligned), axis=0).astype(np.uint8)
cv2.imwrite(out, plate, [cv2.IMWRITE_JPEG_QUALITY, 90])
print(f"wrote {out}: median of {len(aligned)} aligned frames "
      f"({skipped} skipped) from {video}")
