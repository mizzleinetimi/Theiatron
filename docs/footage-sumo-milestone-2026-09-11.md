# Footage-linked SUMO draft milestone

11 September 2026 · branch `codex` · local research software, not a reviewed site twin

This extends M3/M4/M6 with a usable commissioning skeleton. It does not complete
site commissioning, empirical evaluation, a live camera service or investor release.

## Delivered

From a completed video analysis, the workbench can now create a versioned network
hypothesis. It displays the source plate and immutable count lines beside an
editable road sketch. Users can change assumed endpoints, lane count/width,
speed, traffic side, exit assignments and signal timings, then run stock SUMO.

Two independent worlds receive the same recorded arrival IDs and timestamps,
network and routes. No observed demand is multiplied, no missing approaches are
filled with synthetic cars, and an unknown exit blocks computation. A source with
arrivals cannot be silently disabled. The two policies use exclusive stages per
incoming approach, with shared minimum/maximum green and clearance durations.
These are hypothetical software timing rules, not a reviewed field signal plan.

The source artifact/video fingerprints and observations are sealed into the
profile. Edits produce a new revision; existing runs retain their exact profile.
The evidence bundle adds `site-profile.json` and `source-observations.json`.
Rendering uses actual SUMO network geometry, vehicle positions and signal states,
not the old sample layout or a camera-path animation.

Profiles remain `draft-unreviewed`; the API cannot remove that status or the
limitations. Acknowledging assumptions permits an experiment, not a review signoff.
Draft results have `impact_status: not-validated` and no reduction percentage.
Absolute delay and vehicle accounting remain visible for inspection.

## Tested local clip and demo

We retain `IMG_0635.MOV` locally under `out/uploads/`, plus the bundled sample
videos. The latest completed perception run is
`ui-20260910-224633-img-0635-8b41c71f`. Its 120.0552-second analysis contains
**19 recorded arrivals: 13 north, 6 south, 0 east, 0 west**. These are detector
labels, not compass bearings; both populated detectors belong to the original
NS phase. No claim of complete traffic coverage follows from these counts.

Browser-created integration run:

- Run: `ui-20260911-042105-img-0635-e30ff9d0`
- Profile: `7bd457014dc5fb3caccdf94d21f027d041991f37a7c85cc2e139e2497b79966b`
- Source artifact: `24002d7f00b80c73046fd9a6a020c8e8100a3ed25df62374257f842121d663f7`
- SUMO artifact: `76e921b106202c10582d0cbba13c2725f0ba8e8b8d8c8396a6ed34b7dbc82f9a`
- Both worlds account for all 19 arrivals; no collisions, emergency stops or
  teleports. Final replay, streamed metrics and trip-output report agree.
- 121-second simulation horizon, with a disclosed 0.9448-second tail after the
  source window. Saved replay is labelled as replay.
- The camera-direction seed and most-opposite exits were used as **explicit
  test assumptions**, not observations or a claim of physical road topology.
- The sample is **inconclusive**. In particular, the four-stage fixed comparator
  spends time on two zero-count candidate arms. Its apparent disadvantage is not
  evidence that this intervention improves the filmed junction.

Open `/workbench/?compare=ui-20260911-042105-img-0635-e30ff9d0`. Use **Play saved
replay** to inspect this completed run, or **Inspect / edit source profile** to
change assumptions and start fresh computation. Selecting a video and creating a
draft uses that video's own saved analysis, with no sample substitution.

## Limits and next gate

Supported draft inputs: 2–4 enabled approaches, 30–300 source seconds, up to
5,000 recorded arrivals, one assumed exit per incoming approach, 1–3 lanes and
bounded speeds/geometry/timings. Arms closer than 25 degrees require sketch
revision before computation. An arrival exactly at the end of an integer source
window receives a further simulation step rather than disappearing from the
population. SUMO time quantisation remains separate from exact source timestamps.

Still required before a defensible site demonstration:

1. Manually validate this clip's count lines/counts and physical approach mapping.
   Obtain a longer, stable, permissioned segment covering competing movements.
2. Establish metric camera mapping, surveyed/inferred-with-uncertainty road geometry,
   legal turn movements, initial queues and vehicle classes. The count-line
   correction workflow below helps commissioning but does not establish accuracy.
3. Replace one-exit assumptions with measured movement demand, and use the actual
   intervention/baseline question. Have stages and clearances independently
   reviewed; add/tune a representative actuated comparator.
4. Freeze a held-out evaluation protocol and test perception/queue error,
   initial-state and routing sensitivity, adverse results and additional sites.
5. Build warm perception/camera ingestion separately. This change reuses a
   completed file analysis; it is not realtime video-to-SUMO streaming or a Pi
   throughput benchmark.

Tests cover immutable revisions, malformed network edits, checksum tampering,
missing routes, no-demand-scaling, source horizon/cohort preservation, original
phase coverage, clearance transitions and HTTP admission/acknowledgement. Real
SUMO integration checks also exercise custom two-, three- and four-arm layouts.

Verification: **144 Python tests and 6 Node tests pass** in the local environment,
with real SUMO required. Browser checks exercised creation from the retained
clip, explicit exit assumptions, fresh paired computation, saved playback,
profile deep-link reload and consecutive edits/saves without changing the
completed run's profile. Remote CI and another machine were not tested here.

## Follow-on: browser count-line editing and local re-analysis

The Watch view now exposes **Edit count lines / recount local clip** for completed
video runs. Select a detector and place its two line endpoints and approach-side
marker on the source image, or edit the numeric coordinates. Candidate NS/EW
grouping is editable; existing ROI polygons are displayed and retained. The
editor does not label a physical junction, certify a signal stage or mark counts
as human ground truth. Count-line bounds, length and off-line side markers are
validated before starting.

Re-analysis creates an immutable camera revision and a new video job using only
the known job's retained upload. Arbitrary client paths, missing raw files and
symlinks are rejected. The worker verifies the source hash, instantiates a fresh
detector/tracker, processes the same window from the beginning, and emits fresh
previews, counts, canonical simulation, media and replay. It skips automatic
commissioning, not inference. File/model/code changes during processing fail
the run; the original analysis and any SUMO profiles remain untouched.

Browser test `ui-20260911-043720-img-0635-17efa6a7` changed the north count-line
start X from 936 to 937 **solely as an integration test**, not a validated
calibration correction. Its camera revision is
`45e7d9f6de01e5bad64c1d991faf5cba26eb357b8a869318a35babc46f33a446`.
It processed **1,200 fresh frames / 120.0552 source seconds**, retained 19 events,
and completed in **71.2 seconds wall time** including startup/export. This one
local file measurement is not a camera latency, steady-state or Pi benchmark.
The source still has no counted competing-phase traffic; review remains needed.

This workflow supports full-file analysis windows only, not unseen/offset
evaluation segments. It is a local commissioning tool: warm camera ingestion,
annotated validation data, measured turns and reviewed metric geometry remain
separate work. Re-analysis results can create their own new footage-linked SUMO
draft through the existing button.

Follow-on verification: **160 Python tests and 6 Node tests pass**, including
real SUMO. Additional tests cover edited geometry affecting newly inferred
counts, new tracker creation, original-artifact preservation, missing/changed
footage, request authorization and retained-upload path restrictions. The fresh
recount artifact is
`7aa4e1d584f195526ca15fddfb2a7f5a4d284269a76ef1450ffb6c52723a9eb9`.
