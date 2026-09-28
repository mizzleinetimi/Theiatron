# Assisted perspective → fresh-detection 3D — 24 September 2026

## Delivered

The recorded studio and continuous perception lab can now use the same explicitly
saved operator-assisted perspective and road outline. An automatic ground-plane
fit is no longer required when a supported assisted save exists. Saved assisted
geometry takes precedence as a whole: automatic refinement cannot substitute a
different road outline or projection for it.

The live geometry endpoint reproduces the assisted fit from the stored direction
lines and original input draft, checks its algorithm hashes, and compares the
result and quality report with the saved revision. It serves geometry and camera
transforms only, never cached vehicle trajectories. The combined geometry
identity includes both the saved calibration and refinement revisions.

The live panel distinguishes **Operator-assisted perspective · unvalidated**
from **Automatic perspective · unvalidated**, reports supported native frames
and the prepared sampling cadence, and keeps those limitations visible when
the view is paused. Every new session reloads geometry, even on the same clip;
Reload road refreshes it explicitly during a session. Late requests cannot
replace a newer source. Both analysed and visual-only sources link back to their
own road studio; the studio has a direct Try fresh detection link.

Selecting footage now loads that source's road readiness before detection starts.
A different completed session no longer overwrites the selected clip or carries
its old preview, metrics or report into the new clip's display. An actually active
session remains visible and owns the busy controls. Late preview images cannot
reappear after changing the selected source.

## Required operator flow

1. Open the source's recorded studio and Review road.
2. Mark defensible parallel ground edges in two perpendicular directions.
3. Check the preview; explicitly save only an acceptable assisted estimate.
4. Wait for source-bound refinement to finish. A changed draft invalidates the
   old refinement; cached camera registration may be reusable, but must be
   included in a fresh refinement bound to the saved draft.
5. Choose Try fresh detection. Use the prepared cadence (10 FPS for the retained
   showcase recordings) and start detection. Boxes and 3D positions come from
   fresh inference. Road and camera geometry remain prepared estimates.

Ordinary manual anchor saves, unsaved previews, outdated guided fits, unsupported
reference plates, unavailable/rejected camera mappings, changed source bytes and
stale observations do not gain permission to project vehicles. The existing exact
native-frame match, source hash, discontinuity and stale-data checks remain.

## Boundaries

- `intersection.mp4` still has **no saved assisted correction** and remains
  unrectified. This feature does not manufacture a successful calibration for it.
- Operator selection must reflect real scene geometry. Perturbation stability
  and reproduction do not prove semantic correctness or physical accuracy.
- All scale and vehicle dimensions remain estimated. There is no new speed,
  queue, unique-count or traffic-savings claim.
- No online camera calibration, RTSP-to-3D support or Pi performance is implied.
- Fresh observation windows feeding SUMO remain a separate next milestone. A
  reviewed counting/movement adapter is required; drawing cars in 3D is not that
  adapter, and visual-only recordings still have no arrival counts.

## Verification

The full suite passes: **337 Python tests and 58 JavaScript tests**.
Tests cover saved assisted-fit reproduction, untouched raw observations,
automatic-road precedence, outdated algorithm/quality/calibration rejection,
unsupported registration, manual-save demotion, and actual token-protected HTTP
preview → save → registered live-geometry retrieval on an isolated synthetic
source. UI tests cover labels, cadence, late responses and same-source session
revision refresh. Synthetic tests are not calibration of the user's footage.

Browser smoke checks confirmed fresh boxes and moving 3D cars on the existing
IMG_0635 automatic geometry, then zero live cars at session completion. The new
studio-to-live link for `intersection.mp4` kept that source selected even after
the IMG_0635 session completed; its unresolved geometry was still rejected.
No guided correction was saved to either real clip during these checks.

Two 30-second shared-Mac sessions were retained as
`live-20260924-084906-3a8cdee2` and `live-20260924-085014-48e3b141`.
The second session's p95 scheduled-file observation age was 470 ms, with 15
observations above 300 ms and 5 stale-frame rejections. This is a UI/flow smoke
test, not latency sign-off; controlled-load performance work remains necessary.

## Remaining roadmap

1. Finish/review one showcase junction's actual geometry and approach mapping.
2. Freeze a source-bound fresh observation window, review count lines/movements,
   and hand its demand to paired SUMO without inventing arrivals or scaling them.
3. Repeat the complete presenter journey and validate clean-machine installation.
4. Validate perception against human labels and test further sites/conditions.
5. Benchmark the edge pipeline on real camera/Pi hardware before selective native
   optimization or any roadside actuation work.
