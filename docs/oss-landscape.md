# Theiatron — Open-Source Landscape

Researched 2026-08-07 via four parallel deep searches (GitHub API + web), every
repo verified live with license, stars, and last-push date. Stars/dates are as
of that day.

## Headline findings

1. **The niche is empty.** No open-source project joins real-time camera
   perception to signal actuation. The closest things are half-products:
   OpenTrafficCam (camera → trajectories → turning counts, but GPL, desktop,
   batch-only, no control) and the ATSPM lineage (DOT-grade signal metrics,
   but presupposes loop detectors + controller event logs). Every repo that
   attempts the full join is an abandoned student demo (top hit: 202★, dead
   since 2022, sim-only). Non-English ecosystems: nothing credible either.
   The offline, low-cost, autocalibrating camera→controller slot is open.
2. **One legal blocker: Ultralytics AGPL-3.0.** YOLO26n comes via the
   `ultralytics` package; Ultralytics asserts AGPL extends to trained weights
   and downstream deployment. Fine for the challenge prototype; a commercial
   pilot needs either their paid license or a model swap. A fully permissive
   stack exists today (see License hygiene).
3. **The credibility stack is off-the-shelf.** SUMO ships a validated NEMA
   dual-ring controller emulation; UXsim gives peer-reviewed queue physics in
   pure Python; RESCO carries published baselines (incl. max-pressure — the
   bar reviewers actually apply); an MIT ATSPM package computes agency-grade
   metrics. "Beats SUMO's NEMA emulation, reported as HCM control delay and
   arrivals-on-green" is a claim traffic engineers recognize; "beats a fixed
   30s timer" is not.
4. **The hardware bet: Pi 5 + Hailo-8L AI Kit** (~$70 HAT, Pi-official, MIT
   runtime, precompiled YOLO zoo: yolov8s-class at 110+ FPS on-chip, 25–60
   FPS end-to-end measured by Seeed). Zero-extra-hardware fallback: NCNN
   INT8 — Ultralytics' own Pi 5 numbers put YOLO26n @640 at 67 ms in NCNN vs
   126 ms ONNX Runtime, so ~25–30 FPS at our 416px, CPU-only.
5. **The pilot integration standard: NTCIP 1202 v03A over SNMP.** The spec
   PDF is free; modern ATC-class controllers speak it; V2X-Hub (Apache-2.0,
   USDOT, active) contains working client code to crib.

---

## ADOPT NOW

| Project | License | Stars / pushed | What it gives us |
|---|---|---|---|
| [roboflow/supervision](https://github.com/roboflow/supervision) | MIT | 49.2k / 2026-08 | `LineZone` = our count-line semantics (finite segment, anchor choice, directional counts) plus `minimum_crossing_threshold` hysteresis that defeats bbox-jitter false counts. Replaces our hand-rolled counting in ~20 lines. Also `DetectionsSmoother`, zones for queue length. |
| [roboflow/trackers](https://github.com/roboflow/trackers) | Apache-2.0 | 3.6k / 2026-08 | Clean re-implementations of ByteTrack, OC-SORT, BoT-SORT (w/ camera-motion compensation). Same algorithm we use, minus the AGPL wrapper. |
| [Tencent/ncnn](https://github.com/Tencent/ncnn) | BSD-3 | 23.7k / 2026-08 | ~2× our current CPU inference on Pi 5 (measured 67 ms vs 126 ms @640). One-line export from our existing model. INT8 path via ncnn2table. |
| [toruseo/UXsim](https://github.com/toruseo/UXsim) | MIT | 252 / 2026-07 | Pure-Python mesoscopic sim (Newell car-following, JOSS-published). Ships reactive signal-control examples. Same arrivals file drives our point-queue AND real physics → "validated against peer-reviewed traffic physics" in ~a week. |
| [eclipse-sumo/sumo](https://github.com/eclipse-sumo/sumo) | EPL-2.0* | 4.1k / 2026-08 | The heavyweight validator. `tlLogic type="NEMA"` dual-ring actuated emulation (NREL-validated), `routeSampler.py` builds demand from count-line data, TraCI lets our controller drive the sim. *NOTICE.md explicitly exempts TraCI clients from derivative-work status — licensing clean. |
| [ShawnStrasser/atspm](https://github.com/ShawnStrasser/atspm) | MIT | 21 / 2026-07 | Python ATSPM engine by an Oregon DOT signal engineer. Emit our sim/pilot events as hi-res event codes → arrivals-on-green, split failures, Purdue diagrams for free. Same pipeline serves the future live pilot. |
| [jaantollander/OneEuroFilter](https://github.com/jaantollander/OneEuroFilter) | MIT | 302 / 2023 (complete) | 1-Euro filter: causal, zero-lag jitter smoothing — better fit for the live loop than our Savitzky-Golay (which needs a symmetric window). ~50 lines to copy. |
| [mshamrai/yolov8n-visdrone](https://huggingface.co/mshamrai/yolov8n-visdrone) (HF) | OpenRAIL-ish (treat non-permissive) | — | Same-day A/B test for our nadir blindness: VisDrone-trained weights see drone-view cars COCO models miss. Experiment only; license unclear for product. |
| [obss/sahi](https://github.com/obss/sahi) | MIT | 5.5k / 2026-08 | Tiled inference recovers small/nadir vehicles without retraining. Use in the (slow) calibration pass; benchmark before the live loop. |
| [raspberrypi/picamera2](https://github.com/raspberrypi/picamera2) | BSD-2 | 1.2k / 2026-08 | First-party CSI capture — skips RTSP/decode, fewer watts, one less failure domain for the pole-mounted build. |
| [mendersoftware/mender](https://github.com/mendersoftware/mender) (+ mender-convert) | Apache-2.0 | 1.2k / 2026-08 | Atomic A/B OTA with auto-rollback; mender-convert adapts stock Pi OS. Design in from the FIRST field image — retrofitting A/B partitions is painful. |
| [gpiozero/gpiozero](https://github.com/gpiozero/gpiozero) + [joan2937/lg](https://github.com/joan2937/lg) | BSD-3 / Unlicense | 2.1k / 2026-07 | Signal-head relay actuation on Pi 5. **Trap: pigpio (in every old tutorial) does NOT work on Pi 5** (RP1 chip); lgpio/libgpiod is the path. Safety layer (fail-safe to flashing-amber, conflict monitor) is custom engineering, never an OSS import. |
| [visgl/deck.gl](https://github.com/visgl/deck.gl) / [kepler.gl](https://github.com/keplergl/kepler.gl) | MIT | 14.4k / 11.9k, active | The multi-intersection ops/city dashboard tier above our per-intersection twin (TripsLayer animates timestamped trajectories on real basemaps). |
| NTCIP 1202 v03A ([free spec PDF](https://www.ntcip.org/file/2019/07/NTCIP-1202v0328A.pdf)) + HCM control-delay/LOS vocabulary | — | — | The controller wire protocol for a real pilot (SNMP; implementable from Python) and the metric language funders/engineers expect (control delay s/veh → LOS A–F, not "% wait reduction"). |

## BUILD ON

| Project | License | Why |
|---|---|---|
| [hailo-ai/hailort](https://github.com/hailo-ai/hailort) + [model zoo](https://github.com/hailo-ai/hailo_model_zoo) + [rpi5-examples](https://github.com/hailo-ai/hailo-rpi5-examples) | MIT runtime; zoo MIT | The accelerator bet: Pi AI Kit (Hailo-8L). Zoo HEFs (yolov8n 202 FPS, yolov8s 110 FPS @640 batch-1) bypass the one closed piece (the Dataflow Compiler, needed only for custom fine-tunes, x86-hosted, free registration). Frees the whole CPU for tracking + control; thermal/solar headroom. |
| [blakeblackshear/frigate](https://github.com/blakeblackshear/frigate) | MIT | The 24/7 SBC-CV architecture blueprint, MIT so code is liftable: `frigate/detectors/plugins/` is a thin DetectionApi ABC covering exactly our hardware matrix (hailo8l/rknn/onnx/openvino/cpu) — copy it to stay accelerator-agnostic. Also per-process watchdogs, ffmpeg hw-decode presets, motion-gated inference (skip empty-intersection frames). |
| [Pi-Star-Lab/RESCO](https://github.com/Pi-Star-Lab/RESCO) | GPL-3.0 (harness only) | NeurIPS-published benchmark: wrap our controller as a RESCO agent, report against their published Fixed-Time/Max-Pressure/RL numbers on Cologne/Salt-Lake scenarios. GPL boundary: use as external harness, never vendor. |
| [LucasAlegre/sumo-rl](https://github.com/LucasAlegre/sumo-rl) | MIT | The TraCI plumbing template (phase encoding, min-green handling, per-lane queue extraction) for our SUMO bridge. |
| [usdot-fhwa-OPS/V2X-Hub](https://github.com/usdot-fhwa-OPS/V2X-Hub) | Apache-2.0 | Working NTCIP 1202 SNMP client code (SPaT + preemption plugins) to extract for the pilot's controller hop; skip the V2X superstructure. |
| [mnit-rtmc/ntcip](https://github.com/mnit-rtmc/ntcip) | Apache-2.0 | Clean-room Rust NTCIP library (sibling of Minnesota DOT's production IRIS ATMS) — best open MIB/object reference. |
| [roboflow/rf-detr](https://github.com/roboflow/rf-detr) / [Peterande/D-FINE](https://github.com/Peterande/D-FINE) | Apache-2.0 | The AGPL exit for the detector: fine-tune a nano variant on VisDrone + our own footage. Benchmark on-device early to confirm viability. |
| [airockchip/rknn-toolkit2](https://github.com/airockchip/rknn-toolkit2) | Proprietary-but-free | Backup accelerator (RK3588 boards, integrated 6-TOPS NPU, often cheaper than Pi5+Kit) if Hailo pricing/supply fails in Nigeria. Don't lead with it. |
| [tryolabs/norfair](https://github.com/tryolabs/norfair) | BSD-3 | Second-choice tracker: built-in per-object Kalman = tracking + smoothing in one, camera-motion compensation for pole sway. Maintenance slowing (~15 mo quiet). |

## REFERENCE (read, don't vendor)

- [OpenTrafficCam](https://github.com/OpenTrafficCam/OTAnalytics) OTVision/OTAnalytics/OTCamera (GPL-3.0, active, platomo GmbH): the closest whole-product analog to our vision layer — steal the section→event→flow data model and use their GUI as ground-truth validation on our footage; GPL blocks vendoring.
- [AI City Challenge 2020 Track 1 top teams](https://github.com/NVIDIAAICITYCHALLENGE/2020AICITY_Code_From_Top_Teams) + Zero-VIRUS: the best prior art on trajectory→movement assignment (parametric movement models > our fragile entry-heading clustering). Contest code, old deps, license gaps — ideas only.
- [utahudot ATSPM v5](https://github.com/OpenSourceTransportation/Atspm) (Apache-2.0, active): authoritative metric definitions + dashboard patterns; too heavy to run — compute with ShawnStrasser/atspm instead.
- [kafle1/relay](https://github.com/kafle1/relay) (AGPL, 1★, brand-new): closest concept-twin found — camera → PCU-weighted counts → weighted max-pressure with safety invariants; claims 28–44% vs *tuned* fixed timers. Mine the evaluation methodology (PCU weighting for motorcycle-heavy traffic, tuned baselines, noise-robustness sweeps, p95s); watch as competitor.
- [docwza/sumolights](https://github.com/docwza/sumolights) (GPL) + [LibSignal](https://github.com/DaRL-LibSignal/LibSignal) (NO license): Webster/max-pressure/SOTL reference implementations & cross-simulator numbers. Reimplement from equations only.
- [sidewalklabs/sumo-web3d](https://github.com/sidewalklabs/sumo-web3d) (EPL, archived): TraCI→three.js streaming patterns for evolving our twin into a live view.
- [carla-simulator/carla](https://github.com/carla-simulator/carla) (MIT, active): synthetic camera rig to stress-test detection in rain/night/occlusion pre-deployment. Way too heavy for anything else.
- [AlexxIT/go2rtc](https://github.com/AlexxIT/go2rtc) (MIT): camera-gateway resilience if we're ever forced onto IP cameras instead of CSI.
- MMITSS (abandoned): the cautionary tale — full adaptive system built on connected-vehicle penetration that never came. Camera sensing avoids that dependency.
- [a-b-street/abstreet](https://github.com/a-b-street/abstreet) (Apache): OSM ingestion + lay-audience traffic UX reference.
- Roadside auto-calibration research (deep_vp, BrnoCompSpeed — unlicensed; [OpenTrafficCam3D](https://github.com/kvuong2711/OpenTrafficCam3D) MIT): metric/ground-plane calibration for future speed/queue-length estimates. Our approach-learning fix should come from Zero-VIRUS-style movement models instead.

## SKIP

CityFlow (semi-dormant, C++ friction; UXsim+SUMO cover it) · Flow/Berkeley
(bit-rotted) · Google Coral (archived upstream, dead toolchain) ·
streetscape.gl/XVIZ (dead, protocol overkill) · BoxMOT (great bake-off tool
but AGPL — benchmark offline only) · the "smart traffic light" student-demo
corpus (value = proof the niche is empty).

## License hygiene

- **Poison for a shipped product (AGPL):** ultralytics (framework AND
  fine-tuned YOLOv8/11/26 weights per their position), BoxMOT, kafle1/relay.
- **Viral (GPL) — external tools/harnesses only, never vendored:**
  OpenTrafficCam, RESCO, sumolights, IRIS.
- **No license = all rights reserved, no copying:** LibSignal, deep_vp,
  BrnoCompSpeed, carma-streets, VisDrone dataset repo (research norms only).
- **Safe core:** supervision (MIT), trackers (Apache), sahi (MIT), ncnn
  (BSD), UXsim (MIT), atspm (MIT), Frigate (MIT), hailort (MIT), picamera2
  (BSD), mender (Apache), gpiozero (BSD), deck.gl (MIT), V2X-Hub (Apache),
  ntcip crate (Apache), RF-DETR/D-FINE/YOLOX (Apache).
- **SUMO (EPL-2.0):** NOTICE.md explicitly exempts TraCI client apps from
  derivative-work status — safe to build our harness against.
- **Fully-permissive endgame stack (exists today):** RF-DETR-nano or D-FINE
  fine-tuned on VisDrone + own footage → trackers (Apache) → supervision
  (MIT) → ncnn/hailort. Nothing in the product core would be copyleft.

## Sequenced integration plan

**Phase A — credibility (pre-showcase, no new hardware):**
1. Swap counting/tracking to supervision LineZone + trackers ByteTrack;
   A/B 1-Euro vs Savitzky-Golay on real footage. (days)
2. UXsim cross-check: same `out/events.json` arrivals through real queue
   physics; report both sims' numbers side by side. (≈1 week)
3. SUMO harness via routeSampler + TraCI: our controller vs SUMO's NEMA +
   gap-actuated + tuned Webster on replayed real arrivals. New headline:
   "beats NEMA-emulated actuated control on real demand". (1–2 weeks)
4. Emit hi-res event codes from the co-sim → ShawnStrasser/atspm →
   arrivals-on-green / split-failure charts; adopt HCM control-delay + LOS
   in all reporting. (days)
5. VisDrone-weights A/B for nadir footage; SAHI in the calibration pass.
6. NCNN INT8 export + measure on a real Pi 5 → replace "published
   references" with our own measured FPS.

**Phase B — pilot hardware:**
Pi 5 + active cooling + Hailo-8L Kit + CSI camera (picamera2) → zoo
yolov8s-class HEF → Frigate-pattern detector-plugin daemon with per-process
watchdogs + motion gating → gpiozero/lgpio + opto-isolated relay HAT with
hardware fail-safe to flashing-amber → read-only rootfs + Mender A/B OTA →
NTCIP 1202 SNMP client (crib V2X-Hub) for controller-peer mode where an ATC
controller exists.

**Phase C — product/scale:**
AGPL exit (fine-tune RF-DETR-nano/D-FINE on VisDrone + Nigerian footage) ·
PCU-weighted arrivals (motorcycle-heavy traffic; cf. relay's methodology) ·
Zero-VIRUS-style parametric movement models to replace entry-heading
clustering · deck.gl multi-intersection ops dashboard · RESCO published-
baseline comparison for the paper/pitch.
