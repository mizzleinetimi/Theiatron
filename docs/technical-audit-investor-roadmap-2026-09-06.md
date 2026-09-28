# Theiatron: technical audit and investor-demo roadmap

6 September 2026 · branch `codex` · reviewed commit `2a633b3`

## Recommendation

Build a **camera-derived junction analysis and adaptive-control simulation workbench**. Keep the Python perception pipeline and Three.js presentation layer. Add **unmodified, headless Eclipse SUMO through a Python TraCI adapter**. Develop the field perception service as a separate runtime that can later run on a Raspberry Pi. Do not fork SUMO, build a new rendering engine, or start with a custom signal controller board.

The software demonstration should prove four things:

1. New, supported footage is genuinely processed now, with visible detections and measured processing latency.
2. The user can verify the junction configuration and understand what was measured versus assumed.
3. The same demand produces independently simulated vehicle behaviour under a credible baseline and Theiatron, with numbers traceable to the actual simulation.
4. A prospective customer has a reason to use the analysis, and a funded, staged route exists from software to a supervised hardware trial.

This is a credible R&D investment proposition. The current repository is a working research demonstrator, not yet a validated traffic-control product. A stronger scientific and commercial case will help more than increasing the headline percentage or photorealism.

I assume UK investors may fund a Nigeria-first deployment business. Raising money in the UK and selling into UK public-road infrastructure are different strategies. If UK road authorities are the first customers, UK junction design, integration, procurement and assurance become immediate requirements.

## Scope and checks actually performed

Reviewed all first-party Python runtime modules, the runner, launcher, benchmark and utility scripts, all seven test files, YAML configurations, launcher frontend, both Three.js viewer implementations, the marketing site's embedded simulation, and relevant documentation/pitch claims. Third-party vendored Three.js/glTF code, model internals/training data and binary media were not independently audited. This is not a penetration test, a traffic-engineering certification, or a legal opinion.

Preserved the pre-existing untracked `docs/signals-30-days.html`. No product code was changed. This report is the only new tracked-intent document; the smoke run produced additional ignored artifacts under `out/`.

| Check | Result and limitation |
|---|---|
| `.venv/bin/python -m pytest -q` | **46 passed in 2.02 seconds**. Mostly unit tests; not detection-accuracy or roadside-safety validation. |
| JavaScript syntax | `node --check` passed for `viz/app.js`, `viz/twin.js`, `launcher/app.js`. |
| Shell syntax | `bash -n` passed for the launch, live-demo, download, onboarding and installation-watch scripts. |
| Fresh complete pipeline | Reprocessed the retained IMG_0635 upload: full 122-second observation, then fresh 30-second evaluation, headless. Exported report, tracks, video, plate, timeline and a manifest with `three_d.ready: true`. Three arrivals; result correctly inconclusive. Browser interaction was not retested in this audit. |
| Actual evaluation throughput | New smoke run: 300 ticks in 16.9 seconds, manifest **17.75 ticks/s**, approximately 10 sampled video frames/s. Includes evaluation rendering/recording; excludes calibration, model startup, final H.264 conversion and 3D export. |
| Short perception microcheck | Apple M2, CPU, YOLO26n, input size 640, original intersection clip: 50 warmed decode/resize/detect/track samples, mean **28.8 ms**, p95 **30.4 ms**; model initialization **5.09 s**. Sparse scene, no dashboard or simulation; not a Pi or sustained full-pipeline benchmark. |
| Reproduction | The original 40-arrival event replay reproduces 6.04 s adaptive versus 10.9 s fixed. Recent saved reports and timeline outputs differ slightly; investigated below. |
| Non-default queue test | Invoked the existing exporter with filesystem writes mocked. With saturation headway 4 s and startup loss 5 s, the configured fixed result is **22.28 s**, but the exporter still emits **10.9 s**. Confirmed configuration-loss bug. |
| End-of-run boundary | Event at 1.03 s, replay horizon 1.05 s, step 0.1 s: expected one arrival, actual zero. Confirmed dropped partial final step. |
| Local HTTP check | A temporary launcher on loopback returned 200 for health, launcher and viewer pages. It also returned 200 for `/.git/config`; only response status/type inspected, no file contents exposed in the audit. |
| SUMO integration | No SUMO/TraCI implementation in the first-party application; `sumo` was not available on PATH. No SUMO validation was performed. |

The installed environment reports Ultralytics 8.4.108, Torch 2.13.0, NumPy 2.5.1, OpenCV 4.13.0.92 and ONNX Runtime 1.28.0. The dependency file allows broad version movement and is not a reproducible release lock.

New smoke artifacts: [manifest](/Users/user/theiatron/out/audit-20260906-img0635/manifest.json), [report](/Users/user/theiatron/out/audit-20260906-img0635/report.md), [calibration overlay](/Users/user/theiatron/out/audit-20260906-img0635/calibration.png).

## What is already good

- **The detection is real.** `VehicleDetector` executes YOLO tracking on frames. The launcher does not substitute prepared arrival events for an uploaded video.
- **Useful separation of core logic.** Detection, arrival extraction, policy, phase transitions, queue model and reporting are separate modules. Core tests can run without loading a neural network. Preserve this separation.
- **Several hard-won tracking fixes are present.** One tracker per camera, finite count-line segments, direction checks, minimum track age, shared per-camera claimed IDs, and a new detector for the second inference pass avoid important double-counting/state-reuse errors.
- **Controlled comparison is possible.** Both policies receive the same arrivals; recorded event streams make policy experiments repeatable.
- **The timing state machine is separate from the policy.** Min/max green and clearance sequencing are tested. This is a good software design foundation, although it does not constitute a complete public-road safety system.
- **Unfinished vehicles are not simply discarded from reported waits.** Censored waits are included, and negative outcomes are retained in reports.
- **Run isolation and provenance have begun.** Unique directories, a source hash, saved configuration and run-specific 3D assets address the earlier stale-footage problem.
- **The presentation layer is reusable.** Local assets, recognizable footage, matching vehicle labels, synchronized A/B views and browser controls are useful investor-facing features. A frontend rewrite is unnecessary.
- **There is already a functional workflow.** The fresh audit run confirms the pipeline still reaches generated artifacts in the installed environment.

## Current evidence: what the percentages mean

These are point-queue-model results, not measured roadside travel-time improvements. The runs use different clips, durations and calibrations; they are not independent samples from a controlled benchmark suite.

| Saved run | Duration | Counted arrivals | Fixed mean wait | Adaptive mean wait | Mean-wait reduction |
|---|---:|---:|---:|---:|---:|
| Original `out/report.json` | 180 s | 40 | 10.90 s | 6.04 s | 44.6% |
| `img-0642-final` | 180.1 s | 84 | 24.51 s | 18.27 s | 25.5% |
| `img-0635-final` | 122.3 s | 19 | 13.86 s | 3.92 s | 71.7% |
| `final-e2e-3d` | 70.1 s | 16 | 7.73 s | 10.62 s | **−37.4%**: adaptive worse |

Sources: [original report](/Users/user/theiatron/out/report.json), [IMG_0642 report](/Users/user/theiatron/out/img-0642-final/report.json), [IMG_0635 report](/Users/user/theiatron/out/img-0635-final/report.json), [short-run regression](/Users/user/theiatron/out/final-e2e-3d/report.json).

Important interpretation:

- All 19 counted IMG_0635 arrivals belong to NS: north 13, south 6, east/west zero. Its large percentage is heavily influenced by a baseline spending green time on an empty axis. A four-corridor calibration score does not establish representative two-axis demand.
- The original 40 arrivals are also asymmetric: 18 north, 16 south, three east and three west.
- A diagnostic, **post-hoc** equal-split sweep reduced the original fixed mean from 10.90 s at a 30-second split to 9.16 s at a 12-second split. Against that setting, the apparent adaptive advantage is about 34%, rather than 44.6%. This is sensitivity analysis, not a valid held-out benchmark or a recommended signal timing.
- The adaptive policy was developed with recorded-demand parameter sweeps. Tests that it wins on selected asymmetric demand do not establish generalization.
- Censored average waiting through a short horizon is useful, but it is not completed-trip travel time, full eventual waiting, HCM control delay or a network-wide congestion measure. Served and unfinished counts must accompany it.

**Pitch wording supported today:** “In one 180-second prototype simulation driven by 40 detected arrivals, Theiatron reduced modeled average queue waiting by 44.6% versus an equal 30-second fixed timer. Broader simulation and field validation are the next milestones.”

Rounding that particular result to 45% is reasonable if the scope is visible. Calling it a 45% average across footage, promising it in the field, or pairing another clip's video with that number as though it came from that run is not supported. The earlier pitch direction should be tightened accordingly.

## Prioritized technical findings

P1 below means a release/evidence blocker for the proposed investor product. P2 means important hardening or a blocker before wider/pilot use. Roadside actuation has a separate safety gate and is not authorized by a successful demo.

### P1 — simulation and evidence integrity

**1. The 3D comparison has a different calculation path from the report.**

[Exporter line 218](/Users/user/theiatron/scripts/export_timeline.py:218) passes `QueueConfig()` instead of `app.queue`. It independently reruns both policies at 0.1 s, whereas the fresh-video path uses the sampled feed interval. On IMG_0642 the report says 18.27/24.51 s, while the timeline says 18.23/24.48 s. Non-default queue assumptions produce substantially larger discrepancies, as the audit reproduction demonstrates.

Fix: one canonical simulation execution and metrics stream. The report, dashboard, replay and exports consume its results; the renderer never reruns a traffic model. Until replaced, preserve queue settings, common simulation ticks, event identity and full final-step handling, and add report/export parity tests.

**2. The current model cannot substantiate realistic congestion relief.**

[PointQueue](/Users/user/theiatron/theiatron/sim.py:31) represents an unlimited vertical queue with a fixed discharge rate. There is no spatial storage, car-following, turning conflict, downstream blockage, spillback, pedestrian interaction or network coordination. Auto-generated approaches default to one lane. Cars, trucks and motorcycles lose their different service characteristics when reduced to arrival pairs.

Fix: retain the point queue as an explicitly labeled fast research/sanity-check model. Use a calibrated SUMO junction for investor-facing physical what-if results. Adding SUMO does not by itself validate any result.

**3. Measured line crossings are not automatically independent traffic demand.**

[Arrival extraction](/Users/user/theiatron/theiatron/approach.py:129) counts crossings of image-space lines, without proving that those lines are upstream of signal-controlled queues. Existing stopped vehicles, occluded vehicles and vehicles that never cross within the clip can be absent. A near-stop-line crossing stream can describe discharge under the recorded control policy, rather than free arrivals. Treating it as unaffected demand for a new signal can distort the counterfactual.

Fix: define the network boundary, upstream demand measurement, initial occupancy/queues, travel time from detector to junction, and turning movements. Mark unobservable quantities as assumptions with sensitivity ranges. Do not silently insert a vehicle at an upstream network entrance at the time it was observed crossing a downstream line.

**4. “Pressure” currently uses perfect simulated queue state, not measured roadside queues.**

[AdaptiveController](/Users/user/theiatron/theiatron/controller.py:124) reads `PointQueue` length and accumulated waiting. The camera supplies arrivals; it does not independently estimate the real queue or actual waiting used by this policy. The present policy is also not a full network max-pressure controller: it lacks downstream queues and movement-level pressure.

Fix: introduce an explicit observation interface. Benchmark ideal simulator observations separately from realistic virtual-detector observations, including missed detections, stale updates and limited visibility. The field adapter must estimate queue/presence and demand from its camera, with ground-truth evaluation.

**5. Evaluation and confidence gates are too weak for the claims.**

[Metrics line 90](/Users/user/theiatron/theiatron/metrics.py:90) labels any ten-arrival run “ready.” It does not check phase coverage, representative duration, queue visibility, matched population, uncertainty or calibration validity. [Runner line 785](/Users/user/theiatron/run_demo.py:785) can rewind even when `unseen` was requested if the remaining segment is short. Metadata records the fallback, but an evaluation request should not silently lose its holdout property.

Fix: separate `artifacts_ready`, `calibration_reviewed`, `sample_sufficient`, and `evaluation_valid`. Enforce held-out evaluation or return an explicit unavailable result. Design evaluation by independent site/time windows, not by treating correlated frames or vehicles as independent experimental replicates.

**6. Replay drops arrivals in the final partial step.**

[Engine line 71](/Users/user/theiatron/theiatron/engine.py:71) and [exporter line 223](/Users/user/theiatron/scripts/export_timeline.py:223) floor `duration / dt`. The engine also applies the signal state selected at `now` across the whole preceding `dt` interval. Boundary behaviour and variable-step usage need an explicit contract.

Fix: use a single defined time base, consume the final partial interval, validate monotonic time/events, and test phase-transition boundaries and step-size sensitivity. Advance SUMO on its simulation clock, independently of camera sampling and rendering.

### P1 — calibration, perception and the meaning of 3D

**7. Automatic calibration is a useful proposal, not an unattended site configuration.**

[Auto-calibration](/Users/user/theiatron/theiatron/autocal.py:240) clusters moving entry headings, retains at most four corridors and heuristically groups them into two axes. It does not determine true compass bearings, metric lane geometry, legal turns, actual stop lines or safe stage compatibility. The road mask is chiefly dilated motion evidence; it is not a reconstructed road network.

[Quality scoring](/Users/user/theiatron/run_demo.py:393) rewards corridor count, track count and cluster coverage. It does not measure detection accuracy or validate a signal plan. The fresh IMG_0635 overlay is labeled “good” while multiple learned lines lie across the foreground road; it still needs human interpretation. A representative-frame plate avoids blur but does not correct camera movement during tracking.

Fix: provide guided commissioning: preserve aspect ratio, check camera stability/view quality, review/edit zones and approaches, enter lane/turn information and metric references, confirm the signal plan, save a site profile. Support a narrow set of static elevated views first. Reject camera cuts/moving or unobservable scenes early. Do not promise “any footage.”

**8. No empirical perception-accuracy evidence is checked in.**

[Detector](/Users/user/theiatron/theiatron/detection.py:35) uses general vehicle classes and ByteTrack. Track age, line crossing and IoU suppression help, but are not measurements of recall, false arrivals, ID switches or stationary-queue accuracy. Counting once per tracker ID is not a guarantee of counting once per physical vehicle. Stopped traffic is especially important for this product; moving-track selection alone is insufficient.

Fix: build a permissioned, hand-labeled dataset across relevant views, lighting, occlusion and mixed vehicle types. Start with crossing-event precision/recall, per-movement count error, queue/presence error and latency. Validate models and resolutions against these measures before replacing the tracker or reducing input size. Keep bicycles/pedestrians out of claimed coverage until explicitly supported; the present configured classes omit them.

**9. The 3D vehicles do not respond through microscopic traffic dynamics.**

[Viewer line 554](/Users/user/theiatron/viz/app.js:554) retimes smoothed observed paths using point-queue departure times. Queue positions, spacing and promotion timing are hand-built. [Export geometry](/Users/user/theiatron/scripts/export_timeline.py:101) derives an affine map and arbitrary scene scale, not calibrated metric geometry. [Vehicle models](/Users/user/theiatron/viz/app.js:377) cycle through decorative vehicle types; these are not reliably recovered classes/dimensions.

The pure twin uses the same transform for video and tracks. Visual alignment checks overlay consistency, not independent ground-plane accuracy; the “accuracy proof” wording in [twin.html](/Users/user/theiatron/viz/twin.html:33) should change.

Fix: preserve an explicitly labeled observed-track replay mode. In SUMO mode, render SUMO positions, headings, types, lanes and signals. Build road geometry from the same metric network the simulator runs. Never distort simulation timing to make the two scenarios look better or resemble the source clip.

**10. Three-approach support is inconsistent between calibration and rendering.**

Calibration/tests accept T-junctions. The exporter defaults an uncertain exit to `OPP[approach]`, and [viewer path construction](/Users/user/theiatron/viz/app.js:45) assumes that exit exists in `LANES`. `buildKeyframes` requests this path even when a recorded real path is available. A valid three-arm configuration can therefore lead to a missing-arm exception.

Fix: validate every route against actual available connections and test three-arm export/rendering, missing paths and ambiguous movements. Unsupported routes must be visible to the user, not invented.

### P1/P2 — realtime operation and product reliability

**11. The launcher is a batch video workflow, not a camera streaming product.**

[Runner](/Users/user/theiatron/run_demo.py:643) requires a file and normally performs a long observation pass, rewind, evaluation, encoding and export. [VideoFeed](/Users/user/theiatron/theiatron/feeds.py:14) samples a sequential decoder with FPS-derived time. The legacy multicamera loop uses a nominal common cadence rather than each feed's actual timestamps. There is no capture/inference separation, bounded latest-frame queue, capture-age telemetry, reconnect/watchdog or stale-camera state.

Fix: independent capture, perception, controller and presentation clocks. Preload/warm the model; show detection preview immediately after upload/camera setup; reuse reviewed site configuration on subsequent footage. For live sources process fresh timestamped frames and explicitly drop stale ones. For offline analysis, preserve the chosen event-time sampling policy. “Render at 30–60 FPS,” “infer at 10 FPS,” and “signal decision every second” are separate targets, not interchangeable performance claims.

**12. Continuous operation has unbounded memory and increasing work.**

[TrackRecorder](/Users/user/theiatron/theiatron/approach.py:32) caps points per ID but never evicts retired IDs. Counted/claimed IDs, event arrays and departed vehicle lists also grow. [Runner line 852](/Users/user/theiatron/run_demo.py:852) summarizes all historical vehicles and sorts waits every frame. Over long runs this causes increasing cost; the browser also allocates objects for the whole timeline and repeatedly scans paths/events.

Fix: expire retired tracks with identity epochs, append events to durable logs, bound queues/ring buffers, update aggregate metrics incrementally, compute expensive percentiles less frequently, and stream/chunk viewer state. Test memory/latency over hours. Site-level absence of detections must not be confused with a dead camera.

**13. The upload service must remain local until hardened.**

[LauncherHandler](/Users/user/theiatron/launcher_server.py:193) serves the entire repository. The audit confirmed `.git/config` is reachable through it. The single-job check at [line 264](/Users/user/theiatron/launcher_server.py:264) happens before the upload and reservation; concurrent uploads can both pass. Jobs are memory-only and disappear after restart. There is no cancellation, subprocess timeout, retention quota, upload deadline, per-session token or explicit allowed-origin/host policy.

Fix before distributing/sharing: serve only approved UI/assets and authorized run files, reserve a processing slot atomically, probe media content/resource limits, add durable job state, cancellation and process cleanup, disk quotas and retention. Keep loopback binding; require authentication, TLS and tenant/data isolation before any remote service. A small local service does not need enterprise infrastructure, but the development HTTP server is not a hosted product boundary.

**14. UI states can overstate success or hide failure.**

[Launcher result line 74](/Users/user/theiatron/launcher/app.js:74) displays a percentage without respecting `sample_status`. [Dashboard line 196](/Users/user/theiatron/theiatron/dashboard.py:196) shows “measuring...” whenever adaptive is not better, even if the sample is ready. The final card and 3D viewer handle negative outcomes more honestly, so presentation semantics differ. [Viewer loading](/Users/user/theiatron/viz/index.html:105) silently falls back to the original sample for an invalid/missing run parameter. Asset load failures have little user-facing recovery.

Fix: shared result states, explicit negative/equal/inconclusive presentation, visible source/run ID and simulation mode. Invalid run links should produce an error or a labeled sample choice. Progress should be real per-stage work and elapsed time; add retry/cancel, saved-run library, preflight checks and a clearly labeled prerecorded fallback. Make the calibration review editable in the browser rather than a timed OpenCV popup.

**15. Release and artifact reproducibility are incomplete.**

[Requirements](/Users/user/theiatron/requirements.txt) are broadly constrained; [project metadata](/Users/user/theiatron/pyproject.toml) does not declare a complete installable dependency set. No CI workflow, release lock, cross-platform package or model/asset license inventory is checked in. Manifests record a model filename but not its hash, dependency versions or code commit. Several saved IMG_0635/0642 source paths no longer exist, although an IMG_0635 upload copy remains. The 3D model and clips are not sufficient by themselves to rerun perception from a clean checkout.

Fix: pin a known-good environment, model hash and runtime; add a one-command install/preflight and CI; create portable run bundles with relative paths, schema version, source/config/network/model hashes, commit, seeds, time step and metrics definitions. Record media provenance/permission. Test replay after relocating a bundle and after restarting the service. Check video writers and artifacts by decoding them, not just by file presence.

### Before field control — safety and commercial diligence

**16. Software phase interlocks are not a deployable signal safety case.**

[Current state machine](/Users/user/theiatron/theiatron/controller.py:35) is two-stage NS/EW with fixed yellow/all-red defaults and starts green. It lacks movement-level conflicts, site-specific intergreens, pedestrian/cyclist stages, UK red-and-amber behaviour, external controller acknowledgements, health supervision and a hardware-independent fault response. A max-green cap limits one service opportunity, not eventual individual waiting under oversaturated demand.

Keep all public-road actuation disabled. Start with read-only shadow operation. Integrate through an approved existing controller with a traffic engineer and the authority's requirements; independently approved fallback behaviour must survive a stalled/crashed perception computer. Do not treat GPIO relays, a generic flashing-amber fallback or a conflict-monitor component alone as a complete UK-compliant controller. The [DfT Traffic Signs Manual, chapter 6](https://www.gov.uk/government/publications/traffic-signs-manual) covers junction signal design and commissioning; [TOPAS controller specifications](https://topasgroup.org.uk/media/TOPAS-2500B.pdf) illustrate the wider controller/detector/interface requirements. Verify applicable current revisions with the deployment partner.

**17. Licensing needs a real decision, not an assumption.**

The project uses Ultralytics code and weights. AGPL permits commercial use subject to obligations; “a commercial pilot always requires a paid license” is too categorical, and “fine for a prototype” is not a universal exemption. For a closed-source product, obtain a suitable license or independently evaluate an alternative stack, including the model, weights, training data and dependencies. Changing ByteTrack or exporting to ONNX/NCNN does not automatically resolve detector/model licensing. No root project license or consolidated third-party notices were found. See [Ultralytics' licensing position](https://www.ultralytics.com/license); get professional review before distribution/contract commitments.

Stock SUMO is a practical integration boundary. Its [NOTICE](https://github.com/eclipse-sumo/sumo/blob/main/NOTICE.md) explicitly distinguishes public-library TraCI clients from derivative modifications. Preserve applicable notices and review actual packaging; do not call any dependency combination unconditionally “licensing clean.”

**18. Privacy and investor materials need cleanup.**

The pipeline retains originals, annotated videos, plates and trajectories. Not recognizing identities does not mean footage contains no personal data. Define purpose, lawful handling, access, retention and export redaction; assess a DPIA where required. For UK deployments consult the [ICO's video surveillance guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/cctv-and-video-surveillance/guidance-on-video-surveillance-including-cctv/), currently flagged as under review following legislative changes. Demo footage must have appropriate usage permission.

The website claims “every vehicle,” 10 observations/s, and pixels measuring real waiting; the current application does not establish those claims. Its embedded hero traffic simulation is independently coded with random arrivals and different timings, not the Python policy execution. Label it illustrative. The 30-day learning document also describes capabilities/fallbacks/certification as though implemented and calls the benchmark 41 vehicles; the actual benchmark has 40 counted arrivals. Treat these as materials to revise, not evidence.

## SUMO integration: the shortest sound route

### Keep the renderer; replace the source of simulated motion

Use stock headless SUMO. Start with TraCI because separate baseline/adaptive processes are easy to inspect and compare. Profile before switching to libsumo; its similar API is useful, but multiple concurrent simulations need appropriate process isolation. SUMO's [Python interface](https://sumo.dlr.de/docs/TraCI/Interfacing_TraCI_from_Python.html) supports stepping, traffic-light control and subscriptions. These provide the needed bridge without modifying SUMO.

Proposed components:

| Component | Responsibility |
|---|---|
| Site profile / commissioning | Reviewed metric network, camera mapping, zones, lane/movement IDs, legal connections and stage constraints. |
| Perception worker | Timestamped detections/tracks, observation confidence, crossing events and measured queue/presence where validated. |
| Demand builder | Boundary arrivals, vehicle types, turning routes and initial state, with measured/assumed provenance. |
| SUMO adapter | Start/stop/step each scenario, apply approved stage requests, obtain its observations, collect canonical trajectories and metrics. |
| Policy interface | Consume a `TrafficObservation`, propose a stage request; no dependency on `PointQueue` internals. |
| Local application service | Jobs, camera/file sessions, event streaming, run library, cancellation and evidence export. |
| Three.js viewer | Display actual simulator state or observed-track replay; interpolate visually without changing metrics. |

For the first junction, hand-review or author its network in SUMO's tools. Automatic conversion of an arbitrary video into a correct lane graph is a separate R&D problem. A verified network template with assisted fitting is enough for this product version.

Where individual routes are observed, generate explicit vehicle routes with stable IDs. Where only aggregate counts/turn ratios exist, SUMO's [routeSampler](https://sumo.dlr.de/docs/Tools/Turns.html) can fit demand to candidate routes; its output is inferred demand, not recovered exact movements. Preserve this distinction.

Run baseline and adaptive with the same intended arrivals, routes, vehicle parameters, initial conditions and paired seeds. Under congestion, actual insertion times may differ because road space differs: record insertion delay and vehicles not inserted, rather than dropping them from the comparison.

The counterfactual controller must observe **its own simulated scenario** through the defined observation interface. The original video's vehicle positions cannot become correct closed-loop queue feedback after simulated signals diverge. Use virtual detectors/noise models for the physical what-if, and validate the real camera's observation quality separately. Never force simulated cars back onto recorded trajectories with position overrides while claiming a free-running control evaluation.

### Live display and replay should share one format

Publish snapshots containing run/scenario ID, simulation tick/time, vehicle ID, metric position, heading, speed, type, lane, signal state and metrics. A WebSocket can carry the latest state; saved chunks support deterministic replay, seeking and recovery. The local service should retain snapshots independently of browser connection health.

Start with a 0.1-second SUMO step and approximately 10 state updates/s as engineering choices to test. Interpolate at the browser's frame rate. Expose simulation speed explicitly; faster-than-realtime simulation is not faster-than-realtime camera observation. Do not make simulation correctness depend on browser animation timing.

SUMO's [FCD output](https://sumo.dlr.de/docs/Simulation/Output/FCDOutput.html) already records positions, speed and heading for replay. Its position anchor is the front-bumper centre and its heading is navigational degrees; test conversion to the viewer's vehicle-centre/yaw convention, metres and coordinate axes. Add stable-ID, route-validity, seek/reset, left-hand-network and missing-asset tests.

### Benchmark against meaningful alternatives

Keep the equal 30-second timer as a teaching baseline. Add a demand-appropriate fixed plan calibrated on training data and a gap-actuated controller. SUMO provides [static and actuated control](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html). Use its [NEMA implementation](https://sumo.dlr.de/docs/Simulation/NEMA.html) only for a relevant North-American-style study; NEMA is not a proxy for MOVA, SCOOT or the current UK market.

Use common movement/pedestrian constraints across policies. Evaluate held-out balanced, asymmetric, changing and oversaturated demand, downstream blocking, noisy/missing observations and initial queues. Start with three independently reviewed junction datasets and several distinct time windows; add multiple paired seeds when the scenario introduces stochastic behaviour. Replaying the same deterministic input ten times does not create ten independent experiments.

Report absolute mean/p95 waiting, time loss, throughput, queues, per-approach fairness, unfinished vehicles and insertion delays. Distinguish cumulative delay through a fixed horizon from completed-trip results after draining the same cohort. SUMO's [TripInfo definitions](https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html) separate stopped waiting from time lost below ideal speed; enable unfinished/undeparted reporting as appropriate. Do not relabel either measure “HCM control delay” without the required methodology. Preserve adverse outcomes and show uncertainty/sensitivity at the site/run level.

## What the investor should actually see

A single application window, with four connected views:

1. **Observe:** choose footage, immediately see fresh boxes/tracks, source name, processing time, count confidence and data freshness. Mark a file as file analysis; mark a true camera as live.
2. **Commission:** show proposed approaches/zones; accept/edit a saved site profile, metric layout, movements and initial conditions. Display unresolved assumptions before enabling a claim.
3. **Compare:** side-by-side SUMO traffic with the same demand, baseline selector, visible signals/queues and the controller's reason for a decision. An investor can change a supported demand assumption and trigger a new calculation.
4. **Evidence:** report, run ID, sample scope, measured/assumed inputs, model/version, actual metric definitions, baseline configuration and reproducible exports.

The useful demonstration is “this input changed; the system recomputed these decisions and these outcomes.” It does not require unrestricted camera geometry or a photorealistic city. For a known site, reuse calibration so the first live detections appear quickly. For a new site, show commissioning rather than implying instant validation.

A three-minute presentation can spend approximately 30 seconds on fresh perception, 30 on site review, 60 on a running comparison, 30 on the evidence and 30 on the customer/pilot milestone. Run the system beforehand to prove offline readiness, but clearly label any prerecorded fallback. Keep the analysis product useful even when the adaptive result is neutral or worse.

## Delivery plan and acceptance gates

Planning estimate: **4–6 focused weeks** for a credible limited-scope investor software release, assuming one experienced full-time engineer, founder access to suitable footage and part-time traffic-engineering review. Data collection and partner approvals can extend the schedule. This is not a production roadside release estimate.

| Stage | Approximate sequence | Exit condition |
|---|---|---|
| Evidence and release repair | Days 1–3 | Report/export parity, terminal-step tests, consistent inconclusive/negative states, source/run labeling, reproducible environment, restricted asset serving. |
| One physical junction | Remainder of week 1 through week 2 | Reviewed SUMO network; same-demand baseline/adaptive runs; routes conserve vehicles; no unexplained invalid routes, collisions or teleports; metrics generated from the simulator. |
| Product experience | Weeks 2–3 | Browser detection preview, saved/editable site profile, streaming state, cancellation/recovery, report export and explicit simulation/replay modes. |
| Evidence suite | Weeks 3–4 | Independent site/time holdouts, annotated counts, tuned fixed and actuated baselines, sensor-noise/queue sensitivity, observed limitations and regressions documented. |
| Investor release and contingency | Weeks 4–6 | Clean-install rehearsal, offline operation, repeatable complete demo and a customer/pilot evidence pack. A second engineer could shorten some integration work; it does not remove data/validation dependencies. |

Suggested **acceptance targets**, not present achievements or safety standards:

- On a preconfigured site and warmed reference laptop: first visible analysis within a few seconds of local media readiness, sustained at least 10 sampled frames/s and p95 capture-to-observation age below 300 ms. Measure camera and decoder overhead, not only model inference.
- One-hour laptop soak initially, then 24–72-hour device soak before any outdoor shadow trial; stable memory, no silent stalls, measured temperature/power and explicit stale-input handling.
- Ten consecutive complete rehearsals without terminal repair; offline test; missing model, invalid video, disk-full, process interruption and browser reload tests.
- Exact report/replay equality for the same canonical run, with a clearly specified numerical tolerance only where necessary.
- For supported demo footage, agree crossing-event precision/recall and per-movement count-error gates with the adviser. An initial engineering target could be at least 95% crossing precision/recall and no more than 10% count error in adequately populated bins, with absolute-error reporting for sparse bins. These are proposed demo gates, not field acceptance claims.
- No required “percentage improvement” gate. A valid negative result must still produce a correct, usable report. Product value and policy advantage need separate tests.

If the remaining deadline is still **48 hours**, prioritize evidence fixes, clear labeling, saved site profiles, preflight/recovery and a rehearsed existing prototype. Do not represent a rushed SUMO hookup as a validated new product. A basic single-junction SUMO proof can be much quicker than the full release above, but the empirical work is the critical path.

## Hardware R&D the raise should fund

The field unit does not need to render 3D or run two comparison worlds continuously. Those belong on the demonstration/engineering workstation. Its first responsibilities are dependable capture, perception, observation quality, logging and a constrained approved-controller interface.

Prototype on **Pi 5 + active cooling**, benchmarking both a CPU export path and an AI HAT+ path. The current Raspberry Pi documentation lists 13/26-TOPS AI HAT+ variants and says the older AI Kit is no longer in production. Choose the accelerator on measured total workload, power, supply and cost, not TOPS alone. See [Raspberry Pi AI HAT documentation](https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html).

Current Ultralytics documentation lists YOLO26 detection export to Hailo-8/8L, so a detector family swap is not automatically necessary. Compilation is documented for Linux x86_64 with the matching compiler generation and representative INT8 calibration data. Verify the exact pinned model/runtime on the board; host decoding and postprocessing still count. See [Hailo export documentation](https://docs.ultralytics.com/integrations/hailo). Licensing remains a separate decision.

Fund sequential risk reductions:

1. **Bench proof:** actual end-to-end latency, count accuracy, thermal soak, power and storage endurance on the selected device/camera.
2. **Outdoor shadow proof:** permissioned capture only; day/night/rain, pole movement, occlusion, power interruption and maintenance procedures. Compare measured observations with human annotations; no traffic actuation.
3. **Controller-in-loop lab proof:** approved-controller integration, command/status semantics, timeouts, fault injection, audit logs and independent fallback; traffic-engineer review.
4. **Supervised site trial:** agreed authority approvals, operating limits, study design, safety/privacy responsibilities, insurance and support. Only then measure roadside benefit.

Custom electronics, solar sizing, weatherproofing and manufacturing follow measured power/environment requirements. Budget the entire installation—camera, enclosure, mounting, power, communications, integration, commissioning and maintenance—not just the Pi/HAT. OTA rollback, secure boot/update strategy, device identity, physical access and key management belong in field design; they need not become a fleet platform before the first software demo.

## Positioning for UK investors

**The market is not empty.** VivaCity advertises camera-derived sensing and smart signal control; Yunex and TfL describe FUSION adaptive control. TfL's current material describes FUSION replacing SCOOT. This does not disprove a low-cost emerging-market opportunity, but it rules out a credible pitch based on nobody having combined cameras and signals. Sources: [VivaCity's solution](https://info.vivacitylabs.com/congestion-reduction-network-optimisatio-solution/), [Yunex FUSION](https://uk.yunextraffic.com/portfolio/traffic-management-systems/Fusion-adaptive-traffic-control/), [TfL's London on the Move](https://content.tfl.gov.uk/londononthemove.pdf).

My recommended commercial entry is a **paid, supervised junction assessment/shadow-analysis service** for a specific traffic authority, transport consultancy or site operator. It can deliver verified counts, queue observations and scenario reports before public-road control is authorized. Validate willingness to pay; do not assume that investor interest equals customer demand. Private sites can simplify access, but they do not automatically validate public-junction control or share the same buying problem.

For a Nigeria-first strategy, test a concrete advantage: installed lifecycle cost and reliability under local connectivity, power, maintenance and mixed-traffic conditions. Benchmark those claims against a named incumbent/alternative. A Pi bill of materials is not evidence that an installed traffic-control service is cheaper.

Bring the following to investor meetings:

- One clearly named buyer segment and use case, plus documented customer conversations and a genuine pilot/LOI with scope, site/data access, success criteria and decision owner. An LOI is not booked revenue.
- A traffic-engineering adviser or delivery partner, with agreed responsibilities; do not imply a relationship that does not yet exist.
- An evidence pack containing the supported-footage demo, benchmark protocol, all outcomes, provenance and limitations. An independently reviewed result has more value than a larger cherry-picked percentage.
- A competitor comparison on installed cost, commissioning effort, offline operation, maintenance, accuracy, integration and route to approval. Unmeasured columns should say “to validate.”
- A bottom-up R&D budget: engineering time, annotation/data, adviser/testing, prototype devices, installation/access, assurance/legal/privacy, support and contingency. Tie funding to bench, shadow and controller-in-loop gates. Re-cost the previous $100,000/three-junction proposal rather than carrying it forward without quotes.
- A clear company/IP ownership structure, dependency/model licensing plan, commercial milestones and explicit explanation of why this investor's sector/geographic mandate fits the company. Do not assume UK grant or tax-incentive eligibility merely because the pitch occurs in the UK.

For later UK economic appraisal, use appropriate traffic-engineering study design and current [DfT transport analysis guidance](https://www.gov.uk/guidance/transport-analysis-guidance). Simulated vehicle-seconds cannot simply be converted into claimed customer revenue, cash savings or proven emissions reductions.

The defensible assets to build are the permissioned local dataset, reliable commissioning workflow, sensor-aware control performance, integration expertise and customer relationships. Generic YOLO plus a queue policy plus SUMO is useful engineering but not, by itself, a strong moat.

## What to defer

Defer a SUMO fork, Unity/Unreal/CARLA rebuild, reinforcement learning, a second simulator such as UXsim, city-wide optimization, unrestricted video-to-road reconstruction, a custom PCB and multi-tenant cloud platform. Do not replace every working module with an open-source library before benchmarking a specific need. A supervision/tracker swap may be worthwhile, but it is not the main investor blocker or a detector-license cure.

Correct the earlier OSS research before reusing it: market-absence claims, automatic NEMA/NTCIP applicability to the UK, extrapolated Pi throughput, “zero-lag” smoothing, automatic HCM metrics, blanket licensing statements and generic relay/fallback guidance are not sound product specifications. Useful project references can remain references; they do not transfer validation or compliance to Theiatron.

## First implementation milestone

Create one **evidence-consistent junction run**: selected footage → reviewed site configuration → measured demand → stock SUMO baseline/adaptive → streamed Three.js states → reproducible report.

Start by repairing result parity and evaluation gates, then connect one reviewed SUMO network. The investor demonstration should make its current capability unmistakable and its remaining R&D measurable. That gives the strongest foundation for funding discussions without depending on an unsupported promise of universal 45% improvement.
