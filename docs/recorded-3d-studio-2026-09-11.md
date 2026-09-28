# Recorded junction studio — 11 September 2026

## Delivered

Open `http://127.0.0.1:8766/workbench/replay.html?video=ui-20260911-091101-img-0635-07326ab0`.

This is a separate recorded-observation reconstruction, not the point-queue
counterfactual, and not a SUMO replay relabelled as camera footage.

- Local Three.js renderer with an extruded, automatic or hand-traced road polygon, procedural
  vehicle models, shadows, orbit/pan/zoom, four camera presets and focus mode.
- Vehicle selection, source-image anchor highlighting, go-to-track and follow.
- Video-clock-driven replay with original timestamps, speed control and seeking.
  No queue-based time warping, invented departures or synthetic improvement claim.
- Editable four-point projective ground mapping and road outline. Numeric or
  pointer edits, insert/remove/retrace, undo, source-bound immutable draft saves.
- Calibration is keyed to source artifact, source-video hash, track-file hash and
  plate hash. Unknown cameras start without a hand trace and require commissioning;
  they cannot inherit IMG_0635's road. The initial IMG_0635 trace is explicitly
  bound to its exact source-video SHA, not its filename.
- Automatic offline refinement runs when dense source estimates are missing or
  stale. The refined view is the default, with an immediate raw-view toggle.
  Gaps longer than 0.61 seconds, rejected camera states and flagged jumps are not
  interpolated. No extrapolation outside observed segments. Heading is inferred
  from motion; the offline replay may use later movement to orient a leading
  stop, and holds orientation at stops without freezing vehicle positions.

## Automatic refinement update

- Full 1280×720 ORB background registration to the first analysed frame, excluding
  detected vehicle boxes. RANSAC, spatial coverage, residual and projection bounds
  reject unsupported estimates. Failed states are never replaced with identity
  transforms or bridged. The source-video overlay inverse-projects the refined
  reference-plane anchors back into the moving camera view.
- Robust constant-velocity Kalman / RTS offline smoothing, isolated-spike
  downweighting and explicit segment breaks. Original IDs, timestamps, boxes,
  classes, confidence and counts stay unchanged. No identity stitching or
  invented detections. Synthetic known-path tests cover turns and slow traffic;
  lower image roughness alone does not establish localization accuracy.
- A vehicle-masked, registered temporal median (at most 21 half-resolution
  frames) supplies appearance for the road proposal. Motion-supported GrabCut
  and bounded contour regularization reduce vehicle/pole cut-outs. This is not
  semantic segmentation: occluded road edges are inferred, and the original
  first-frame plate remains the calibration/evidence image. The outline can be
  copied into the editor for review without changing projection anchors.
- Refinement is a cancellable, ten-minute-bounded subprocess with single-worker
  admission, parent watchdog and safe retry ownership. Camera registration has
  a source-bound checksum cache independent of road draft edits; final estimates
  additionally bind the calibration and algorithm code. New full-clip runs retain
  a real first-processed-frame plate. Historical composite plates require recount
  before camera compensation; the UI identifies this limitation.
- This is offline reconstruction work, not the proposed edge real-time pipeline.
  No Raspberry Pi throughput claim is implied.

Actual IMG_0635 result: 1,200 / 1,200 camera frames accepted, all 6,368 observations
retained for refinement; three isolated spikes downweighted and 92 discontinuity
boundaries split. Background reprojection residual median: 0.873 px **on matched
inliers, not independent ground truth**. Estimated road-probe displacement from
the first view: median 37.3 px, maximum 56.9 px. This supports correcting camera
motion but does not measure metric road accuracy.

The filtering second-difference median in the camera-registered image plane is
3.25 → 0.054 px. It is a smoothness diagnostic affected by registration noise,
not an accuracy percentage. The final automatic outline has 38 vertices; its
near-complete motion-seed coverage is not a road-boundary accuracy score.
Vehicle-size perspective fitting remains rejected on this clip: its inferred
horizon is inconsistent with the road. The subsequent
[ground-plane correction](ground-plane-projection-fix-2026-09-11.md) uses independent
static scene vanishing directions instead; the old manual mapping remains available.

## Fresh local inference

Source: retained IMG_0635.mov, SHA
`d589e58a8ab46839b81c1870d43c8b254def8b3ab9d9301384f52cd85497ffa5`.

Run: `ui-20260911-091101-img-0635-07326ab0`.

Parent: `ui-20260911-043720-img-0635-17efa6a7`. Same candidate count lines;
no new upload and no change to earlier analysis artifacts.

The fresh 120.0552-second analysis retains 6,368 detector observations in 157
tracker fragments and preserves the 19 counted arrivals. **157 fragments are not
157 distinct vehicles.** Dense `recorded-tracks.json` preserves every processed
frame's timestamp, track ID, bottom-centre anchor, bounding box, class and
confidence, including stationary observations previously thinned by the legacy
export. The studio selects the dense artifact when present and identifies the
legacy fallback explicitly.

Class models use majority detector class over the recorded track. Nominal sizes:
car 4.5 m, motorcycle 2.1 m, bus 10 m, truck 7.5 m. These are not measured sizes,
and class errors (including SUVs/rickshaws assigned another class) remain possible.
The selected-track panel shows mean detector confidence and class consistency;
neither is an empirical accuracy score. Paint colours are identity aids.

## Validation

Automated tests cover projective corner mapping, degenerate/crossing geometry,
occlusion gaps, deterministic sampling/backward seeking, immutable source-bound
drafts, checksum/path guards, retained dense detection metadata and HTTP write
protection. The existing real-SUMO/core tests remain in the regression suite.
Final local regression: **237 Python tests and 21 Node tests passed**, with stock
SUMO required. Preflight passes with all local viewer and inference assets present.

Browser checks on the narrow in-app panel: source loading, video-clock playback,
camera presets, focus mode, track selection/jump, rejection of a zero-width
calibration, draft save and reload. Also inspected the wider background-tab
layout and missing-source failure. No viewport override was used. No browser
performance or Raspberry Pi FPS claim.

## Accuracy limits and next milestone

This is an inspectable draft planar reconstruction, **not a surveyed digital
twin**. A detector box bottom-centre is not a measured ground-contact centroid.
The initial homography rectangle and 50 m × 12 m scale are assumptions. Road
boundaries are appearance/motion estimates or manual traces. Lane markings,
kerbs, signal positions, building geometry and road elevation have not been
recovered or surveyed. Background camera motion is
now estimated, but parallax, rolling shutter and unmasked motion can remain.

Next work, in order:

1. Establish ground reference measurements and camera calibration; validate
   reprojection with independent points instead of judging by visual alignment.
2. Review detector classes, anchor placement, occlusion gaps and track identity
   switches against the clip. Consider oriented vehicle boxes / contact points
   before treating model footprints or spacing as measurements.
3. Commission lane centre lines, turns and signal geometry on the same calibrated
   ground plane, then build/export a consistent SUMO network. The existing
   footage-linked SUMO draft still uses its separate assumed network.
4. Reuse the scene renderer for synchronized SUMO A/B playback after that geometry
   boundary is established. Do not splice observed and simulated motion or claim
   the recorded studio already validates controller savings.

The unfinished crossing-review module from the earlier roadmap is not integrated
by this milestone; the user's reconstruction-first request superseded that work.
