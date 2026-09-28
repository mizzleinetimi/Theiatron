/* Rendering interpolation only. Metrics and identities remain simulator output. */
(function (root) {
  function pose(v) {
    const a = (v.angle * Math.PI) / 180;
    return {
      id: v.id,
      classId: 2,
      x: v.x - (Math.sin(a) * v.length) / 2,
      z: -v.y + (Math.cos(a) * v.length) / 2,
      yaw: -a,
    };
  }
  function frameAt(frames, t) {
    if (!frames.length) return null;
    let lo = 0,
      hi = frames.length - 1;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (frames[mid].t <= t) lo = mid;
      else hi = mid - 1;
    }
    const a = frames[lo],
      b = frames[Math.min(lo + 1, frames.length - 1)];
    const ratio =
      b.t > a.t ? Math.max(0, Math.min(1, (t - a.t) / (b.t - a.t))) : 0;
    const worlds = {};
    for (const name of ["fixed", "adaptive"]) {
      const next = new Map(b.worlds[name].vehicles.map((v) => [v.id, v]));
      worlds[name] = {
        ...a.worlds[name],
        vehicles: a.worlds[name].vehicles.map((v) => {
          const w = next.get(v.id);
          if (!w) return v;
          const angle = ((w.angle - v.angle + 540) % 360) - 180;
          return {
            ...v,
            x: v.x + (w.x - v.x) * ratio,
            y: v.y + (w.y - v.y) * ratio,
            angle: v.angle + angle * ratio,
          };
        }),
      };
    }
    return { ...a, worlds };
  }
  function outcome(report) {
    if (!report?.valid)
      return "No valid completed result — inspect diagnostics.";
    if (report.demand_basis !== "generated-not-observed")
      return "Recorded arrivals tested on estimated geometry. No validated traffic-benefit claim.";
    const p = report.simulation_reduction_pct;
    if (!Number.isFinite(p))
      return "No percentage comparison is available for this experiment.";
    return `${Math.abs(p).toFixed(1)}% ${p >= 0 ? "less" : "more"} modelled delay · this synthetic experiment only`;
  }
  function policyNames(scenario = {}) {
    return {
      baseline:
        scenario.baseline_policy === "actuated"
          ? "Actuated gap-out"
          : "Fixed timing",
      candidate:
        scenario.adaptive_policy === "service-v2"
          ? "Theiatron service v2"
          : "Theiatron pressure v1",
    };
  }
  const api = { pose, frameAt, outcome, policyNames };
  if (typeof module !== "undefined") module.exports = api;
  else root.DemoMath = api;
})(typeof window !== "undefined" ? window : globalThis);
