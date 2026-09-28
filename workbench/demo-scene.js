/* Shared Three.js studio assets; all vehicle poses and signals are SUMO output. */
class DemoScene extends TrafficScene {
  constructor(element) {
    super(element);
    this.renderer.domElement.setAttribute(
      "aria-label",
      "SUMO 3D simulation. Drag to orbit, right-drag to pan, scroll to zoom.",
    );
    this.signals = [];
  }
  geometry(data) {
    super.frame([]);
    const points = data.lanes.flatMap((l) => l.points);
    const xs = points.map((p) => p[0]),
      ys = points.map((p) => p[1]);
    const bounds = [
      [Math.min(...xs) - 8, Math.min(...ys) - 8],
      [Math.max(...xs) + 8, Math.min(...ys) - 8],
      [Math.max(...xs) + 8, Math.max(...ys) + 8],
      [Math.min(...xs) - 8, Math.max(...ys) + 8],
    ];
    this.setRoad(
      (data.context_road?.length ? data.context_road : data.junction).map(
        (p) => [p[0], -p[1]],
      ),
    );
    for (const child of this.road.children) {
      if (child.geometry?.type === "ExtrudeGeometry")
        child.material.color.setHex(0x718078);
    }
    // The footprint is context. Lane ribbons are the actual procedural SUMO network.
    this.signals = [];
    for (const lane of data.lanes) {
      for (let i = 1; i < lane.points.length; i++) {
        const a = lane.points[i - 1],
          b = lane.points[i],
          dx = b[0] - a[0],
          dz = a[1] - b[1],
          length = Math.hypot(dx, dz),
          angle = Math.atan2(dx, dz);
        const road = this.mesh(
          new THREE.BoxGeometry(lane.width, 0.12, length),
          this.material(0x28353b),
          this.road,
          (a[0] + b[0]) / 2,
          0.15,
          -(a[1] + b[1]) / 2,
        );
        road.rotation.y = angle;
        road.castShadow = false;
        for (let d = 1; d < length; d += 5) {
          const mark = this.mesh(
            new THREE.BoxGeometry(0.09, 0.015, Math.min(2, length - d)),
            this.material(0xb1bcb5),
            this.road,
            a[0] + (dx * d) / length - (Math.cos(angle) * lane.width) / 2,
            0.22,
            -a[1] + (dz * d) / length + (Math.sin(angle) * lane.width) / 2,
          );
          mark.rotation.y = angle;
          mark.castShadow = false;
        }
      }
      if (lane.id.includes("_in_")) {
        const p = lane.points.at(-1);
        const post = this.mesh(
          new THREE.CylinderGeometry(0.1, 0.14, 3, 8),
          this.material(0x283c38),
          this.road,
          p[0],
          1.7,
          -p[1],
        );
        const bulb = this.mesh(
          new THREE.SphereGeometry(0.65, 12, 8),
          this.material(0xe45555),
          this.road,
          p[0],
          3.4,
          -p[1],
        );
        this.signals.push({ phase: lane.signal_phase || lane.arm, bulb });
      }
    }
    const shape = new THREE.Shape(
      data.junction.map((p) => new THREE.Vector2(p[0], p[1])),
    );
    const junction = this.mesh(
      new THREE.ShapeGeometry(shape),
      this.material(0x28353b),
      this.road,
      0,
      0.21,
      0,
    );
    junction.rotation.x = -Math.PI / 2;
    junction.castShadow = false;
    this.center.set(
      (Math.min(...xs) + Math.max(...xs)) / 2,
      0,
      -(Math.min(...ys) + Math.max(...ys)) / 2,
    );
    this.radius =
      Math.max(
        ...bounds.map((p) =>
          Math.hypot(p[0] - this.center.x, -p[1] - this.center.z),
        ),
      ) * 0.78;
    this.preset("junction");
  }
  frame(world) {
    super.frame(world.vehicles.map(DemoMath.pose));
    for (const s of this.signals) {
      const active = s.phase === world.phase;
      const color =
        active && world.signal === "GREEN"
          ? 0x21d7a1
          : active && world.signal === "YELLOW"
            ? 0xf3bf55
            : 0xe46565;
      s.bulb.material.color.setHex(color);
      s.bulb.material.emissive.setHex(color);
      s.bulb.material.emissiveIntensity = 0.35;
    }
  }
}
