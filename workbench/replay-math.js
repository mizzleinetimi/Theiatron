/* Pure reconstruction helpers, shared with Node regression tests. No queue model. */
(function (root) {
  "use strict";
  const cross = (a, b, c) =>
    (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
  function solve(matrix, rhs) {
    const a = matrix.map((row, i) => [...row, rhs[i]]),
      n = rhs.length;
    for (let k = 0; k < n; k++) {
      let pivot = k;
      for (let i = k + 1; i < n; i++)
        if (Math.abs(a[i][k]) > Math.abs(a[pivot][k])) pivot = i;
      if (Math.abs(a[pivot][k]) < 1e-10)
        throw Error(
          "Calibration is degenerate. Spread the four corners apart.",
        );
      [a[pivot], a[k]] = [a[k], a[pivot]];
      const divisor = a[k][k];
      for (let j = k; j <= n; j++) a[k][j] /= divisor;
      for (let i = 0; i < n; i++)
        if (i !== k) {
          const f = a[i][k];
          for (let j = k; j <= n; j++) a[i][j] -= f * a[k][j];
        }
    }
    return a.map((row) => row[n]);
  }
  function homography(anchors, width, depth) {
    if (
      !Array.isArray(anchors) ||
      anchors.length !== 4 ||
      anchors.some((p) => p.length !== 2 || p.some((v) => !Number.isFinite(v)))
    )
      throw Error("Four finite image points are required.");
    if (
      !Number.isFinite(width) ||
      !Number.isFinite(depth) ||
      width < 2 ||
      depth < 2 ||
      width > 150 ||
      depth > 150
    )
      throw Error("Assumed dimensions must be 2–150 m.");
    const turns = anchors.map((p, i) =>
      cross(p, anchors[(i + 1) % 4], anchors[(i + 2) % 4]),
    );
    if (!turns.every((v) => v > 100) && !turns.every((v) => v < -100))
      throw Error("Place A–B–C–D in order around a convex ground rectangle.");
    const world = [
      [-width / 2, -depth / 2],
      [width / 2, -depth / 2],
      [width / 2, depth / 2],
      [-width / 2, depth / 2],
    ];
    const matrix = [],
      rhs = [];
    anchors.forEach((p, i) => {
      const [x, y] = [p[0] / 1280, p[1] / 720],
        [u, v] = world[i];
      matrix.push(
        [x, y, 1, 0, 0, 0, -u * x, -u * y],
        [0, 0, 0, x, y, 1, -v * x, -v * y],
      );
      rhs.push(u, v);
    });
    const h = [...solve(matrix, rhs), 1];
    // Homographies have arbitrary global sign. Choose the side containing the
    // calibrated ground rectangle, not the side containing image origin (0,0).
    // A real horizon inside the image commonly gives H[8] < 0 after this choice.
    const cx = anchors.reduce((a, p) => a + p[0], 0) / anchors.length / 1280,
      cy = anchors.reduce((a, p) => a + p[1], 0) / anchors.length / 720;
    return h[6] * cx + h[7] * cy + h[8] < 0 ? h.map((v) => -v) : h;
  }
  function project(h, point) {
    const x = point[0] / 1280,
      y = point[1] / 720,
      w = h[6] * x + h[7] * y + h[8];
    if (w < 1e-5) return null; // do not project across/behind the planar horizon
    const p = [
      (h[0] * x + h[1] * y + h[2]) / w,
      (h[3] * x + h[4] * y + h[5]) / w,
    ];
    return p.every(Number.isFinite) && Math.hypot(...p) < 500 ? p : null;
  }
  function roadWorld(calibration) {
    const h = homography(
      calibration.anchors,
      calibration.width_m,
      calibration.depth_m,
    );
    if (calibration.road.length < 3)
      throw Error("Trace the visible road outline before opening this scene.");
    const points = calibration.road.map((p) => project(h, p));
    if (points.some((p) => !p))
      throw Error(
        "Road crosses the calibration horizon. Move the anchors onto the road plane.",
      );
    // Reject self-crossing outlines before they reach the triangulator.
    const between = (a, b, p) =>
      Math.min(a[0], b[0]) <= p[0] &&
      p[0] <= Math.max(a[0], b[0]) &&
      Math.min(a[1], b[1]) <= p[1] &&
      p[1] <= Math.max(a[1], b[1]);
    for (let i = 0; i < points.length; i++) {
      const a = points[i],
        b = points[(i + 1) % points.length];
      if (Math.hypot(a[0] - b[0], a[1] - b[1]) < 0.001)
        throw Error("Remove duplicate road corners.");
      for (let j = i + 2; j < points.length; j++) {
        if (i === 0 && j === points.length - 1) continue;
        const c = points[j],
          d = points[(j + 1) % points.length],
          u = cross(a, b, c),
          v = cross(a, b, d),
          w = cross(c, d, a),
          x = cross(c, d, b);
        if (
          (u * v < 0 && w * x < 0) ||
          (u === 0 && between(a, b, c)) ||
          (v === 0 && between(a, b, d)) ||
          (w === 0 && between(c, d, a)) ||
          (x === 0 && between(c, d, b))
        )
          throw Error(
            "Road outline crosses itself. Trace around its perimeter.",
          );
      }
    }
    return { h, points };
  }
  function inside(point, polygon) {
    let found = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const a = polygon[i],
        b = polygon[j];
      if (
        a[1] > point[1] !== b[1] > point[1] &&
        point[0] < ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0]
      )
        found = !found;
    }
    return found;
  }
  function unproject(h, ground) {
    const [u, v] = ground;
    // Solve image coordinates directly; both equations eliminate the common
    // homogeneous scale and work with either valid global matrix sign.
    const a = h[0] - u * h[6],
      b = h[1] - u * h[7],
      c = u * h[8] - h[2],
      d = h[3] - v * h[6],
      e = h[4] - v * h[7],
      f = v * h[8] - h[5],
      det = a * e - b * d;
    if (Math.abs(det) < 1e-10) return null;
    const p = [((c * e - b * f) / det) * 1280, ((a * f - c * d) / det) * 720];
    return p.every(Number.isFinite) && project(h, p) ? p : null;
  }
  function groundGrid(polygon, spacing = 5) {
    if (!Number.isFinite(spacing) || spacing < 1 || polygon.length < 3)
      return [];
    const lines = [];
    for (const axis of [0, 1]) {
      const values = polygon.map((p) => p[axis]),
        start = Math.ceil(Math.min(...values) / spacing),
        end = Math.floor(Math.max(...values) / spacing);
      if (end - start > 1000)
        throw Error("Ground grid exceeds supported bounds");
      for (let k = start; k <= end; k++) {
        const fixed = k * spacing,
          cuts = [];
        for (let i = 0; i < polygon.length; i++) {
          const a = polygon[i],
            b = polygon[(i + 1) % polygon.length];
          if (a[axis] > fixed === b[axis] > fixed) continue;
          const u = (fixed - a[axis]) / (b[axis] - a[axis]);
          cuts.push(a[1 - axis] + u * (b[1 - axis] - a[1 - axis]));
        }
        cuts.sort((a, b) => a - b);
        for (let i = 0; i + 1 < cuts.length; i += 2) {
          if (cuts[i + 1] - cuts[i] < 1e-7) continue;
          const a = [],
            b = [];
          a[axis] = b[axis] = fixed;
          a[1 - axis] = cuts[i];
          b[1 - axis] = cuts[i + 1];
          lines.push([a, b]);
        }
      }
    }
    return lines;
  }
  function prepareTracks(raw, h) {
    return ["counted", "extras"].flatMap((kind) =>
      (raw[kind] || []).map((r, index) => {
        const segments = [];
        const breaks = new Set(r.breaks || []);
        const originals = new Map(
          (r.raw_pts || r.pts || []).map((p) => [p[0], p.slice(1)]),
        );
        let segment = [],
          previous = null;
        for (const entry of r.pts || []) {
          const p =
            entry.length === 3 && entry.every(Number.isFinite)
              ? project(h, entry.slice(1))
              : null;
          if (!p || entry[0] < 0 || (previous && entry[0] <= previous[0])) {
            if (segment.length) segments.push(segment);
            segment = [];
            previous = null;
            continue;
          }
          // Legacy exports downsample some tracks. Gaps are unknown, not licence
          // to bridge occlusions or teleport an ID into a plausible route.
          if (
            previous &&
            (entry[0] - previous[0] > 0.61 || breaks.has(entry[0]))
          ) {
            if (segment.length) segments.push(segment);
            segment = [];
          }
          segment.push([entry[0], ...p, entry[1], entry[2]]);
          previous = entry;
        }
        if (segment.length) segments.push(segment);
        // Precompute continuous, unwrapped headings once per segment. A small
        // residual box wobble must not flip a stopped car through 180 degrees.
        for (const segment of segments) stableHeadings(segment);
        return {
          id:
            r.id ||
            (kind === "counted" ? `${r.a}:${r.n}` : `uncounted:${index + 1}`),
          classId: r.class_id,
          confidence: r.mean_confidence,
          classConsistency: r.class_consistency,
          arrival: kind === "counted" ? `${r.a}:${r.n}` : null,
          counted: kind === "counted",
          segments,
          originals,
          refined: !!r.raw_pts,
        };
      }),
    );
  }
  function stableHeadings(p) {
    let angle = null;
    for (let i = 0; i < p.length; i++) {
      let a = i,
        b = i;
      while (a > 0 && p[i][0] - p[a - 1][0] < 0.6) a--;
      while (b < p.length - 1 && p[b + 1][0] - p[i][0] < 0.6) b++;
      const dx = p[b][1] - p[a][1],
        dz = p[b][2] - p[a][2],
        distance = Math.hypot(dx, dz);
      const moving =
        distance > 0.35 && distance / Math.max(0.1, p[b][0] - p[a][0]) > 0.45;
      if (moving) {
        const target = Math.atan2(-dx, -dz);
        if (angle === null) angle = target;
        else {
          const delta = Math.atan2(
            Math.sin(target - angle),
            Math.cos(target - angle),
          );
          // Reject a noisy abrupt reversal in a near-stop. Genuine sustained
          // reversal is a tracking review issue, not random per-frame yaw.
          if (Math.abs(delta) < Math.PI * 0.65 || distance > 1.5) {
            const dt = i ? p[i][0] - p[i - 1][0] : 0.1;
            angle += Math.max(
              -dt * 1.7,
              Math.min(dt * 1.7, delta * (1 - Math.exp(-dt / 0.22))),
            );
          }
        }
      }
      p[i][5] = angle;
    }
    // Offline inference: the first reliable movement may orient a leading stop.
    // A segment with no reliable movement keeps an explicitly unknown heading.
    const first = p.find((v) => v[5] !== null)?.[5];
    if (first !== undefined)
      for (const v of p) {
        if (v[5] !== null) break;
        v[5] = first;
      }
  }
  function sampleTrack(track, time, stabilize = false) {
    const p = track.segments.find(
      (s) => s.length > 1 && time >= s[0][0] && time <= s.at(-1)[0],
    );
    if (!p) return null;
    let lo = 0,
      hi = p.length - 1;
    while (lo + 1 < hi) {
      const mid = (lo + hi) >> 1;
      if (p[mid][0] <= time) lo = mid;
      else hi = mid;
    }
    const u = (time - p[lo][0]) / (p[hi][0] - p[lo][0]);
    const raw = [1, 2].map((k) => p[lo][k] + u * (p[hi][k] - p[lo][k]));
    let position = raw;
    // Optional display-only local linear fit. No retiming or alteration of
    // saved points. Do not smooth across missing observations.
    if (stabilize) {
      const nearby = p.filter((v) => Math.abs(v[0] - time) < 0.25);
      if (nearby.length >= 3) {
        const n = nearby.length,
          dt = nearby.map((v) => v[0] - time),
          sum = dt.reduce((a, b) => a + b, 0),
          sum2 = dt.reduce((a, b) => a + b * b, 0),
          den = n * sum2 - sum * sum;
        if (den > 1e-8)
          position = [1, 2].map(
            (k) =>
              (sum2 * nearby.reduce((a, v) => a + v[k], 0) -
                sum * nearby.reduce((a, v, i) => a + v[k] * dt[i], 0)) /
              den,
          );
      }
    }
    const yaw0 = p[lo][5],
      yaw1 = p[hi][5];
    const known = yaw0 !== null && yaw0 !== undefined;
    const heading =
      yaw0 !== null && yaw0 !== undefined
        ? yaw0 + u * ((yaw1 ?? yaw0) - yaw0)
        : 0;
    const original0 = track.originals?.get(p[lo][0]) || p[lo].slice(3, 5),
      original1 = track.originals?.get(p[hi][0]) || p[hi].slice(3, 5);
    return {
      id: track.id,
      classId: track.classId,
      confidence: track.confidence,
      classConsistency: track.classConsistency,
      arrival: track.arrival,
      x: position[0],
      z: position[1],
      raw,
      yaw: heading,
      headingKnown: known,
      counted: track.counted,
      pixel: [3, 4].map((k) => p[lo][k] + u * (p[hi][k] - p[lo][k])),
      rawPixel: [0, 1].map(
        (k) => original0[k] + u * (original1[k] - original0[k]),
      ),
      refined: track.refined,
      sampleTime: p[lo][0],
    };
  }
  function cameraPixel(registration, time, referencePoint) {
    // Reference-plane estimates must be reprojected into the moving video for
    // the evidence overlay. Never bridge a rejected/missing camera frame.
    const frames = registration?.frames;
    if (!frames?.length || !Number.isFinite(time)) return null;
    let lo = 0,
      hi = frames.length - 1;
    if (time < frames[lo].t - 1e-6 || time > frames[hi].t + 1e-6) return null;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (frames[mid].t <= time) lo = mid;
      else hi = mid;
    }
    const warp = (row) => {
      if (!["accepted", "reference"].includes(row.status)) return null;
      const h = row.inverse_H,
        [x, y] = referencePoint;
      if (!h) return null;
      const w = h[2][0] * x + h[2][1] * y + h[2][2];
      if (w < 1e-6) return null;
      const p = [
        (h[0][0] * x + h[0][1] * y + h[0][2]) / w,
        (h[1][0] * x + h[1][1] * y + h[1][2]) / w,
      ];
      return p.every(Number.isFinite) ? p : null;
    };
    if (Math.abs(time - frames[lo].t) < 1e-6) return warp(frames[lo]);
    if (Math.abs(time - frames[hi].t) < 1e-6) return warp(frames[hi]);
    if (
      frames[hi].t - frames[lo].t >
      Math.max(0.15, (registration.cadence_s || 0.1) * 1.1)
    )
      return null;
    const a = warp(frames[lo]),
      b = warp(frames[hi]);
    if (!a || !b) return null;
    const u = (time - frames[lo].t) / (frames[hi].t - frames[lo].t);
    return a.map((v, i) => v + u * (b[i] - v));
  }
  function projectionStatus(data) {
    if (data?.assistance)
      return "Operator-assisted perspective from selected road directions. Parallel lines and perpendicular axes were supplied by the operator; flat ground and camera intrinsics are assumed. Click sensitivity was checked, not physical accuracy. Metres remain estimated. Saved manual geometry is not replaced by automatic refinement.";
    const r = data?.refinement, g = r?.ground_quality;
    if (!r || r.stale || !g)
      return "Waiting for a source-specific camera-plane estimate.";
    const temporal = g.temporal;
    const evidence = temporal
      ? ` Multi-frame check: ${temporal.frames} frames · ${temporal.persistent_segments} persistent markings. Repeated markings count once; temporal agreement is not measured accuracy.`
      : "";
    if (!r.ground_projection) {
      const reason = String(g.reason || g.status).replace(/[.!?]+$/, "");
      const caveat = data.default_projection_kind === "unrectified-image-plane" && !data.revision
        ? "The preview preserves image-plane shape; perspective and physical dimensions have NOT been recovered."
        : "Manual mapping is available in Review road.";
      return `Camera perspective needs review: ${reason}. ${caveat}${evidence}`;
    }
    const method = g.evidence === "temporal-road-direction-families"
      ? "repeated road markings (orthogonality assumed; time blocks agree)"
      : g.evidence === "two-road-direction-families"
        ? "two road-line families (orthogonality assumed)" : "scene directions";
    const fov = Number.isFinite(g.horizontal_fov_deg) ? `${g.horizontal_fov_deg.toFixed(1)}° horizontal field of view` : "field of view unavailable";
    const horizon = Number.isFinite(g.horizon_at_centre_y) ? `horizon at image y=${g.horizon_at_centre_y.toFixed(0)}` : "tilted horizon";
    const sensitivity = Number.isFinite(g.sensitivity?.shape_error_p95)
      ? ` Road-shape sensitivity p95: ${(100*g.sensitivity.shape_error_p95).toFixed(1)}% (not measured accuracy).` : "";
    return `Camera estimate from ${method}: ${fov} · ${horizon}. Shape corrected under flat-ground / orthogonal-scene assumptions. Metres remain estimated.${sensitivity}${evidence}`;
  }
  const api = {
    homography,
    project,
    roadWorld,
    inside,
    prepareTracks,
    sampleTrack,
    cameraPixel,
    unproject,
    groundGrid,
    projectionStatus,
  };
  if (typeof module !== "undefined") module.exports = api;
  else root.ReplayMath = api;
})(typeof window !== "undefined" ? window : globalThis);
