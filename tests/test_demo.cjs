const test = require("node:test"),
  assert = require("node:assert/strict");
const M = require("../workbench/demo-math.js");
test("policy labels preserve historical runs and identify the actuated comparator", () => {
  assert.equal(M.policyNames({}).candidate, "Theiatron pressure v1");
  const names = M.policyNames({
    baseline_policy: "actuated",
    adaptive_policy: "service-v2",
  });
  assert.equal(names.baseline, "Actuated gap-out");
  assert.equal(names.candidate, "Theiatron service v2");
});
test("front-bumper and north convention matches the recorded studio", () => {
  const p = M.pose({ id: "car", x: 10, y: 20, length: 4, angle: 90 });
  assert.equal(p.x, 8);
  assert.equal(p.z, -20);
  assert.equal(p.yaw, -Math.PI / 2);
});
test("interpolates only matching recorded simulator IDs, with no future metrics", () => {
  const w = (x, angle) => ({
    vehicles: [{ id: "a", x, y: 0, angle }],
    metrics: { time: x },
  });
  const frames = [
    { t: 1, worlds: { fixed: w(0, 350), adaptive: w(0, 350) } },
    { t: 2, worlds: { fixed: w(10, 10), adaptive: w(10, 10) } },
  ];
  frames[1].worlds.fixed.vehicles.push({ id: "future", x: 20, y: 0, angle: 0 });
  const v = M.frameAt(frames, 1.5).worlds.fixed;
  assert.equal(v.vehicles.length, 1);
  assert.equal(v.vehicles[0].x, 5);
  assert.equal(v.vehicles[0].angle, 360);
  assert.equal(v.metrics.time, 0);
  assert.equal(M.frameAt(frames, 3).worlds.fixed.vehicles.length, 2);
  assert.equal(frames[0].worlds.fixed.vehicles[0].x, 0);
});
test("negative, zero, invalid and observed outcomes do not become winning claims", () => {
  const r = {
    valid: true,
    demand_basis: "generated-not-observed",
    simulation_reduction_pct: -12.3,
  };
  assert.match(M.outcome(r), /12.3% more/);
  assert.match(M.outcome({ ...r, valid: false }), /No valid/);
  assert.match(M.outcome({ ...r, demand_basis: "observed" }), /No validated/);
  assert.doesNotMatch(
    M.outcome({ ...r, simulation_reduction_pct: null }),
    /null%/,
  );
});
