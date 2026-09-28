/* Shared, side-effect-free presentation of evidence. Safe to require in tests. */
const TheiatronComparison = (() => {
  function present(result) {
    // Historic runs lack phase coverage/provenance: do not grandfather their
    // headline percentages into the stricter evidence policy.
    const phases = result?.phase_arrivals;
    if (result?.sample_status !== "ready" || !phases?.NS || !phases?.EW) {
      return { text: "INCONCLUSIVE SAMPLE", color: "#ffb724",
        reason: (result?.sample_reasons || ["Re-analyze this run with the current evidence checks."]).join(" ") };
    }
    return { text: result.headline || "COMPARISON UNAVAILABLE",
      color: result.outcome === "better" ? "#46c46e" : result.outcome === "worse" ? "#e34a3f" : "#cccccc",
      reason: "Exploratory modeled queue wait; not a measured travel-time saving." };
  }

  function atTime(timeline, t, adaptiveWait, fixedWait) {
    if (t >= timeline.duration) return present(timeline.comparison);
    // No knowledge of future arrivals is used for an intermediate verdict.
    const counts = { NS: 0, EW: 0 };
    let total = 0;
    for (const v of timeline.theiatron.vehicles) {
      if (v.t0 > t) continue;
      total++;
      const phase = timeline.phase_of?.[v.a];
      if (phase in counts) counts[phase]++;
    }
    if (total < 10 || !counts.NS || !counts.EW) {
      return { text: `INCONCLUSIVE SO FAR — ${total} ARRIVALS`, color: "#ffb724",
        reason: "Need at least 10 arrivals and demand on both phases." };
    }
    const a = Math.round(adaptiveWait * 100) / 100;
    const f = Math.round(fixedWait * 100) / 100;
    const pct = f ? Math.round(1000 * (f - a) / f) / 10 : null;
    const outcome = a < f ? "better" : a > f ? "worse" : "equal";
    const headline = outcome === "equal" ? "EQUAL MODELED WAIT" : pct === null
      ? "MORE WAITING (FIXED = 0s)"
      : `${pct === 0 ? "<0.1" : Math.abs(pct).toFixed(1)}% ${outcome === "better" ? "LESS" : "MORE"} WAITING`;
    return present({ sample_status: "ready", phase_arrivals: counts, outcome, headline: `${headline} SO FAR` });
  }
  return { present, atTime };
})();
if (typeof module !== "undefined") module.exports = TheiatronComparison;
