# Theiatron code review — 25 September 2026

Full read of the working tree on branch `codex` (last commit `2a633b3`, 9 Aug):
every Python module, `launcher_server.py`, `run_demo.py`, the scripts, all 20
docs, the CI workflow, and the front end (`workbench/`, `viz/`, `launcher/`,
`tests/*.cjs`). Verified on this machine: **337 Python tests pass in 70 s;
63 Node tests pass**. Line references are to the working tree as read today.

## 1. Where the project stands

| Fact | Value |
|---|---|
| Code size | ~26,400 lines (17,500 Python/JS/HTML in `theiatron/`, `workbench/`, `tests/`, `scripts/`, `launcher/`) |
| Uncommitted work | **88 untracked files + 15 modified**; nothing committed since 9 Aug; GitHub is seven weeks stale |
| CI | `.github/workflows/tests.yml` exists but is untracked, so it has never run |
| Retained data under `out/` | 81 run dirs, 1.7 GB; 727 MB of your iPhone footage under `out/uploads/`; no retention policy |
| Foreign data in the tree | `outputs/student-media-2026-09-15/` (79 MB) is **Bickqr** outreach material: contact lists, email drafts. Untracked, inside a public repo |
| Dead code | `theiatron/event_review.py` (183 lines): no endpoint, no import, no test |

## 2. What is being done well

**Evidence integrity is a real architecture, not a slogan.** Every result is
a content-addressed artifact: `simulation.json` carries steps, config snapshot
and a fingerprint (`theiatron/artifacts.py:52-67`); replay must reproduce the
recorded scenarios exactly (`artifacts.py:98-107`); the 3D exporter decorates
the canonical artifact instead of re-running physics (`scripts/export_timeline.py:30-49`),
which closes the September-6 audit's P1 finding. SUMO bundles hash every file
and the controller source before *and* after a run (`theiatron/sumo_demo.py:380-425`),
refuse to overwrite existing evidence, and cross-check streamed metrics against
SUMO's own trip output (`:427-430`). Site profiles, reconstructions, camera
profiles and refinements are immutable revisions keyed by hash.

**Honest labelling is enforced in code.** `assess_comparison` decides the
headline and refuses percentages on thin or one-phase samples
(`theiatron/metrics.py:79-127`); `review_status` and the assumptions list
cannot be edited out of a profile (`theiatron/site_profiles.py:133`);
`demo_profiles.propose` refuses to substitute a stock site (`:84`); the one
hand-traced road is bound to its footage SHA so it cannot leak into other clips
(`theiatron/reconstruction.py:21-28`). The front end mirrors this everywhere the
reviewer looked: OBSERVED/ESTIMATED/COMPUTED cards, "SAVED SIMULATION REPLAY"
vs "COMPUTING", "UNRECTIFIED PREVIEW", "NOT A LIVE FEED", and tests that assert
the *absence* of overclaims (`tests/test_demo.cjs:43-49`).

**The controller benchmark is methodologically sound.** `theiatron/benchmark.py`
tunes the fixed split on fixed-world delay only, freezes code hashes, evaluates
on held-out seeds, and keeps every row including regressions; the milestone doc
reports the losses alongside the wins. That is exactly how you avoid fooling
yourself, and it is rare in a prototype.

**The local service is properly hardened.** Loopback bind, Host/Origin
allowlist and per-launch token with constant-time compare
(`launcher_server.py:479-489`), asset allowlist that rejects dotfiles, symlinks
and traversal (`:412-433`), atomic single-slot job reservation (`:210-223`),
bounded uploads with deadlines, process groups plus parent-death watchdogs,
durable job state that marks interrupted jobs, and a single-instance lock. The
`.git/config` exposure from the August audit is gone.

**Continuous perception is designed like a systems engineer designed it.**
Capture and inference are decoupled through a capacity-one mailbox
(`theiatron/streaming.py:20-55`); stale frames are rejected, drops and deadline
misses counted, latency kept in a constant-memory histogram; tracker resets on
discontinuities; the resident worker is process-isolated with IPC and start/stop
deadlines (`theiatron/live_service.py`). The soak numbers are reported with
their bad tail (8.24 FPS, 780 misses, 5.9 s worst case) rather than a best run.

**The original core is still clean.** `controller.py`, `engine.py`, `sim.py`
and `approach.py` are small, documented, PEP8, and the "state machine owns the
safety invariants, policies only request" split is the right one. The counting
hardening (one tracker per feed, finite segment crossing, per-camera claimed
set, IoU dedupe, min track age) is all present and explained.

**Tests are broad and CI-viable.** The detector is stubbed everywhere it is
needed (`tests/test_recount.py:103`, `tests/test_visual_capture.py:36`), SUMO
tests are gated by `THEIATRON_REQUIRE_SUMO`, HTTP tests cover the security
cases, and the whole Python suite runs in 70 s.

## 3. What is being done poorly

### 3.1 Delivery hygiene (the most serious item)

Seven weeks of work, roughly 12,000 new lines, exists only in this working tree.
There is no history to bisect, nothing for a reviewer or adviser to read, no CI
result, and a single disk failure loses it. Compounding this:

- `git add -A` would publish 79 MB of Bickqr contact lists and email drafts to a
  public repository. Move `outputs/student-media-2026-09-15/` out of the repo
  before anything else.
- The application's *durable* state lives under the ignored `out/` directory
  (`out/.launcher/jobs.json`, `out/.profiles`, `out/.reconstructions`,
  `out/.camera-profiles`). Clearing `out/` to reclaim 1.7 GB silently destroys
  the app's database. Give state its own directory.
- Nothing ever deletes uploads or run directories; the docs acknowledge this.

### 3.2 Two code dialects

The August modules are readable PEP8. Most September modules are written in a
dense style: semicolon-joined statements, one-letter names, 120-200 character
lines, no blank lines between logical blocks.

| File | Lines > 120 chars | `;`-joined statements |
|---|---:|---:|
| `theiatron/refinement.py` | 23 | 24 |
| `theiatron/sumo_demo.py` | 22 | 0 |
| `launcher_server.py` | 21 | 7 |
| `theiatron/ground_plane.py` | 11 | 13 |

The front end has the same split: prettier-formatted `replay.js`/`app.js`
beside minified-style `showcase.js`/`assist-guide.js`, and a ~600-character
nested ternary at `workbench/replay.js:100`. There is no formatter, linter or
pre-commit hook configured. For a project whose next step is recruiting an
engineer and a traffic adviser to review it, this is a real cost.

### 3.3 Structure that has outgrown its files

- `run_demo.py` is 1,332 lines; `run_live_demo` alone is ~440. `theiatron/recount.py:105`
  imports helpers *from the CLI script* (`from run_demo import ...`), an inverted
  dependency. Those helpers belong in a `theiatron/pipeline.py`.
- `launcher_server.py` routes by a chain of regexes inside `do_GET`/`do_POST`
  and keeps all state in module globals (`JOBS`, `PROCESSES`, `REFINEMENTS`,
  `LIVE_SERVICE`). Workable at this size; it will not survive one more feature.
- Three generations of UI are served side by side: `launcher/` (overclaims: "detect
  every arrival", `launcher/index.html:23,75`), `viz/`, and `workbench/`. Retire
  or stop serving the first two.
- Front end (from the reviewer): six hand-rolled fetch helpers with different
  timeout/error semantics; `profiles.js` and `counting.js` mutate ~25 implicit
  globals owned by `app.js`; page controllers are 600-1000-line closures that
  tests can only reach by slicing source text.
- Dead or duplicated: `event_review.py`; `sampleTrack(stabilize)`
  (`workbench/replay-math.js:305-321`); `uploadRequest` (`workbench/demo.js:30`);
  `vehiclePose` vs `DemoMath.pose`; `viz/app.js` and `viz/twin.js` duplicate
  `sgSmooth`, `textSprite`, `loadCarModels`.

### 3.4 Concrete bugs (all front end; none found in the Python package by reading)

| # | Severity | Where | What happens |
|---|---|---|---|
| 1 | **High**, presenter-facing | `workbench/live.js:328-329, 283-284` | The live lab adopts *any* active reconstruction job regardless of source and navigates away when it completes. Prepare clip X in one tab, run detection on clip Y in another: both tabs jump to X's replay while Y keeps running. `tests/test_live_preparation.cjs:52-55` enshrines it. |
| 2 | Medium | `workbench/replay.js:181-202` | `refreshRefinement()` has no generation check after its await; a save that races the poll reverts calibration and clears the dirty flag. |
| 3 | Medium | `workbench/app.js:588-626`, `demo.js:617-707` | Poll loops have no timeout; a stalled response freezes the page while the banner still says CONNECTED. `live.js`/`replay.js` do it right. |
| 4 | Medium | `replay.js:311` + `demo.js:464-468` | The studio iframe auto-starts a refinement; the demo then refuses "Compute new comparison" with "still refining" for minutes. |
| 5 | Low-med | `demo.js:615`, `replay.js:401` | `requestAnimationFrame` re-armed at the *end* of the tick, so one exception stops rendering for the page. |
| 6 | Low | `demo.js:160-165`, `traffic-scene.js:615-623` | Scenes are rebuilt on every experiment switch without `forceContextLoss()`; WebGL contexts leak until eviction. |
| 7 | Low | `demo.js:541-547` | Late cancel response reinstalls a cancelled job over a newly selected experiment. |
| 8 | Low | `app.js:596-622` | An unknown `?video=` id is reported as a service outage twice a second. |

### 3.5 Runtime and operations

- `_append_log` rewrites the whole job store on **every stdout line** of a
  worker (`launcher_server.py:169-173`); the store is 165 KB with 29 jobs and is
  never pruned. Combine with two pages polling `/api/runs` at 2-4 Hz, each call
  copying the logs of up to 50 jobs (`:176-183, 521-524`).
- No disk-space check before accepting a 4 GB upload; no quota.
- The legacy `run_live` loop still never evicts retired tracks
  (`theiatron/approach.py:24-46`); the audit's finding 12 is fixed only in the
  new `live_worker` path.
- Two p95 definitions coexist: linear interpolation for point-queue
  (`metrics.py:13-24`), nearest-rank for SUMO (`sumo_demo.py:251`). SUMO
  reports state their method; the point-queue report does not.

### 3.6 Documentation and claims

- `README.md` is 385 lines of accreted milestone prose. Its top disclaims any
  delay benefit; its bottom still shows the 44.6 % table, "Adaptive won on
  every approach", and extrapolated Pi frame rates. Pick one.
- Twenty milestone diaries in `docs/`, no single current architecture or status
  page. Test counts disagree across README/docs (39, 118, 337; JS 5, 37, 63).
- `site/index.html:206-228` still claims "SEES EVERY VEHICLE", "10×/s" and
  "pixels become how many are stuck", all flagged by the September-6 audit and
  still unfixed. The legacy launcher copy has the same problem.

### 3.7 Where the effort went

Roughly 1,800 lines and four successive estimators (automatic vanishing
points, road-line families, temporal road evidence, operator-assisted lines)
went into ground-plane geometry, and the flagship overhead clip still fails the
stability gate (`docs/temporal-road-evidence-2026-09-22.md`). Meanwhile the
evidence gates the September plan called critical remain open: no labelled
perception dataset (the tool for it, `event_review.py`, was written and never
wired in), no reviewed real junction, no documented customer conversation or
pilot sponsor. The geometry work is impressive engineering; it is not what the
investor case is waiting on.

## 4. Recommendations, in order

1. **Today.** Move `outputs/student-media-2026-09-15/` out of the repo. Commit
   the September work on `codex` (one commit per milestone doc is a natural
   split), push, and confirm the workflow goes green on GitHub. Tag the
   evaluation state referenced by the sealed manifests.
2. **This week.** Add `ruff` + `prettier` with a line-length limit and a
   pre-commit hook; reformat `refinement.py`, `ground_plane.py`,
   `launcher_server.py` (tail), `showcase*.js`, `assist-guide.js`. No logic
   changes, tests stay green.
3. Fix bugs 1-5 above; they are small and 1 is presenter-facing. Extract one
   shared fetch client (timeout, JSON-error normalisation, token header) and
   use it from all six pages.
4. Move durable state out of `out/` into `state/`; add upload/run retention
   with a size cap; debounce job-store persistence and prune old jobs.
5. Wire `event_review.py` into the workbench and use it: the labelled-crossing
   precision/recall report is the first missing evidence item. Delete the other
   dead code.
6. Split `run_demo.py` into `theiatron/pipeline.py` + a thin CLI; stop importing
   from the script; retire `launcher/` and `viz/` or stop serving them.
7. Rewrite `README.md` as a current status/architecture page; move the diaries
   to `docs/history/`; fix `site/index.html` claims; align test counts.
8. Re-balance the roadmap toward the open evidence gates (reviewed junction,
   labelled counts, pilot sponsor) before adding a fifth geometry estimator.

## 5. Front-end review detail

The full front-end findings (done well / bugs / smells / labelling audit / test
posture) are reproduced from the reviewer's report below for reference.

### Done well
- Fail-closed geometry with descriptive errors (`workbench/replay-math.js:13-15, 34, 43, 48, 92, 96, 108, 125, 168`); `project()` returns null behind the horizon or beyond 500 m; `unproject()` verifies the round trip.
- Inputs never mutated; tests assert it (`tests/test_reconstruction.cjs:180-191, 345-353, 379-391`).
- Late-response protection where it matters: generation counter + AbortController (`replay.js:203-256`), `selectionVersion` checks (`app.js:369, 383, 391, 428`), generation/job checks in `demo.js`, abort-on-reload in `live-scene.js:23-49`.
- Three.js hygiene: shared templates, `disposeGroup` dedup, road/paths/grid disposed before rebuild, `dispose()` releases observer/controls/renderer.
- Bounded memory everywhere (undo ≤60, road corners ≤100, detections ≤256, history ≤8).
- No `innerHTML` with data; token only in `X-Theiatron-Token`; every script is local so the offline claim holds.
- Showcase gates before showing any number (`showcase-math.js:5-21`).

### Smells
- Six divergent fetch helpers; implicit globals across `app.js`/`profiles.js`/`counting.js`; monolithic page closures.
- Duplicated logic (`vehiclePose`/`DemoMath.pose`, duration formula, `preset()` angle, viz duplicates); two renderers of `geometry.json` with different fallbacks (`view.js:128` vs `demo-scene.js:82`).
- Hard-coded run ids in `showcase.js:82-83`; "4×" label true only while `STEP = 0.5`; frame-size constants scattered; tuning thresholds undocumented at definition.
- Polling at 2-4 Hz against a fat endpoint; loops do not pause when the tab is hidden (except `replay.js`).
- No Content-Security-Policy header.

### Labelling gaps
- `launcher/index.html:23, 75` overclaims.
- Legacy viewer colours Theiatron green before any verdict.
- Exactly 0.0 % renders as "0.0% less" in `demo-math.js:51-54`.
- Provisional per-world tiles during computation are not marked "to date" (`demo.js:568-573`).
- Static subtitles do not change when the baseline switches to actuated (`demo.html:192, 203`).

### Test posture
- Covered: reconstruction math, `LivePoses`, `LiveSceneView`, `LiveUpload`, `live.js` in a vm, assist-guide, demo/showcase/live math, `comparison.js`, `load-run.js`.
- Not covered: `app.js`, `demo.js`, most of `replay.js`, all rendering, `profiles.js`, `counting.js`, `launcher/app.js`, `viz/twin.js`.
- Brittle: source slicing by string markers (`test_assist_guide.cjs:30`, `test_reconstruction.cjs:45`, `test_viewer.cjs:47`); vm fixtures re-declare closure variables by hand; timers identified by `ms === 250`.
