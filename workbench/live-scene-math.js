/* Fresh observations -> estimated ground poses. No recorded vehicle tracks.
   Registration is a saved camera estimate for the SAME bytes and native frame.
   Presentation filtering is causal, bounded and never extrapolates a vehicle. */
(function (root) {
  "use strict";
  const M = typeof module !== "undefined" ? require("./replay-math.js") : root.ReplayMath;
  const finitePoint = (p) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite);
  function registeredPoint(matrix, point) {
    if (!finitePoint(point) || !Array.isArray(matrix) || matrix.length !== 3 ||
        matrix.some((r) => !Array.isArray(r) || r.length !== 3 || !r.every(Number.isFinite))) return null;
    const q = matrix.map((r) => r[0] * point[0] + r[1] * point[1] + r[2]);
    if (q[2] <= 1e-6) return null;
    const p = [q[0] / q[2], q[1] / q[2]];
    return finitePoint(p) ? p : null;
  }
  const angleDelta = (from, to) => Math.atan2(Math.sin(to - from), Math.cos(to - from));
  class LivePoses {
    constructor(geometry) {
      if (geometry.schema_version !== 1 || geometry.image_size?.join() !== "1280,720" ||
          !geometry.binding?.source_run || !geometry.binding?.source_sha256)
        throw Error("Unsupported source-bound geometry");
      if (geometry.projection_kind && !["automatic-estimate", "operator-assisted-estimate"].includes(geometry.projection_kind))
        throw Error("Unsupported ground perspective evidence");
      this.geometry = geometry;
      this.projectionLabel = geometry.projection_kind === "operator-assisted-estimate"
        ? "Operator-assisted perspective · unvalidated" : "Automatic perspective · unvalidated";
      const { h, points } = M.roadWorld(geometry.calibration);
      this.h = h;
      this.points = points;
      this.registration = new Map();
      for (const row of geometry.registration || []) {
        if (!Number.isSafeInteger(row.frame_index) || row.frame_index < 0 || this.registration.has(row.frame_index))
          throw Error("Ambiguous camera frame mapping");
        this.registration.set(row.frame_index, row);
      }
      this.clear();
    }
    clear() {
      this.tracks = new Map();
      this.key = null;
      this.namespace = null;
      this.lastTime = null;
      this.result = { poses: [], hidden: 0, headingUnknown: 0, reason: "Waiting for fresh observations" };
    }
    reject(reason, hidden = 0) {
      this.clear();
      this.result.reason = reason;
      this.result.hidden = hidden;
      return this.result;
    }
    update(session, now = Date.now() / 1000) {
      const row = session?.last_observation;
      const reject = (reason) => this.reject(reason, Array.isArray(row?.detections) ? row.detections.length : 0);
      if (!session || session.state !== "running") return reject("Session not running · no live cars shown");
      if (session.source_kind !== "paced-file" || session.source_run !== this.geometry.binding.source_run ||
          session.source_sha256 !== this.geometry.binding.source_sha256)
        return reject("Source mismatch · projection disabled");
      if (!row || !Number.isFinite(row.completed_at) || !Number.isFinite(row.age_ms) || row.age_ms < 0 ||
          now - row.completed_at + row.age_ms / 1000 > 1 || now < row.completed_at - 1)
        return reject("Observations stale · cars hidden");
      if (!Number.isFinite(row.source_time_s) || !Number.isSafeInteger(row.sequence) ||
          !Number.isSafeInteger(row.frame_index) || typeof row.namespace !== "string" || !Array.isArray(row.detections))
        return reject("No exact source-frame identity · projection disabled");
      const registration = this.registration.get(row.frame_index);
      if (!registration || !["accepted", "reference"].includes(registration.status) || !registration.H)
        return reject("Camera mapping missing or rejected for this frame · cars hidden");
      const key = `${session.id}:${row.namespace}:${row.sequence}`;
      if (this.key === key) return this.result;
      if (this.namespace !== row.namespace || this.lastTime === null ||
          row.source_time_s <= this.lastTime || row.source_time_s - this.lastTime > .5) this.clear();
      this.namespace = row.namespace;
      this.lastTime = row.source_time_s;
      this.key = key;
      const current = new Map(), poses = [];
      let hidden = 0, jumps = 0;
      // Hard cap protects the renderer too; no history grows with session time.
      for (const d of row.detections.slice(0, 256)) {
        if (!Number.isSafeInteger(d.track_id) || ![2,3,5,7].includes(d.cls) || !finitePoint([d.x, d.y])) {
          hidden++; continue;
        }
        const pixel = registeredPoint(registration.H, [d.x, d.y]);
        const ground = pixel && M.project(this.h, pixel);
        if (!ground || !M.inside(ground, this.points)) { hidden++; continue; }
        const id = `${row.namespace}:${d.track_id}`;
        if (current.has(id)) { hidden++; continue; }
        const previous = this.tracks.get(id);
        const dt = previous ? row.source_time_s - previous.t : 0;
        if (previous && Math.hypot(ground[0] - previous.raw[0], ground[1] - previous.raw[1]) > Math.max(3, dt * 25)) {
          hidden++; jumps++; continue; // No interpolation through jumps; reacquire on the next observation.
        }
        const alpha = dt ? 1 - Math.exp(-dt / .12) : 1;
        const position = previous
          ? ground.map((v, i) => previous.position[i] + alpha * (v - previous.position[i])) : ground;
        if (!M.inside(position, this.points)) { hidden++; continue; }
        const history = [...(previous?.history || []), [row.source_time_s, ...ground]]
          .filter((p) => row.source_time_s - p[0] <= .6).slice(-8);
        const first = history[0], dx = ground[0] - first[1], dz = ground[1] - first[2];
        let yaw = previous?.yaw ?? 0, headingKnown = previous?.headingKnown ?? false;
        if (row.source_time_s - first[0] >= .2 && Math.hypot(dx, dz) > .35) {
          const target = Math.atan2(-dx, -dz);
          yaw = headingKnown ? yaw + Math.min(1, dt / .2) * angleDelta(yaw, target) : target;
          headingKnown = true;
        }
        const track = { t: row.source_time_s, raw: ground, position, history, yaw, headingKnown,
                        classId: previous?.classId ?? d.cls };
        current.set(id, track);
        poses.push({ id, x: position[0], z: position[1], yaw, classId: track.classId, headingKnown,
                     from: previous ? { x: previous.position[0], z: previous.position[1], yaw: previous.yaw } : null,
                     arrivedAt: now, pixel, confidence: d.conf });
      }
      hidden += Math.max(0, row.detections.length - 256);
      this.tracks = current; // Missing IDs are removed immediately; never bridge an occlusion.
      this.result = { poses, hidden, jumps, headingUnknown: poses.filter((p) => !p.headingKnown).length,
                     reason: `Fresh detections · ${this.projectionLabel}`, sourceTime: row.source_time_s };
      return this.result;
    }
    sample(now = Date.now() / 1000) {
      return this.result.poses.map((p) => {
        // Up to 120 ms visual easing BETWEEN received poses only. No future prediction.
        const u = Math.max(0, Math.min(1, (now - p.arrivedAt) / .12));
        if (!p.from) return p;
        const x = p.from.x + u * (p.x - p.from.x), z = p.from.z + u * (p.z - p.from.z);
        // Concave roads can make even short straight segments leave the road.
        if (!M.inside([x,z], this.points)) return p;
        return { ...p, x, z, yaw: p.from.yaw + u * angleDelta(p.from.yaw, p.yaw) };
      });
    }
  }
  const api = { LivePoses, registeredPoint };
  if (typeof module !== "undefined") module.exports = api;
  else root.LiveSceneMath = api;
})(typeof window !== "undefined" ? window : globalThis);
