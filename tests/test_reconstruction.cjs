const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../workbench/replay-math.js");
const fs = require("node:fs"), vm = require("node:vm");
const anchors = [
  [100, 200],
  [1000, 220],
  [1200, 680],
  [0, 650],
];
const h = M.homography(anchors, 40, 15);
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-7, `${a} != ${b}`);
test("temporal evidence labels preserve rejected and stale geometry boundaries", () => {
  const data = {
    default_projection_kind: "unrectified-image-plane",
    refinement: {ground_projection:null, ground_quality: {
      status:"unstable-road-perspective", reason:"Not stable.",
      temporal:{frames:12, persistent_segments:74}
    }}
  };
  const label = M.projectionStatus(data);
  assert.match(label, /Not stable\. The preview/);
  assert.match(label, /physical dimensions have NOT been recovered/);
  assert.match(label, /12 frames · 74 persistent markings/);
  assert.doesNotMatch(label, /time blocks agree|Shape corrected|Not stable\.\./);
  data.refinement.stale = true;
  assert.match(M.projectionStatus(data), /^Waiting/);
  assert.doesNotMatch(M.projectionStatus(data), /74 persistent/);
});
test("accepted temporal cameras disclose assumptions and do not imply measured accuracy", () => {
  const data = {refinement:{ground_projection:{}, ground_quality:{
    evidence:"temporal-road-direction-families",horizontal_fov_deg:75,
    horizon_at_centre_y:null,sensitivity:{shape_error_p95:.02},
    temporal:{frames:12,persistent_segments:70}
  }}};
  const label = M.projectionStatus(data);
  assert.match(label, /repeated road markings/);
  assert.match(label, /orthogonality assumed; time blocks agree/);
  assert.match(label, /tilted horizon/);
  assert.match(label, /Metres remain estimated/);
  assert.match(label, /2.0% \(not measured accuracy\)/);
});
test("the actual replay status panel handles rejected, stale and missing camera evidence", () => {
  const source = fs.readFileSync(require.resolve("../workbench/replay.js"), "utf8");
  const panel = source.slice(source.indexOf("  function showRefinement()"), source.indexOf("  function workerStatus("));
  const elements = {};
  const data = {default_projection_kind:"unrectified-image-plane", refinement:{
    stale:false, calibration:{}, ground_projection:null, ground_quality:{status:"unstable-road-perspective"},
    diagnostics:{samples:100,isolated_outliers:0,segment_breaks:2},
    road_quality:{status:"automatic-candidate"}, camera_status:"background-registered-estimate"
  }};
  const context = vm.createContext({M,data,$:id => elements[id] ||= {}});
  vm.runInContext(`${panel}; showRefinement();`,context);
  assert.equal(elements.perspectiveCorrection.disabled,true);
  assert.equal(elements.automaticRoad.disabled,false);
  assert.match(elements.refinementStatus.textContent,/Ground projection: unstable-road-perspective/);
  assert.match(elements.projectionStatus.textContent,/physical dimensions have NOT been recovered/);
  data.refinement.stale = true;
  vm.runInContext("showRefinement();",context);
  assert.equal(elements.automaticRoad.disabled,true);
  assert.match(elements.refinementStatus.textContent,/no longer match/);
  data.refinement = null;
  vm.runInContext("showRefinement();",context);
  assert.match(elements.projectionStatus.textContent,/Waiting/);
});
test("projective mapping exactly maps the four supplied ground corners", () => {
  const targets = [
    [-20, -7.5],
    [20, -7.5],
    [20, 7.5],
    [-20, 7.5],
  ];
  anchors.forEach((p, i) =>
    M.project(h, p).forEach((v, j) => close(v, targets[i][j])),
  );
});

test("in-image horizon is valid and equal-width road expands correctly with depth", () => {
  const anchors = [
      [500, 400],
      [780, 400],
      [920, 650],
      [360, 650],
    ],
    calibration = { anchors, width_m: 12, depth_m: 20, road: anchors },
    { h, points } = M.roadWorld(calibration);
  assert.ok(
    h[8] < 0,
    "ground-facing sign must not be tied to the image origin",
  );
  close(
    Math.hypot(points[1][0] - points[0][0], points[1][1] - points[0][1]),
    12,
  );
  close(
    Math.hypot(points[2][0] - points[3][0], points[2][1] - points[3][1]),
    12,
  );
  for (let i = 0; i < 4; i++)
    M.unproject(h, points[i]).forEach((v, k) => close(v, anchors[i][k]));
  assert.equal(
    M.project(h, [640, 100]),
    null,
    "pixels above the true horizon must still fail closed",
  );
  const grid = M.groundGrid(points, 5);
  assert.ok(grid.length >= 5);
  for (const line of grid)
    for (const p of line)
      assert.ok(
        p[0] >= -6.00001 &&
          p[0] <= 6.00001 &&
          p[1] >= -10.00001 &&
          p[1] <= 10.00001,
      );
});
test("collapsed, concave and crossing calibration points cannot render", () => {
  for (const p of [
    [
      [0, 0],
      [10, 0],
      [20, 0],
      [30, 0],
    ],
    [
      [0, 0],
      [100, 0],
      [20, 20],
      [0, 100],
    ],
    [
      [0, 0],
      [100, 100],
      [100, 0],
      [0, 100],
    ],
  ])
    assert.throws(() => M.homography(p, 30, 12));
  assert.throws(() => M.homography(anchors, NaN, 12));
  assert.throws(() => M.homography(anchors, 30, Infinity));
});
test("new cameras must have a traced road and cannot silently get a sample road", () => {
  assert.throws(
    () => M.roadWorld({ anchors, width_m: 40, depth_m: 15, road: [] }),
    /Trace/,
  );
  assert.throws(
    () =>
      M.roadWorld({
        anchors,
        width_m: 40,
        depth_m: 15,
        road: [
          [100, 300],
          [800, 600],
          [800, 300],
          [100, 600],
        ],
      }),
    /crosses/,
  );
  assert.equal(M.inside([500, 400], anchors), true);
  assert.equal(M.inside([1279, 10], anchors), false);
});
test("interpolation keeps observed timestamps and exact raw sample anchors", () => {
  const raw = {
    counted: [
      {
        a: "north",
        n: 1,
        pts: [
          [1, 300, 400],
          [1.1, 310, 400],
          [1.2, 320, 400],
        ],
      },
    ],
    extras: [],
  };
  const before = JSON.stringify(raw),
    t = M.prepareTracks(raw, h)[0];
  const p = M.sampleTrack(t, 1.1);
  assert.equal(p.id, "north:1");
  close(p.pixel[0], 310);
  M.project(h, [310, 400]).forEach((v, i) => close(v, [p.x, p.z][i]));
  const half = M.sampleTrack(t, 1.05);
  close(half.pixel[0], 305);
  assert.equal(M.sampleTrack(t, 0.99), null);
  assert.equal(M.sampleTrack(t, 1.21), null);
  M.sampleTrack(t, 1.1, true);
  assert.equal(JSON.stringify(raw), before);
});
test("occlusion gaps are never filled with an invented route", () => {
  const t = M.prepareTracks(
    {
      extras: [
        {
          pts: [
            [0, 300, 400],
            [0.1, 310, 400],
            [1, 450, 400],
            [1.1, 460, 400],
          ],
        },
      ],
    },
    h,
  )[0];
  assert.equal(t.segments.length, 2);
  assert.equal(M.sampleTrack(t, 0.5), null);
  assert.ok(M.sampleTrack(t, 1.05));
});
test("sampling is deterministic when seeking backward and stabilization preserves a linear path", () => {
  const affine = M.homography(
    [
      [0, 0],
      [1279, 0],
      [1279, 719],
      [0, 719],
    ],
    40,
    20,
  );
  const t = M.prepareTracks(
    {
      extras: [
        {
          pts: Array.from({ length: 12 }, (_, i) => [
            i * 0.1,
            100 + i * 15,
            400,
          ]),
        },
      ],
    },
    affine,
  )[0];
  const a = M.sampleTrack(t, 0.45, true);
  M.sampleTrack(t, 0.9, true);
  assert.deepEqual(M.sampleTrack(t, 0.45, true), a);
  const b = M.sampleTrack(t, 0.45, false);
  close(a.x, b.x);
  close(a.z, b.z);
  assert.equal(a.headingKnown, true);
});
test("unknown stationary heading is explicit and invalid projection fails closed", () => {
  const t = M.prepareTracks(
    {
      extras: [
        {
          pts: [
            [0, 400, 400],
            [0.1, 400, 400],
            [0.2, 400, 400],
          ],
        },
      ],
    },
    h,
  )[0];
  assert.equal(M.sampleTrack(t, 0.1).headingKnown, false);
  assert.equal(M.project([1, 0, 0, 0, 1, 0, 0, 0, -1], [10, 10]), null);
});

const affineGround = M.homography(
  [
    [0, 0],
    [1279, 0],
    [1279, 719],
    [0, 719],
  ],
  40,
  20,
);
test("tiny stationary box wobble never becomes a rotating vehicle", () => {
  const pts = Array.from({ length: 60 }, (_, i) => [
    i / 10,
    500 + Math.sin(i * 1.3) * 1.2,
    450 + Math.cos(i * 1.9) * 1.2,
  ]);
  const t = M.prepareTracks({ extras: [{ pts }] }, affineGround)[0];
  for (let i = 0; i < pts.length; i++) {
    const p = M.sampleTrack(t, i / 10);
    assert.equal(p.headingKnown, false);
    close(p.yaw, 0);
  }
});
test("heading holds through a stop without freezing or editing its position", () => {
  const pts = Array.from({ length: 70 }, (_, i) => [
    i / 10,
    i < 25 ? 200 + 4 * i : 296 + Math.sin(i) * 0.8,
    450 + (i < 25 ? 0 : Math.cos(i) * 0.8),
  ]);
  const t = M.prepareTracks({ extras: [{ pts }] }, affineGround)[0];
  const heading = M.sampleTrack(t, 3.5).yaw;
  for (let i = 36; i < pts.length; i++) {
    const p = M.sampleTrack(t, i / 10);
    assert.equal(p.headingKnown, true);
    close(p.yaw, heading);
    close(p.pixel[0], pts[i][1]);
    close(p.pixel[1], pts[i][2]);
  }
});
test("sustained slow motion is never snapped to a stationary anchor", () => {
  const pts = Array.from({ length: 70 }, (_, i) => [
    i / 10,
    400 + i * 0.12,
    450 + i * 0.03,
  ]);
  const t = M.prepareTracks({ extras: [{ pts }] }, affineGround)[0];
  let previousX = -Infinity;
  for (let i = 0; i < pts.length; i++) {
    const p = M.sampleTrack(t, i / 10);
    assert.ok(p.x > previousX);
    previousX = p.x;
    close(p.pixel[0], pts[i][1]);
    close(p.pixel[1], pts[i][2]);
  }
});
test("a turn across the yaw boundary remains continuous and seek-independent", () => {
  const pts = Array.from({ length: 61 }, (_, i) => {
    const u = i / 60;
    return [i / 10, 500 + 120 * (u - 0.5) ** 2, 100 + 400 * u];
  });
  const t = M.prepareTracks({ extras: [{ pts }] }, affineGround)[0];
  const yaws = pts.map((p) => M.sampleTrack(t, p[0]).yaw);
  assert.ok(yaws[0] < Math.PI && yaws.at(-1) > Math.PI);
  for (let i = 1; i < yaws.length; i++)
    assert.ok(Math.abs(yaws[i] - yaws[i - 1]) < 0.18);
  const expected = M.sampleTrack(t, 2.35);
  M.sampleTrack(t, 5.9);
  M.sampleTrack(t, 0.01);
  assert.deepEqual(M.sampleTrack(t, 2.35), expected);
});
test("explicit discontinuities reset heading and do not bridge adjacent samples", () => {
  const pts = [
    [0, 100, 450],
    [0.1, 120, 450],
    [0.2, 140, 450],
    [0.3, 700, 450],
    [0.4, 680, 450],
    [0.5, 660, 450],
  ];
  const raw = { extras: [{ id: "track:4", pts, breaks: [0.3] }] };
  const before = JSON.stringify(raw);
  const t = M.prepareTracks(raw, affineGround)[0];
  assert.equal(t.segments.length, 2);
  assert.equal(M.sampleTrack(t, 0.25), null);
  const beforeBreak = M.sampleTrack(t, 0.15);
  const afterBreak = M.sampleTrack(t, 0.35);
  close(Math.abs(beforeBreak.yaw - afterBreak.yaw), Math.PI);
  assert.equal(afterBreak.id, "track:4");
  assert.equal(JSON.stringify(raw), before);
});
test("refinement retains separate raw evidence and original timestamps", () => {
  const raw = {
    counted: [
      {
        id: "track:11",
        a: "east",
        n: 2,
        class_id: 5,
        mean_confidence: 0.91,
        class_consistency: 0.8,
        pts: [
          [1, 300, 400],
          [1.1, 310, 401],
          [1.2, 320, 402],
        ],
        raw_pts: [
          [1, 298, 404],
          [1.1, 318, 399],
          [1.2, 316, 405],
        ],
        breaks: [],
      },
    ],
  };
  const before = JSON.stringify(raw);
  const t = M.prepareTracks(raw, affineGround)[0];
  const observed = M.sampleTrack(t, 1.1);
  assert.deepEqual(observed.pixel, [310, 401]);
  assert.deepEqual(observed.rawPixel, [318, 399]);
  assert.equal(observed.sampleTime, 1.1);
  assert.equal(observed.arrival, "east:2");
  assert.equal(observed.classId, 5);
  assert.equal(observed.refined, true);
  const between = M.sampleTrack(t, 1.05);
  close(between.pixel[0], 305);
  close(between.rawPixel[0], 308);
  assert.equal(JSON.stringify(raw), before);
});

test("camera overlay inverts reference coordinates without bridging rejected frames", () => {
  const row = (t, shift) => ({
    t,
    status: "accepted",
    inverse_H: [
      [1, 0, shift],
      [0, 1, 0],
      [0, 0, 1],
    ],
  });
  const registration = {
    cadence_s: 0.1,
    frames: [
      row(0.1, 10),
      row(0.2, 20),
      { t: 0.3, status: "rejected", inverse_H: null },
      row(0.4, 40),
    ],
  };
  assert.deepEqual(M.cameraPixel(registration, 0.1, [200, 300]), [210, 300]);
  close(M.cameraPixel(registration, 0.15, [200, 300])[0], 215);
  assert.equal(M.cameraPixel(registration, 0.25, [200, 300]), null);
  assert.equal(M.cameraPixel(registration, 0.3, [200, 300]), null);
  assert.equal(M.cameraPixel(registration, 0.35, [200, 300]), null);
  assert.equal(M.cameraPixel(registration, 0.5, [200, 300]), null);
  assert.equal(M.cameraPixel(registration, 0, [200, 300]), null);
  assert.deepEqual(M.cameraPixel(registration, 0.4, [200, 300]), [240, 300]);
  assert.equal(
    M.cameraPixel({ frames: [row(0.1, 10), row(0.5, 50)] }, 0.2, [200, 300]),
    null,
  );
});
