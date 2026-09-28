# Controller benchmark and single-inference video processing

13 September 2026 · local software milestone · branch `codex`

## Delivered

- **Service v2** experimental SUMO controller. Moving vehicles count as demand;
  an empty stopped queue no longer means that a platoon has finished crossing.
  The controller uses a committed, demand-proportional green budget, presence
  gap-out and waiting-approach priority. Minimum/maximum green, yellow, all-red
  and the next stage committed during clearance remain enforced.
- **Actuated comparator** using the same lane presence/arrival-time observations,
  cyclic nonempty-stage selection and gap-out. It is a software comparator, not
  a model of any incumbent signal installation. Both policies use ideal sensing
  from their own simulation world, not future arrivals or the other world.
- **Explicit policy selection** in the presenter. Older saved runs remain
  pressure v1; new runs record the baseline and candidate in their scenario,
  trace and report. The evidence ZIP preserves these identities.
- **Same-run observation reuse** in full-clip video analysis. A disk spool keeps
  the detections from road/count-line discovery. The clip is decoded again for
  overlays and counting, but not inferred again. Pixel hashes verify the matching
  frames; the same tracker continues beyond the retained prefix. Mismatches
  fail closed. `--perception-pass fresh` preserves the original two-pass option.
- **Earlier detection preview:** the presenter shows first-pass detection while
  learning the road, with source time and preview age, instead of waiting until
  the counting pass. This is still an uploaded-file workflow, not a camera feed.

## Why the controller changed

The old controller often switched as soon as a stopped queue began moving.
In inspected 180-second tidal/heavy runs it spent about 65–67.5 seconds in
yellow/all-red, versus 35 seconds for the original 20-second fixed split.
Moving-lane presence and a service budget address this failure mechanism.
No simulator trajectories or result percentages were retimed or edited.

## Frozen synthetic evaluation

One estimated IMG_0635 network; 180-second empty-start runs; three demand
patterns (balanced, tidal, heavy); homogeneous cars and ideal simulator sensing.
The generated population replaces recorded arrivals. This does not evaluate
perception accuracy, physical geometry or field benefit.

Development seeds **42, 43** choose among **12, 20, 30 second** fixed splits,
minimising aggregate fixed-world delay alone. The selected split is **12 seconds**.
Service v2 then runs against this fixed baseline and the actuated comparator.
Development gains were 13.526% versus fixed and 1.117% versus actuated; the
actuated comparison included two regressions out of six.

The controller was frozen before evaluating seeds **103, 107, 109**. The
evaluation refuses changed controller/benchmark code. For each case it verifies
identical demand/network hashes and reproducible fixed-world metrics across
candidate comparisons. Every outcome is retained; there is no winning-case filter.

| Held-out-seed comparison | Mean-delay cases improved / worsened | Aggregate delay reduction | Finished: baseline → candidate | p95 worsened cases |
|---|---:|---:|---:|---:|
| Pressure v1 vs tuned fixed | 6 / 3 | 1.452% | 464 → 444 | 2 / 9 |
| Service v2 vs tuned fixed | 8 / 1 | 15.079% | 464 → 523 | 1 / 9 |
| Service v2 vs actuated | 9 / 0 | 4.748% | 512 → 523 | 3 / 9 |

The percentage uses the sum of stopped-plus-insertion delay over the common
intended-demand cohorts, including pending and unfinished vehicles; it is not
an average of selected percentages or completed-trip journey-time savings.
Service v2's fixed-baseline regression is heavy demand, seed 103: **54.7324 s**
versus **54.6766 s** mean delay. Its p95 regressions against actuated occur in
balanced 107 and heavy 103/107. These remain follow-up work, not hidden failures.

This is a small held-out-random-seed software test on one hypothetical network,
not independent real footage, multiple sites or a statistically established
commercial advantage. Do not present these percentages as real traffic savings.

### Reproduce / inspect

```bash
.venv/bin/python -m theiatron.benchmark --phase develop \
  --profile 39e69990ce80d1b12330cef047f27be486c557f6dcdb9448341d5dae676117ae \
  --out out/controller-development-new
.venv/bin/python -m theiatron.benchmark --phase evaluate \
  --development out/controller-development-new --out out/controller-evaluation-new
```

Directories must be new. Development creates 30 paired runs and evaluation 27.
Existing sealed manifests:

- `out/controller-development-20260913-v2-final/benchmark.json`
- `out/controller-evaluation-20260913-v2/benchmark.json`
- Evaluation artifact: `3d8c1230c7ba60a700e048e1ee5d9c0a735cd63267363bb330db88d4011445e5`
- Selected immutable profile: `66d2f95752035b9fff38ab9d59b71e8b5218ea544a42744d25ca050ff44623c5`

The earlier development directory `out/controller-development-20260913-v2`
is retained. The final rerun corrected descriptive policy labels and separated
the selected-baseline summary from the fixed-split tuning rows; it did not tune
the controller on held-out results. Runtime/package versions and code hashes
are recorded in individual simulator reports.

## Video verification and limits

The retained IMG_0635 source was processed for 120.055 seconds at approximately
10 sampled frames/second. Reuse performed **1,200 inference calls instead of
2,400**. It retained the same **19 crossings and 157 track fragments**; its entire
`recorded-tracks.json` equals the earlier fresh-pass output. Track fragments are
not unique-vehicle ground truth. The file hash, retained observations and code/
model fingerprints are recorded with the run.

An initial reuse run took 160.224 seconds while the controller benchmark was
running concurrently; this is not a clean speed comparison. Decode, annotation,
encoding and later camera refinement still cost time. Detector-only ticks/s and
analysis ticks/s must not be labelled end-to-end camera FPS or capture latency.

A subsequent same-code, same-source timing pair (no concurrent simulator or
test suite) took **171.946 s with two fresh inference passes** and **129.376 s
with observation reuse**, a **24.758% reduction** in this single local spot
check. The complete dense tracks and 19 crossings were identical; inference
calls were 2,400 versus 1,200. Both used the same CPU detector settings, 120-second
observation/evaluation targets and video/dashboard exports. Artifacts are
`out/perception-fresh-timing-20260913` and `out/perception-reuse-timing-20260913`.
This is not a repeated, controlled thermal benchmark; upload and separate camera
refinement are excluded. At 129 seconds for 120 seconds of source, the full
export pipeline is still not realtime, despite detector-only throughput above
10 sampled frames/second.

## Verification / demo

- 260 Python tests and 25 JavaScript tests passed after the controller/reuse
  changes, including real SUMO cohort/clearance checks and cache mismatch tests.
- Preflight passed for local model, renderer assets, video tools and SUMO.
- Browser-selected service v2 versus actuated completed a fresh 180-second
  changing-demand experiment: `ui-20260913-154542-img-0635-f2c42871`.
  The 7.6% modelled delay reduction is only that example, not the benchmark gain.
  Its 13-file evidence ZIP matches the final report and identifies both policies.
- A fresh API upload, `ui-20260913-211034-img-0635-1a145c2d`, displayed a loaded
  960×540 preview while still learning the road (before the counting pass).
  Browser cancellation stopped it; no final simulation artifact was created.
  The temporary test tab was closed and the completed comparison restored.

## Next engineering gates

1. **Continuous laptop perception:** resident per-camera worker, bounded latest-
   frame ingestion, explicit dropped-frame/source timestamps, warm/cold startup
   and p50/p95 observation-age measurements; then a one-hour soak. Observation
   reuse removes duplicated file inference but does not implement these pieces.
2. **Control robustness:** reduce tail-delay regressions under heavy demand;
   add longer horizons, nonempty initial queues, turns, varied lane capacities
   and noisy sensing. The used seeds are now development evidence; predeclare
   genuinely new holdouts before evaluating another tuned policy.
3. **Perception evidence:** annotate independent clips for counts, identity
   continuity and road/camera error. Uncalibrated scene estimates remain useful
   demonstrations, not survey-accurate digital twins.
4. **Release and field R&D:** clean-machine packaging, then separately benchmark
   the selected Pi/accelerator and obtain traffic-engineering/pilot review.
   Nothing here authorises or implements roadside signal actuation.
