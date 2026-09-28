# Independent recorded reconstruction

20 September 2026 · local software demonstrator · branch `codex`

## What changed

The live-upload screen now offers an independent **Prepare road & saved 3D**
pipeline. It reuses retained source bytes, runs fresh YOLO/ByteTrack observations
at a nominal 10 source FPS for up to 120 seconds, saves annotated H.264 footage
and dense raw tracks, then attempts camera registration and road/ground-plane
estimation. No arrival extractor, controller or SUMO simulation runs here.

This removes the previous requirement for a confident set of count lines before
recorded visual reconstruction can begin. It does not weaken the existing
counting gate or guarantee successful geometric calibration on arbitrary clips.

## Evidence boundary

- A distinct `reconstruction` job owns a checksummed
  `reconstruction-source.json`, source SHA, detector/model/code provenance,
  native cadence, frame count, and hashes for tracks, reference plate and video.
- This pipeline creates no `simulation.json`, arrival events or savings report.
  All dense tracks are uncounted. The simulation loader rejects visual artifacts.
- Visual sources can be refined and used for fresh detection, but cannot create
  counting or experiment profiles. Replay links return to live detection rather
  than offering an unsupported A/B comparison.
- Geometry completion is separate from observation completion. The job reports
  `geometry_ready: false` when a road and ground-plane estimate are unavailable.
  Saved detections remain accessible; no sample road is substituted.
- Camera registration remains an exact-frame, quality-gated estimate. Physical
  dimensions and ground accuracy are unvalidated even when estimation succeeds.

## Operator flow

1. Open `/workbench/live.html`, choose or upload a clip, and stop any active
   detection session.
2. Choose **Prepare road & saved 3D**. Progress survives page reload; preparation
   can be cancelled. The server admits only one heavy job at a time.
3. On completion, inspect the road outline, camera-perspective status and raw
   versus filtered tracks in the recorded studio. Orbit, pan and zoom are
   visualization controls, not proof of recovered physical geometry.
4. Use **Run fresh detection** to return to the live lab. Live 3D
   requires accepted source-specific ground and exact-frame camera estimates;
   detection remains available if either is missing.

This is offline preparation followed by saved replay or fresh paced-file
inference, not instant online reconstruction, a physical camera connection or
a Raspberry Pi performance result.

## Verification

- Full Python suite: 294 passing tests; full JavaScript suite: 45 passing tests.
- New UI regression tests cover the independent endpoint, progress after reload,
  cancellation/failure, and navigation to replay rather than the presenter.
- Existing counting-quality regression still rejects a high-score configuration
  whose weakest corridor has only two tracks.
- A browser-initiated test of the previously rejected `intersection.mp4` is
  recorded as `ui-20260920-190946-intersection-56e8bdae`. This is a new visual job;
  the earlier failed counting analysis remains failed and unchanged.
- This new capture contains 1,198 processed frames (119.9198 source seconds),
  118 tracker fragments and 6,849 raw observations. These are not unique-vehicle
  counts. All tracks have no arrival assignment and no simulation artifact was
  generated. Source and asset hashes were verified independently after capture.
- Initial end-to-end preparation took 400.5 seconds on this Mac, including
  fresh detection, encoding and independent registration of 1,198 frames.
  Concurrent tests ran during part of the job; this is not a clean benchmark.
- Camera registration accepted all 1,198 frames, with a median fitted residual
  of 0.914 pixels. That is fit residual, not measured vehicle/road accuracy.
- The first run exposed another coupling: a generic trapezoidal starter mapping
  pushed a correctly bounded image outline beyond the viewer's 500 m guard.
  Unknown cameras now start with a uniform image-plane preview, not an invented
  horizon. No road outline is invented. Refreshing refinement reused the verified
  registration cache and produced a 52-vertex appearance-based road candidate.
- This overhead clip still fails the camera-plane estimator's scene-direction
  support requirement. The saved viewer renders cars/road with orbit and playback,
  prominently labelled **UNRECTIFIED PREVIEW · physical road shape unresolved**.
  It does not undo perspective or establish physical scale. `geometry_ready`
  remains false and the live 3D bridge rejects this mapping. Fresh 2D detection
  remains available. More general ground-plane recovery is still unfinished.
- Fresh-detection handoff also completed on the visual-only source:
  `live-20260920-191907-39552d8e`, 30.12 seconds, 298 observations, recent
  throughput 9.98 FPS, 56 ms histogram p95 observation age, no over-300 ms
  observations, no overwritten or stale-rejected frames. This short paced-file
  Mac spot check is not a real-camera or Raspberry Pi reliability claim.
