# Workbench / stock-SUMO integration milestone

Implemented 10 September; handoff checks 11 September 2026 · branch `codex` · local R&D software, not a field release

Subsequent milestone: [footage-linked SUMO drafts](footage-sumo-milestone-2026-09-11.md)
now connect retained observations to editable, explicitly unreviewed networks.
The implementation and test counts below describe the earlier fixture milestone.

## Delivered scope

This implements the first engineering slice of the remaining plan: parts of
M2 (local service integrity), the synthetic-fixture portion of M4, and initial
M5/M6 (progressive preview and Watch / Compare / Evidence). It does **not** mark
M1–M8 complete or turn arbitrary footage into a validated digital twin.

### Local application

`launcher_server.py` now opens `/workbench/`. Its three views expose:

- **Watch:** native video selection/upload, real detection previews during
  commissioning and evaluation, source time, time since last published preview,
  detection/count information and the existing point-queue replay.
- **Compare:** two independent stock-SUMO processes, matched metric geometry,
  actual front-bumper positions converted to vehicle centres, actual signal
  state and separate own-world queue observations. Top-down is the default;
  perspective is selectable with no auto-orbit. Different scenario inputs
  start different computations. Saved playback is labelled separately.
- **Evidence:** absolute metrics, common population and horizon, per-approach
  accounting, model assumptions, diagnostics, seed/timings and downloadable
  report/network/demand/trajectory/trip-output files with SHA-256 checksums.

The older `/launcher/` video interface and `/viz/` point-queue replays remain
available. They are not relabelled as SUMO.

### Simulator contract

Stock Eclipse SUMO, TraCI and sumolib are pinned to **1.27.1** in the optional
requirements. No SUMO fork or game engine is used.

- `theiatron/sumo_demo.py` generates a **synthetic** metric four-arm network
  using `netconvert`, with straight movements, one lane in each direction,
  right-hand traffic, homogeneous cars and deterministic driver behaviour.
- Explicit seeded demand is serialized once and shared by fixed and adaptive
  worlds. Their traffic states are independent. The pressure policy consumes
  `PhaseObservation` values, not fabricated `PointQueue` instances.
- Both policies pass through the same two-phase green/yellow/all-red software
  state machine. These are **simulation constraints**, not certified roadside
  safety assurances. There is no actuation interface.
- Simulation steps are 0.5 seconds. Browser updates poll the latest state;
  current rendering is discrete snapshot playback, not a 60 FPS interpolated
  trajectory renderer. Requested computation pace is separate from replay pace.
- At termination, canonical SUMO trip output is checked against streamed
  metrics. Missing/duplicated vehicles or disagreement fail the run.
- All intended departures before the common horizon stay in the population:
  completed + active + pending insertion = intended. Pending vehicles accrue
  insertion delay; unfinished trips are censored at the horizon.
- Primary delay is **stopped waiting + insertion delay to date**, not travel
  time, SUMO timeLoss, completed-trip-only waiting or observed real savings.
  p95 uses nearest rank across the common intended-demand population.
- Teleports, collisions and emergency stops are recorded and suppress a valid
  comparison if present. A negative policy result is not a software failure.
- `--verify` checks report/file hashes. A repeated experiment reproduces
  metrics, routes, network and trajectory frames on the tested environment.
  Whole-bundle IDs can differ because raw simulator logs contain execution
  context. Checksums prove consistency, not empirical accuracy.

### Service integrity

- Loopback bind only; explicit static/run asset paths; no directory listings,
  `.git`, repository source, raw upload-directory access, traversal or symlinks.
- Host and Origin checks plus a per-launch session token for writes.
- Atomic job reservation **before** reading upload data; one active job for
  this prototype. Upload size/read timeout and worker runtime bounds.
- Durable atomically published job history, bounded logs, explicit cancellation,
  worker process-group cleanup and parent-death watchdogs. Interrupted jobs
  are not restored as completed. A process lock prevents two launchers sharing
  the same job store. This implementation targets macOS/Linux, not Windows.
- Atomic latest-image/state publication; correct byte-range video responses.
- Configuration validation for finite timings, positive lanes/cadence, unique
  approach names, phases and finite nondegenerate count lines.
- Local detector weights are required instead of silently downloading at
  demo time. New video evidence records package versions and code/model hashes.
- Read-only `scripts/preflight.py`, a tested macOS/ARM64 package-version snapshot,
  and a CI workflow requiring real SUMO tests. The snapshot is not a portable
  hash-locked installer, and CI has not been run on a remote runner here.

## Verification

- **118 Python tests pass**, including real SUMO binaries; **6 Node tests pass**.
  Reconfirmed in the project environment on 11 September. A separate minimal
  clean environment initially timed out starting its newly installed macOS
  binaries (including `netconvert` beyond the 60-second window), then passed
  **all 118 tests** on a later run. No OS security verification was bypassed.
  The first-launch/retry experience still needs packaging work; this is not
  proof of a reliable first-run installer on another machine or Linux CI.
- Two identical 60-second SUMO runs produce byte-identical trajectory frames,
  demand and network, identical metrics and diagnostic results. Final replay,
  latest frame and report metrics agree exactly.
- Actual signal timelines pass minimum-green / yellow / all-red transition
  checks; evidence tampering and missing trip-output vehicles fail closed.
- HTTP tests cover private assets, HEAD, ranges, symlinks, traversal, Host/Origin,
  missing tokens, malformed scenario settings, simultaneous admission, upload
  cancellation, process stopping and interrupted-job recovery.
- A 180-second heavy-demand/2× manual check accounts for **355** intended cars.
  Fixed: 162 completed / 74 active / 119 pending. Adaptive: 126 / 77 / 152.
  No collisions, emergency stops or teleports occurred. This is a deliberately
  retained negative result, not a claim of operational performance.
- Browser checks exercised creation of a fresh 180-second SUMO experiment,
  actual rendered state, saved-job restoration and perspective switching.
  `IMG_0635.MOV` was selected through the native picker: fresh tracked frames,
  source time and age appeared while inference was running. Cancellation
  stopped its worker and remained cancelled after reload.
- The final stable-code `IMG_0635.MOV` test then completed in **137.1 seconds**
  (upload excluded), including up to 120 source seconds of commissioning,
  another 120-source-second inference pass and export. This is one cold/file
  processing measurement, not a steady-state realtime or Pi benchmark.
  Its 19 events are all on the NS phase, so the sample remains **inconclusive**.
  The exact replay reproduces `simulation.json` byte for byte, artifact
  `24002d7f00b80c73046fd9a6a020c8e8100a3ed25df62374257f842121d663f7`.

## What remains before the investor release

1. **M1/M3: scope and real-site commissioning.** Choose the initial buyer and
   deployment market, the exact intervention, and one permissioned junction.
   Review metric lanes, turns, signal stages/clearances, camera mapping, counting
   zones and initial queues. The synthetic right-hand-traffic fixture is not
   a UK junction. Uploading footage does not fill these missing facts.
2. **M4/M7: meaningful control comparison.** Connect reviewed observed demand
   to the real network; implement/tune representative fixed and actuated
   comparators; freeze held-out periods and paired seeds. Inspect the queue-only
   policy's behaviour when approaching vehicles are moving but not yet queued.
   Do not tune until one attractive percentage appears or hide negative cases.
3. **M5: actual live service.** Saved profiles, a persistent warm detector,
   bounded capture/inference queues, source timestamps, RTSP/camera ingestion,
   dropout handling and measured latency/throughput. The current upload flow
   still commissions and then reprocesses a file; previews do not make it a
   field-ready realtime camera system.
4. **M6/M8: release product.** Browser commissioning/review, smoother synchronized
   trajectory playback, report bundle export, fully pinned/hash-checked install,
   storage limits/retention, log/privacy handling, device-independent rehearsal,
   offline package/licensing review and ten end-to-end rehearsals. Job history
   is retained locally; it does not automatically erase uploaded footage.
5. **M9 onward:** actual Pi measurements, read-only outdoor shadowing, approved
   controller-in-loop work and supervised trials. Nothing here authorizes or
   implements public-road control.

The next substantive gate is **one reviewed real junction with observed
turning demand**, alongside the baseline/measurement protocol. The laboratory
now provides a working place to test that integration and expose its failures.

## Technical references used

- [Official SUMO downloads / Python distribution](https://eclipse.dev/sumo/docs/Downloads.html)
- [Python TraCI connections](https://sumo.dlr.de/docs/TraCI/Interfacing_TraCI_from_Python.html)
- [Vehicle positions, headings and waiting-time retrieval](https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html)
- [SUMO trip output and unfinished vehicles](https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html)
