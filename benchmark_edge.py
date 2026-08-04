#!/usr/bin/env python3
"""Edge-feasibility benchmark for Theiatron's detector.

Exports the nano detector to ONNX (the interchange format edge runtimes
consume) and measures CPU-only inference latency via onnxruntime — no GPU,
no Apple Neural Engine — at 640 and 416 input, single and multi thread.

Published Raspberry Pi 5 measurements are printed alongside for the edge
claim; citing measured third-party numbers is more defensible than scaling
laptop results across CPU microarchitectures.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

# Published Pi 5 benchmarks (see README for sources):
# - Ultralytics Raspberry Pi guide: YOLO11n ONNX @640 ~157 ms (~6.4 FPS)
# - INT8-quantized YOLO11n ONNX @640 ~77 ms (~13 FPS)
# - YOLO26n ONNX @640 ~7.8 FPS
PI5_TABLE = """
Published Raspberry Pi 5 reference points (CPU only, @640):
  YOLO11n ONNX FP32   ~157 ms/frame  (~6.4 FPS)
  YOLO11n ONNX INT8    ~77 ms/frame  (~13 FPS)
  YOLO26n ONNX FP32                  (~7.8 FPS)
At 416 input, compute scales ~(416/640)^2 = 0.42x -> roughly 12-15 FPS FP32.

Theiatron needs ~10 processed FPS per approach for reliable tracking, or a
4-feed round-robin at ~2.5 FPS/feed for queue estimation - both within
Pi 5-class reach at 416 input (comfortably so with INT8 or NCNN export).
"""


def export_onnx(weights: str, imgsz: int) -> Path:
    from ultralytics import YOLO

    model = YOLO(weights)
    path = model.export(format="onnx", imgsz=imgsz, verbose=False)
    return Path(path)


def bench(onnx_path: Path, imgsz: int, threads: int, iters: int = 50) -> tuple[float, float]:
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    sess = ort.InferenceSession(
        str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"]
    )
    name = sess.get_inputs()[0].name
    x = np.random.rand(1, 3, imgsz, imgsz).astype(np.float32)
    for _ in range(10):
        sess.run(None, {name: x})
    times = []
    for _ in range(iters):
        t0 = time.perf_counter()
        sess.run(None, {name: x})
        times.append((time.perf_counter() - t0) * 1000.0)
    arr = np.array(times)
    return float(arr.mean()), float(arr.std())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo26n.pt", help="fallback: yolo11n.pt")
    ap.add_argument("--iters", type=int, default=50)
    args = ap.parse_args()

    print(f"model: {args.model}\n")
    rows = []
    for imgsz in (640, 416):
        onnx_path = export_onnx(args.model, imgsz)
        size_mb = onnx_path.stat().st_size / 1e6
        for threads in (1, 4):
            mean, std = bench(onnx_path, imgsz, threads, args.iters)
            rows.append((imgsz, threads, mean, std, 1000.0 / mean, size_mb))

    print(f"{'imgsz':>6} {'threads':>8} {'ms/frame':>10} {'std':>6} {'FPS':>7} {'onnx MB':>8}")
    for imgsz, threads, mean, std, fps, size_mb in rows:
        print(f"{imgsz:>6} {threads:>8} {mean:>10.1f} {std:>6.1f} {fps:>7.1f} {size_mb:>8.1f}")
    print("\n(measured on this machine, CPU execution provider only)")
    print(PI5_TABLE)


if __name__ == "__main__":
    main()
