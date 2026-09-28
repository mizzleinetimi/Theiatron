# Theiatron: remaining milestones and demo product plan

10 September 2026 · working branch `codex`

## Decision

Build a local **junction observation and control-evaluation workbench**, with a
presenter mode for investors. Keep Python and Three.js; add stock SUMO. Lead
with fresh perception, show a clear physical comparison, then expose evidence.
Make 3D a useful explanation of real simulator state, not the definition of
the product or the main proof of effectiveness.

Commercial hypothesis: a permissioned junction assessment / shadow-analysis
offering is a plausible first sale, followed by an approved-controller
integration. This needs customer validation. It is not proof of demand and
does not require abandoning the eventual edge-control product.

Assumption: UK investors may fund a Nigeria-first deployment. A UK-first
customer strategy requires UK junctions, relevant incumbent comparisons and
local integration/assurance expertise much earlier. Choose this in M1; the
fundraising location should not implicitly choose the deployment market.

## Planning baseline (before implementation on 10 September)

Implementation has since begun. For the updated delivered scope and checks,
see [the workbench milestone](workbench-milestone-2026-09-10.md). The statements
below are retained as the starting baseline, not the current implementation.

- Existing changes remain on `codex`, uncommitted. No product code was changed
  during this planning review.
- 71 Python tests and 5 Node viewer tests pass on this machine. These are
  software checks, not field accuracy, safety or statistically validated benefit.
- M0, the evidence-consistency slice, is implemented: canonical simulation
  record, exact replay, report/timeline agreement, full-precision events,
  fractional horizons, honest outcome states, preservation of existing replay
  evidence and fail-closed selected-run loading.
- The retained fresh IMG_0635 smoke artifact is explicitly `point-queue` with
  `illustrative-not-metric` geometry. Report and timeline fingerprints agree.
  Its 30.0138-second evaluation contains three NS arrivals and is inconclusive.
- There is no SUMO application adapter or SUMO executable on PATH. The existing
  3D comparison still retimes observed tracks using a point-queue model.
- File analysis still involves observation, calibration, another inference
  pass, encoding and export. It is not yet the requested instant streaming
  workflow. A camera service, browser commissioning editor, durable/cancellable
  jobs, empirical benchmark dataset and reproducible distributable release
  remain to be built.

M0 is NOT completion of the original broader “evidence and release repair”
stage: deployment/release hardening from that stage is still M2 below.

## Remaining milestones before the investor software release

Effort ranges are planning estimates of hands-on engineering, not promises or
calendar deadlines. They assume one experienced full-time engineer, founder
ownership of data/customer work, and part-time traffic-engineering review.

| Milestone | Deliverables | Exit gate | Owner / dependencies | Effort |
|---|---|---|---|---|
| M1. Choose the product and demonstration case | First buyer, deployment market, one intervention, supported source types, reference laptop and permissioned junction footage. Decide whether the demonstrated intervention is retiming an existing signal or proposing signals at an unsignalised junction. | A one-page scope and accessible data; the baseline represents the actual question. No “any video / any junction” promise. | Founder + traffic adviser; starts now, alongside M2 | 1–2 days plus access lead time |
| M2. Finish the software foundation | Restricted static assets/run access, atomic upload/job reservation, input/config validation, pinned environment and model/asset hashes, install/preflight checks, CI and a tested source checkpoint. | Clean install works; repository/private paths cannot be served; concurrent upload test passes; current 71+5 tests remain green. | Engineer; M0 in place | 2–3 days |
| M3. Commission one defensible junction | Versioned site profile: camera stability/scale, lanes, legal turns, movement IDs, reviewed signal stages/clearances, detector zones, initial queues and vehicle classes. Annotated counts/queues and provenance of measured versus assumed inputs. | Adviser signs off the network/profile; observed counts and queues meet agreed error bounds on an annotated segment. Saved profile can be reused; changed camera invalidates it. | Engineer + adviser + founder/data; M1 | 3–5 days plus data/review |
| M4. Integrate stock SUMO end to end | Synthetic CI fixture first, then reviewed network. Separate baseline/adaptive instances; common intended demand/routes/initial state/paired seed; policy observation interface; real SUMO vehicle/signal trace and metric adapter. | Vehicles reconcile across intended, inserted, active, finished and exceptional states; invalid routes/collisions/teleports are absent or explicitly diagnosed. Each controller reads its own world. Viewer/report use the same SUMO trace. | Engineer + adviser; fixture can start during M3, physical result requires M3 | 4–7 days |
| M5. Progressive analysis and streaming | Warm perception worker, timestamped capture and bounded queues, browser detection preview, explicit file/camera/replay clocks, simulation-state stream, durable job state, cancellation, recovery and stale-source handling. | New supported input produces fresh visible observations without waiting for a rendered movie; slow browser does not stall computation; restart/reconnect/cancel tests pass. | Engineer; M2; paired simulation streaming requires M4 | 3–5 days |
| M6. A coherent product interface | Watch / Compare / Evidence views; browser profile review/edit; saved-run library; fixed/top-down camera by default; synchronized A/B state; controller decision explanation; one supported scenario edit that starts a new computation. | A new viewer can tell observed versus simulated, live versus replay, baseline, site and run. No terminal needed during a supported demo. Changing demand really reruns the model. | Engineer + founder/user feedback; M3–M5 | 3–5 days |
| M7. Credible evaluation | Tuned fixed and actuated baselines, frozen policy/config, independent evaluation periods, perception ground truth, initial-queue/turn/noise sensitivity and all results, including adverse cases. | A reviewed benchmark report with absolute metrics, sample scope, uncertainty/sensitivity, completed and unfinished populations. No tuning on test data. An additional site is required before claiming cross-site transfer. | Engineer + adviser + annotation/data; protocol starts in M1, final runs require M4 | 4–7 days plus annotation/review |
| M8. Investor release and pilot package | Offline bundle, ten full rehearsals, recorded fallback clearly labelled, portable evidence export, brief operator guide, claim/licensing/privacy review, scoped pilot proposal, customer feedback and costed funding milestones. | Another person can run the supported workflow from a clean setup; failures are understandable; claims match evidence; pilot commitments are accurately described. | Engineer + founder + appropriate reviewers; M2–M7 | 2–3 days plus commercial work |

### What “SUMO done” must mean

Installing SUMO or producing moving cars is not M4 completion. The minimum
vertical slice is: source demand → reviewed network → independent controller
worlds → actual vehicle dynamics → canonical positions/metrics → browser and
report. Road geometry must come from the simulator's network, not an arbitrary
affine warp of the camera plate.

Stock TraCI supports stepping, signal control, subscriptions and multiple
instances; there is no rendering requirement that justifies a SUMO fork.
Start with process-isolated TraCI worlds; profile before considering libsumo.
[Official Python interface](https://sumo.dlr.de/docs/TraCI/Interfacing_TraCI_from_Python.html).

Introduce a small policy interface (observations in, permitted stage request
out) so control is not coupled to `PointQueue`. The next metric/trajectory
schema should explicitly distinguish SUMO results from the current point-queue
artifact. Keep existing replay evidence readable rather than changing its meaning.

### The demand and baseline trap

Visible stop-line crossings may be discharge under the recorded control,
not independent arrivals. Missing initial queues, vehicles hidden outside
the image, unknown turning ratios and downstream blockages change results.
If footage cannot identify demand, use labelled assumptions and sensitivity
ranges; do not treat automatic corridor detection as full reconstruction.

If the source junction has no functioning signals, the question is not merely
“adaptive versus existing fixed lights.” Distinguish the benefit of adding
signals from the benefit of adaptive timing. A defensible observed/no-signal
baseline needs traffic-engineering input, especially for mixed traffic and
informal priority behaviour. Start with a supported signalised junction if
that is the shortest way to obtain a credible comparison.

The actual local control plan, if known, should be the primary comparator.
Otherwise label the demand-tuned fixed and actuated alternatives as simulation
baselines, not “today's traffic.” SUMO provides static and actuated control;
neither is automatically an implementation of a UK incumbent system.
[Traffic-light documentation](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html).

### Validation and release targets

Set these before tuning. Proposed engineering targets below are not achievements,
statistical sample-size guarantees, regulatory standards or field acceptance:

- One independently reviewed junction and separately captured evaluation
  periods for the first site-specific release. Start with several distinct
  periods; size/length must cover representative demand and enough cycles,
  and be agreed with the adviser. Add a second-site transfer test before any
  cross-site claim, then expand to the broader multi-site benchmark.
- Report crossing-event precision/recall, per-movement count error, queue error,
  failures and label coverage. Candidate supported-demo targets: 95% crossing
  precision/recall and ≤10% count error on sufficiently populated bins;
  use absolute errors for sparse movements. These must be tested, not assumed.
- For stochastic simulations, predeclare paired seeds and report variation;
  repeated deterministic replay is a reproducibility check, not extra evidence.
- Include balanced, asymmetric, changing and oversaturated demand, downstream
  restriction, sensor loss/noise and nonempty initial state. No required
  improvement percentage: a correct negative result passes software integrity
  while potentially failing the commercial/control-performance hypothesis.
- Mean stopped waiting, p95, throughput and queues must identify the population
  and horizon. Preserve insertion delay, undeparted demand and unfinished trips.
  Completed-trip results need a common cohort/drain rule or explicit censoring;
  do not silently omit stranded vehicles. SUMO's waiting time, time loss and
  trip duration are distinct quantities, not interchangeable “time saved.”
  [TripInfo definitions](https://sumo.dlr.de/docs/Simulation/Output/TripInfo.html).
- On a warmed reference laptop with a saved profile, target visible analysis
  within 2–5 seconds **after media is available**, ≥10 sampled frames/s and
  p95 capture-to-observation age <300ms. Benchmark cold start, upload and decode
  separately. These are not Pi performance claims.
- Initially one-hour laptop soak; ten end-to-end rehearsals; offline, bad media,
  missing asset, full disk, killed worker, browser reload, cancellation and
  simultaneous upload tests. An interrupted run must never appear completed.
- Separate “artifacts ready,” “profile reviewed,” “sample sufficient” and
  “comparison valid.” The existing ten-arrival/two-phase UI guard is not enough
  to establish the latter states.

## Order and realistic timing

Run three workstreams in parallel, not eight isolated feature projects:

1. **Engineering:** M2 → M4 fixture → M4 reviewed site → M5/M6 → release checks.
2. **Traffic evidence:** M1 → M3 → frozen M7 protocol → held-out M7 results.
3. **Commercial:** buyer interviews, data rights, pilot sponsor, licence/privacy
   review and bottom-up R&D budget, feeding M8 throughout.

The engineer still cannot do concurrent full-time implementation on both
engineering and evidence tracks. Founder/adviser/data availability is what
makes the calendar parallelism possible.

- First internal SUMO vertical slice: approximately **5–10 working days** if
  a suitable network/data choice is available. This proves the integration,
  not traffic benefit or generality.
- Narrow, single-site investor software release: approximately **5–7 focused
  weeks remaining**, with **6–8 weeks a safer planning allowance**. The earlier
  4–6 weeks is a stretch case with ready data/review and disciplined scope, not
  a commitment for all field milestones.
- Additional sites, broad scene support, authority approval and deployment
  cannot responsibly be promised on that software timetable.

First five working days: lock the question/site and benchmark protocol; harden
and checkpoint the existing baseline; add the synthetic SUMO fixture; introduce
the policy/trajectory contract; prove same-demand baseline/adaptive results and
a basic actual-trajectory browser view. In parallel obtain annotated data and
review the real junction profile. If data is delayed, label the fixture synthetic.

## Recommended display

### Default: one workbench, three presenter views

**Watch:** the video is large, not a postage stamp. Show fresh tracks/count lines,
source name, captured/source time, processing age, mode and observed movement
counts. A saved profile avoids repeating commissioning in every demo. A new
camera position gets an explicit setup/review step. Expose uncertainty and stale
input instead of claiming every vehicle is detected.

**Compare:** two same-scale, synchronized top-down or restrained 2.5D junctions:
credible baseline and Theiatron. A small source preview remains visible and can
be expanded. Show queues, signal state, one policy reason and at most three
headline measures: modeled mean wait, p95 wait and completed/remaining vehicles.
Put the absolute baseline and adaptive values before a percentage. Keep a
per-approach fairness/detail panel available. A real road-network bottleneck
must remain visible even if adaptive cannot improve it.

**Evidence:** measured/assumed input register, profile reviewer/status, source,
model/network/config versions, scenario seed, baseline, run identifier, horizon,
all cohorts and downloadable report/replay. Separate provisional live metrics
from the completed evaluation. This is a one-click inspection, not a wall of
small print competing with the main demonstration.

Commissioning and advanced parameters belong in the operator workflow; do not
make an investor watch a long setup form or obscure them entirely. Provide an
obvious “review site” affordance and show the saved profile's review status.

### Presentation choices

| Option | Advantage | Limitation | Decision |
|---|---|---|---|
| Only photorealistic/rotating 3D | Visual spectacle | Can resemble a game; hides detection, modelling assumptions and queue comparisons | Do not lead with this |
| Only video and charts | Clear real-input evidence; simpler | Harder to show independent physical consequences of the two signal policies | Useful Watch/Evidence views, not the entire story |
| Large video + focused A/B + evidence drill-down | Demonstrates measurement, causal intervention and traceable outcomes | Requires a coherent shared session, clocks and data contract | Recommended |

Keep a selectable perspective/3D view and optional matched-vehicle follow mode;
disable auto-orbit by default. Top-down is the recommended comparison view
because storage, conflicting movements and spillback are easier to inspect.
Do not use dramatic camera motion or manually spaced traffic to sell a result.

Distinguish four modes in visible text: **file analysed now**, **live camera**,
**simulation running now** and **saved replay**. Wall-clock live observations
cannot reveal future minutes of demand. A faster-than-realtime what-if either
uses already observed file data or explicitly forecast/synthetic arrivals.
Display that source and simulation multiplier; never imply future camera input
was observed. Freeze a demand window for a reproducible final comparison.

One investor action should cause a real recalculation: select another supported
time window, switch a baseline, or apply a labelled demand adjustment to both
worlds. Do not make a slider merely speed up the winning animation, and do not
overwrite the previous result; create a new scenario/run.

The accompanying interface sketch is a concept, not a screenshot of implemented
SUMO or a source of performance numbers. Its tabs illustrate emphasis changes.

### Three-minute demonstration

| Time | What to show | What it proves |
|---|---|---|
| 0:00–0:20 | Specific buyer's problem and the site's current control | A real question, not generic AI traffic imagery |
| 0:20–0:50 | Supported footage being processed now; visible source time | Genuine perception and data freshness |
| 0:50–1:05 | Reviewed profile and measured/assumed demand | The system knows what it can and cannot infer |
| 1:05–2:05 | Synchronized A/B; one live scenario change; policy reason | The software computes decisions and physical consequences |
| 2:05–2:35 | Absolute outcome, remaining vehicles, comparison scope and evidence | Traceable result rather than a selected percentage |
| 2:35–3:00 | Named pilot objective, hardware gate and use of funds | The route from software to a business |

Keep a preflighted, permissioned case and a clearly labelled replay fallback.
Use a separate supported clip/time window chosen during the meeting to test
fresh processing; arbitrary unseen camera geometry belongs to commissioning,
not a universal on-stage promise.

Test the layout with five people unfamiliar with the project: after 30 seconds,
can they identify what is real, what is simulated, which baseline is used, and
why the controller made a decision? Record misunderstandings and revise before
spending on visual polish. This is a proposed usability check, not completed
research or a claim that one layout maximises fundraising success.

## Remaining milestones after the software release

| Milestone | Work and exit evidence | When |
|---|---|---|
| M9. Target-device bench prototype | Separate bounded capture/perception service on actual Pi/accelerator/camera; accuracy/latency, power, temperature, storage and 24–72h soak; restart/watchdog/stale-input and update rollback tests. | Early funded R&D; can overlap later software work when hardware is available |
| M10. Outdoor read-only shadow trial | Permissioned mounting and capture; day/night/rain/occlusion/mixed-traffic observations; human-labelled validation, uptime, maintenance and cost evidence. No actuation. | After bench gate and site/data/privacy arrangements |
| M11. Controller-in-loop lab integration | Approved controller/interface, reviewed movement conflicts/intergreens/pedestrian needs, request/acknowledgement semantics, fault injection, audit logging and independently effective fallback. | Parallel preparation with shadow trial; must precede field actuation |
| M12. Supervised operational pilot | Site-specific approvals/responsibilities, agreed study design, staged commissioning, operational limits, safety monitoring and stop criteria; independent evaluation of actual outcomes. | Only after shadow, lab and authority/assurance gates |
| M13. Repeatable commercial deployment | Paying customer case, installation and lifetime-cost evidence, procurement/support model, device security/identity/updates, maintenance, supply chain and repeat installations. Custom board only if justified. | After pilot evidence; do not infer production readiness from a successful demonstration |

No responsible calendar estimate for M10–M13 is possible until a site partner,
controller interface, jurisdiction and assurance plan are identified. Outdoor
evaluation is a months-scale activity dependent on conditions/access, not a
two-day extension of the demo. A particular board's inference FPS cannot prove
site-level reliability or signal safety.

The field unit does **not** need to render 3D or continuously run two SUMO
worlds. It needs dependable observations, health supervision and an authorised
interface. Keep the workstation comparison product and the field service as
separate runtime responsibilities, sharing versioned observation contracts.

## What materially improves the investment case

- Validate a specific buyer's willingness to use/pay for an assessment or pilot.
  Founder targets: several substantive buyer conversations, one scoped pilot
  sponsor and access to relevant data. A proposal or LOI is not revenue.
- Recruit a traffic-engineering reviewer. Independent review and a realistic
  baseline carry more weight than increasing the animation's apparent benefit.
- Build a costed R&D plan: labour, annotation, adviser/testing, devices, full
  installation, power, enclosures, integration, privacy/licensing, maintenance
  and contingency. Obtain quotes before stating an investment amount.
- Make the differentiation falsifiable: commissioning time, installed cost,
  offline reliability and accuracy/control performance in the target conditions.
  Existing suppliers already combine sensing and adaptive signals. VivaCity's
  programme explicitly includes independent validation and A/B testing; TfL
  describes FUSION as replacing SCOOT. The opportunity cannot simply be
  “nobody else has AI traffic lights.”
  [VivaCity programme](https://info.vivacitylabs.com/smart_junctions_early_adopter_programme),
  [TfL programme](https://content.tfl.gov.uk/londononthemove.pdf).
- Clean up all website/deck claims. The original 44.6% point-queue result is
  evidence about one scenario, not the future SUMO average or a field promise.
  Do not pair another video's imagery with it as if it were that video's result.
- Confirm footage rights, handling/retention/redaction, company/IP ownership
  and model/software licensing with appropriate reviewers before distribution
  and contractual commitments. Exporting a model does not erase its obligations.

## Defer

No SUMO fork, Unity/Unreal/CARLA rewrite, reinforcement-learning detour, city-wide
control, automatic reconstruction of arbitrary roads, custom PCB, universal
camera support or multi-tenant cloud platform for this release. Defer emissions
and monetary-savings headline claims until their inputs and appraisal are
defensible. The near-term product value is trustworthy observation, comparison
and a clear decision/report, whether or not every scenario favours adaptive.

## Immediate recommendation

Update, 11 September: the user's priority is recorded-junction reconstruction
before the next A/B renderer pass. The [recorded 3D studio](recorded-3d-studio-2026-09-11.md)
now provides the interactive renderer, source-video replay and draft planar
calibration/road tracing. This advances the M3/M6 tooling, not empirical site
validation. Next: measured ground references and tracking review, then a common
lane/turn geometry for reconstruction and SUMO. M7 evaluation and investor
release gates remain open.

Proceed with **M1 and M2**, while starting the **M4 synthetic integration fixture**
and securing **M3 data/review**. Implement Watch/Compare/Evidence as part of that
same end-to-end slice, not as a separate cosmetic rewrite. A coherent, honest
software product plus a real pilot opportunity is the recommended route; a
larger simulated percentage or more cinematic 3D cannot guarantee funding.
