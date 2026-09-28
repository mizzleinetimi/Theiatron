const assert = require("node:assert/strict");
const { test } = require("node:test");
const { present, atTime } = require("../viz/comparison.js");
const { resolveRun } = require("../viz/load-run.js");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

test("invalid run selectors never fall back to sample", () => {
  for (const query of ["?run=", "?run=../old", "?run=out/foo/bar", "?run=%3Cscript%3E"]) {
    assert.throws(() => resolveRun(query), /Invalid run/);
  }
  assert.deepEqual(resolveRun("?run=out/img-0635-final"), { run: "out/img-0635-final", base: "../out/img-0635-final" });
  assert.equal(resolveRun("").base, ".");
});

test("legacy, sparse and missing-phase comparisons cannot headline savings", () => {
  for (const result of [undefined, { sample_status: "ready", avg_wait_reduction_pct: 80 },
    { sample_status: "inconclusive", phase_arrivals: { NS: 5, EW: 2 }, headline: "80% LESS" },
    { sample_status: "ready", phase_arrivals: { NS: 20, EW: 0 }, headline: "80% LESS" }]) {
    assert.equal(present(result).text, "INCONCLUSIVE SAMPLE");
  }
});

test("all final outcomes use the canonical headline", () => {
  for (const [outcome, headline, color] of [["better", "45.0% LESS WAITING", "#46c46e"],
    ["worse", "37.4% MORE WAITING", "#e34a3f"], ["equal", "EQUAL MODELED WAIT", "#cccccc"]]) {
    const comparison = { sample_status: "ready", phase_arrivals: { NS: 10, EW: 4 }, outcome, headline };
    assert.equal(present(comparison).text, headline);
    assert.equal(present(comparison).color, color);
    assert.equal(atTime({ duration: 30, comparison }, 30, 100, 1).text, headline);
  }
});

test("intermediate verdict cannot use future arrivals", () => {
  const timeline = { duration: 100, phase_of: { north: "NS", east: "EW" },
    theiatron: { vehicles: Array.from({ length: 20 }, (_, i) => ({ t0: i * 3, a: i < 10 ? "north" : "east" })) } };
  assert.match(atTime(timeline, 10, 1, 20).text, /INCONCLUSIVE SO FAR — 4 ARRIVALS/);
  assert.match(atTime(timeline, 40, 10, 5).text, /MORE WAITING SO FAR/);
  assert.match(atTime(timeline, 40, 0, 0).text, /EQUAL MODELED WAIT/);
  assert.match(atTime(timeline, 40, 2, 0).text, /MORE WAITING \(FIXED = 0s\)/);
});

test("T-junction queue geometry tolerates an unknown exit", () => {
  // Exercise the actual renderer path helper without needing a WebGL context.
  const source = fs.readFileSync(path.join(__dirname, "../viz/app.js"), "utf8");
  const helper = source.slice(source.indexOf("const pathCache"), source.indexOf("// --- keyframes"));
  const context = vm.createContext({ LANES: { east: { P: [10, 0], f: [-1, 0] } } });
  vm.runInContext(helper, context);
  const result = vm.runInContext("pathPos(getPath('east', null), -5)", context);
  assert.equal(result.x, 15);
  assert.equal(result.z, 0);
});
