/* Theiatron 3D replay — twin-frame rebase.
   Two worlds, same recorded vehicles, different signal policies — both built
   in the digital twin's coordinate frame: ONE global image->world affine maps
   the ground (a clean plate extracted from the footage), every count line,
   and every car's real recorded trajectory (Savitzky-Golay smoothed). Cars
   are Kenney Car Kit CC0 glTF models riding their real paths, diverging from
   the footage only while a red light holds them.
   Vanilla Three.js r147 UMD, file:// safe. */

const DUR = TIMELINE.duration;

// --- twin frame --------------------------------------------------------------
const AF = TIMELINE.twin_affine;  // wx = a*px + b*py + c ; wz = d*px + e*py + f
const CLTW = TIMELINE.count_lines_tw || {};
const IMG_W = 1280, IMG_H = 720;
function imgToWorld(px, py) {
  return [AF[0] * px + AF[1] * py + AF[2], AF[3] * px + AF[4] * py + AF[5]];
}
const _corners = [[0, 0], [IMG_W, 0], [0, IMG_H], [IMG_W, IMG_H]].map((c) => imgToWorld(c[0], c[1]));
const minX = Math.min(..._corners.map((c) => c[0])), maxX = Math.max(..._corners.map((c) => c[0]));
const minZ = Math.min(..._corners.map((c) => c[1])), maxZ = Math.max(..._corners.map((c) => c[1]));
const GW = maxX - minX, GH = maxZ - minZ;
const CX = minX + GW / 2, CZ = minZ + GH / 2;

// --- geometry constants (world scale derived from the mapping itself:
//     a car in this footage is ~52 px long, same rule as the twin view) ------
const PX_SCALE = Math.hypot(AF[0], AF[3]);
const CAR_LEN = Math.max(2.5, 52 * PX_SCALE);
const SC = CAR_LEN / 4.4;          // twin units per old schematic unit
const CAR_GAP = 2.6 * SC, SLOT = CAR_LEN + CAR_GAP;
const SPAWN_DIST = 150 * SC;
const APPROACH_SPEED = 14 * SC;
const PROMOTE_TIME = 1.4;
const TRAIL_Y = 0.35 * SC;

// Real lane geometry from the calibration: each approach's count line and
// inbound direction, mapped into the twin frame by the exporter.
const LANES = {};
for (const [_name, _cl] of Object.entries(CLTW)) {
  const [_p1, _p2] = _cl.line;
  LANES[_name] = { f: _cl.dir, P: [(_p1[0] + _p2[0]) / 2, (_p1[1] + _p2[1]) / 2], line: _cl.line };
}
const OPP = { north: "south", south: "north", east: "west", west: "east" };

function outLane(arm) {
  const { f, P } = LANES[arm];
  const along = P[0] * f[0] + P[1] * f[1];
  const lat = [P[0] - f[0] * along, P[1] - f[1] * along];
  return { dir: [-f[0], -f[1]], P: [-lat[0] + f[0] * along, -lat[1] + f[1] * along] };
}

const pathCache = new Map();
function getPath(entry, exit) {
  const key = entry + ">" + exit;
  if (pathCache.has(key)) return pathCache.get(key);
  const E = LANES[entry], X = outLane(exit);
  const A = E.P, B = X.P;
  // control point at the junction center's projection onto the inbound ray
  const along = Math.max(2 * SC, -(E.P[0] * E.f[0] + E.P[1] * E.f[1]));
  const C = [E.P[0] + E.f[0] * along, E.P[1] + E.f[1] * along];
  const pts = [A.slice()];
  for (let k = 1; k <= 14; k++) {
    const u = k / 14, w0 = (1 - u) * (1 - u), w1 = 2 * u * (1 - u), w2 = u * u;
    pts.push([w0 * A[0] + w1 * C[0] + w2 * B[0], w0 * A[1] + w1 * C[1] + w2 * B[1]]);
  }
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  }
  const p = { entry: E, pts, cum, Lint: cum[cum.length - 1], exitDir: X.dir, B };
  pathCache.set(key, p);
  return p;
}

function pathPos(path, s) {
  const E = path.entry;
  if (s <= 0) return { x: E.P[0] + E.f[0] * s, z: E.P[1] + E.f[1] * s, tan: E.f };
  if (s >= path.Lint) {
    const e = s - path.Lint;
    return { x: path.B[0] + path.exitDir[0] * e, z: path.B[1] + path.exitDir[1] * e,
             tan: path.exitDir };
  }
  const { pts, cum } = path;
  let i = 1;
  while (cum[i] < s) i++;
  const seg = cum[i] - cum[i - 1] || 1, u = (s - cum[i - 1]) / seg;
  return {
    x: pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * u,
    z: pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * u,
    tan: [(pts[i][0] - pts[i - 1][0]) / seg, (pts[i][1] - pts[i - 1][1]) / seg],
  };
}

// --- keyframes (queue behaviour) --------------------------------------------
function buildKeyframes(scn) {
  const perApproach = {};
  TIMELINE.approaches.forEach((a) => (perApproach[a] = []));
  scn.vehicles.forEach((v, i) => {
    v.id = i;
    v.kf = [];
    perApproach[v.a].push(v);
  });
  for (const a of TIMELINE.approaches) {
    const evts = [];
    perApproach[a].forEach((v) => {
      evts.push({ t: v.t0, kind: 0, v });
      if (v.t1 !== null) evts.push({ t: v.t1, kind: 1, v });
    });
    evts.sort((x, y) => x.t - y.t || x.kind - y.kind);
    const queue = [];
    const slotS = (i) => -(SC + i * SLOT);
    for (const e of evts) {
      const v = e.v;
      v.path = v.path || getPath(v.a, v.exit || OPP[v.a]);
      if (e.kind === 0) {
        const slot = queue.length;
        const s = slotS(slot);
        const lead = Math.max(v.t0 - (v.ts ?? v.t0 - 6), 0.5);
        const spawnS = -Math.min(SPAWN_DIST, Math.max(20 * SC, APPROACH_SPEED * lead));
        v.kf.push([v.t0 - lead, spawnS]);
        v.kf.push([e.t, s]);
        queue.push(v);
      } else {
        const idx = queue.indexOf(v);
        queue.splice(idx, 1);
        const cross = v.cross || 4.0;
        v.kf.push([e.t, v.kf[v.kf.length - 1][1]]);
        v.kf.push([e.t + cross, v.path.Lint]);
        v.kf.push([e.t + cross + 2.2, v.path.Lint + 36 * SC]);
        queue.forEach((w, j) => {
          const cur = w.kf[w.kf.length - 1][1];
          const tgt = slotS(j);
          if (tgt > cur + 0.01) {
            w.kf.push([e.t + 0.2, cur]);
            w.kf.push([e.t + 0.2 + PROMOTE_TIME, tgt]);
          }
        });
      }
    }
  }
  return scn.vehicles;
}

function posAt(v, t) {
  const kf = v.kf;
  if (t < kf[0][0]) return null;
  if (v.t1 !== null && t > v.t1 + (v.cross || 4.0) + 2.7) return null;
  let s = kf[kf.length - 1][1];
  for (let i = 0; i < kf.length - 1; i++) {
    if (t >= kf[i][0] && t <= kf[i + 1][0]) {
      const [ta, sa] = kf[i], [tb, sb] = kf[i + 1];
      const u = tb > ta ? (t - ta) / (tb - ta) : 1;
      const e = u * u * (3 - 2 * u);
      s = sa + (sb - sa) * e;
      break;
    }
  }
  return s;
}

// --- real recorded paths, Savitzky-Golay smoothed ----------------------------
// SG window 9, poly order 2: the standard treatment for CV-extracted vehicle
// trajectories (NGSIM/highD lineage) - kills bbox jitter, keeps real
// acceleration and curvature.
const SG = [-21, 14, 39, 54, 59, 54, 39, 14, -21].map((c) => c / 231);

function sgSmooth(pw) {
  const n = pw.length;
  if (n < 9) return pw.map((p) => p.slice());
  const out = [];
  for (let i = 0; i < n; i++) {
    let x = 0, z = 0;
    for (let k = -4; k <= 4; k++) {
      const j = Math.min(n - 1, Math.max(0, i + k));
      x += SG[k + 4] * pw[j][1];
      z += SG[k + 4] * pw[j][2];
    }
    out.push([pw[i][0], x, z]);
  }
  return out;
}

function buildRealPath(v) {
  // GLOBAL twin frame (v.tw): one shared transform for every car, so all
  // relative geometry is preserved exactly as filmed — no per-lane anchoring.
  if (!v.tw || v.tw.length < 5) return null;
  const pw = sgSmooth(sgSmooth(v.tw));  // two passes: residual p99 spikes gone
  const cum = [0];
  for (let i = 1; i < pw.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pw[i][1] - pw[i - 1][1], pw[i][2] - pw[i - 1][2]));
  }
  let s0 = 0;
  for (let i = 0; i < pw.length - 1; i++) {
    if (pw[i][0] <= v.t0 && v.t0 <= pw[i + 1][0]) {
      const u = (v.t0 - pw[i][0]) / Math.max(pw[i + 1][0] - pw[i][0], 1e-6);
      s0 = cum[i] + (cum[i + 1] - cum[i]) * u;
      break;
    }
    if (pw[i][0] > v.t0) break;
    s0 = cum[i + 1];
  }
  return { pw, cum, s0, tEnd: pw[pw.length - 1][0] };
}

function realSAt(rp, tq) {
  const { pw, cum, s0 } = rp;
  if (tq <= pw[0][0]) return cum[0] - s0;
  if (tq >= rp.tEnd) return cum[cum.length - 1] - s0;
  let i = 0;
  while (i < pw.length - 2 && pw[i + 1][0] < tq) i++;
  const u = (tq - pw[i][0]) / Math.max(pw[i + 1][0] - pw[i][0], 1e-6);
  return cum[i] + (cum[i + 1] - cum[i]) * u - s0;
}

function realPosAt(rp, s) {
  const { pw, cum, s0 } = rp;
  const target = s + s0;
  if (target <= 0) {
    const d = _tan(pw[0], pw[1]);
    return { x: pw[0][1] + d[0] * target, z: pw[0][2] + d[1] * target, tan: d };
  }
  const L = cum[cum.length - 1];
  if (target >= L) {
    const a = pw[pw.length - 2], b = pw[pw.length - 1];
    const d = _tan(a, b);
    return { x: b[1] + d[0] * (target - L), z: b[2] + d[1] * (target - L), tan: d };
  }
  let i = 1;
  while (cum[i] < target) i++;
  const seg = cum[i] - cum[i - 1] || 1;
  const u = (target - cum[i - 1]) / seg;
  return {
    x: pw[i - 1][1] + (pw[i][1] - pw[i - 1][1]) * u,
    z: pw[i - 1][2] + (pw[i][2] - pw[i - 1][2]) * u,
    tan: _tan(pw[i - 1], pw[i]),
  };
}

function _tan(a, b) {
  const dx = b[1] - a[1], dz = b[2] - a[2];
  const n = Math.hypot(dx, dz) || 1;
  return [dx / n, dz / n];
}

function lightAt(scn, approach, t) {
  const arr = scn.lights[approach];
  let cur = arr[0][1];
  for (const [tt, st] of arr) { if (tt <= t) cur = st; else break; }
  return cur;
}

// --- text sprites -----------------------------------------------------------
function textSprite(text, { fg = "#fff", bg = "rgba(10,10,10,0.72)", scale = 7 } = {}) {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = bg;
  g.fillRect(28, 18, 200, 92);
  g.font = "bold 64px Arial";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillStyle = fg;
  g.fillText(text, 128, 66);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  sp.scale.set(scale, scale / 2, 1);
  return sp;
}

// --- world building ---------------------------------------------------------
const LIGHT_COLORS = { GREEN: 0x35c96b, YELLOW: 0xf0c22e, RED: 0xe04545 };

// The ground is the clean plate (temporal-median of the stabilized footage:
// moving cars erased, parked cars and every road marking kept), affine-warped
// onto the world plane exactly like the digital twin warps the live video.
const plateImg = new Image();
const plateLoaded = new Promise((res) => {
  plateImg.onload = () => res();
  plateImg.onerror = () => res();
});
plateImg.src = "plate.jpg";

let plateTex = null;
function makePlateTexture() {
  const GSCALE = 2048 / Math.max(GW, GH);
  const c = document.createElement("canvas");
  c.width = Math.round(GW * GSCALE);
  c.height = Math.round(GH * GSCALE);
  const g = c.getContext("2d");
  g.fillStyle = "#14161f";
  g.fillRect(0, 0, c.width, c.height);
  if (plateImg.naturalWidth) {
    // canvas_px = (world - min) * GSCALE ; world = AF * image
    const a = AF[0] * GSCALE, b = AF[1] * GSCALE, cc = (AF[2] - minX) * GSCALE;
    const d = AF[3] * GSCALE, e = AF[4] * GSCALE, f = (AF[5] - minZ) * GSCALE;
    g.setTransform(a, d, b, e, cc, f);
    g.drawImage(plateImg, 0, 0, IMG_W, IMG_H);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.encoding = THREE.sRGBEncoding;
  tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return tex;
}

function buildWorld(scene) {
  scene.background = new THREE.Color(0x0c0e16);
  scene.add(new THREE.HemisphereLight(0xcdd8e8, 0x50483c, 0.9));
  const sun = new THREE.DirectionalLight(0xfff0d8, 1.1);
  sun.position.set(60, 100, 40);
  scene.add(sun);

  if (!plateTex) plateTex = makePlateTexture();
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(GW, GH),
    new THREE.MeshBasicMaterial({ map: plateTex })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(CX, 0, CZ);
  scene.add(ground);

  // compass letters just outside each approach's count line
  for (const [name, L] of Object.entries(LANES)) {
    const sp = textSprite(name[0].toUpperCase(),
      { fg: "#d4a43c", bg: "rgba(0,0,0,0)", scale: CAR_LEN * 2.2 });
    sp.position.set(L.P[0] - L.f[0] * CAR_LEN * 4, CAR_LEN * 1.4,
                    L.P[1] - L.f[1] * CAR_LEN * 4);
    scene.add(sp);
  }
  return scene;
}

function makeStopBars(scene) {
  const bars = {};
  for (const a of TIMELINE.approaches) {
    const L = LANES[a];
    if (!L) continue;
    const [p1, p2] = L.line;
    const dx = p2[0] - p1[0], dz = p2[1] - p1[1];
    const len = Math.hypot(dx, dz);
    // stop bar lying on the real count line
    const mat = new THREE.MeshBasicMaterial({ color: LIGHT_COLORS.RED,
      transparent: true, opacity: 0.8 });
    const bar = new THREE.Mesh(new THREE.PlaneGeometry(len, CAR_LEN * 0.22), mat);
    bar.rotation.x = -Math.PI / 2;
    const barG = new THREE.Group();
    barG.add(bar);
    barG.rotation.y = Math.atan2(-dz, dx);
    barG.position.set(L.P[0], 0.06, L.P[1]);
    scene.add(barG);
    // signal pole + head at the count line's end, nudged upstream
    const side = [p2[0] - L.f[0] * CAR_LEN * 0.7, p2[1] - L.f[1] * CAR_LEN * 0.7];
    const pole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.22 * SC, 0.26 * SC, 7 * SC),
      new THREE.MeshLambertMaterial({ color: 0x3c3f46 })
    );
    pole.position.set(side[0], 3.5 * SC, side[1]);
    scene.add(pole);
    const head = new THREE.Mesh(
      new THREE.BoxGeometry(1.5 * SC, 3.6 * SC, 1.0 * SC),
      new THREE.MeshLambertMaterial({ color: 0x23252b }));
    head.position.set(side[0], 8.0 * SC, side[1]);
    scene.add(head);
    const lampMats = [];
    [["RED", 9.0], ["YELLOW", 8.0], ["GREEN", 7.0]].forEach(([name, y]) => {
      const m = new THREE.MeshBasicMaterial({ color: LIGHT_COLORS[name] });
      const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.42 * SC, 12, 12), m);
      lamp.position.set(side[0], y * SC, side[1]);
      scene.add(lamp);
      lampMats.push([name, m]);
    });
    bars[a] = { bar: mat, lamps: lampMats };
  }
  return bars;
}

// --- car models --------------------------------------------------------------
const MODEL_ORDER = ["sedan", "sedan", "suv", "van", "sedan", "suv", "taxi",
                     "delivery", "van", "truck"];
const TINTS = [0xffffff, 0xd8e2ea, 0xe8d9c8, 0xcfe0cf, 0xdccfe0, 0xc9d4e2];
const carTemplates = {};

let blobTex = null;
function makeBlobTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(64, 64, 8, 64, 64, 62);
  grad.addColorStop(0, "rgba(0,0,0,0.42)");
  grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

function loadCarModels() {
  const manager = new THREE.LoadingManager();
  const whitePixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVR4nGP8//8/AwMDEwMYAAAkBgMBXaJOiAAAAABJRU5ErkJggg==";
  manager.setURLModifier((url) => url.endsWith("Textures/colormap.png") ? whitePixel : url);
  const loader = new THREE.GLTFLoader(manager);
  const jobs = Object.entries(CAR_GLB_B64).map(([name, b64]) =>
    new Promise((resolve) => {
      const bin = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
      loader.parse(bin.buffer, "", (gltf) => {
        const root = gltf.scene;
        const box = new THREE.Box3().setFromObject(root);
        const size = new THREE.Vector3();
        box.getSize(size);
        const scale = CAR_LEN / Math.max(size.z, 0.001);
        root.scale.setScalar(scale);
        const box2 = new THREE.Box3().setFromObject(root);
        root.position.y = -box2.min.y;
        root.traverse((o) => {
          if (o.isMesh) { o.castShadow = true; }
        });
        carTemplates[name] = root;
        resolve();
      }, () => resolve());
    })
  );
  return Promise.all(jobs);
}

function makeCarPool(scene, vehicles) {
  const meshes = new Map();
  vehicles.forEach((v) => {
    const g = new THREE.Group();
    const modelName = MODEL_ORDER[v.id % MODEL_ORDER.length];
    const tpl = carTemplates[modelName] || carTemplates.sedan;
    const bodyMats = [];
    if (tpl) {
      const inst = tpl.clone(true);
      inst.traverse((o) => {
        if (o.isMesh) {
          o.material = o.material.clone();
          bodyMats.push(o.material);
        }
      });
      const tint = new THREE.Color(TINTS[(v.id * 7) % TINTS.length]);
      bodyMats.forEach((m) => m.color.multiply(tint));
      g.add(inst);
    }
    // soft contact shadow: grounds the car on the photographic plate
    if (!blobTex) blobTex = makeBlobTexture();
    const blob = new THREE.Mesh(
      new THREE.PlaneGeometry(CAR_LEN * 0.78, CAR_LEN * 1.3),
      new THREE.MeshBasicMaterial({ map: blobTex, transparent: true,
        depthWrite: false })
    );
    blob.rotation.x = -Math.PI / 2;
    blob.position.y = 0.04;
    g.add(blob);
    const tag = textSprite(v.label, { scale: CAR_LEN * 1.27 });
    tag.position.y = CAR_LEN * 1.05;
    g.add(tag);
    g.visible = false;
    g.userData.vid = v.id;
    scene.add(g);
    meshes.set(v.id, {
      g, bodyMats,
      baseColors: bodyMats.map((m) => m.color.clone()),
      quat: new THREE.Quaternion(),
      lastPos: null,
      trail: [],
    });
  });
  return meshes;
}

const cWait = new THREE.Color(), cFrom = new THREE.Color(0x9dc89d),
      cMid = new THREE.Color(0xe0b34a), cTo = new THREE.Color(0xd94b3a),
      cWhite = new THREE.Color(0xffffff);

function waitColor(sec) {
  const u = Math.min(sec / 30, 1);
  if (u < 0.5) cWait.lerpColors(cFrom, cMid, u * 2);
  else cWait.lerpColors(cMid, cTo, (u - 0.5) * 2);
  return cWait;
}

// --- trails ------------------------------------------------------------------
const TRAIL_AGE = 2.4;
function makeTrail(scene) {
  const geo = new THREE.BufferGeometry();
  const maxSeg = 60 * 30;
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(maxSeg * 6), 3));
  geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(maxSeg * 6), 3));
  const line = new THREE.LineSegments(geo,
    new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9 }));
  line.frustumCulled = false;
  scene.add(line);
  return line;
}

function updateTrail(S, t) {
  const pos = S.trailLine.geometry.attributes.position.array;
  const col = S.trailLine.geometry.attributes.color.array;
  const bg = new THREE.Color(0xb9bcc0);  // fade toward the plate's asphalt
  let n = 0;
  const tmp = new THREE.Color();
  for (const v of S.vehicles) {
    const rec = S.cars.get(v.id);
    const tr = rec.trail;
    while (tr.length && t - tr[0][2] > TRAIL_AGE) tr.shift();
    if (tr.length > 1 && rec.g.visible) {
      const carCol = waitColor(Math.max(0, Math.min(t, v.t1 ?? t) - v.t0)).clone();
      for (let i = 0; i < tr.length - 1 && n < pos.length / 6; i++) {
        const age = (t - tr[i][2]) / TRAIL_AGE;
        tmp.lerpColors(carCol, bg, Math.min(1, age));
        pos[n * 6] = tr[i][0]; pos[n * 6 + 1] = TRAIL_Y; pos[n * 6 + 2] = tr[i][1];
        pos[n * 6 + 3] = tr[i + 1][0]; pos[n * 6 + 4] = TRAIL_Y; pos[n * 6 + 5] = tr[i + 1][1];
        for (const off of [0, 3]) {
          col[n * 6 + off] = tmp.r; col[n * 6 + off + 1] = tmp.g; col[n * 6 + off + 2] = tmp.b;
        }
        n++;
      }
    }
  }
  S.trailLine.geometry.setDrawRange(0, n * 2);
  S.trailLine.geometry.attributes.position.needsUpdate = true;
  S.trailLine.geometry.attributes.color.needsUpdate = true;
}

// --- scenarios ---------------------------------------------------------------
function makeScenario(scnData) {
  const scene = buildWorld(new THREE.Scene());
  const vehicles = buildKeyframes(scnData);
  return {
    data: scnData,
    scene,
    bars: makeStopBars(scene),
    cars: makeCarPool(scene, vehicles),
    vehicles,
    trailLine: makeTrail(scene),
  };
}

const _q = new THREE.Quaternion(), _e = new THREE.Euler();

function updateScenario(S, t) {
  for (const a of TIMELINE.approaches) {
    const st = lightAt(S.data, a, t);
    S.bars[a].bar.color.setHex(LIGHT_COLORS[st]);
    for (const [name, m] of S.bars[a].lamps) {
      m.color.setHex(LIGHT_COLORS[name]);
      const on = name === st;
      m.color.multiplyScalar(on ? 1.0 : 0.16);
    }
  }
  let waitSum = 0, waitN = 0, served = 0;
  for (const v of S.vehicles) {
    const rec = S.cars.get(v.id);
    if (v.rp === undefined) v.rp = buildRealPath(v);
    let pp = null;
    if (v.rp) {
      let s;
      if (v.t1 !== null && t >= v.t1) {
        const tq = v.t0 + (t - v.t1);
        if (tq > v.rp.tEnd + 2.2) s = null;
        else s = realSAt(v.rp, tq);
      } else if (t < v.rp.pw[0][0]) {
        s = null;
      } else {
        const sk = posAt(v, t);
        s = Math.min(realSAt(v.rp, t), sk === null ? Infinity : sk);
      }
      if (s !== null) pp = realPosAt(v.rp, s);
    } else {
      const s = posAt(v, t);
      if (s !== null) pp = pathPos(v.path || getPath(v.a, v.exit || OPP[v.a]), s);
    }
    if (pp === null) { rec.g.visible = false; rec.lastPos = null; }
    else {
      const appearing = !rec.g.visible;
      rec.g.visible = true;
      // freeze micro-motion: parked cars must not wobble or spin
      const moved = rec.lastPos
        ? Math.hypot(pp.x - rec.lastPos[0], pp.z - rec.lastPos[1]) : 1;
      if (moved > 0.015 || appearing) {
        rec.g.position.set(pp.x, 0, pp.z);
        _e.set(0, Math.atan2(pp.tan[0], pp.tan[1]), 0);
        _q.setFromEuler(_e);
        if (appearing) rec.quat.copy(_q);
        else rec.quat.slerp(_q, Math.min(1, 0.16 + moved * 0.05));
        rec.g.quaternion.copy(rec.quat);
        rec.lastPos = [pp.x, pp.z];
        const tr = rec.trail;
        if (!tr.length || Math.hypot(pp.x - tr[tr.length - 1][0], pp.z - tr[tr.length - 1][1]) > 0.6 * SC) {
          tr.push([pp.x, pp.z, t]);
        }
      }
      const waited = Math.max(0, Math.min(t, v.t1 ?? t) - v.t0);
      const wc = waitColor(waited);
      const age = t - v.t0;
      rec.bodyMats.forEach((m, i) => {
        m.color.copy(rec.baseColors[i]).lerp(wc, Math.min(0.75, waited / 10));
        if (age >= 0 && age < 1.0) m.color.lerp(cWhite, 1 - age);
      });
    }
    if (t >= v.t0) {
      waitSum += Math.max(0, Math.min(t, v.t1 ?? t) - v.t0);
      waitN += 1;
      if (v.t1 !== null && t >= v.t1) served += 1;
    }
  }
  updateTrail(S, t);
  return { avg: waitN ? waitSum / waitN : 0, served };
}

// --- footage strip -----------------------------------------------------------
const FOOT_TILE = { north: [0, 0], south: [640, 0], east: [0, 360], west: [640, 360] };
const footVideo = document.createElement("video");
footVideo.src = window.THEIATRON_FOOTAGE_SRC || "footage.mp4";
footVideo.muted = true;
footVideo.preload = "auto";
const footCanvas = document.getElementById("footage");
const footCtx = footCanvas.getContext("2d");
const ARRIVALS = {};
TIMELINE.approaches.forEach((a) => (ARRIVALS[a] = []));
TIMELINE.theiatron.vehicles.forEach((v) => ARRIVALS[v.a].push(v.t0));
const FOOT_SINGLE = TIMELINE.footage_layout === "single";

function badge(x, y, text) {
  footCtx.fillStyle = "#35c96b";
  footCtx.beginPath();
  footCtx.arc(x, y, 16, 0, Math.PI * 2);
  footCtx.fill();
  footCtx.fillStyle = "#fff";
  footCtx.font = "bold 12px Arial";
  footCtx.textAlign = "center";
  footCtx.fillText(text, x, y + 4);
}

function drawFootage(t, isPlaying, speed) {
  if (isPlaying) {
    footVideo.playbackRate = Math.min(speed, 8);
    if (footVideo.paused) footVideo.play().catch(() => {});
  } else if (!footVideo.paused) footVideo.pause();
  if (Math.abs(footVideo.currentTime - t) > 0.35) footVideo.currentTime = t;

  const W = footCanvas.width, H = footCanvas.height;
  if (FOOT_SINGLE) {
    if (footVideo.readyState >= 2) footCtx.drawImage(footVideo, 0, 0, W, H);
    else { footCtx.fillStyle = "#222"; footCtx.fillRect(0, 0, W, H); }
    const corners = { north: [26, 26], south: [W - 26, H - 26],
                      east: [W - 26, 26], west: [26, H - 26] };
    TIMELINE.approaches.forEach((a) => {
      if (ARRIVALS[a].some((t0) => t >= t0 && t - t0 < 0.9)) {
        const [x, y] = corners[a] || [26, 26];
        badge(x, y, a[0].toUpperCase() + "+1");
      }
    });
    footCtx.strokeStyle = "rgba(255,255,255,.25)";
    footCtx.strokeRect(0.5, 0.5, W - 1, H - 1);
    return;
  }
  const n = TIMELINE.approaches.length;
  const tw = W / n, th = H;
  TIMELINE.approaches.forEach((a, i) => {
    const [sx, sy] = FOOT_TILE[a];
    if (footVideo.readyState >= 2) {
      footCtx.drawImage(footVideo, sx, sy, 640, 360, i * tw, 0, tw, th);
    } else {
      footCtx.fillStyle = "#222";
      footCtx.fillRect(i * tw, 0, tw, th);
    }
    if (ARRIVALS[a].some((t0) => t >= t0 && t - t0 < 0.9)) badge(i * tw + tw - 26, 20, "+1");
    footCtx.strokeStyle = "rgba(255,255,255,.25)";
    footCtx.strokeRect(i * tw + 0.5, 0.5, tw - 1, th - 1);
  });
}

// --- renderer / cameras ------------------------------------------------------
const canvas = document.getElementById("c");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
THREE.ColorManagement.legacyMode = false;
renderer.outputEncoding = THREE.sRGBEncoding;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const camera = new THREE.PerspectiveCamera(46, 1, 0.5, 1200);
camera.position.set(CX, GH * 0.9, CZ + GH * 1.0);
const controls = new THREE.OrbitControls(camera, canvas);
controls.target.set(CX, 0, CZ);
controls.maxPolarAngle = Math.PI * 0.46;
controls.minDistance = 12 * SC;
controls.maxDistance = Math.max(GW, GH) * 3;
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.autoRotateSpeed = 0.45;
const camR = camera.clone();

const CAM_PRESETS = {
  high: { pos: [CX, GH * 0.9, CZ + GH * 1.0], tgt: [CX, 0, CZ] },
  top: { pos: [CX, Math.max(GW, GH) * 1.35, CZ + 1.5], tgt: [CX, 0, CZ] },
  low: { pos: [CX + GW * 0.42, 16 * SC, CZ + GH * 0.65], tgt: [CX, 1.5 * SC, CZ] },
};
let camAnim = null;
function flyTo(name) {
  const p = CAM_PRESETS[name];
  camAnim = { from: camera.position.clone(), fromT: controls.target.clone(),
              to: new THREE.Vector3(...p.pos), toT: new THREE.Vector3(...p.tgt), u: 0 };
  follow = null;
}
document.querySelectorAll("[data-cam]").forEach((b) => {
  b.addEventListener("click", () => flyTo(b.dataset.cam));
});

// idle auto-orbit
let lastInteract = -1e9;
controls.addEventListener("start", () => { lastInteract = performance.now(); camAnim = null; });

// click-to-follow: the SAME car is tracked in both worlds
let follow = null;
const raycaster = new THREE.Raycaster();
canvas.addEventListener("click", (ev) => {
  const r = canvas.getBoundingClientRect();
  const half = r.width / 2;
  const leftPane = ev.clientX - r.left < half;
  const x = leftPane ? (ev.clientX - r.left) / half : (ev.clientX - r.left - half) / half;
  const ndc = new THREE.Vector2(x * 2 - 1, -(((ev.clientY - r.top) / r.height) * 2 - 1));
  const cam = leftPane ? camera : camR;
  const S = leftPane ? left : right;
  raycaster.setFromCamera(ndc, cam);
  const groups = [];
  S.cars.forEach((rec) => { if (rec.g.visible) groups.push(rec.g); });
  const hits = raycaster.intersectObjects(groups, true);
  let vid = null;
  if (hits.length) {
    let o = hits[0].object;
    while (o && o.userData.vid === undefined) o = o.parent;
    if (o) vid = o.userData.vid;
  }
  follow = vid !== null ? { vid } : null;
  document.getElementById("followHint").textContent =
    follow ? `following ${left.vehicles[follow.vid].label} - click empty road to release` : "";
});

function resize() {
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  renderer.setSize(cw, ch, false);
  const aspect = cw / 2 / ch;
  camera.aspect = aspect;
  camera.updateProjectionMatrix();
  camR.aspect = aspect;
  camR.updateProjectionMatrix();
  const wrap = document.getElementById("footwrap");
  const availH = wrap.clientHeight - 26;
  const tilesAcross = FOOT_SINGLE ? 1 : 4;
  const w = Math.min(wrap.clientWidth, availH * tilesAcross * (640 / 360));
  footCanvas.style.width = w + "px";
  footCanvas.width = Math.round(w);
  footCanvas.height = Math.round((w / tilesAcross) * (360 / 640));
}
addEventListener("resize", resize);
resize();

// --- playback ----------------------------------------------------------------
let t = 0, playing = false, last = null;
let left = null, right = null, ready = false;
const playBtn = document.getElementById("play");
const speedSel = document.getElementById("speed");
const seek = document.getElementById("seek");
seek.max = DUR;
const fmt = (x) => `${Math.floor(x / 60)}:${String(Math.floor(x % 60)).padStart(2, "0")}`;

playBtn.onclick = () => {
  playing = !playing;
  playBtn.innerHTML = playing ? "&#10074;&#10074; Pause" : "&#9654; Play";
  last = null;
};
document.getElementById("restart").onclick = () => { t = 0; };
seek.oninput = () => { t = parseFloat(seek.value); };

const _v3 = new THREE.Vector3();

function frame(ts) {
  requestAnimationFrame(frame);
  if (!ready) return;
  if (playing) {
    if (last !== null) t = Math.min(DUR, t + ((ts - last) / 1000) * parseFloat(speedSel.value));
    last = ts;
    if (t >= DUR) { playing = false; playBtn.innerHTML = "&#9654; Play"; }
  } else last = ts;
  seek.value = t;
  document.getElementById("clock").textContent = fmt(t);

  drawFootage(t, playing, parseFloat(speedSel.value));
  const L = updateScenario(left, t);
  const R = updateScenario(right, t);
  document.getElementById("waitL").textContent = L.avg.toFixed(1) + "s";
  document.getElementById("waitR").textContent = R.avg.toFixed(1) + "s";
  document.getElementById("servedL").textContent = L.served;
  document.getElementById("servedR").textContent = R.served;
  const verdict = document.getElementById("verdictTop");
  const enoughDemand = (TIMELINE.sample_status ||
    ((TIMELINE.arrivals || TIMELINE.theiatron.vehicles.length) >= 10 ? "ready" : "inconclusive")) === "ready";
  if (!enoughDemand && t > 10) {
    verdict.textContent = `INCONCLUSIVE — ${TIMELINE.arrivals || TIMELINE.theiatron.vehicles.length} ARRIVALS`;
    verdict.style.color = "#ffb724";
  } else if (t > 45 && R.avg > 0.5 && L.avg < R.avg) {
    verdict.textContent = `${Math.round(100 * (R.avg - L.avg) / R.avg)}% LESS WAITING WITH THEIATRON`;
    verdict.style.color = "#46c46e";
  } else if (t > 45 && R.avg > 0.5 && L.avg > R.avg) {
    verdict.textContent = `${Math.round(100 * (L.avg - R.avg) / R.avg)}% MORE WAITING ON THIS SAMPLE`;
    verdict.style.color = "#e34a3f";
  } else verdict.textContent = "";

  // camera: preset flight > follow > user orbit + idle auto-rotate
  if (camAnim) {
    camAnim.u = Math.min(1, camAnim.u + 0.025);
    const e = camAnim.u * camAnim.u * (3 - 2 * camAnim.u);
    camera.position.lerpVectors(camAnim.from, camAnim.to, e);
    controls.target.lerpVectors(camAnim.fromT, camAnim.toT, e);
    if (camAnim.u >= 1) camAnim = null;
  } else if (follow) {
    const recL = left.cars.get(follow.vid);
    if (recL.g.visible) {
      _v3.copy(recL.g.position);
      controls.target.lerp(_v3.setY(1.5 * SC), 0.08);
    }
  }
  controls.autoRotate = !follow && !camAnim && performance.now() - lastInteract > 9000 && playing;
  controls.update();
  camR.position.copy(camera.position);
  camR.quaternion.copy(camera.quaternion);
  if (follow) {
    const recR = right.cars.get(follow.vid);
    if (recR.g.visible) {
      const off = _v3.copy(camera.position).sub(controls.target);
      camR.position.copy(recR.g.position).setY(1.5 * SC).add(off);
      camR.lookAt(recR.g.position.x, 1.5 * SC, recR.g.position.z);
    }
  }

  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setScissorTest(true);
  renderer.setViewport(0, 0, w / 2, h);
  renderer.setScissor(0, 0, w / 2, h);
  renderer.render(left.scene, camera);
  renderer.setViewport(w / 2, 0, w / 2, h);
  renderer.setScissor(w / 2, 0, w / 2, h);
  renderer.render(right.scene, camR);
}

Promise.all([loadCarModels(), plateLoaded]).then(() => {
  left = makeScenario(TIMELINE.theiatron);
  right = makeScenario(TIMELINE.fixed);
  ready = true;
});
requestAnimationFrame(frame);
