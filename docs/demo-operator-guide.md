# Theiatron investor demo — operator guide

Updated 14 September 2026 · local software demonstrator · branch `codex`

Latest update: service-v2/actuated selection, locked synthetic controller
evaluation, and single-inference file processing are now implemented. The local
IMG_0635 timing pair was 172 → 129 seconds with identical tracks/counts; this
remains file processing, not realtime camera operation. Full details and the
remaining gates are in the [controller/perception milestone](controller-perception-milestone-2026-09-13.md).

## Start

On this configured Mac, double-click **Start Demo.command**. Keep its terminal
open and follow `http://127.0.0.1:8766/workbench/demo.html`. Alternatively:

```bash
.venv/bin/python scripts/preflight.py
.venv/bin/python launcher_server.py --port 8766
```

Expand the browser for the side-by-side desktop view. A narrow pane stacks the
simulations. All renderer/model assets are local; no CDN is required. Installation
on another machine has not been verified. Run preflight before going offline.

## Three-minute presentation

1. **Observe.** Select an analysed local clip to show its saved detection video.
   To demonstrate fresh work, choose **Analyse new footage**: upload goes to the
   loopback service, then fresh detection previews appear as processing proceeds.
   The file pipeline infers each sampled frame once, then reuses its observations
   after learning count lines; video decoding and export still take time.
   It is not instantaneous or a live camera feed. Processing opens reconstruction
   automatically on completion. Cancellation and errors are visible.
   For fresh inference at source speed without the full export pipeline, open
   **Continuous detection lab**. Choose a retained clip and press **Start fresh
   detection**; show boxes and measured latency. Stop the session before starting
   a SUMO/file-processing job. The lab now shows fresh vehicle positions in an
   adjustable Three.js view alongside the detection preview. For IMG_0635 choose
   **10 FPS** to match its saved camera estimates. The road and camera transforms
   are reused from that exact clip; vehicle tracks are fresh. Missing/rejected
   camera frames or stale observations hide cars. This is not online geometry
   recovery from an arbitrary camera. See the [live 3D bridge notes](live-3d-bridge-2026-09-14.md).
   To try a new clip immediately, choose **New local video → Upload & start
   detection** in the live lab. This skips the full analysis stage, but transfer
   and detector startup still take time. A new detection-only upload has no road
   estimate yet. Stop it, then choose **Prepare road & saved 3D** to reuse those
   uploaded bytes in the independent visual reconstruction pipeline. Counting
   calibration is not required. Progress survives reload and can be cancelled;
   the recorded studio opens on completion. Check its perspective/road status:
   observation completion is not a guarantee of recovered physical geometry.
2. **Reconstruct.** Orbit the source-specific Three.js road and vehicles. Use the
   video and ground-grid controls to explain perspective correction. Automatic
   refinement runs when missing/stale; no measured site calibration is required
   to view estimates. A weak camera estimate may still need review. The source
   outline is not a surveyed boundary or a complete lane network.
   For overhead clips, the estimator can try two road-line families without
   upright building edges. It assumes those directions are perpendicular and
   rejects estimates that change too much when their supporting lines are
   perturbed. **UNRECTIFIED PREVIEW** means physical road shape is still unresolved;
   do not describe it as perspective-corrected. The current `intersection.mp4`
   remains in that state. See the [21 September checkpoint](road-camera-fallback-2026-09-21.md).
   Refinement now also tries repeated road-line evidence across up to 12 registered
   frames, with separate earlier/later checks. The panel reports sampled frames
   and persistent segments, not a road-accuracy percentage. This fallback still
   rejects the current overhead clip. See [multi-frame evidence](temporal-road-evidence-2026-09-22.md).
   **Guided fallback:** in **Review road**, choose **Mark four direction lines**.
   Select two real-world parallel ground edges for A, and two for a perpendicular
   direction B (eight endpoints). **Check & preview in 3D** rejects sensitive fits
   and otherwise opens an explicitly unsaved assisted preview. Adjust, discard,
   or explicitly save. No measured distances are required, but physical scale
   remains assumed and selected lines must actually follow the stated geometry.
   See [guided perspective](guided-perspective-2026-09-22.md). After explicitly
   saving, let the source-bound refinement finish, then choose **Try fresh
   detection**. The live bridge now uses the saved assisted projection and road
   intact, even when automatic perspective is unresolved. It still requires
   usable native-frame camera registration. The live panel labels assisted vs
   automatic estimates, and reports the prepared cadence; use its matching FPS
   setting. A new session reloads geometry; **Reload road** explicitly refreshes
   it within a session. No preview or ordinary manual draft counts as assisted
   evidence. Physical scale and accuracy remain unvalidated. See
   [the assisted live bridge](assisted-live-bridge-2026-09-24.md).
3. **Experiment.** Choose recorded crossings or generated changing/balanced/heavy
   traffic. Select **Service v2** or legacy **Pressure v1**, and a **Fixed timing**
   or **Actuated** baseline. Click **Compute new comparison**. This starts two real SUMO worlds,
   not a retimed saved animation. Both receive identical routes, departures and
   seed. Default pacing presents 180 simulated seconds over roughly 30 wall
   seconds plus startup. Unpaced local rehearsal runs took about 5–6 seconds.
4. **Evidence.** Explain observed vs estimated vs computed inputs. Show mean
   stopped-plus-insertion delay, queues, finished vehicles and pending entry.
   Download the evidence ZIP, including network, routes, traces, source-event
   snapshot, reports and hashes. Raw footage is excluded.

The headline is the **final** experiment result; playback tiles follow the
selected replay time. Completed experiments open at their final state. Press
**Play saved replay** to replay from the beginning. Drag to orbit, right-drag to
pan, scroll to zoom; **Reset 3D views** restores the paired overview.

## What to say

“Theiatron turns camera footage into traffic observations and an estimated
reconstruction. We can test alternative signal decisions in a reproducible
simulator. This demonstration uses hypothetical lane/control assumptions;
funding supports validation, stronger control policies and edge deployment.”

Avoid “45% proven savings”, “any video gives an accurate digital twin”, “live on
a Raspberry Pi”, or describing an untuned fixed timer as the site's current
operation. A positive synthetic result is an example within its stated model,
not proof of general improvement. Retain and disclose negative cases too.

## Recovery / fallback

- **Already analysed footage:** choose its saved run; no inference is needed for
  playback. **Geometry, assumptions & saved experiments** opens previous SUMO
  experiments. Saved playback is explicitly labelled.
- **Fresh computation fails:** read the error; use the network editor for
  ambiguous arm directions. No unrelated sample layout is silently substituted.
- **Another worker is active:** finish/cancel it in the workbench. The service
  intentionally admits one heavy task at a time, including refinement.
- **Live 3D is empty:** check the status under the road. Use 10 FPS for IMG_0635;
  other cadences may not have an exact saved camera frame. If estimates are
  missing/stale, stop continuous detection, refine the clip in the recorded
  studio, then return and choose **Reload road**. Do not substitute another
  clip's mapping. The 3D checkbox pauses visualization without stopping inference.
- **New-upload detection works but road preparation fails:** the full pipeline
  still requires sufficiently supported motion corridors/count lines. A clip can
  be usable for detection but fail this gate. Return to the continuous lab and
  select its detection-only upload; the source has not been deleted. Do not
  describe the failed reconstruction as complete or lower confidence thresholds
  merely to produce a presentation asset.
- **Soak evidence:** the first one-hour run completed; its report is in
  `out/continuous-soak-20260914-bridge/soak.json`. It averaged 8.24 FPS with 780
  over-300 ms observations and a 5.94-second worst case. This proves sustained
  lifecycle operation under shared laptop load, not a realtime latency guarantee.
  For future soaks, **Stop session** is safe but ends the test early.
- **Server restarts:** reload the page to renew the session token. Interrupted
  jobs are not labelled complete; completed artifacts remain available.
- **New video:** use a stable elevated view of a mostly flat road, enough visible
  motion, and a supported local video format. Crops, occlusion, camera movement,
  non-orthogonal buildings or sloped roads can defeat automatic estimates.
- **Another laptop:** do not assume copying the folder is sufficient. Install
  dependencies and native SUMO requirements, retain the local model/assets, and
  run preflight and a full rehearsal before presenting.

## Earlier presenter verification (pressure v1)

Final browser verification on 13 September: streamed simulator states,
cancellation with no final result, cancelled-run deep-link recovery, completed
replay reload, and matching evidence ZIP. The fresh-upload source is
`ui-20260912-162811-img-0635-ddba8b2c`; its final balanced-demand example is
`ui-20260913-151030-img-0635-851c6a23` (17.43% less modelled delay in that one
synthetic experiment, not a field result). The broader rehearsal results below
remain visible and include worse outcomes.

- 248 Python and 24 JavaScript regression tests passed at this milestone.
- Ten consecutive fresh API simulation/export rehearsals passed: one observed
  case and nine generated cases (three patterns × seeds 42–44). All account for
  their intended population; all ZIPs contained the matching final report.
- Direct presenter upload of the retained IMG_0635 clip completed fresh inference
  in 134.6 seconds, retaining 19 crossings and 157 track fragments. It opened its
  own studio and completed automatic camera/road refinement without a manual
  calibration step. This is a file-workflow measurement on this Mac, not a Pi or
  live-camera latency benchmark.
- The nine generated outcomes range from **20.08% more** to **30.75% less**
  modelled delay. Three improved and six worsened. This is a software rehearsal,
  not held-out evaluation; the legacy policy does not consistently outperform
  the fixed comparator.

Repeat the non-cherry-picked rehearsal with:

```bash
.venv/bin/python scripts/rehearse_demo.py \
  --source ui-20260911-091101-img-0635-07326ab0 --count 10
```

This creates new immutable experiments. It does not edit raw observations or
select only favourable outcomes. The reports remain in the saved-run library.

## Remaining R&D, not demo blockers

See [the 13 September controller/perception milestone](controller-perception-milestone-2026-09-13.md)
for the new development/held-out-seed benchmark and same-run inference reuse.
Synthetic tuned/actuated comparators are now available; representative real-site
baselines are still needed. Validated geometry/counts/turns, stronger control
under saturation, independent periods/sites, warm live-camera ingestion,
Pi throughput/latency benchmarks, clean-machine packaging, traffic-engineering
review and deployment/licensing/privacy approvals remain separate milestones.
