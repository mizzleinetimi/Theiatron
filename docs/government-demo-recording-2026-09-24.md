# Theiatron — government innovation demo recording

Prepared for the requested 9 pm submission, 24 September 2026.
Target: approximately three minutes. No recording or submission is automatic.

## Open

- Full demo: http://127.0.0.1:8766/workbench/showcase.html
- Prepared footage: IMG_0635.mov, source `ui-20260912-162811-img-0635-ddba8b2c`.
- Keep the local workbench server running. All required app assets are local.
- screenmucord Dev is the recording app. Record the Chrome showcase window or
  its display, with your microphone enabled. Check the microphone source and
  make a ten-second test before the final take. Do not record private tabs,
  notifications or this script. The assistant has not started recording.
- Record in landscape; use 1080p if available. Leave sufficient time to watch
  the exported file, check sound and submit. Aim to finish a usable take well
  before 8:30 pm, rather than use the deadline for the first export.
- Close Presenter notes before recording. They are also available chapter by
  chapter on the demo page. The page is not itself a screen recorder.

## Exact shot list

| Time | What to show | What to do |
| --- | --- | --- |
| 0:00–0:25 | The problem / opening page | Introduce yourself. Show the real source image and software-prototype label. |
| 0:25–1:10 | See traffic | Select 2 minutes and 10 FPS, then Start fresh detection. Wait for boxes to move; point out tracking IDs. This is fresh inference from a recorded file. |
| 1:10–1:30 | Inspect in 3D | Next stops the demo detection session. Press Play in the recorded studio and orbit gently once. Clearly call it saved tracks on estimated geometry. |
| 1:30–2:30 | Test decisions | Keep Actuated / Service v2 / generated changing demand / seed 42. Press Compute new comparison. Both genuine SUMO worlds run; allow roughly 30 seconds plus startup. |
| 2:30–3:00 | Evidence & next step | Read the final on-screen result and long-wait tradeoff. Point to the evidence bundle. Ask for an observation-only pilot and validation support. |

The preloaded experiment is explicitly saved. Clicking Compute new comparison
creates a fresh run; the evidence chapter follows that run, not the earlier
result. It refuses to advance while the experiment is incomplete. The selected
example historically showed 7.6% less modelled mean delay, with **worse**
95th-percentile delay. Read whatever the new run actually reports; never promise
that percentage before it finishes.

## Spoken script

### 1 — The problem

Good evening. I’m [your name], founder of Theiatron. Traffic changes throughout
the day, but a fixed timer cannot see a growing queue. We are developing
camera-based traffic intelligence to help signals respond better. Today I’ll
show what our software can do, and what still needs validation.

### 2 — See traffic

This is recorded junction footage being processed now on this computer. The
boxes and tracking IDs are fresh detector output, not a prerecorded detection
animation. The software follows visible vehicles as frames arrive. This is the
perception foundation for traffic measurement. Missed detections and ID changes
still need independent evaluation. We have not yet demonstrated this on roadside
Raspberry Pi hardware.

### 3 — Inspect in 3D

Here, saved observations are reconstructed in an adjustable 3D view. This helps
us inspect movement from another angle. The road geometry, scale and vehicle
sizes are estimates, not a surveyed digital twin. That distinction matters
before making real traffic decisions.

### 4 — Test decisions

Now I’m starting a new traffic simulation. Both worlds receive the same generated
vehicles, routes and timing. One uses an actuated, presence-responsive comparator;
the other uses Theiatron’s experimental control policy. SUMO computes the vehicle
motion and delays independently in each world. We measure the difference instead
of building in a promised percentage. This tests a junction hypothesis; it is
not a claim that we have already improved traffic on this road.

### 5 — Evidence and request

The result is traceable to its inputs, controller settings and simulation logs.
In this example the average delay improves, but the longer-wait metric is
worse—so more validation and controller work are necessary. We are seeking
support for a supervised, observation-only pilot: validate with traffic engineers
and labelled footage, then benchmark affordable edge hardware. Theiatron is a
working software foundation with a clear path to testing its real-world value.

If the fresh result differs, replace the outcome sentence with: “This run shows
[read the actual direction and value]. It is a modelled result, not a field
saving.” Keep any adverse long-wait result visible and acknowledge it.

## What not to claim

- Not “45% proven savings”, “every junction improves”, or “already deployed”.
- Not “live roadside camera”: the source is a recorded file, processed afresh.
- Not “accurate digital twin”: road geometry, scale, turns and sizes are estimates.
- Not “running on Raspberry Pi”: this demonstration runs on the Mac.
- Not “the detector is already controlling this simulation live”: the selected
  comparison uses generated demand and ideal simulator sensing. A fresh
  observation-window-to-SUMO adapter is still separate work.
- Mean stopped-plus-entry delay is not total journey-time savings.
- A software test count does not establish field safety or traffic benefit.

## If something fails while recording

Stop and retake if practical. Do not narrate a stalled or saved image as live.
If fresh computation fails, use the completed saved simulation and explicitly
say: “This is a replay of a previously computed experiment.” If fresh detection
fails, saved footage can illustrate detection output, but call it saved analysis.
Do not change scenarios repeatedly to hunt for a larger percentage.

For a two-minute limit, omit the separate 3D chapter. Keep fresh detection,
the fair-comparison explanation, the evidence boundary and the pilot request.
