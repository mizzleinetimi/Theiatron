#!/usr/bin/env python3
"""Read-only camera-motion diagnostic for one retained recorded-tracks run.

Fits each sampled frame to the reference frame using ORB background features,
excluding tracked vehicle boxes. Results measure image registration, not metric
road calibration. Outputs are intentionally not consumed by the demo pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def percentiles(values):
    if not values:
        return None
    return {f"p{p}": float(np.percentile(values, p)) for p in (50, 90, 95, 99, 100)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--step", type=float, default=0.5)
    args = parser.parse_args()
    if args.step < 0.09:
        parser.error("step must be at least 0.09 seconds")
    recorded = json.loads((args.run / "recorded-tracks.json").read_text())
    simulation = json.loads((args.run / "simulation.json").read_text())
    source = Path(simulation["source_meta"]["source"])
    width, height = recorded["image_size"]
    observations = {}
    for track in recorded["tracks"]:
        for sample in track["samples"]:
            observations.setdefault(sample["t"], []).append(sample)
    timestamps = np.array(sorted(observations))
    reference_time = float(timestamps[0])
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open retained source: {source}")
    orb = cv2.ORB_create(nfeatures=6000, fastThreshold=12)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    def frame_features(time):
        cap.set(cv2.CAP_PROP_POS_MSEC, float(time) * 1000)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Could not decode at {time:.3f}s")
        frame = cv2.resize(frame, (width, height))
        mask = np.full((height, width), 255, dtype=np.uint8)
        nearest = float(timestamps[np.argmin(abs(timestamps - time))])
        for sample in observations[nearest]:
            x1, y1, x2, y2 = sample["box"]
            margin = 15
            cv2.rectangle(
                mask,
                (max(0, int(x1) - margin), max(0, int(y1) - margin)),
                (min(width - 1, int(x2) + margin), min(height - 1, int(y2) + margin)),
                0,
                -1,
            )
        return orb.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), mask)

    ref_keypoints, ref_descriptors = frame_features(reference_time)
    probe_points = np.float32(
        [[200, 450], [640, 400], [1050, 450], [200, 650], [640, 650], [1050, 650]]
    ).reshape(-1, 1, 2)
    rows = []
    times = np.arange(reference_time, float(timestamps[-1]) + 0.001, args.step)
    for index, time in enumerate(times):
        keypoints, descriptors = frame_features(float(time))
        pairs = matcher.knnMatch(descriptors, ref_descriptors, k=2)
        matches = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < 0.72 * b.distance]
        current = np.float32([keypoints[m.queryIdx].pt for m in matches])
        reference = np.float32([ref_keypoints[m.trainIdx].pt for m in matches])
        row = {"t": round(float(time), 6), "matches": len(matches)}
        if len(matches) >= 12:
            transform, inliers = cv2.findHomography(current, reference, cv2.RANSAC, 2.0)
            if transform is not None:
                keep = inliers.ravel().astype(bool)
                residual = np.linalg.norm(
                    cv2.perspectiveTransform(current.reshape(-1, 1, 2), transform).reshape(-1, 2) - reference,
                    axis=1,
                )
                displacement = cv2.perspectiveTransform(probe_points, transform) - probe_points
                row.update(
                    transform_to_reference=transform.tolist(),
                    inliers=int(keep.sum()),
                    inlier_fraction=float(keep.mean()),
                    residual_px=percentiles(residual[keep].tolist()),
                    road_probe_mean_displacement_px=float(np.linalg.norm(displacement.reshape(-1, 2), axis=1).mean()),
                    road_probe_displacements_px=displacement.reshape(-1, 2).tolist(),
                )
        rows.append(row)
        if index % 40 == 0:
            print(f"{index + 1}/{len(times)} sampled frames", flush=True)
    cap.release()

    # Local second-difference residual is an image-space roughness diagnostic,
    # not tracking error ground truth: real accelerations and turns contribute.
    roughness = []
    for track in recorded["tracks"]:
        samples = track["samples"]
        for a, b, c in zip(samples, samples[1:], samples[2:]):
            if max(b["t"] - a["t"], c["t"] - b["t"]) > 0.15:
                continue
            u = (b["t"] - a["t"]) / (c["t"] - a["t"])
            linear = np.asarray(a["anchor"]) * (1 - u) + np.asarray(c["anchor"]) * u
            roughness.append(float(np.linalg.norm(np.asarray(b["anchor"]) - linear)))

    usable = [row for row in rows if row.get("inliers", 0) >= 30 and row.get("inlier_fraction", 0) >= 0.5]
    differences = []
    for a, b in zip(usable, usable[1:]):
        if b["t"] - a["t"] > args.step * 1.2:
            continue
        delta = np.array(b["road_probe_displacements_px"]) - np.array(a["road_probe_displacements_px"])
        differences.append(float(np.linalg.norm(delta, axis=1).mean()))
    summary = {
        "source": str(source),
        "run": str(args.run.resolve()),
        "coordinate_size": [width, height],
        "reference_time": reference_time,
        "sample_step_s": args.step,
        "sampled_frames": len(rows),
        "usable_frames": len(usable),
        "reference_keypoints": len(ref_keypoints),
        "road_displacement_from_reference_px": percentiles([r["road_probe_mean_displacement_px"] for r in usable]),
        "road_displacement_per_sample_px": percentiles(differences),
        "inlier_residual_median_px": percentiles([r["residual_px"]["p50"] for r in usable]),
        "anchor_midpoint_roughness_px": percentiles(roughness),
        "anchor_roughness_samples": len(roughness),
        "caveats": [
            "Vehicle boxes are excluded, but undetected vehicles, people, and moving foliage are not explicitly masked.",
            "RANSAC registration residuals are not manual feature-tracking ground truth.",
            "A global homography can mix road-plane motion with static structures at different depths.",
            "Image motion and vehicle anchor roughness do not identify metric scale, camera intrinsics, or ground-contact locations.",
            "No replay points or source artifacts have been changed.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "camera-motion.json").write_text(json.dumps({"summary": summary, "frames": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
