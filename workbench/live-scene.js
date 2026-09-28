/* UI adapter: live boxes only; saved source-specific geometry is explicitly labelled. */
class LiveSceneView {
  constructor(element, status, details = null) {
    this.element = element;
    this.status = status;
    this.details = details;
    this.scene = null;
    this.adapter = null;
    this.session = null;
    this.source = null;
    this.enabled = true;
    this.connected = true;
    this.generation = 0;
    this.message = "Start detection to load this source’s estimated road.";
    this.tick = this.tick.bind(this);
    this.animation = requestAnimationFrame(this.tick);
    // A back/forward-cache page resumes its own animation on return. Dispose
    // only when the document actually leaves, not when it is temporarily frozen.
    this.onPageHide = (event) => { if (!event.persisted) this.dispose(); };
    addEventListener("pagehide", this.onPageHide);
  }
  async load(source) {
    const generation = ++this.generation;
    this.abort?.abort();
    const controller = new AbortController();
    this.abort = controller;
    this.source = source;
    this.adapter = null;
    this.scene?.dispose();
    this.scene = null;
    this.element.replaceChildren();
    this.element.dataset.vehicleCount = "0";
    this.element.dataset.sourceRun = source || "";
    this.element.dataset.geometryRevision = "";
    this.element.dataset.projectionKind = "";
    if (!source) {
      this.message = "Choose footage to inspect its saved road.";
      if (this.details) this.details.textContent = this.message;
      return;
    }
    this.message = "Loading source-bound road and camera estimates…";
    if (this.details) this.details.textContent = this.message;
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(source)}/live-geometry`,
        { cache: "no-store", signal: controller.signal });
      const geometry = await response.json();
      if (generation !== this.generation) return;
      if (!response.ok) throw Error(geometry.error || "Road estimate unavailable");
      const adapter = new LiveSceneMath.LivePoses(geometry);
      this.scene = new TrafficScene(this.element);
      // Modest local preview cost. Detection remains on its isolated worker.
      this.scene.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
      this.scene.setRoad(adapter.points);
      this.scene.setGroundGrid(ReplayMath.groundGrid(adapter.points));
      this.scene.groundGrid.visible = false;
      this.scene.preset("junction");
      this.adapter = adapter;
      this.element.dataset.geometryRevision = geometry.geometry_revision || "";
      this.element.dataset.projectionKind = geometry.projection_kind || "automatic-estimate";
      if (this.details) {
        const mapped = (geometry.registration || []).filter(r => ["accepted", "reference"].includes(r.status) && r.H).length;
        const cadence = geometry.registration_cadence_s;
        const fps = Number.isFinite(cadence) && cadence > 0 ? (1 / cadence).toFixed(1) : null;
        this.details.textContent = `${adapter.projectionLabel} · physical scale estimated. ${mapped}/${geometry.registration?.length || 0} native camera frames supported.${fps ? ` Prepared at approximately ${fps} FPS; other cadences can leave cars unmapped.` : ""}`;
      }
      this.message = "Geometry loaded · waiting for fresh matching observations.";
    } catch (e) {
      if (generation !== this.generation) return;
      this.scene?.dispose();
      this.scene = null;
      this.element.replaceChildren();
      this.message = `3D unavailable: ${e.message}. Detection remains available.`;
      if (this.details) this.details.textContent = "No supported road loaded. Review this clip in the recorded studio, save a supported estimate, and finish refinement before reloading the road.";
    } finally {
      clearTimeout(timeout);
    }
  }
  update(session, connected = true, selectedSource = session?.source_run || null) {
    const newSession = session?.id && session.id !== this.session?.id;
    this.session = session;
    this.connected = connected;
    // A new session on the same clip must not retain an earlier road revision.
    if (this.source !== selectedSource || (selectedSource && newSession)) this.load(selectedSource);
  }
  setEnabled(value) {
    this.enabled = value;
    if (!value) this.adapter?.clear();
  }
  preset(name) { this.scene?.preset(name); }
  tick(timestamp) {
    this.animation = requestAnimationFrame(this.tick);
    if (document.hidden || (this.lastDraw && timestamp - this.lastDraw < 1000 / 30)) return;
    this.lastDraw = timestamp;
    let message = this.message;
    if (this.adapter && this.scene) {
      if (!this.enabled || !this.connected) {
        this.adapter.clear();
        this.scene.frame([]);
        message = this.connected ? "3D paused · detections continue" : "Disconnected · live cars hidden";
      } else {
        const result = this.adapter.update(this.session);
        this.scene.frame(this.adapter.sample());
        message = `${result.reason} · ${result.poses.length} shown · ${result.hidden} hidden`;
        if (result.headingUnknown) message += ` · ${result.headingUnknown} headings unknown`;
        if (result.jumps) message += ` · ${result.jumps} jumps rejected`;
      }
      this.scene.render();
      this.element.dataset.vehicleCount = String(this.scene.cars.size);
      this.element.dataset.sourceRun = this.source;
      this.element.dataset.sessionId = this.session?.id || "";
    }
    if (this.status.textContent !== message) this.status.textContent = message;
  }
  dispose() {
    this.generation++;
    this.abort?.abort();
    cancelAnimationFrame(this.animation);
    this.scene?.dispose();
    removeEventListener("pagehide", this.onPageHide);
  }
}
