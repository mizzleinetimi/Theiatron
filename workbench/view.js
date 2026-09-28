/* Rendering only: every vehicle position and signal comes from a SUMO frame. */
/* SUMO positions are front-bumper centres; metres, heading clockwise from north. */
function vehiclePose(v) {
  const angle = (v.angle * Math.PI) / 180;
  return {
    x: v.x - (Math.sin(angle) * v.length) / 2,
    z: -v.y + (Math.cos(angle) * v.length) / 2,
    yaw: -angle,
  };
}
if (typeof module !== "undefined") module.exports = { vehiclePose };

class SumoView {
  constructor(element, colour) {
    this.element = element;
    this.colour = colour;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x101922);
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    element.append(this.renderer.domElement);
    this.camera = new THREE.OrthographicCamera(-150, 150, 100, -100, 0.1, 1000);
    this.scene.add(new THREE.HemisphereLight(0xcde4ff, 0x303924, 0.75));
    const sun = new THREE.DirectionalLight(0xffffff, 0.65);
    sun.position.set(50, 100, 20);
    this.scene.add(sun);
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(2000, 2000),
      new THREE.MeshBasicMaterial({ color: 0x101d24 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.1;
    this.scene.add(ground);
    const grid = new THREE.GridHelper(600, 60, 0x253842, 0x1c2b35);
    grid.position.y = -0.05;
    this.scene.add(grid);
    this.road = new THREE.Group();
    this.scene.add(this.road);
    this.cars = new Map();
    this.signals = [];
    this.bodyGeo = new THREE.BoxGeometry(1.8, 1.35, 4.5);
    this.roofGeo = new THREE.BoxGeometry(1.5, 0.5, 2.2);
    this.bodyMat = new THREE.MeshStandardMaterial({
      color: colour,
      roughness: 0.45,
    });
    this.roofMat = new THREE.MeshStandardMaterial({
      color: 0x2a4451,
      roughness: 0.3,
    });
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(element);
    this.perspective(false);
  }
  resize() {
    const w = this.element.clientWidth,
      h = this.element.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    const ratio = w / h;
    this.camera.left = -100 * ratio;
    this.camera.right = 100 * ratio;
    this.camera.top = 100;
    this.camera.bottom = -100;
    this.camera.updateProjectionMatrix();
    this.render();
  }
  perspective(on) {
    this.camera.position.set(on ? 115 : 0, on ? 170 : 240, on ? 140 : 0.001);
    this.camera.up.set(0, on ? 1 : 0, on ? 0 : -1);
    this.camera.lookAt(0, 0, 0);
    this.resize();
  }
  geometry(data) {
    for (const child of [...this.road.children]) {
      this.road.remove(child);
      child.geometry?.dispose();
      child.material?.dispose();
    }
    this.signals = [];
    const mesh = (geo, col, x, y, z, lit = false) => {
      const m = new THREE.Mesh(
        geo,
        lit
          ? new THREE.MeshStandardMaterial({ color: col, roughness: 0.95 })
          : new THREE.MeshBasicMaterial({ color: col }),
      );
      m.position.set(x, y, z);
      this.road.add(m);
      return m;
    };
    for (const lane of data.lanes) {
      for (let i = 1; i < lane.points.length; i++) {
        const a = lane.points[i - 1],
          b = lane.points[i],
          dx = b[0] - a[0],
          dz = -(b[1] - a[1]);
        const segment = mesh(
          new THREE.BoxGeometry(lane.width, 0.1, Math.hypot(dx, dz)),
          0x34434d,
          (a[0] + b[0]) / 2,
          0,
          -(a[1] + b[1]) / 2,
        );
        segment.rotation.y = Math.atan2(dx, dz);
        const edge = mesh(
          new THREE.BoxGeometry(0.12, 0.12, Math.hypot(dx, dz)),
          0x74838a,
          (a[0] + b[0]) / 2 - (lane.width / 2) * Math.cos(segment.rotation.y),
          0.02,
          -(a[1] + b[1]) / 2 + (lane.width / 2) * Math.sin(segment.rotation.y),
        );
        edge.rotation.y = segment.rotation.y;
      }
      if (lane.id.includes("_in_")) {
        const p = lane.points.at(-1),
          arm = lane.id.split("_")[0];
        const bulb = mesh(
          new THREE.SphereGeometry(1.25, 12, 8),
          0x567077,
          p[0],
          3,
          -p[1],
          true,
        );
        this.signals.push({
          bulb,
          phase: lane.signal_phase || (["north", "south"].includes(arm) ? "NS" : "EW"),
        });
      }
    }
    const shape = new THREE.Shape();
    data.junction.forEach((p, i) =>
      i ? shape.lineTo(...p) : shape.moveTo(...p),
    );
    shape.closePath();
    const junction = mesh(new THREE.ShapeGeometry(shape), 0x34434d, 0, 0.06, 0);
    junction.rotation.x = -Math.PI / 2;
    this.render();
  }
  frame(world) {
    const present = new Set(world.vehicles.map((v) => v.id));
    for (const [id, car] of this.cars)
      if (!present.has(id)) {
        this.scene.remove(car);
        this.cars.delete(id);
      }
    for (const vehicle of world.vehicles) {
      let car = this.cars.get(vehicle.id);
      if (!car) {
        car = new THREE.Group();
        const body = new THREE.Mesh(this.bodyGeo, this.bodyMat);
        body.position.y = 0.75;
        car.add(body);
        const roof = new THREE.Mesh(this.roofGeo, this.roofMat);
        roof.position.y = 1.6;
        car.add(roof);
        this.scene.add(car);
        this.cars.set(vehicle.id, car);
      }
      const pose = vehiclePose(vehicle);
      car.position.set(pose.x, 0, pose.z);
      car.rotation.y = pose.yaw;
    }
    for (const s of this.signals) {
      const active = s.phase === world.phase;
      const colour =
        active && world.signal === "GREEN"
          ? 0x86f0b6
          : active && world.signal === "YELLOW"
            ? 0xffc75c
            : 0xe75e63;
      s.bulb.material.color.setHex(colour);
      s.bulb.material.emissive.setHex(colour);
      s.bulb.material.emissiveIntensity = 0.45;
    }
    this.render();
  }
  clear() {
    for (const car of this.cars.values()) this.scene.remove(car);
    this.cars.clear();
    this.render();
  }
  render() {
    this.renderer.render(this.scene, this.camera);
  }
}
