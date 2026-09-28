# Guided perspective fallback

22 September 2026 · recorded-junction demonstrator · branch `codex`

## Operator flow

1. Open the recorded studio and choose **Review road**.
2. In **Guided perspective**, choose **Mark four direction lines**.
3. Click both endpoints of A1, then A2: two long ground edges that are parallel
   in the real scene. They need not look parallel in the camera image.
4. Mark B1 and B2 along a second real-world direction perpendicular to A. Do not
   assume arbitrary junction arms are perpendicular. Avoid car roofs, shadows,
   curved kerbs and edges at different heights. The guide numbers all eight clicks.
   Numeric endpoint entry and **Undo last endpoint** support precise adjustment.
5. Choose **Check & preview in 3D**. Invalid or sensitive selections are rejected
   without applying a correction. A successful preview is prominently labelled
   **UNSAVED ASSISTED PREVIEW** and can be orbited/inspected against the footage.
6. Choose **Adjust lines**, **Discard preview**, or **Save assisted estimate**.
   Previewing does not save. Discard restores the saved scene and preserves any
   manual draft edits that preceded the guide.

No measured distance is required to try this. The software transfers the existing
assumed display scale uniformly; it does not measure road width, distance or speed.
Selected directions provide additional assumptions, not a survey.

## Geometry and provenance

- The four lines specify two vanishing-direction pairs for a flat road, under a
  pinhole camera, centred principal point and square-pixel assumptions.
- Each selected segment must be at least 80 normalized image pixels long, with
  separate edges in each pair. Image-parallel/degenerate directions, unsupported
  focal estimates, unsafe horizons and invalid projected footprints are rejected.
- A 64-trial, 1-pixel endpoint-perturbation check requires at least 52 supported
  fits and shape-error p95 no greater than 0.08. This checks click sensitivity,
  not semantic correctness, measured accuracy or field performance.
- Preview is read-only. Saving recomputes the estimate from the original lines
  and draft on the server; it does not trust a client-provided matrix or approval.
- Source binding and the base saved revision must match. A changed source/draft
  is rejected. Immutable saved revisions include selected lines, input draft,
  quality/assumption report and implementation hashes. All remain unvalidated.
- The recorded viewer explicitly labels saved assisted estimates and keeps them
  separate from automatic estimates. Automatic refresh does not replace an
  operator's saved assisted geometry. A later ordinary manual save is recorded
  as a manual draft, without retaining an assisted-result approval label.

At this 22 September checkpoint the feature changed the recorded studio only.
The [24 September live bridge](assisted-live-bridge-2026-09-24.md) subsequently
added explicitly saved assisted geometry to fresh-detection 3D, with reproduced
fit and source-bound registration checks. Neither change edits raw tracks or
arrival counts or produces new traffic-savings evidence.

## Verification and current clip

- Full test suites: **326 Python tests and 54 JavaScript tests passed**.
- Backend tests cover known synthetic geometry, true aspect preservation,
  click-sensitive selections, invalid inputs, source/revision mismatch,
  read-only previews and immutable assisted saves.
- Real HTTP tests cover token protection, request bounds, preview, save, reload
  and stale-revision rejection against an isolated synthetic test source.
- UI tests execute the actual preview/save/discard handlers, including stale
  asynchronous responses, failed-save retry and retention of earlier manual edits.
- Browser smoke testing used explicitly synthetic direction coordinates on an
  **unsaved** preview, then discarded them. This was a UI test, not calibration
  of the filmed junction. The real source API was checked afterwards:
  `revision: null`, `assistance: null` for
  `ui-20260920-190946-intersection-56e8bdae`.

The current overhead clip therefore remains **unrectified** until a defensible
selection is provided and reviewed. The guide is a fallback for operator-supplied
evidence, not a claim that arbitrary footage can now be calibrated automatically.
