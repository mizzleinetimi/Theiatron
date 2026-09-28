# Milestone 1: consistent, inspectable evidence

Implemented on `codex`, 8 September 2026. This is the evidence-consistency
slice of the investor-demo roadmap, not completion of the software product.

## Delivered

- One canonical `simulation.json` per new analysis: complete config, exact
  arrival batches and simulation clock, full-precision vehicle timings,
  signal changes, backend/metric identity, summaries and comparison policy.
- SHA-256 content fingerprint shared by the report, timeline and manifest.
  This detects accidental mixing/corruption; it is not a digital signature
  or independent verification of the detected demand/model assumptions.
- Exact replay from a moved run directory without rerunning vision. The
  replay checks its resulting vehicle/signal trace against the recorded one.
- 3D export decorates that trace instead of rerunning the controllers with
  default queue parameters and an unrelated timestep.
- Final fractional replay intervals and boundary arrivals are included;
  event recording no longer rounds away timestamp precision.
- Common better/worse/equal/inconclusive presentation. Both phase coverage
  and a minimum count are checked. A zero baseline with positive adaptive
  delay is shown as worse without an undefined percentage.
- Invalid/missing selected-run links fail visibly instead of substituting
  the first sample. Unknown T-junction exits do not invent a fourth road;
  without a recorded path, vehicles are hidden after queue discharge.
- Explicitly unseen evaluations cannot silently become full-clip reruns.

## Verification

- 71 Python tests pass (`.venv/bin/python -m pytest -q`).
- 5 Node viewer tests pass (`node --test tests/test_viewer.cjs`).
- Tests prove canonical export never invokes a simulation engine, non-default
  queue parameters survive legacy export, live-style irregular clocks replay
  exactly, malformed/missing artifacts fail closed, and intermediate verdicts
  do not use future arrivals.
- Fresh vision run of retained `IMG_0635.mov`:
  `out/evidence-20260908-img0635`. Observed 122.3 seconds for calibration;
  evaluated a fresh 30.0138-second pass (300 inference ticks, about 17.3
  seconds evaluation wall time). Three arrivals: **inconclusive**, 1.20s mean
  censored queue wait for each controller. These throughput figures exclude
  calibration/export and are not a Raspberry Pi benchmark.
- `out/evidence-20260908-img0635-verified` exactly reproduces that run's
  simulation record and report.
- Replays targeting an existing evidence directory create a new `replay-*`
  child; shorter experiments cannot truncate source events or replace earlier
  reports. The source-protection path is regression-tested.
- Original 40-arrival sample replay in `out/evidence-20260908-original`
  preserves 10.90s fixed versus 6.04s adaptive: 44.6% modeled reduction on
  that specific sample, not an average across sites or a field saving.
- Browser checked: run-specific road plate and detection video render,
  result is inconclusive, and an invalid run link shows an error without
  loading sample footage. Existing model-loader UV warnings remain.

Generated run data is ignored by Git; retain whole run directories for evidence.
Keep original historical outputs unchanged. Re-exporting legacy events creates
a `legacy-recomputed` timeline, not retroactive proof of exact live results.

## SUMO integration boundary: next implementation milestone

The new artifact boundary separates simulation results from presentation.
It deliberately identifies the current backend as `point-queue`, its metric
as `censored-queue-wait-seconds`, and geometry as `illustrative-not-metric`.
The current exporter refuses an unknown backend rather than rendering SUMO
data under point-queue assumptions. No SUMO executable, TraCI connection or
microscopic traffic model has been added in this milestone.

The next vertical slice should:

1. Add stock SUMO as an optional, pinned simulation dependency, with a
   deterministic synthetic junction fixture explicitly labelled synthetic.
   Then commission one reviewed metric junction network for the target demo.
2. Translate detected boundary demand into explicit route/turn demand with
   documented assumptions. Keep initial queues and held-out observations
   distinct. Do not place the original footage trajectories into both worlds.
3. Run fixed, adaptive and subsequently actuated baselines in separate SUMO
   instances with paired seeds/demand. Each controller reads its own world's
   queues. Preserve a reviewed signal program and clearance transitions.
4. Emit authoritative SUMO position/heading/speed samples, signal state and
   stable vehicle IDs into a backend-specific versioned trace. Three.js must
   render these trajectories, not retime recorded camera paths.
5. Report journey/queue metrics with their definitions and units, including
   insertion delay, pending demand and unfinished vehicles. Never equate the
   current point-queue metric to SUMO travel time. Include network/config/seed
   provenance and compare over multiple runs.
6. Stream sampled state through a bounded transport for live viewing while
   persisting the same data for replay. Use the same final artifact/report
   consistency checks established here.

## Not solved by this milestone

- Automatic geometric quality scores are still heuristics, not metric road
  calibration or verified turn-lane topology. Human commissioning is needed.
- The point-queue model retains its existing discrete-tick service/control
  semantics. It is not a microscopic vehicle-dynamics model.
- Ten vehicles across two phases is only a minimum UI guard. It does not
  establish sufficient statistical power, good baseline tuning, fair demand
  modelling, or external validity.
- Traces and departed-vehicle histories remain unbounded for long-running
  sessions; this is a finite-video demo path, not the field streaming runtime.
- Launcher still needs restricted static-file serving, upload admission
  reservation, persistent/cancellable jobs and production hardening. Keep it
  local; do not expose it as an internet service.
- No target Raspberry Pi/Hailo performance, thermal, power or fault testing;
  no real-road signal-controller integration, safety certification or pilot.
- SUMO integration, a reviewed junction, tuned baselines, repeated held-out
  evaluation and a credible pilot package remain before the investor release.
