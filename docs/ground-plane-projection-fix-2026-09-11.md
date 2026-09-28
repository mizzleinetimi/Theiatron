# Ground-plane perspective correction — 11 September 2026

## What was wrong

The detected road polygon was not the main problem. Two projection issues made
the distant footprint too narrow:

1. The initial manually positioned rectangle implied a horizon at approximately
   image y = −448 at the centre of IMG_0635. That introduces much weaker depth
   expansion than the new camera estimate.
2. Both the browser and Python validator normalized the homography to H33 = 1
   and rejected negative projection denominators. A homography has arbitrary
   global sign; valid ground below an in-image horizon can have a negative
   denominator in that representation. The guard was rejecting valid calibration
   rectangles. It now chooses the sign from the calibrated rectangle, while
   continuing to reject points across the true horizon.

The matrix relates two projective planes, not independently scaled image axes;
see [OpenCV's homography and perspective-correction explanation](https://docs.opencv.org/4.13.0/d9/dab/tutorial_homography.html).

## Implementation

`theiatron/ground_plane.py` extracts long static line segments, excluding detected
vehicles in the reference frame. It proposes two horizontal vanishing families,
balances their support with a third upright family, and estimates focal length
under centred-principal-point / square-pixel / orthogonal-scene assumptions.
Camera rays are intersected with a flat ground plane and expressed in an
orthonormal ground basis. The road outline is not redrawn or forced rectangular.

Only a uniform scale and in-plane rotation transfer the existing assumed
reference span. This preserves the recovered metric aspect rather than squeezing
the two ground axes independently. An inverse-projected ground rectangle encodes
the resulting mapping in the existing editable calibration format.

The automatic projection is source-bound and code-fingerprinted, separate from
the saved manual draft and the automatically detected road polygon. Rejected
camera estimates produce no stock-camera fallback. Original detections, times,
IDs, counts and SUMO artifacts are unchanged.

## Current clip

Run: `ui-20260911-091101-img-0635-07326ab0`, retained IMG_0635.mov.

- Estimated horizontal field of view: 64.37°; focal length: 1016.83 pixels in the
  normalized 1280 × 720 image.
- Estimated horizon at the image centre: y = 185.51 pixels.
- Supporting static line segments: 15 and 46 in the two horizontal families,
  9 in the upright family. These are fitting supports, not independent accuracy
  validation. Upright angular residual median is approximately 0.36°.
- The original assumed 50 m reference span supplies uniform display scale; no
  actual road distance has been measured. The derived editable rectangle is
  22.5 × 12 m at that assumed scale, not an independently detected rectangle.
- The same mapping projects all 38 automatic boundary vertices and every
  refined vehicle anchor. Observed motion remains separate from simulated motion.

## Inspect it

Open the recorded studio. **Undo camera perspective** is enabled by default when
the source has an accepted camera proposal; switch it off to compare the old
manual projection. **Show ground grid** adds equal assumed 5 m squares on the
3D road. **Review road** shows that grid inverse-projected into the reference
image, plus the estimated horizon. Opening the editor does not save a draft.

The image grid should narrow into the distance; its 3D squares remain equal.
Road and vehicle positions always use the same selected mapping. The camera
video overlay still reprojects motion-compensated estimates into each video frame.

## Verification and limits

237 Python and 21 JavaScript tests pass. New tests cover valid in-image horizons,
continued rejection above the horizon, equal near/far road widths, recovery of
known metric aspect from a synthetic pinhole scene, synthetic static-line camera
fitting, inverse-grid projection, blank-image refusal and immutable road outlines.

This fixes the projection pipeline and supplies a defensible camera estimate;
it is not a surveyed digital twin. Lens distortion, non-orthogonal architecture,
sloping/uneven roads and inaccurate line families can bias the estimate. Absolute
scale needs measured references; physical correctness needs independent ground
points. The reconstructed footprint remains limited by the camera crop and
occlusions—its irregular edges are not all detected kerbs or actual road ends.
