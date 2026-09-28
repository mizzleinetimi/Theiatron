# Continuous perception milestone

14 September 2026 · local prototype · branch `codex`

Later on 14 September: a fresh-detection → Three.js bridge and an instrumented
one-hour soak were added. The historical measurements below remain unchanged.
See [live 3D bridge status](live-3d-bridge-2026-09-14.md) for the new integration,
repeat measurements and remaining boundaries.

## What now works

Open `/workbench/live.html`, also linked from **Observe → Continuous detection
lab** in the investor presenter. Select retained footage, a time limit and a
sample cadence. **Start fresh detection** performs new YOLO/ByteTrack inference
as file frames are presented at source speed. It does not replay cached boxes.

The first request creates an isolated worker, loads the model and warms its
predictor. Subsequent sessions reuse the same worker/model. Each session resets
tracking, has a unique identity namespace, and writes a separate output directory.
The detector is never shared concurrently between cameras.

Capture and inference are decoupled. The pending-frame buffer has capacity one;
old pending work is overwritten under load. Samples more than 300 ms old are
rejected before inference. A completed inference can still exceed the deadline;
these misses are measured, not hidden. Source-time gaps over 0.5 seconds and
loop boundaries reset the tracker and start a new namespace. The path keeps no
growing frame history and does not synchronously encode a whole output video.

The UI shows fresh boxes, source position, processing FPS, p50/p95 observation
age, mean inference duration, drops, stale rejection, deadline misses, and reset
counts. A stopped/disconnected preview is explicitly stale. Browser reload can
reattach to the active session, including sessions started through the local API.
Other heavy file/refinement/SUMO jobs cannot be admitted while streaming.

**Stop session** retains the warm model. The worker also stops on source EOF,
the selected duration, capture failure, or service shutdown. Startup and stop
deadlines guard unresponsive workers; the parent watchdog prevents orphaned
worker processes. An interrupted worker cannot become live again merely because
its last JSON snapshot said `running`.

## Actual measurements

Three 30-second fresh sessions of retained IMG_0635 on this Mac, CPU detector,
640-pixel model input; source frames normalized to 1280×720. No controller was
driven by these observations. All three sessions used worker PID **18998** and
separate track namespaces; the model was loaded once.

| Case | Offered cadence | Request → first observation | Full trace p95 observation age | Observations | Pending frames overwritten |
|---|---:|---:|---:|---:|---:|
| First/cold start | 10 FPS | 3.344 s | 140.119 ms | 284 | 15 |
| Warm restart | 10 FPS | 0.269 s | 68.126 ms | 298 | 2 |
| Higher offered cadence | 30 FPS | 0.605 s | 208.314 ms | 393 | 491 |

The warm run's recent processing rate was **9.96 FPS**, with no observations over
300 ms. The first run had three deadline misses. The 30 FPS case had eleven;
the regression suite ran concurrently during that third case, so it is an
overload demonstration, **not an isolated maximum-throughput benchmark**.
No frames or worse outcomes were removed from these records.

The UI's session percentiles are 1 ms histogram upper bounds. The table uses
nearest-rank percentiles recomputed from every retained timing row. The input
accounting is checked: offered = overwritten + taken + pending; taken =
inferred + stale-rejected. Normal native-video-to-target-cadence sampling is
separate from dropped target frames.

Artifacts: `out/continuous-benchmark-20260914-run1/benchmark.json`, with per-case
reports and raw traces in the referenced `out/live-*` directories. An initial
attempt in `out/continuous-benchmark-20260914` failed before any session because
the service had not finished starting; it is not a completed benchmark.

These are small laptop spot checks. CPU contention can breach the 300 ms
threshold even at 10 FPS. This is not a hard-realtime guarantee, a detector
accuracy evaluation, physical camera capture latency, or Raspberry Pi evidence.

## Reproduce

Start the local workbench, wait for it to report ready, then:

```bash
.venv/bin/python scripts/benchmark_live.py \
  --source ui-20260912-162811-img-0635-ddba8b2c \
  --out out/continuous-benchmark-new --seconds 30
```

Use a new output directory. A previously warmed worker is reported as such,
not relabelled cold. No video upload occurs in this retained-source test.

The standalone path can also process a new local video without prior road
calibration or the full analysis/export pipeline:

```bash
.venv/bin/python -m theiatron.live_worker --source /absolute/path/to/clip.mov \
  --out out/continuous-new-clip --duration 120 --fps 10
```

For an explicitly configured camera, the CLI accepts `--camera-env VARIABLE`
instead of `--source`; the named environment variable must contain its RTSP URL.
The browser does not accept arbitrary network URLs or filesystem paths. No camera
was opened during this milestone. The RTSP adapter uses bounded open/read timeouts,
stops on disconnect, and records **host read-completion** timestamps. Camera-side
encoding, transport and decoder buffering are unmeasured, so this must not be
called sensor-to-decision latency. The adapter still requires real-device testing.

## Artifacts and boundaries

- `latest.json`: current observations, counters, source clock, worker identity
  and freshness. A partial snapshot is not a final result.
- `observations.jsonl`: per-observation detections, track namespace, timestamps,
  inference duration and observation age. Pixel frames are not accumulated.
- `preview.jpg`: bounded latest annotated image, published at up to 5 FPS.
- `stream-report.json`: terminal state, source/model/code hashes, aggregate
  timing counters and checksums for the trace/preview. Stopped and failed sessions
  retain their actual state; they are not relabelled complete.

Paced-file age starts at a frame's scheduled presentation time. It is useful for
checking that compute keeps up with an input clock. For RTSP the basis is only a
host timestamp proxy. Neither includes browser delivery latency. Preview age and
time since the last observation are shown separately.

This worker does **not** automatically regenerate the 3D road, perform calibrated
arrival/queue measurement, or supply a safety-qualified signal controller. The
existing recorded reconstruction and SUMO evidence workflows remain separate.
The new UI currently chooses previously analysed retained clips; the CLI accepts
new files directly. Broad camera support and direct-to-stream uploads are not
claimed complete.

## Verification and next gates

272 Python tests and 26 JavaScript tests passed, including overwrite accounting,
stale-input failure, cancellation before start, loop identity resets, warm
predictor retention, HTTP admission/security, startup failure and dead-worker
snapshot handling. Full service shutdown was checked to end its owned worker.

A 140-second looping session (`live-20260914-123909-070f7250`) completed after
crossing the source EOF and verified a different identity namespace on the next
loop. It retained 1,159 observations, 52 over-300 ms observations and a 280 ms
histogram p95; its maximum was 1,267.728 ms. The full regression suite ran during
the first part of this stress check. These spikes demonstrate why a capacity-one
buffer does not guarantee a processing deadline. Browser start/preview/stop was
then verified on `live-20260914-124301-f21ef496`, with the same warm worker PID
20338 retained after stopping. The stopped preview is labelled as saved, not live.

Next: a one-hour clean-machine soak and repeated cold/warm latency runs; a real
camera with trustworthy timestamps/disconnect tests; then independently validated
live counts/queues and a preview-only bridge into the 3D view. Pi/accelerator
profiling and any roadside actuation remain separate hardware/safety work.
