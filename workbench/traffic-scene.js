/* Three.js r147, local assets only. Presentation never manufactures trajectories. */
class TrafficScene {
  constructor(element) {
    this.element = element;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xadb9b5);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputEncoding = THREE.sRGBEncoding;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.9;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.setAttribute(
      "aria-label",
      "Interactive 3D road reconstruction. Drag to orbit, right-drag to pan, scroll to zoom.",
    );
    element.append(this.renderer.domElement);
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 1500);
    this.controls = new THREE.OrbitControls(
      this.camera,
      this.renderer.domElement,
    );
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.09;
    this.controls.screenSpacePanning = false;
    this.controls.minDistance = 7;
    this.controls.maxDistance = 600;
    this.controls.minPolarAngle = 0.03;
    this.controls.maxPolarAngle = Math.PI * 0.475;
    this.controls.addEventListener("start", () => {
      this.follow = false;
      this.onOrbit?.();
    });
    this.scene.add(new THREE.HemisphereLight(0xecf8ff, 0x636b60, 0.65));
    const sun = new THREE.DirectionalLight(0xfff1d8, 1.1);
    sun.position.set(-35, 65, 25);
    sun.castShadow = true;
    Object.assign(sun.shadow.camera, {
      left: -90,
      right: 90,
      top: 90,
      bottom: -90,
      near: 1,
      far: 180,
    });
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0005;
    sun.shadow.normalBias = 0.025;
    this.scene.add(sun);
    this.road = new THREE.Group();
    this.scene.add(this.road);
    this.paths = new THREE.Group();
    this.scene.add(this.paths);
    this.cars = new Map();
    this.templates = new Map();
    this.palette = [
      0xe6edf0, 0x90b4bb, 0x526e7c, 0xe0bf7c, 0xbdc2c8, 0x83998b, 0xc7a49a,
    ];
    this.pick = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.selection = new THREE.Mesh(
      new THREE.RingGeometry(2.7, 2.82, 64),
      new THREE.MeshBasicMaterial({
        color: 0x18b69b,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
      }),
    );
    this.selection.rotation.x = -Math.PI / 2;
    this.selection.visible = false;
    this.scene.add(this.selection);
    let down = null;
    this.renderer.domElement.addEventListener("pointerdown", (e) => {
      down = [e.clientX, e.clientY];
    });
    this.renderer.domElement.addEventListener("pointerup", (e) => {
      if (
        !down ||
        Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5 ||
        e.button !== 0
      )
        return;
      const r = this.renderer.domElement.getBoundingClientRect();
      this.pointer.set(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        (-(e.clientY - r.top) / r.height) * 2 + 1,
      );
      this.pick.setFromCamera(this.pointer, this.camera);
      let target = this.pick.intersectObjects([...this.cars.values()], true)[0]
        ?.object;
      while (target && !target.userData.trackId) target = target.parent;
      this.select(target?.userData.trackId || null);
      this.onSelect?.(this.selected);
    });
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(element);
    this.center = new THREE.Vector3();
    this.radius = 50;
    this.preset("junction");
  }
  resize() {
    const w = this.element.clientWidth,
      h = this.element.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.render();
  }
  disposeGroup(group) {
    const geometries = new Set(),
      materials = new Set();
    group.traverse((o) => {
      if (o.geometry) geometries.add(o.geometry);
      if (o.material)
        (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) =>
          materials.add(m),
        );
    });
    geometries.forEach((g) => g.dispose());
    materials.forEach((m) => {
      m.map?.dispose();
      m.dispose();
    });
    group.clear();
  }
  material(color, roughness = 0.8) {
    return new THREE.MeshStandardMaterial({
      color,
      roughness,
      metalness: 0.04,
    });
  }
  mesh(geometry, material, parent, x = 0, y = 0, z = 0) {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    parent.add(mesh);
    return mesh;
  }
  rounded(width, length, height, radius = 0.1) {
    const s = new THREE.Shape(),
      x = -width / 2,
      y = -length / 2,
      r = radius;
    s.moveTo(x + r, y);
    s.lineTo(x + width - r, y);
    s.quadraticCurveTo(x + width, y, x + width, y + r);
    s.lineTo(x + width, y + length - r);
    s.quadraticCurveTo(x + width, y + length, x + width - r, y + length);
    s.lineTo(x + r, y + length);
    s.quadraticCurveTo(x, y + length, x, y + length - r);
    s.lineTo(x, y + r);
    s.quadraticCurveTo(x, y, x + r, y);
    const g = new THREE.ExtrudeGeometry(s, {
      depth: height,
      bevelEnabled: true,
      bevelThickness: 0.045,
      bevelSize: 0.045,
      bevelSegments: 2,
      steps: 1,
      curveSegments: 4,
    });
    g.rotateX(-Math.PI / 2);
    return g;
  }
  carTemplate(index) {
    if (this.templates.has(index)) return this.templates.get(index);
    const car = new THREE.Group(),
      paint = this.material(this.palette[index], 0.3),
      glass = this.material(0x243b46, 0.19),
      rubber = this.material(0x20272b),
      metal = this.material(0x97a7ad, 0.32);
    paint.metalness = 0.32;
    glass.metalness = 0.36;
    this.mesh(this.rounded(1.77, 4.42, 0.53, 0.28), paint, car, 0, 0.43, 0);
    this.mesh(this.rounded(1.69, 4.22, 0.2, 0.24), paint, car, 0, 0.92, 0);
    // Tapered glazed passenger cabin. Front is local -Z.
    const vertices = [
      [-0.75, 1.05, -0.99],
      [0.75, 1.05, -0.99],
      [0.75, 1.05, 1.28],
      [-0.75, 1.05, 1.28],
      [-0.61, 1.64, -0.46],
      [0.61, 1.64, -0.46],
      [0.61, 1.64, 0.8],
      [-0.61, 1.64, 0.8],
    ];
    const faces = [
      0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7, 4,
      5, 6, 4, 6, 7,
    ];
    const cab = new THREE.BufferGeometry();
    cab.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(vertices.flat(), 3),
    );
    cab.setIndex(faces);
    cab.computeVertexNormals();
    glass.side = THREE.DoubleSide;
    this.mesh(cab, glass, car);
    this.mesh(this.rounded(1.21, 1.28, 0.05, 0.12), paint, car, 0, 1.64, 0.17);
    for (const side of [-1, 1]) {
      this.mesh(
        new THREE.BoxGeometry(0.06, 0.49, 0.12),
        paint,
        car,
        side * 0.73,
        1.32,
        0.22,
      );
      this.mesh(
        this.rounded(0.2, 0.3, 0.13, 0.06),
        paint,
        car,
        side * 0.94,
        1.12,
        -0.72,
      );
      for (const z of [-1.35, 1.37]) {
        const tyre = this.mesh(
          new THREE.CylinderGeometry(0.35, 0.35, 0.21, 16),
          rubber,
          car,
          side * 0.86,
          0.37,
          z,
        );
        tyre.rotation.z = Math.PI / 2;
        const rim = this.mesh(
          new THREE.CylinderGeometry(0.2, 0.2, 0.012, 12),
          metal,
          car,
          side * 0.971,
          0.37,
          z,
        );
        rim.rotation.z = Math.PI / 2;
      }
      const white = new THREE.MeshStandardMaterial({
        color: 0xf3eddc,
        emissive: 0xe6dcb7,
        emissiveIntensity: 0.35,
      });
      const red = new THREE.MeshStandardMaterial({
        color: 0xa52e32,
        emissive: 0xa51c25,
        emissiveIntensity: 0.3,
      });
      this.mesh(
        new THREE.BoxGeometry(0.48, 0.15, 0.04),
        white,
        car,
        side * 0.52,
        0.87,
        -2.21,
      );
      this.mesh(
        new THREE.BoxGeometry(0.46, 0.15, 0.04),
        red,
        car,
        side * 0.53,
        0.87,
        2.21,
      );
    }
    this.mesh(
      new THREE.BoxGeometry(0.75, 0.13, 0.05),
      rubber,
      car,
      0,
      0.59,
      -2.25,
    );
    this.mesh(
      new THREE.BoxGeometry(0.43, 0.13, 0.05),
      metal,
      car,
      0,
      0.65,
      2.25,
    );
    this.templates.set(index, car);
    return car;
  }
  setRoad(points) {
    this.disposeGroup(this.road);
    this.disposeGroup(this.paths);
    const xs = points.map((p) => p[0]),
      zs = points.map((p) => p[1]);
    const minX = Math.min(...xs),
      maxX = Math.max(...xs),
      minZ = Math.min(...zs),
      maxZ = Math.max(...zs);
    this.center.set((minX + maxX) / 2, 0, (minZ + maxZ) / 2);
    this.radius = Math.max(maxX - minX, maxZ - minZ) / 2;
    const ground = this.mesh(
      this.rounded(maxX - minX + 20, maxZ - minZ + 20, 0.7, 3),
      this.material(0x8b9790),
      this.road,
      this.center.x,
      -0.82,
      this.center.z,
    );
    ground.castShadow = false;
    const grid = new THREE.GridHelper(300, 60, 0xa2b0ab, 0xa2b0ab);
    grid.position.y = -0.08;
    grid.material.transparent = true;
    grid.material.opacity = 0.25;
    this.road.add(grid);
    const shape = new THREE.Shape(
      points.map((p) => new THREE.Vector2(p[0], -p[1])),
    );
    const road = this.mesh(
      new THREE.ExtrudeGeometry(shape, { depth: 0.09, bevelEnabled: false }),
      this.material(0x080c0f, 0.96),
      this.road,
    );
    road.rotation.x = -Math.PI / 2;
    road.position.y = -0.04;
    road.castShadow = false;
    // A traced boundary, not invented lane paint, lanes, signals or buildings.
    const lineGeo = new THREE.BufferGeometry().setFromPoints(
      [...points, points[0]].map((p) => new THREE.Vector3(p[0], 0.08, p[1])),
    );
    this.road.add(
      new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: 0x8caaa3 })),
    );
    this.groundGrid = new THREE.Group();
    this.road.add(this.groundGrid);
    this.preset("junction");
  }
  setPaths(tracks) {
    this.disposeGroup(this.paths);
    const material = new THREE.LineBasicMaterial({
      color: 0x267a76,
      transparent: true,
      opacity: 0.35,
      depthWrite: false,
    });
    for (const track of tracks)
      for (const segment of track.segments)
        if (segment.length > 1) {
          const g = new THREE.BufferGeometry().setFromPoints(
            segment.map((p) => new THREE.Vector3(p[1], 0.12, p[2])),
          );
          this.paths.add(new THREE.Line(g, material));
        }
    this.paths.visible = false;
  }
  setGroundGrid(lines) {
    this.disposeGroup(this.groundGrid);
    const material = new THREE.LineBasicMaterial({
      color: 0x75b5ac,
      transparent: true,
      opacity: 0.35,
      depthWrite: false,
    });
    const vertices = lines.flatMap(([a, b]) => [
      new THREE.Vector3(a[0], 0.105, a[1]),
      new THREE.Vector3(b[0], 0.105, b[1]),
    ]);
    this.groundGrid.add(
      new THREE.LineSegments(
        new THREE.BufferGeometry().setFromPoints(vertices),
        material,
      ),
    );
  }
  frame(poses) {
    const visible = new Set(poses.map((p) => p.id));
    for (const [id, car] of this.cars)
      if (!visible.has(id)) {
        this.scene.remove(car);
        this.cars.delete(id);
      }
    for (const p of poses) {
      let car = this.cars.get(p.id);
      if (!car) {
        const hash = [...p.id].reduce(
          (a, c) => (a * 31 + c.charCodeAt(0)) >>> 0,
          0,
        );
        car = this.vehicleTemplate(hash % this.palette.length, p.classId).clone(
          true,
        );
        car.userData.trackId = p.id;
        this.cars.set(p.id, car);
        this.scene.add(car);
      }
      car.position.set(p.x, 0.07, p.z);
      car.rotation.y = p.yaw;
      car.userData.pose = p;
    }
    this.select(this.selected);
    if (this.follow && this.selection.visible) {
      const delta = this.selection.position.clone().sub(this.controls.target);
      delta.y = 0;
      this.camera.position.add(delta);
      this.controls.target.add(delta);
    }
  }
  select(id) {
    this.selected = id;
    const car = this.cars.get(id);
    this.selection.visible = !!car;
    if (car) this.selection.position.set(car.position.x, 0.15, car.position.z);
  }
  vehicleTemplate(index, classId) {
    if (![3, 5, 7].includes(classId)) return this.carTemplate(index);
    const key = `${index}:${classId}`;
    if (this.templates.has(key)) return this.templates.get(key);
    const model = new THREE.Group(),
      paint = this.material(this.palette[index], 0.35),
      glass = this.material(0x203942, 0.22),
      tyre = this.material(0x182226),
      rim = this.material(0x9eadaf, 0.3);
    if (classId === 3) {
      // Motorcycle-class proxy. Rickshaws are not a distinct detector class.
      this.mesh(this.rounded(0.5, 1.45, 0.3, 0.16), paint, model, 0, 0.55, 0);
      this.mesh(
        this.rounded(0.4, 0.75, 0.15, 0.12),
        tyre,
        model,
        0,
        0.87,
        0.25,
      );
      this.mesh(
        new THREE.BoxGeometry(0.78, 0.07, 0.07),
        rim,
        model,
        0,
        1.16,
        -0.65,
      );
      for (const z of [-0.8, 0.8]) {
        const wheel = this.mesh(
          new THREE.CylinderGeometry(0.33, 0.33, 0.16, 16),
          tyre,
          model,
          0,
          0.34,
          z,
        );
        wheel.rotation.z = Math.PI / 2;
        for (const side of [-1, 1]) {
          const hub = this.mesh(
            new THREE.CylinderGeometry(0.22, 0.22, 0.012, 16),
            rim,
            model,
            side * 0.085,
            0.34,
            z,
          );
          hub.rotation.z = Math.PI / 2;
        }
      }
    } else {
      const bus = classId === 5,
        length = bus ? 10 : 7.5,
        width = 2.4;
      this.mesh(
        this.rounded(width, length, 1.7, 0.25),
        paint,
        model,
        0,
        0.64,
        0,
      );
      if (bus) {
        this.mesh(this.rounded(2.32, 9.8, 0.8, 0.2), glass, model, 0, 2.34, 0);
        this.mesh(this.rounded(2.42, 10, 0.13, 0.2), paint, model, 0, 3.14, 0);
        for (let z = -3.7; z < 4.5; z += 1.2)
          this.mesh(
            new THREE.BoxGeometry(2.37, 0.85, 0.09),
            paint,
            model,
            0,
            2.72,
            z,
          );
      } else {
        this.mesh(
          this.rounded(2.35, 4.7, 1, 0.1),
          this.material(0xb6c0bd),
          model,
          0,
          2.28,
          1.28,
        );
        this.mesh(
          new THREE.BoxGeometry(2.1, 0.85, 0.05),
          glass,
          model,
          0,
          2.28,
          -length / 2 - 0.01,
        );
        this.mesh(
          new THREE.BoxGeometry(2.42, 0.8, 1.45),
          glass,
          model,
          0,
          2.3,
          -2.9,
        );
        this.mesh(
          this.rounded(2.42, 1.55, 0.1, 0.1),
          paint,
          model,
          0,
          2.72,
          -2.93,
        );
      }
      for (const side of [-1, 1])
        for (const z of [-length * 0.32, length * 0.32]) {
          const wheel = this.mesh(
            new THREE.CylinderGeometry(0.53, 0.53, 0.25, 18),
            tyre,
            model,
            side * 1.12,
            0.54,
            z,
          );
          wheel.rotation.z = Math.PI / 2;
          const hub = this.mesh(
            new THREE.CylinderGeometry(0.32, 0.32, 0.02, 16),
            rim,
            model,
            side * 1.25,
            0.54,
            z,
          );
          hub.rotation.z = Math.PI / 2;
        }
      for (const side of [-1, 1]) {
        this.mesh(
          new THREE.BoxGeometry(0.4, 0.21, 0.05),
          this.material(0xf4ead5),
          model,
          side * 0.82,
          1.12,
          -length / 2 - 0.02,
        );
        this.mesh(
          new THREE.BoxGeometry(0.36, 0.21, 0.05),
          this.material(0xad353b),
          model,
          side * 0.84,
          1.1,
          length / 2 + 0.02,
        );
      }
    }
    this.templates.set(key, model);
    return model;
  }
  preset(name) {
    this.follow = false;
    this.controls.target.copy(this.center);
    const halfAngle = Math.min(
      (this.camera.fov * Math.PI) / 360,
      Math.atan(
        Math.tan((this.camera.fov * Math.PI) / 360) * this.camera.aspect,
      ),
    );
    if (name === "fit") {
      const angle = Math.min(
        (this.camera.fov * Math.PI) / 360,
        Math.atan(
          Math.tan((this.camera.fov * Math.PI) / 360) * this.camera.aspect,
        ),
      );
      const d = (this.radius * 1.2) / Math.sin(angle);
      this.camera.position
        .copy(this.center)
        .add(new THREE.Vector3(0.55, 0.9, 1).normalize().multiplyScalar(d));
    } else if (name === "top")
      this.camera.position
        .copy(this.center)
        .add(
          new THREE.Vector3(
            0,
            Math.max(35, (this.radius * 1.08) / Math.tan(halfAngle)),
            0.01,
          ),
        );
    else if (name === "street")
      this.camera.position.copy(this.center).add(new THREE.Vector3(17, 9, 24));
    else {
      this.camera.position
        .copy(this.center)
        .add(
          new THREE.Vector3(0.55, 0.8, 0.95)
            .normalize()
            .multiplyScalar(
              Math.max(35, (this.radius * 1.12) / Math.sin(halfAngle)),
            ),
        );
    }
    this.controls.update();
    this.resize();
  }
  render() {
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
  dispose() {
    this.observer.disconnect();
    this.controls.dispose();
    this.disposeGroup(this.road);
    this.disposeGroup(this.paths);
    this.templates.forEach((t) => this.disposeGroup(t));
    this.selection.geometry.dispose();
    this.selection.material.dispose();
    this.renderer.dispose();
  }
}
