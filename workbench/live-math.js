(function (root) {
  function freshness(session, now = Date.now() / 1000) {
    if (!session?.last_observation)
      return { text: "No observations yet.", stale: true };
    const age = Math.max(0, now - session.last_observation.completed_at);
    const running = ["starting", "running", "stopping"].includes(session.state);
    return {
      text: running
        ? `${age.toFixed(1)}s since last observation`
        : `Session ${session.state} · saved final preview`,
      stale: !running || age > 1,
    };
  }
  function value(number, suffix = "", digits = 1) {
    return Number.isFinite(number) ? number.toFixed(digits) + suffix : "—";
  }
  const api = { freshness, value };
  if (typeof module !== "undefined") module.exports = api;
  else root.LiveMath = api;
})(typeof window !== "undefined" ? window : globalThis);
