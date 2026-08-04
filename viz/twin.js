/* Theiatron digital twin: pure replay of the footage in 3D.
   One global image->world affine maps BOTH the video (warped onto the
   ground plane) and every car's trajectory, so relative geometry is
   preserved exactly as filmed: real roads, real spacing, no simulation
   logic, no queue capping. Alignment of each 3D car with its own image
   is the built-in accuracy proof. */

const DUR = TIMELINE.duration;
const AF = TIMELINE.twin_affine; // wx = a*px + b*py + c ; wz = d*px + e*py + f
if (!AF) document.getElementById("legend").textContent =
  "timeline has no twin data - re-run scripts/export_timeline.py";

const VEHICLES = TIMELINE.theiatron.vehicles.filter((v) => v.tw && v.tw.length > 4);
// Uncounted-but-tracked vehicles: parked cars, outbound and cross traffic.
// Rendered without tags so every boxed car in the footage has a 3D twin.
const EXTRAS = (TIMELINE.extras || [])
  .filter((e) => e.tw && e.tw.length > 1)
  .map((e, i) => ({ label: null, tw: e.tw, _extra: true, key: "x" + i }));

// --- Savitzky-Golay smoothing (window 9, order 2), two passes ---------------
const SGC = [-21, 14, 39, 54, 59, 54, 39, 14, -21].map((c) => c / 231);
function sgSmooth(pw) {
  const n = pw.length;
  if (n < 9) return pw.map((p) => p.slice());
  const out = [];
  for (let i = 0; i < n; i++) {
    let x = 0, z = 0;
    for (let k = -4; k <= 4; k++) {
      const j = Math.min(n - 1, Math.max(0, i + k));
      x += SGC[k + 4] * pw[j][1];
      z += SGC[k + 4] * pw[j][2];
    }
    out.push([pw[i][0], x, z]);
  }
  return out;
}
VEHICLES.forEach((v) => { v.key = v.label; v.sm = sgSmooth(sgSmooth(v.tw)); });
EXTRAS.forEach((v) => { v.sm = sgSmooth(sgSmooth(v.tw)); });
const ALL = VEHICLES.concat(EXTRAS);

function posAt(v, t) {
  const p = v.sm;
  if (t < p[0][0] - 0.05 || t > p[p.length - 1][0] + 0.05) return null;
  let i = 0;
  while (i < p.length - 2 && p[i + 1][0] < t) i++;
  const u = Math.max(0, Math.min(1, (t - p[i][0]) / Math.max(p[i + 1][0] - p[i][0], 1e-6)));
  const x = p[i][1] + (p[i + 1][1] - p[i][1]) * u;
  const z = p[i][2] + (p[i + 1][2] - p[i][2]) * u;
  // tangent from a wider window for stable heading
  const j0 = Math.max(0, i - 1), j1 = Math.min(p.length - 1, i + 2);
  let dx = p[j1][1] - p[j0][1], dz = p[j1][2] - p[j0][2];
  const n = Math.hypot(dx, dz);
  return { x, z, tan: n > 0.05 ? [dx / n, dz / n] : null };
}

// --- renderer ----------------------------------------------------------------
const canvas = document.getElementById("c");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
THREE.ColorManagement.legacyMode = false;
renderer.outputEncoding = THREE.sRGBEncoding;
renderer.toneMapping = THREE.ACESFilmicToneMapping;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0c0e16);
scene.add(new THREE.HemisphereLight(0xcdd8e8, 0x50483c, 0.9));
const sun = new THREE.DirectionalLight(0xfff0d8, 1.1);
sun.position.set(60, 100, 40);
scene.add(sun);

// --- ground: the actual footage, affine-warped onto the world plane ----------
const IMG_W = 1280, IMG_H = 720;
function imgToWorld(px, py) {
  return [AF[0] * px + AF[1] * py + AF[2], AF[3] * px + AF[4] * py + AF[5]];
}
// world-space bounds of the projected frame
const corners = [[0, 0], [IMG_W, 0], [0, IMG_H], [IMG_W, IMG_H]].map(([x, y]) => imgToWorld(x, y));
const minX = Math.min(...corners.map((c) => c[0])), maxX = Math.max(...corners.map((c) => c[0]));
const minZ = Math.min(...corners.map((c) => c[1])), maxZ = Math.max(...corners.map((c) => c[1]));
const GW = maxX - minX, GH = maxZ - minZ;

const groundCanvas = document.createElement("canvas");
const GSCALE = 2048 / Math.max(GW, GH);
groundCanvas.width = Math.round(GW * GSCALE);
groundCanvas.height = Math.round(GH * GSCALE);
const gctx = groundCanvas.getContext("2d");
const groundTex = new THREE.CanvasTexture(groundCanvas);
groundTex.encoding = THREE.sRGBEncoding;
groundTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(GW, GH),
  new THREE.MeshBasicMaterial({ map: groundTex })
);
ground.rotation.x = -Math.PI / 2;
// After rotation.x=-PI/2 with default flipY textures, canvas +y already
// maps to world +z, so no mirroring is needed.
ground.position.set(minX + GW / 2, 0, minZ + GH / 2);
scene.add(ground);

const video = document.createElement("video");
video.src = window.THEIATRON_FOOTAGE_SRC || "footage.mp4";
video.muted = true;
video.preload = "auto";

function drawGround(t, isPlaying, speed) {
  if (isPlaying) {
    video.playbackRate = Math.min(speed, 8);
    if (video.paused) video.play().catch(() => {});
  } else if (!video.paused) video.pause();
  if (Math.abs(video.currentTime - t) > 0.35) video.currentTime = t;
  gctx.setTransform(1, 0, 0, 1, 0, 0);
  gctx.fillStyle = "#14161f";
  gctx.fillRect(0, 0, groundCanvas.width, groundCanvas.height);
  if (video.readyState >= 2) {
    // canvas_px = (world - min) * GSCALE ; world = AF * image
    const a = AF[0] * GSCALE, b = AF[1] * GSCALE, c = (AF[2] - minX) * GSCALE;
    const d = AF[3] * GSCALE, e = AF[4] * GSCALE, f = (AF[5] - minZ) * GSCALE;
    gctx.setTransform(a, d, b, e, c, f);
    gctx.drawImage(video, 0, 0, IMG_W, IMG_H);
    gctx.setTransform(1, 0, 0, 1, 0, 0);
  }
  groundTex.needsUpdate = true;
}

// --- cars --------------------------------------------------------------------
// Car length derived from the mapping itself: ~52 px of image car length.
const PX_SCALE = Math.hypot(AF[0], AF[3]);
const CAR_LEN = Math.max(2.5, 52 * PX_SCALE);

function textSprite(text) {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "rgba(10,10,10,0.72)";
  g.fillRect(28, 18, 200, 92);
  g.font = "bold 64px Arial";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillStyle = "#fff";
  g.fillText(text, 128, 66);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  sp.scale.set(CAR_LEN * 1.3, CAR_LEN * 0.65, 1);
  return sp;
}

const MODEL_ORDER = ["sedan", "sedan", "suv", "van", "sedan", "suv", "taxi",
                     "delivery", "van", "truck"];
const carTemplates = {};
function loadCarModels() {
  const manager = new THREE.LoadingManager();
  const whitePixel = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVR4nGP8//8/AwMDEwMYAAAkBgMBXaJOiAAAAABJRU5ErkJggg==";
  manager.setURLModifier((url) => url.endsWith("Textures/colormap.png") ? whitePixel : url);
  const loader = new THREE.GLTFLoader(manager);
  return Promise.all(Object.entries(CAR_GLB_B64).map(([name, b64]) =>
    new Promise((resolve) => {
      const bin = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
      loader.parse(bin.buffer, "", (gltf) => {
        const root = gltf.scene;
        const box = new THREE.Box3().setFromObject(root);
        const size = new THREE.Vector3();
        box.getSize(size);
        root.scale.setScalar(CAR_LEN / Math.max(size.z, 0.001));
        const box2 = new THREE.Box3().setFromObject(root);
        root.position.y = -box2.min.y;
        carTemplates[name] = root;
        resolve();
      }, () => resolve());
    })));
}

const cars = new Map();
const _q = new THREE.Quaternion(), _e = new THREE.Euler();
function buildCars() {
  ALL.forEach((v, i) => {
    const g = new THREE.Group();
    const tpl = carTemplates[MODEL_ORDER[i % MODEL_ORDER.length]] || carTemplates.sedan;
    if (tpl) {
      const inst = tpl.clone(true);
      inst.traverse((o) => { if (o.isMesh) o.material = o.material.clone(); });
      g.add(inst);
    }
    if (v.label) {  // counted arrivals keep their footage-matching tag
      const tag = textSprite(v.label);
      tag.position.y = CAR_LEN * 1.05;
      g.add(tag);
    }
    g.visible = false;
    scene.add(g);
    cars.set(v.key, { g, quat: new THREE.Quaternion(), last: null });
  });
}

// --- camera ------------------------------------------------------------------
const camera = new THREE.PerspectiveCamera(46, 1, 0.5, 900);
camera.position.set(minX + GW / 2, GH * 1.05, minZ + GH * 1.15);
const controls = new THREE.OrbitControls(camera, canvas);
controls.target.set(minX + GW / 2, 0, minZ + GH / 2);
controls.maxPolarAngle = Math.PI * 0.47;
controls.enableDamping = true;
controls.dampingFactor = 0.08;

function resize() {
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  renderer.setSize(cw, ch, false);
  camera.aspect = cw / ch;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
resize();

// --- playback ----------------------------------------------------------------
let t = 0, playing = false, last = null, ready = false;
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

function frame(ts) {
  requestAnimationFrame(frame);
  if (!ready || !AF) return;
  if (playing) {
    if (last !== null) t = Math.min(DUR, t + ((ts - last) / 1000) * parseFloat(speedSel.value));
    last = ts;
    if (t >= DUR) { playing = false; playBtn.innerHTML = "&#9654; Play"; }
  } else last = ts;
  seek.value = t;
  document.getElementById("clock").textContent = fmt(t);

  drawGround(t, playing, parseFloat(speedSel.value));
  for (const v of ALL) {
    const rec = cars.get(v.key);
    const pp = posAt(v, t);
    if (!pp) { rec.g.visible = false; rec.last = null; continue; }
    const appearing = !rec.g.visible;
    rec.g.visible = true;
    const moved = rec.last ? Math.hypot(pp.x - rec.last[0], pp.z - rec.last[1]) : 1;
    rec.g.position.set(pp.x, 0, pp.z);
    if (pp.tan && (moved > 0.012 || appearing)) {
      _e.set(0, Math.atan2(pp.tan[0], pp.tan[1]), 0);
      _q.setFromEuler(_e);
      if (appearing) rec.quat.copy(_q);
      else rec.quat.slerp(_q, Math.min(1, 0.15 + moved * 0.05));
    }
    rec.g.quaternion.copy(rec.quat);
    rec.last = [pp.x, pp.z];
  }
  controls.update();
  renderer.render(scene, camera);
}

loadCarModels().then(() => { buildCars(); ready = true; });
requestAnimationFrame(frame);
