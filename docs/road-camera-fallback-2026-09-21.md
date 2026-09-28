# Road-direction camera recovery and performance checkpoint

21 September 2026 · local software demonstrator · branch `codex`

## Delivered

Ground-plane estimation now has a fallback for views without enough upright
building edges. The existing three-direction scene estimator remains primary.
When it cannot produce a camera, the fallback searches for two distinct road-line
families inside the source-specific road candidate, excluding detected vehicles.
It does not divide lines by their angle on screen, so diagonal overhead views
and camera roll can be considered.

The two road directions are **assumed to be perpendicular**, with parallel lines
within each family. A pinhole camera with square pixels and a centred principal
point is also assumed. This is not a surveyed calibration, semantic lane detector
or guarantee that a junction is actually perpendicular. Absolute scale remains
assumed; the projection does not establish measured metres or speeds.

Candidate checks require enough distributed line support, a usable focal length,
a safe horizon, agreement among similarly supported competing models, and stable
road shape under line resampling. The sensitivity check performs 64 trials with
resampled lines and 0.5-pixel endpoint perturbations. At least 52 must remain
supported, with normalized shape-error p95 no greater than 0.08. Shape is compared
after translation, uniform scale and rotation only; an affine fit cannot hide
aspect or perspective errors. These thresholds are engineering gates, not a
statistical accuracy guarantee or independently validated error bound.

The viewer identifies road-line estimates and their assumptions. Failed estimates
explain why perspective correction was withheld. It continues to show an
explicitly labelled image-plane preview, never another video's camera geometry.

## Current footage: still unresolved

Run: `ui-20260920-190946-intersection-56e8bdae` (`intersection.mp4`).

- The primary estimator lacks sufficient scene-direction support.
- The new fallback found 64 eligible road segments but failed its sensitivity
  gate: only **18 of 64 trials** remained supported; normalized shape-error p95
  was **0.2496** among those supported trials.
- No ground projection was applied. The recorded studio still displays
  **UNRECTIFIED PREVIEW · physical road shape unresolved**. Fresh 2D detection
  remains available; the live 3D bridge cannot treat this as recovered geometry.
- Its full source-bound registration cache remains in use. The raw observations,
  detection-only provenance and separation from traffic/savings evidence remain
  unchanged.

The previous IMG_0635 source was refreshed as a regression check. Synthetic tests
cover a 55-degree overhead camera, camera roll, missing or vehicle-masked road
evidence, a single line family and noisy endpoints. Success on these synthetic
images does **not** establish arbitrary-footage or field accuracy.

## Performance experiment: not deployed

An experimental smaller feature search was compared with the unchanged full
registration method on the same 24 frames from each of two retained clips.
Execution order alternated, masks were identical, and all 24 frame fits were
accepted by both methods for each clip. The experiment was moved to
`scripts/registration_candidate.py`; production does not import it.

Final paired report: `out/registration-benchmark-20260921-final.json`.

| Source | Full search | Experimental search | Ratio | Maximum projection disagreement |
| --- | ---: | ---: | ---: | ---: |
| intersection.mp4 | 2.815 s | 1.045 s | 2.69× | 10.85 px |
| IMG_0635.mov | 2.202 s | 0.920 s | 2.39× | 10.82 px |

Times cover registration calls on the selected decoded frames, excluding decode,
reference setup, detection, encoding and road estimation. Disagreement is measured
at 15 image probes against the full method, **not against ground truth**. Similar
fit residuals and acceptance counts did not prevent materially different
projections. Therefore the speed candidate was **rejected for production**, and
this milestone makes no new end-to-end speed claim.

Production `theiatron/camera_registration.py` is unchanged from before this
experiment (SHA-256
`04d046f53322c887bc0fac6c4469d647587fc93f4a26dfd62f335055941d47dd`).
The benchmark records source bindings, implementation hashes, frame-level results
and `production_enabled: false`. It refuses to overwrite an existing report:

```bash
.venv/bin/python scripts/benchmark_registration.py \
  --run ui-20260920-190946-intersection-56e8bdae \
  --run ui-20260912-162811-img-0635-ddba8b2c \
  --samples 24 --out out/registration-benchmark-new.json
```

## Verification and next work

- Full Python suite: **306 passed**. JavaScript suite: **45 passed**.
- Refreshed source-bound estimates for the overhead clip and IMG_0635, reusing
  the verified full-registration caches rather than regenerating detections.
- Recorded studio checked in the browser with the current clip, rejection reason,
  source video and interactive road/vehicle view.

The next geometry milestone is better evidence across multiple registered views
or an explicit, minimal operator-supplied direction reference when automatic
evidence is ambiguous. Any manual assistance must stay visibly identified.
The next performance milestone needs an independent reprojection check before a
faster matcher can replace the full one. Neither should be presented as complete
until held-out footage supports it. Camera ingestion, Raspberry Pi benchmarks and
measured physical accuracy remain separate unfinished work.
