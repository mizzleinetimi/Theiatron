# Fresh detections → estimated 3D

14 September 2026 · local software prototype · branch `codex`

## Delivered

The continuous-perception lab now places **fresh YOLO/ByteTrack observations**
into the existing Three.js vehicle/road renderer. Open:

`http://127.0.0.1:8766/workbench/live.html?video=ui-20260912-162811-img-0635-ddba8b2c`

Use the retained IMG_0635 source at 10 FPS. The source preview and orbitable 3D
view are alongside each other in a wide window and stacked in a narrow pane.
Orbit, top and fit controls, plus a visualization-only pause, are available.

This closes the **fresh vehicle observations → 3D presentation** gap for a
prepared, retained clip. It does not close the arbitrary footage → automatically
commissioned camera → validated live traffic measurements → control loop gap.

## Data boundary

1. The worker now records each observation's native `frame_index`, including
   after skipped samples and file loops. RTSP observations have no such file
   identity and are not eligible for this bridge.
2. `/api/runs/:id/live-geometry` returns validated-source bindings, the existing
   estimated ground mapping, road outline and camera registration. It returns
   **no saved vehicle tracks**. Missing/stale estimates are an error, not a
   reason to use another source's geometry.
3. The browser matches both the run and source SHA-256. It registers detector
   bottom-centre anchors against the exact native camera frame, then applies
   the same ground-plane homography as the recorded studio.
4. Rejected/missing camera transforms, out-of-road positions, invalid points,
   large jumps and stale observations are hidden. No nearest-frame camera
   transform, occluded trajectory or future vehicle position is invented.
5. Per-track filtering is causal (120 ms time constant); rendered movement eases
   between received filtered positions for at most 120 ms. It adds visual lag,
   not information. Histories hold at most eight samples for at most 256 current
   IDs, and reset on gaps/namespaces. Heading comes from recent observed motion;
   an initially stationary vehicle has an unknown heading/default orientation.

Camera/road estimates are **saved and reused**, not recomputed online. Geometry
can still be inaccurate, especially near the horizon and occlusions. Metres,
vehicle sizes and road edges are not surveyed. Colours identify tracks, not paint.
No validated speeds, queues, unique counts, delay savings or controller inputs
are produced by this view. Detection previews and the 3D view update separately;
they are not frame-locked video, and UI transport/easing is not included in the
detector's latency percentile.

3D freshness checks include the observation's scheduled-frame age plus time
since completion; over-one-second observations are hidden even if inference
has only just finished. Stopped/disconnected sessions clear live cars. Reloads
reattach to the same resident session; late geometry responses cannot overwrite
the selected source. Camera controls remain usable while detection continues.

## Verification

- **278 Python tests passed**, including the geometry HTTP boundary, missing
  estimates, no-track payload, native frame indices, real decoder loop indices,
  soak accounting/checksums and the existing simulator/service suite.
- **37 JavaScript tests** cover existing viewers plus source binding, rejected
  mappings, stale input, causal easing, gaps, hard memory bounds, geometry-load
  races, disconnect/pause, and back/forward-cache lifecycle.
- Browser verification: fresh meshes on the source-specific road; top/fit
  controls; visualization pause leaves inference running; reload reattaches.
  A high-DPI canvas sizing bug found during visual checking was corrected.
- Real trace contract check: all 267 first-start and 266 warm-restart
  observations at offered 10 FPS had exact camera mappings. At offered 30 FPS,
  only 98/292 had matching saved camera frames; the other 194 were hidden.
  This checks correspondence/software behavior, **not spatial accuracy**.

## Repeat performance measurements

Three new 30-second sessions, same resident worker PID 41254. Source IMG_0635,
CPU detector, 640-pixel inference. All observations and bad outcomes retained.

| Offered cadence / case | Request → first observation | Full-trace p95 age | Observations |
|---|---:|---:|---:|
| First/cold 10 FPS | 7.976 s | 196.964 ms | 267 |
| Warm 10 FPS | 0.437 s | 223.690 ms | 266 |
| Higher offered 30 FPS | 0.377 s | 192.371 ms | 292 |

Artifacts: `out/continuous-benchmark-20260914-bridge/benchmark.json` plus all
three reports/traces. These differ substantially from the earlier 68 ms warm
spot check. No full Python/SUMO regression suite ran concurrently with this
repeat benchmark, but this was **not an isolated machine**: local development,
API reads and other applications were present. Do not advertise one best run
as a guaranteed rate or sensor-to-decision latency.

## One-hour soak: lifecycle completed, latency not signed off

`scripts/soak_live.py` starts a bounded, looping retained-file session and records
worker identity, RSS snapshots, completed observations, deadline misses and
freshness every five seconds. On completion it verifies the full trace hash,
report checksum, input accounting, monotonic sequence and loop namespaces.
It computes full-trace percentiles and first/last-quartile median RSS. OS memory
compression/reclamation means RSS is not a standalone proof of no leak.

Current run: `live-20260914-163720-033ba0dc`.
Progress/final report: `out/continuous-soak-20260914-bridge/soak.json`.
Raw observer samples: `out/continuous-soak-20260914-bridge/samples.jsonl`.

The run completed 3,601.107 seconds, and its final report/trace hashes, accounting
and loop namespace checks were independently recomputed. Results:

| Measurement | Result |
|---|---:|
| Observations / average processed cadence | 29,679 / 8.24 FPS |
| p50 / p95 scheduled-file observation age | 57.577 / 210.499 ms |
| Maximum observation age | **5,936.946 ms** |
| Observations over 300 ms | 780 (2.63%) |
| Pending frames overwritten / stale inputs rejected | 4,394 / 193 |
| Source loops / tracker resets | 29 / 395 |
| First / last quartile median sampled RSS | 211.91 / 218.14 MiB |
| Maximum sampled RSS | 235.28 MiB |

The process survived the full duration with bounded input accounting. It did
**not** maintain the requested 10 FPS or a 300 ms deadline throughout. The high
reset count includes load-related gaps, not just file loops. RSS snapshots show
no runaway rise in this one run but cannot establish leak freedom or total
physical footprint under macOS compression/reclamation. System load was elevated (one diagnostic snapshot
showed a one-minute load average of 20.94). The frontend was being developed
and exercised during the soak, including focused upload HTTP/unit tests late
in the run; it is a shared-laptop interactive stability test,
**not a clean-machine, idle-machine, camera or Raspberry Pi benchmark**.

Reproduce into a new directory with the workbench ready:

```bash
.venv/bin/python scripts/soak_live.py \
  --source ui-20260912-162811-img-0635-ddba8b2c \
  --out out/continuous-soak-new --seconds 3600 --fps 10 \
  --context 'Describe machine load and whether the 3D preview is open'
```

Stopping is supported, but the script reports an early stop as an incomplete
soak, not success. A completed duration is a lifecycle result, not a latency
pass: p95/max age, misses, drops and memory still need evaluation.

## Next

1. Review the completed soak, then repeat under controlled load; reduce
   contention and measure the incremental cost of the UI/3D bridge.
2. Direct-to-stream new uploads and online camera registration/road estimation,
   with confidence-based failure handling. Current browser sources still require
   prior analysis and the bridge requires saved estimates.
3. Real camera timestamp/disconnect tests, independently labelled counts/queues,
   and a separate observation-window adapter for fair SUMO experiments.
4. Clean-machine investor release/rehearsal, then hardware and permissioned pilot
   validation. No roadside actuation is included.
