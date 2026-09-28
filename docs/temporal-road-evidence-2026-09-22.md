# Multi-frame road-direction evidence

22 September 2026 · local software demonstrator · branch `codex`

## Implemented

When the single-frame camera estimators cannot provide a usable projection,
refinement now checks road-line evidence across up to 12 frames spread over the
clip. Each frame must have an accepted, exact native-frame registration to the
reference image. Failed registrations and incorrectly decoded frame indices are
excluded; there is no interpolation or identity fallback.

Line detection runs on the native normalized frame **before** any warping.
Detected vehicle boxes mask intersecting segments, including narrow boxes that
would fall between spaced point samples. Only then are endpoints projected into
the reference plane and checked against the estimated road outline. This avoids
manufacturing geometric evidence from temporal-median seams or warped image
borders. No new detector model or video export is required.

Repeated, overlapping collinear segments are consolidated. A candidate must occur
in at least three distinct frames, and each frame contributes at most one segment
to its median endpoints. This prevents repeated observations of one marking from
being counted as many independent lines. Persistence still does not prove a line
is on the road: shadows, static occluders and appearance-mask errors can remain.

The existing camera, horizon, support and sensitivity gates are unchanged. An
accepted pooled camera must additionally agree with cameras estimated separately
from the earlier and later halves of the sampled frames. Both halves must pass
the same gates, and normalized shape disagreement must not exceed 0.08. These are
engineering rejection criteria, not measured accuracy or statistical confidence.
The two time blocks share estimated camera registration and scene assumptions.

An existing successful single-frame estimate stays primary. All estimates remain
source-bound and code-hashed; a post-computation raw-video hash check also rejects
footage changed during refinement. Counting, controller evaluation and savings
results are untouched.

## Real footage result

Current source: `ui-20260920-190946-intersection-56e8bdae` (`intersection.mp4`).

- 12 requested native frames were decoded correctly, spanning 0.1001–119.9198
  source seconds, with no decode failures.
- 633 eligible line observations consolidated into **73 persistent segments**.
- The pooled camera still failed sensitivity: **7/64** perturbed fits remained
  supported, below the required 52. The shape-error p95 of 0.04790 applies only
  to those seven surviving fits and must not be presented as accuracy or as a
  passing result.
- The pooled failure stops promotion before time-block acceptance. There is no
  ground projection, so this remains an **UNRECTIFIED PREVIEW** and is not ready
  for the live 3D bridge. It is not a newly recovered physical road shape.
- Final refinement revision:
  `605e87d524b99578cad4e11b5f8013beae997bc682aaa24a01887ae1025634b2`.

The previous IMG_0635 run (`ui-20260912-162811-img-0635-ddba8b2c`) retains its
single-frame camera-plane candidate without invoking the temporal fallback.
Its scale remains estimated, not surveyed. Refreshed revision:
`84979b640e12d13edeacb2d1005c683ef9ddc51446f5390f38009795be8140d1`.

Full registration is unchanged. The faster experimental matcher from the previous
checkpoint is still excluded from production. This milestone adds an optional
offline analysis stage, not a new real-time performance claim.

## Verification

- Python: **315 tests passed**. JavaScript: **48 tests passed**.
- Synthetic known-camera tests cover changing occlusion and line noise, repeated
  edges within one frame, disjoint time-block disagreement, missing later
  evidence and insufficient/invalid inputs.
- Capture tests reject mismatched native frame positions and registrations whose
  status is rejected even if a matrix remains present. Projection bounds remain
  active after temporal fitting; no observations are rewritten.
- Browser testing caught and fixed a status-panel variable error. A regression
  now executes the actual panel function with rejected, stale and missing camera
  evidence. The refreshed studio displays the frame/segment counts, refusal
  reason and unrectified warning alongside synchronized replay.

## Remaining gap

Multi-frame visibility is now used, but more observations from the same estimated
reference plane do not guarantee identifiable camera geometry. The current clip
still needs better direction/intrinsic evidence or an explicitly labelled,
operator-assisted reference. Do not lower the sensitivity threshold just to make
the road look plausible. Automatic geometry on arbitrary footage, measured scale,
physical-camera ingestion and Raspberry Pi performance remain unfinished.
