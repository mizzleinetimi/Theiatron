# Theiatron

**Smart traffic lights that see.** Theiatron is an R&D prototype for camera-based
junction observation and adaptive signal evaluation. A nano detector measures
traffic from footage; software compares control decisions. Whether it reduces
delay depends on the scenario and is not yet established in the field.

Selected for the NextGen Innovation Challenge (concept stage); this repository
is the working prototype.

## Local workbench — current implementation

**Three-minute innovation recording:** `/workbench/showcase.html` is a guided,
source-bound page for recording the working prototype: fresh detection, estimated
3D, a new SUMO comparison, and evidence with adverse long-wait outcomes visible.
The [recording script and shot list](docs/government-demo-recording-2026-09-24.md)
explain exactly what to show and which claims are not established. Screen
recording remains a separate, user-controlled action.

**Investor presenter:** open `/workbench/demo.html`, or double-click
`Start Demo.command` on this configured Mac. See the
[operator guide](docs/demo-operator-guide.md) for the three-minute walkthrough.
The presenter supports direct footage upload, fresh detection previews, automatic
recorded reconstruction, and genuine paired SUMO computation. No survey is
required to run a **labelled hypothesis**. Accepted camera-ground estimates seed
the network directions and visible-footprint context in one coordinate plane;
lane geometry, extensions and exits remain procedural assumptions.

Experiment demand is explicitly either recorded crossing timestamps or a new
generated population. Generated experiments can display **within-model** delay
differences, including negative outcomes; neither mode establishes field savings.
Checksummed evidence ZIPs exclude raw video. This is a local R&D demonstrator,
not a calibrated digital twin, live camera service or hardware-ready controller.

The presenter now offers **service v2** (experimental moving-vehicle-aware
control), the legacy pressure policy, and fixed-time or actuated gap-out
comparators. Every run records its policy versions. The reproducible controller
benchmark separates development seeds from locked evaluation seeds; see
[the controller/perception milestone](docs/controller-perception-milestone-2026-09-13.md).

**Continuous perception lab:** `/workbench/live.html` runs fresh detection on
new uploads or retained footage paced at camera speed. **Upload & start
detection** bypasses the full analysis/export pipeline; transfer and cold model
loading still take time. **Prepare road & saved 3D** reuses the uploaded bytes in
an independent visual pipeline after detection stops: count-line confidence no
longer blocks recorded observations and road estimation. Geometry may still need
review; this path creates no counts or savings results. See
[independent reconstruction](docs/independent-reconstruction-2026-09-20.md).
An overhead-camera fallback now tests two road-line direction families when
upright scene cues are missing. Unstable estimates remain explicitly unrectified;
this is not universal or measured calibration. See the
[perspective recovery and performance checkpoint](docs/road-camera-fallback-2026-09-21.md).
When single-frame recovery fails, refinement now consolidates repeated road lines
across registered native frames and requires early/late evidence agreement. The
current overhead clip still fails the stability gate; see the
[multi-frame evidence checkpoint](docs/temporal-road-evidence-2026-09-22.md).
**Review road → Guided perspective** now offers an eight-endpoint direction
guide, stability check, unsaved 3D preview and explicit assisted save. It requires
appropriate parallel/perpendicular ground edges, not measured distances; scale
remains assumed. See [the guided fallback](docs/guided-perspective-2026-09-22.md).
Saved guided perspective now also feeds **fresh-detection 3D** after source-bound
camera refinement completes. The live endpoint reproduces the saved fit and
keeps it separate from automatic geometry; stale or unsupported evidence still
blocks projection. See [the assisted live bridge](docs/assisted-live-bridge-2026-09-24.md).
A resident detector, single-slot input
buffer, explicit drop counters and observation-age metrics avoid a growing
backlog. The warm 10 FPS local spot check reached 9.96 processed FPS and 68 ms
p95 scheduled-file observation age; this is not sensor capture latency or Pi
performance. See [the continuous-perception milestone](docs/continuous-perception-milestone-2026-09-14.md).
The lab now projects **fresh detections into Three.js** using this retained
clip's saved road/camera estimates, matched by source hash and native frame.
It does not replay saved vehicle tracks or estimate geometry live. Missing
camera mappings and stale observations hide vehicles. Full media export and
SUMO remain separate. See [the live 3D bridge and soak status](docs/live-3d-bridge-2026-09-14.md).

```bash
# Existing project environment; install the optional stock simulator once:
uv pip install --python .venv/bin/python -r requirements-sumo.txt
.venv/bin/python scripts/preflight.py
.venv/bin/python launcher_server.py --port 8766
```

Open **http://127.0.0.1:8766/workbench/**. The server binds only to loopback;
do not expose it through a public tunnel or use it as a production web service.
The pinned SUMO wheel may require vendor-documented native dependencies on a
new Mac. Run the preflight before going offline.

- **Watch:** choose footage, see fresh boxes/tracks while the worker processes
  it, inspect source time and preview age, then **Open recorded 3D studio**.
  Opening the studio automatically refines dense observations: background camera
  registration, offline robust trajectory filtering and a motion/appearance road
  proposal. Progress, cancel and source-bound caching keep the viewer usable.
  **Undo camera perspective** applies a source-specific vanishing-direction camera
  estimate to the road and tracks together. **Show ground grid** and the editor's
  projected grid help inspect foreshortening; the model does not establish metres.
  Orbit/pan/zoom, compare raw/refined anchors against the source video, and
  review/edit the automatic outline and perspective mapping. New analyses retain
  observations, classes, boxes and confidence. New cameras never inherit another
  video's scene. Physical scale and road geometry remain unvalidated; a measured
  reference and review are still needed. The old point-queue illustration is
  separate. This is file
  processing, not a live camera service. Full-clip analysis now reuses its own
  initial detections after learning count lines, avoiding duplicate inference.
  Frames are decoded again for overlays and checked against retained pixel hashes.
  For a completed local clip, **Edit count lines / recount local clip** lets
  you place count-line endpoints and approach-side markers, then perform one
  fresh inference pass without re-uploading or automatically recalibrating.
  It creates a new run and camera revision; old results are preserved.
- **Compare:** run two independent **stock SUMO 1.27.1** simulations on identical
  generated demand, or use a footage-linked draft with the recorded arrivals.
  Top-down and perspective views use actual simulator
  positions, lengths and signals. Demand pattern/scale, horizon and seed create
  a new experiment. Saved playback is explicitly labelled as replay.
- **Evidence:** inspect the cohort, assumptions, seed, timing configuration,
  diagnostics and checksummed report/network/routes/trajectory files. Failed,
  cancelled and interrupted workers do not become completed evidence.

**Footage-linked draft:** select a completed video in Saved runs → **Create
footage-linked SUMO draft**. Inspect its count lines, edit assumed endpoints,
lanes, speeds, traffic side and timings, choose an explicit assumed exit for
each enabled approach, then acknowledge the limitations and compute. Revisions
are immutable and retain the original arrival IDs/timestamps and source hashes.
This adapter supports 2–4 arms and 30–300 source seconds; it does not infer
turning counts, survey dimensions or let users silently multiply observed demand.

**Important boundary:** neither mode is a validated reconstruction of the
uploaded site. The original laboratory fixture remains explicitly synthetic.
The footage-linked mode starts from a camera-direction sketch and assumed
metric geometry/routes, with an exclusive signal stage per incoming approach.
Both modes use ideal queue sensing and an empty initial network. Draft profiles
cannot be marked reviewed. Recorded-arrival improvement headlines are disabled;
explicit generated experiments have separate, labelled within-model differences.
Reviewed metric geometry, observed turns, representative baselines and held-out
perception validation remain the next evidence gate.
Negative results are retained; there is no preset improvement percentage.

See [the footage-linked milestone](docs/footage-sumo-milestone-2026-09-11.md)
for the tested local clip, evidence boundary and remaining commissioning work.
See [the recorded 3D studio milestone](docs/recorded-3d-studio-2026-09-11.md)
for the new source replay, fresh IMG_0635 run, calibration controls and accuracy
limits. The studio road and existing SUMO draft network are not yet a shared,
validated lane model; recorded replay does not establish controller savings.

SUMO comparisons report **stopped waiting + insertion delay accrued to a common
horizon**, including unfinished and undeparted vehicles. This is not journey
time, SUMO timeLoss, observed field savings or Raspberry Pi performance.

```bash
# Fast, reproducible laboratory experiment (pace 0 means as fast as possible):
.venv/bin/python -m theiatron.sumo_demo --out out/sumo-example --duration 180 --pace 0
.venv/bin/python -m theiatron.sumo_demo --out out/sumo-example --verify
# Use a NEW directory to recompute the same scenario; existing evidence is protected:
.venv/bin/python -m theiatron.sumo_demo --out out/sumo-example-repeat --duration 180 --pace 0
THEIATRON_REQUIRE_SUMO=1 .venv/bin/python -m pytest -q
node --test tests/test_viewer.cjs tests/test_workbench.cjs tests/test_reconstruction.cjs
```

`requirements-macos-arm64.snapshot.txt` records the tested local environment;
it is a platform-specific version snapshot, not a fully hash-locked portable
release. CI configuration tests core logic and the real simulator without
downloading detector weights. See [implementation status and remaining gates](docs/workbench-milestone-2026-09-10.md).

## What the prototype demonstrates

1. **Real perception.** Vehicles in real traffic footage are detected
   (YOLO26n, ~6 MB) and tracked (ByteTrack); each vehicle registers one
   arrival when it crosses a calibrated count line. This is the exact
   starting point for an edge deployment; target-hardware optimization and
   field validation remain to be done.
2. **Adaptive control versus a fixed timer.** A queue-pressure controller with
   safety interlocks (min/max green, yellow, all-red, anti-starvation) is
   compared against a classic fixed-split timer **on the identical arrival
   stream**, reporting average and 95th-percentile modeled queue wait.
   Outcomes can be better, equal, worse or inconclusive.
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

## Reproducible run evidence

New analyses save `simulation.json`: a versioned, checksummed record of the
actual simulation ticks, arrival batches, signal transitions, vehicle
arrival/departure times, config snapshot and both controller results.
`report.json`, the launcher and the 3D timeline reference this same artifact.
The 3D exporter adds illustrative motion to recorded results; it does not
run a second simulation for a current-format run.

An exact replay uses the recorded clock and config, without needing the
original video or an original absolute config path:

```bash
.venv/bin/python run_demo.py --replay out/YOUR_RUN/events.json --out out/YOUR_RUN-verified
.venv/bin/python -m pytest -q
node --test tests/test_viewer.cjs
```

An explicit `--config` or `--duration` override starts a **new** nominal-0.1s
experiment, not an exact replay. Historical event files without a simulation
record also use this legacy mode; previously rounded timestamps cannot be
recovered. The exporter rejects a mismatched config, duration or event stream
when a canonical artifact is present.
If the replay output directory already contains evidence, a new `replay-*`
child directory is created so the source run and earlier results are preserved.

A percentage headline requires at least 10 arrivals and observed demand on
both NS and EW phases. These are minimum demonstration guards, not statistical
confidence, calibrated geometry or proof of effectiveness. One-phase/sparse
samples are labelled inconclusive; negative and equal outcomes remain visible.
Wait includes unfinished vehicles' wait **so far**, not complete journey time.
`--evaluation-scope unseen` now refuses insufficient held-out footage instead
of silently rewinding; explicitly select `full` for a full-clip experiment.

The **video-derived** backend remains explicitly identified as `point-queue`,
with illustrative (not metric) geometry. The separate laboratory comparison
above now uses stock SUMO. See
[the first milestone and SUMO integration boundary](docs/evidence-milestone-2026-09-08.md).

## Auto-calibration: point it at a new intersection

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

## Live demo on new footage

The stage workflow runs the underlying perception system on a new video; it
does not replay prepared arrivals:

```bash
bash scripts/launcher.sh
```

This opens a local, offline launcher. Choose or drop a video and it copies the
file into an isolated run, shows calibration and inference progress, validates
the generated artifacts, and opens that run's 3D comparison automatically.
No terminal interaction is needed after the launcher is open.

The command-line equivalent remains:

```bash
bash scripts/live_demo.sh path/to/intersection.mp4
```

The opening observation segment is processed by YOLO + ByteTrack to learn the
traffic corridors and counting lines. The default then recounts those retained
observations while decoding the clip for overlays. Each sampled frame receives
one fresh inference; if the evaluation extends beyond the retained prefix, the
same tracker continues on the next new frame. Pixel hashes reject mismatches.
This is full-clip exploratory counting, not held-out perception validation.
`--perception-pass fresh` retains the original two-pass workflow with a new
detector for the second pass. Use `--evaluation-scope unseen` to continue into
only the post-calibration segment. Neither option makes this a live camera feed.

Each run writes a timestamped directory under `out/` containing the learned
config, calibration overlay and road mask, annotated dashboard video, arrival
events, track motions, run-specific 3D timeline and footage, reproducibility
manifest, and comparison report. On macOS the launcher opens that run directly
in the side-by-side 3D viewer when processing finishes. See `DEMO.md` for the
stage checklist and supported-footage constraints.

Validation on the demo intersection: a full-clip observation recovered all 4
approaches, count-line geometry, compass names, and phase pairing from the
checked-in auto-calibration with zero human input.

A clean full inference pass through that learned configuration counted 36
arrivals and produced 9.09 s adaptive versus 13.01 s fixed modeled average
wait (30.1% lower). The detector used for evaluation is deliberately a fresh
instance: reusing the calibration tracker can recycle IDs and merge vehicles.

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
pytest                                  # 39 unit tests
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
Pexels 13905519, 180 s, 40 vehicles — the primary checked-in run):

| Metric | Fixed timer | Theiatron adaptive | Change |
|---|---|---|---|
| Average wait | 10.9 s | 6.04 s | **−44.6%** |
| 95th-percentile wait | 36.73 s | 17.96 s | **−51.1%** |
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
