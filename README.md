# Theiatron

**Smart traffic lights that see.** Theiatron replaces fixed signal timers with
on-device computer vision: a nano object detector watches each approach,
measures real demand, and a pressure-based controller allocates green time
dynamically — cutting wait times without any cloud connectivity.

Selected for the NextGen Innovation Challenge (concept stage); this repository
is the working prototype.

## What the prototype demonstrates

1. **Real perception.** Vehicles in real traffic footage are detected
   (YOLO26n, ~6 MB) and tracked (ByteTrack); each vehicle registers one
   arrival when it crosses a calibrated count line. This is the exact
   perception stack an edge deployment would run.
2. **Adaptive control beats a fixed timer.** A queue-pressure controller with
   safety interlocks (min/max green, yellow, all-red, anti-starvation) is
   compared against a classic fixed-split timer **on the identical arrival
   stream**, reporting average and 95th-percentile wait reductions.
3. **Edge feasibility.** The detector exports to ONNX and is benchmarked
   CPU-only, alongside published Raspberry Pi 5 measurements.

## Honest framing of the simulation

Recorded vehicles cannot react to our simulated light. So:

- **Demand is real** — arrival events come from detecting and tracking
  vehicles in real video.
- **Service is simulated** — a standard point-queue model accumulates
  arrivals on red and discharges at saturation flow (1 veh / 2 s / lane,
  2 s startup lost time) on green.
- **The comparison is controlled** — both controllers consume the same
  arrival stream; arrivals can be recorded (`--record-arrivals`) and
  replayed (`--replay`) so every reported number is reproducible.

We claim *real-video demand, simulated service, controlled A/B* — not
closed-loop control of real traffic.

## Auto-calibration: point it at any intersection

Theiatron can learn an intersection's layout by watching it — no clicks:

```bash
python run_demo.py --config configs/intersection.yaml --auto-calibrate --observe 180
```

It tracks traffic for the observation window, clusters vehicle entry
headings into inbound corridors, locates the junction center as the
least-squares intersection of the corridor axes, places each count line
perpendicular to its corridor as far upstream as track coverage allows,
names approaches by compass direction, pairs opposite corridors into
signal phases, and writes the config (previous config kept as `.bak`,
review overlay at `out/autocal_overlay.png`).

Count lines are constrained to drivable surface via a **road mask**:
motion evidence (everywhere traffic actually drove) unioned with a
Cityscapes-trained SegFormer segmentation of visible asphalt
(`--road-model motion|segformer|auto`). Segmentation alone loses
tree-shadowed stretches on elevated views, so motion evidence is always
trusted.

Validation on the demo intersection: auto-calibration recovered all 4
approaches with the same compass names and phase pairing as the hand
calibration, captured 36/41 of the hand-config's arrivals with zero human
input, and the resulting A/B still shows a 30% average-wait reduction.

## Quickstart

```bash
uv venv --python 3.12 .venv
uv pip install -p .venv/bin/python -r requirements.txt
source .venv/bin/activate

bash scripts/get_videos.sh          # fetch + normalize 4 free-license clips
python run_demo.py --calibrate north   # click count line (repeat per approach)
python run_demo.py --config configs/intersection.yaml --duration 180  # single-camera demo
python run_demo.py --duration 120      # 4-camera variant (configs/approaches.yaml)
python run_demo.py --replay out/events.json   # reproduce numbers, no vision
python benchmark_edge.py               # ONNX CPU benchmark
pytest                                  # 20+ unit tests
```

## Architecture

```
video (1 per approach)        REAL            SIMULATED
   └─ detection.py  YOLO26n + ByteTrack (one instance per feed)
       └─ approach.py  count-line crossing -> arrival events
           ├─ engine.py (adaptive)  ┐  point-queue sim (sim.py)
           └─ engine.py (fixed shadow) ┘  identical arrivals
                └─ controller.py  interlocked phase state machine;
                                  policies only request switches
                     └─ metrics.py / dashboard.py  live A/B + report
```

Safety invariants (never two greens, yellow 3 s, all-red 1 s, min green 8 s,
max green 45 s) live in one state machine, enforced identically for every
control policy, and are unit-tested.

## Results

**Single elevated camera, one real intersection** (`configs/intersection.yaml`,
Pexels 13905519, 180 s, 41 vehicles — the primary demo):

| Metric | Fixed timer | Theiatron adaptive | Change |
|---|---|---|---|
| Average wait | 10.6 s | 5.9 s | **−44.4%** |
| 95th-percentile wait | 36.7 s | 17.9 s | **−51.2%** |
| Worst single wait | 40.9 s | 20.7 s | — |

**Four independent approach cameras** (`configs/approaches.yaml`, 4 city
clips, 180 s, 101 vehicles — higher-demand scenario):

| Metric | Fixed timer | Theiatron adaptive | Change |
|---|---|---|---|
| Average wait | 21.4 s | 13.7 s | **−35.8%** |
| 95th-percentile wait | 45.5 s | 30.0 s | **−34.1%** |
| Worst single wait | 49.8 s | 49.4 s | — |

Adaptive won on **every** approach individually. Key controller insight
(found by sweeping parameters against a recorded arrival stream): every
phase switch burns ~6 s of capacity in yellow + all-red + startup lost
time, so the policy serves the active queue until it fully drains and
strongly resists pre-emption; naive "switch whenever the other side is
bigger" logic loses to a fixed timer under load.

## Edge feasibility

Measured on Apple M2, CPU-only ONNX Runtime (no GPU/ANE), YOLO26n
(9.3 MB ONNX):

| Input | Threads | ms/frame | FPS |
|---|---|---|---|
| 640 | 1 | 83.0 | 12.1 |
| 640 | 4 | 29.9 | 33.5 |
| 416 | 1 | 35.3 | 28.4 |
| 416 | 4 | 12.1 | 83.0 |

Published Raspberry Pi 5 reference points (CPU): YOLO11n ONNX @640 ≈ 157 ms
(~6.4 FPS), INT8 ≈ 77 ms (~13 FPS); YOLO26n ONNX @640 ≈ 7.8 FPS. At 416
input (what Theiatron uses), compute scales ≈ 0.42×, giving roughly 12–15
FPS FP32. A 4-approach intersection needs either ~10 FPS on one shared
camera or a ~2.5 FPS/feed round-robin across four cameras — both within
Pi 5-class hardware, comfortably with INT8/NCNN. Sources: Ultralytics
Raspberry Pi guide & YOLO26 docs, LearnOpenCV Pi 5 measurements.

## License / footage

Traffic clips are fetched from Pexels/Pixabay under their free licenses;
`scripts/get_videos.sh` pins exact URLs and checksums.
