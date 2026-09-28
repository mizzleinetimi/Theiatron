# Direct upload → fresh detection

14 September 2026 · local demonstrator · branch `codex`

## Workflow

Open `/workbench/live.html`. Choose **New local video**, set duration/cadence,
then **Upload & start detection**. The browser transfers the complete file to
the loopback server and fresh YOLO/ByteTrack inference starts automatically.
This bypasses automatic count-line discovery, full recording export and saved
reconstruction. Startup still includes file transfer, source hashing and, on a
cold worker, model loading. It is not instant or live camera capture.

A detection-only upload is labelled separately in the retained source library.
It is not a completed analysis or validated traffic result. Existing analysed
clips still use their own saved camera/road estimates for the live 3D bridge.
New uploads do not inherit geometry from other footage, even if the filenames
match. Their 3D panel explains that geometry has not yet been prepared.

After stopping detection, choose **Prepare road & saved 3D**. As of 20 September,
this uses an independent recorded-perception pipeline against the retained bytes
(without uploading again). It captures up to 120 seconds, stabilises camera
motion, filters tracks and proposes road geometry without discovering count
lines or running a controller. The saved replay opens after preparation.
Geometry confidence remains independent: usable detections do not guarantee a
recoverable camera plane or a surveyed reconstruction. The full count-analysis
endpoint remains separate and retains its original confidence gate.

## Admission, cancellation and recovery

- A small token-protected reservation request precedes binary upload, so the
  browser has an explicit job ID before bytes move. The reservation occupies
  the single-heavy-job slot. It expires if transfer has not started in 60 seconds.
- Transfer uses a bounded 1 MiB buffer, a required exact Content-Length, a
  4 GiB cap, a 30-second socket timeout and ten-minute transfer deadline.
  Paths are generated server-side and uploads remain outside the public asset
  allowlist. Symlinks, duplicate/chunked framing and unsupported extensions are
  rejected. A valid extension does not prove decodability; the detector reports
  codec/corruption failures and does not manufacture observations.
- Only a complete transfer is published and admitted to inference. Completion
  and detector admission happen under the same lock, so another heavy job
  cannot enter between them. Partial transfer failure never starts inference.
- **Cancel upload** cancels the reserved source; if its transfer just completed,
  the server also stops that source's live session. A different source's session
  is not stopped. Completed bytes remain available; only task-owned partial
  transfers are discarded. This is not a file-deletion feature.
- Reload exposes active upload reservations for cancellation. Server restart
  marks unfinished upload jobs interrupted, not complete. Retained sources can
  be selected again after restart. Network uncertainty is not presented as a
  successful transfer or automatically retried into a duplicate session.
- Raw upload source records are not offered as analysed videos to the old
  workbench and cannot create calibrated/counting profiles merely because the
  file transfer completed.

## Verification checkpoint

- **286 Python + 42 JavaScript tests passed**, including actual HTTP requests,
  upload reservation/body admission, cancellation races, retained-byte recovery,
  private-path safeguards, UI upload progress and the existing simulator suite.
- Browser-selected `videos/intersection.mp4` uploaded directly as
  `ui-20260914-173858-intersection-8a151899`. Fresh detection automatically ran
  in `live-20260914-173858-e3057fe0`; no analysis pipeline ran during upload.
  The 30-second session completed with a 78 ms histogram p95 and zero
  over-300 ms observations. This is a short local spot check, not a guarantee.
- Reload preserved the detection-only source and correctly labelled the saved
  final preview. The 3D panel explicitly reported missing estimates rather than
  displaying another junction. **Prepare road & saved 3D** successfully handed
  the same retained file to analysis `ui-20260914-173948-intersection-96da32a9`.
  That analysis then **failed its existing calibration-confidence gate** after
  72.7 seconds: 118 observed tracks, 44 moving tracks, but only two tracks in the
  weakest inferred corridor. No completed reconstruction was claimed. The
  uploaded bytes and successful direct-detection report remain intact. This
  exposes a remaining coupling: the full road/replay pipeline is blocked by
  count-line/approach confidence even when basic detection works.
- The earlier one-hour soak completed with 29,679 observations and intact
  evidence accounting, but 780 missed 300 ms deadlines and the maximum age
  reached 5.94 seconds. See the [soak result](live-3d-bridge-2026-09-14.md).

## Remaining boundaries

Online camera/road estimation, actual camera timestamp/disconnect validation,
ground-truth counts/queues and live observation windows feeding SUMO remain
separate work. The investor workflow can now accept a new local clip directly
for fresh perception; it still requires the longer analysis step to prepare its
road reconstruction. No Raspberry Pi performance or roadside actuation claim.
The geometry/count-line separation is now implemented. See
[the independent reconstruction checkpoint](independent-reconstruction-2026-09-20.md).
