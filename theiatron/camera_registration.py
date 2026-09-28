"""Bounded offline background registration, not metric camera calibration.

Maps each analysed source frame into the first analysed frame's image plane.
Vehicle boxes are excluded before ORB/RANSAC. Every processed frame is estimated
independently against the reference: rejected registrations have no transform,
and neither time interpolation nor identity fallback conceals a failure.
"""
from __future__ import annotations

from bisect import bisect_left
import math
from pathlib import Path

import cv2
import numpy as np

VERSION = "orb-background-reference-v2-full-resolution"
MAX_FRAMES = 3600
IMAGE_SIZE = (1280, 720)


def transform_point(matrix, point):
    """Transform one image point, returning None outside a finite projection."""
    if matrix is None:
        return None
    h = np.asarray(matrix, dtype=float)
    p = np.asarray(point, dtype=float)
    if h.shape != (3, 3) or p.shape != (2,) or not np.isfinite(h).all() or not np.isfinite(p).all():
        return None
    q = h @ np.r_[p, 1.]
    if q[2] <= 1e-6:
        return None
    result = q[:2] / q[2]
    return result.tolist() if np.isfinite(result).all() else None


def registration_at(result, timestamp):
    """Exact processed-time lookup only; failures and missing times return None."""
    frames = result.get("frames", [])
    index = bisect_left(frames, timestamp - 1e-7, key=lambda row: row["t"])
    if index == len(frames) or abs(frames[index]["t"] - timestamp) > 1e-6:
        return None
    row = frames[index]
    return row if row.get("status") in {"accepted", "reference"} and row.get("H") is not None else None


def _failure(reason, **quality):
    return {"status": "rejected", "H": None, "reason": reason, **quality}


class BackgroundRegistrar:
    """Reusable first-frame feature cache. Input boxes use 1280×720 coordinates."""

    def __init__(self, reference, boxes=()):
        self.orb = cv2.ORB_create(nfeatures=6000, fastThreshold=12)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.reference_points, self.reference_descriptors = self._features(reference, boxes)

    def _features(self, frame, boxes):
        if frame is None or frame.ndim not in {2, 3}:
            return [], None
        small = cv2.resize(frame, IMAGE_SIZE, interpolation=cv2.INTER_AREA)
        gray = small if small.ndim == 2 else cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        mask = np.full((720, 1280), 255, dtype=np.uint8)
        for box in boxes:
            if len(box) != 4 or not all(math.isfinite(v) for v in box):
                raise ValueError("camera registration boxes require four finite coordinates")
            x1, y1, x2, y2 = np.asarray(box)
            if x2 <= x1 or y2 <= y1:
                raise ValueError("camera registration boxes must be ordered")
            margin = 16
            cv2.rectangle(mask, (max(0, int(x1) - margin), max(0, int(y1) - margin)),
                          (min(1279, int(x2) + margin), min(719, int(y2) + margin)), 0, -1)
        return self.orb.detectAndCompute(gray, mask)

    def register(self, frame, boxes=()):
        points, descriptors = self._features(frame, boxes)
        if self.reference_descriptors is None or len(self.reference_points) < 60:
            return _failure("insufficient-reference-background-features")
        if descriptors is None or len(points) < 60:
            return _failure("insufficient-current-background-features")
        pairs = self.matcher.knnMatch(descriptors, self.reference_descriptors, k=2)
        matches = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < .72 * b.distance]
        quality = {"matches": len(matches)}
        if len(matches) < 30:
            return _failure("insufficient-background-matches", **quality)
        current = np.float32([points[m.queryIdx].pt for m in matches])
        reference = np.float32([self.reference_points[m.trainIdx].pt for m in matches])
        cv2.setRNGSeed(1701)
        small_h, inliers = cv2.findHomography(current, reference, cv2.RANSAC, 2.0, maxIters=1500, confidence=.995)
        if small_h is None or inliers is None or not np.isfinite(small_h).all():
            return _failure("homography-fit-failed", **quality)
        keep = inliers.ravel().astype(bool)
        quality.update(inliers=int(keep.sum()), inlier_fraction=float(keep.mean()))
        if keep.sum() < 30 or keep.mean() < .5:
            return _failure("weak-background-consensus", **quality)
        h = small_h.copy()
        h /= h[2, 2]
        predicted = cv2.perspectiveTransform(current.reshape(-1, 1, 2), small_h).reshape(-1, 2)
        residuals = np.linalg.norm(predicted[keep] - reference[keep], axis=1)
        quality["residual_px"] = {"median": float(np.median(residuals)), "p90": float(np.percentile(residuals, 90))}
        coverage = min(cv2.contourArea(cv2.convexHull(v[keep])) / (1280 * 720) for v in (current, reference))
        quality["background_coverage"] = float(coverage)
        if coverage < .06:
            return _failure("background-features-too-localized", **quality)
        if quality["residual_px"]["p90"] > 2.2:
            return _failure("registration-residual-too-large", **quality)
        corners = [[0, 0], [1280, 0], [1280, 720], [0, 720]]
        warped = [transform_point(h, p) for p in corners]
        if any(p is None for p in warped):
            return _failure("projection-crosses-horizon", **quality)
        warped = np.float32(warped)
        area_ratio = cv2.contourArea(warped, oriented=True) / (1280 * 720)
        displacements = np.linalg.norm(warped - np.asarray(corners), axis=1)
        quality["max_corner_displacement_px"] = float(displacements.max())
        quality["area_ratio"] = float(area_ratio)
        if not .5 < area_ratio < 1.8 or not cv2.isContourConvex(warped) or displacements.max() > 450:
            return _failure("camera-transform-outside-supported-range", **quality)
        return {"status": "accepted", "H": h.tolist(), "reason": None, **quality}


def register_camera(source_path, dense, process_fps=10.0, progress=None):
    """Estimate every processed frame against the first analysed frame.

    source_path is a server-resolved retained raw path, never a request path.
    Cadence and first frame match VideoFeed: native frame skip-1 is labelled dt.
    At most 3600 processed frames and 100000 observations are accepted. Source
    tracks are read only; consumers choose explicitly how to handle rejections.
    """
    if not math.isfinite(process_fps) or not 1 <= process_fps <= 60:
        raise ValueError("camera registration process_fps must be in [1, 60]")
    if not isinstance(dense, dict) or dense.get("image_size") != list(IMAGE_SIZE):
        raise ValueError("camera registration requires 1280×720 recorded tracks")
    samples = [sample for track in dense.get("tracks", []) for sample in track.get("samples", [])]
    if not samples or len(samples) > 100_000:
        raise ValueError("camera registration requires 1–100000 dense observations")
    if any(type(s.get("t")) not in {int, float} or not math.isfinite(s["t"]) or s["t"] <= 0 for s in samples):
        raise ValueError("camera registration timestamps must be finite and positive")
    source = Path(source_path)
    if not source.is_file():
        raise ValueError("retained raw footage is unavailable")
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        cap.release()
        raise ValueError("retained raw footage cannot be decoded")
    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(native_fps) or not 1 <= native_fps <= 240:
            raise ValueError("retained footage has unsupported native frame rate")
        skip = max(1, round(native_fps / process_fps))
        dt = skip / native_fps
        last_tick = round(max(s["t"] for s in samples) / dt)
        if not 1 <= last_tick <= MAX_FRAMES:
            raise ValueError("camera registration supports at most 3600 processed frames")
        boxes, timestamps = {}, {}
        for sample in samples:
            tick = round(sample["t"] / dt)
            # The two historical runners use nominal multiplication or repeated
            # six-decimal addition. Bound only that known rounding discrepancy.
            if tick < 1 or abs(sample["t"] - tick * dt) > max(2e-6, tick * .50001e-6):
                raise ValueError("recorded timestamps do not match retained footage cadence")
            if tick in timestamps and abs(timestamps[tick] - sample["t"]) > 1e-6:
                raise ValueError("conflicting timestamps for one processed frame")
            timestamps[tick] = sample["t"]
            boxes.setdefault(tick, []).append(sample["box"])
        times = list(timestamps.items())
        accumulated = sum(abs(t - k * round(dt, 6)) for k, t in times)
        nominal = sum(abs(t - k * dt) for k, t in times)
        clock_dt = round(dt, 6) if accumulated <= nominal else dt
        frames, registrar = [], None
        for tick in range(1, last_tick + 1):
            for _ in range(skip - 1):
                cap.grab()
            ok, raw = cap.read()
            if not ok:
                raise ValueError("retained raw footage ended before recorded observations")
            # Same two-stage normalization as the recording/reference plate.
            frame = cv2.resize(raw, IMAGE_SIZE, interpolation=cv2.INTER_AREA)
            if registrar is None:
                registrar = BackgroundRegistrar(frame, boxes.get(tick, []))
                row = (dict(status="reference", H=np.eye(3).tolist(), reason=None,
                            inliers=len(registrar.reference_points), inlier_fraction=1.,
                            residual_px={"median": 0., "p90": 0.})
                       if len(registrar.reference_points) >= 60
                       else _failure("insufficient-reference-background-features"))
            else:
                row = registrar.register(frame, boxes.get(tick, []))
            row.update(t=timestamps.get(tick, round(tick * clock_dt, 6)), frame_index=tick * skip - 1)
            frames.append(row)
            if progress and (tick == 1 or tick % 100 == 0 or tick == last_tick):
                progress(tick, last_tick)
    finally:
        cap.release()
    accepted = [r for r in frames if r["status"] in {"reference", "accepted"}]
    residuals = [r["residual_px"]["median"] for r in accepted if r["status"] != "reference"]
    return {
        "schema_version": 1, "method": VERSION, "image_size": list(IMAGE_SIZE),
        "reference_frame_index": skip - 1, "reference_t": frames[0]["t"],
        "cadence_s": dt, "interpolation": "none-every-processed-frame", "frames": frames,
        "summary": {
            "frames": len(frames), "accepted": len(accepted), "rejected": len(frames) - len(accepted),
            "acceptance_fraction": len(accepted) / len(frames),
            "median_registration_residual_px": float(np.median(residuals)) if residuals else None,
            "metric_calibration": False, "accuracy_validated": False,
            "caveats": ["Background registration is an estimate, not measured road geometry.",
                        "Unmasked people, undetected vehicles, parallax and rolling shutter may remain.",
                        "Rejected or missing states are not interpolated or replaced with identity transforms."],
        },
    }
