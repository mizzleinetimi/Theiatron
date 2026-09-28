const test = require("node:test");
const assert = require("node:assert/strict");
const { vehiclePose } = require("../workbench/view.js");
test("SUMO front bumper is converted to vehicle centre, metres not pixels", () => {
  const north = vehiclePose({ x: 10, y: 20, angle: 0, length: 4 });
  assert.equal(north.x, 10);
  assert.equal(north.z, -18);
  const east = vehiclePose({ x: 10, y: 20, angle: 90, length: 4 });
  assert.equal(east.x, 8);
  assert.equal(east.z, -20);
  assert.equal(east.yaw, -Math.PI / 2);
});
