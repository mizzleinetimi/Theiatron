/* Recorded tracks only. Never reads point-queue departure times or SUMO states. */
(async function () {
  "use strict";
  const $ = (id) => document.getElementById(id),
    M = ReplayMath;
  const run = new URLSearchParams(location.search).get("video");
  $("demoLink").href = `/workbench/demo.html?video=${encodeURIComponent(run||'')}&step=compare`;
  let data,
    token,
    scene,
    tracks = [],
    calibration,
    draft,
    undo = [],
    selectedPoint = "a:0";
  let time = 0,
    playing = false,
    mediaFailed = false,
    lastWall = performance.now(),
    lastText = -1,
    dirty = false;
  let refinementTimer = null,
    refinementRequest = null,
    refinementState = "idle",
    refinementErrors = 0,
    pageActive = true,
    refinementGeneration = 0;
  const activeRefinement = (state) =>
    ["starting", "queued", "processing", "cancelling"].includes(state);
  const video = $("sourceClip"),
    plate = new Image(),
    canvas = $("calibrationCanvas"),
    ctx = canvas.getContext("2d");
  const overlay = $("overlay").getContext("2d");
  const clock = (t) =>
    `${Math.floor(t / 60)}:${Math.floor(t % 60)
      .toString()
      .padStart(2, "0")}`;
  const className = (id) =>
    ({ 2: "car", 3: "motorcycle", 5: "bus", 7: "truck" })[id] ||
    "generic vehicle";
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const assistGuide = new AssistGuide();
  let assistPreview = null, assistGeneration = 0, assistWasDirty = null;
  async function read(url, options) {
    const r = await fetch(url, { cache: "no-store", ...options });
    const d = await r.json();
    if (!r.ok) throw Error(d.error || `Request failed (${r.status})`);
    return d;
  }
  function fatal(message) {
    $("fatal").hidden = false;
    $("fatal").textContent = message;
  }
  function pause() {
    playing = false;
    video.pause();
    $("play").textContent = "Play";
  }
  function seek(t) {
    time = Math.max(0, Math.min(data.duration, t));
    if (video.readyState >= 1)
      video.currentTime = Math.max(
        0,
        Math.min(video.duration - 0.001, time - data.video_offset_s),
      );
    $("seek").value = time;
    lastText = -1;
    draw();
  }
  function rebuild(value, keepCamera = false) {
    const selectedTrack = scene.selected,
      wasFollowing = scene.follow;
    const cameraState = keepCamera
      ? {
          position: scene.camera.position.clone(),
          target: scene.controls.target.clone(),
        }
      : null;
    const { h, points } = M.roadWorld(value);
    const refined =
      $("stabilize").checked && data.refinement && !data.refinement.stale;
    const prepared = M.prepareTracks(
      refined ? data.refinement.tracks : data.tracks,
      h,
    );
    scene.setRoad(points);
    scene.setGroundGrid(M.groundGrid(points));
    scene.groundGrid.visible = $("showGroundGrid").checked;
    scene.setPaths(prepared);
    tracks = prepared;
    calibration = clone(value);
    if (cameraState) {
      scene.camera.position.copy(cameraState.position);
      scene.controls.target.copy(cameraState.target);
    }
    scene.paths.visible = $("showTrails").checked;
    $("fatal").hidden = true;
    $("sceneStatus").textContent =
      `${data.source_name} · ${refined ? "refined motion" : "raw motion"} · ${assistPreview ? "UNSAVED ASSISTED PREVIEW" : data.assistance ? "OPERATOR-ASSISTED ESTIMATE · unvalidated" : $("perspectiveCorrection").checked && data.refinement?.ground_projection && !data.refinement.stale ? "camera-rectified ground" : data.default_projection_kind === "unrectified-image-plane" && !data.revision ? "UNRECTIFIED PREVIEW · physical road shape unresolved" : "manual projection"} · scale estimated`;
    $("trackTotal").textContent = tracks.length;
    $("trackSelect").replaceChildren(
      new Option("Click a car or select a track", ""),
      ...tracks.map(
        (t) =>
          new Option(
            `${t.id} · ${className(t.classId)}${t.counted ? " · counted" : ""}`,
            t.id,
          ),
      ),
    );
    if (selectedTrack && tracks.some((t) => t.id === selectedTrack)) {
      scene.select(selectedTrack);
      $("trackSelect").value = selectedTrack;
      scene.follow = wasFollowing;
    }
    ["play", "restart", "seek"].forEach((id) => ($(id).disabled = false));
    draw();
  }
  function currentGeometry() {
    if (assistPreview) return clone(assistPreview.result.calibration);
    if (data.assistance) return clone(data.calibration);
    const value = clone(data.calibration),
      r = data.refinement;
    if (r && !r.stale) {
      if ($("automaticRoad").checked && r.calibration)
        value.road = clone(r.calibration.road);
      if ($("perspectiveCorrection").checked && r.ground_projection) {
        for (const key of ["anchors", "width_m", "depth_m", "label"])
          value[key] = clone(r.ground_projection[key]);
      }
    }
    return value;
  }
  function showRefinement() {
    const r = data.refinement, g = r?.ground_quality;
    if(data.assistance){$("automaticRoad").checked=false;$("perspectiveCorrection").checked=false;}
    $("automaticRoad").disabled = !!data.assistance || !r?.calibration || r.stale;
    $("editAutomaticRoad").disabled = !r?.calibration || r.stale;
    $("perspectiveCorrection").disabled = !!data.assistance || !r?.ground_projection || r.stale;
    $("projectionStatus").textContent = M.projectionStatus(data);
    if (!r) {
      $("refinementStatus").textContent =
        data.track_sampling === "dense-processed-frames"
          ? "Automatic estimates are being prepared. Original detections and counts remain unchanged."
          : "Automatic refinement needs dense observations. Reanalyse this local clip in the workbench first.";
      return;
    }
    if (r.stale) {
      $("refinementStatus").textContent =
        "Saved estimates no longer match the current source, calibration or algorithm. Raw observations are shown while a fresh refinement is prepared.";
      return;
    }
    const d = r.diagnostics;
    const camera = r.camera_registration?.summary;
    $("refinementStatus").textContent =
      `${d.samples.toLocaleString()} observations · ${d.isolated_outliers} isolated spikes downweighted · ${d.segment_breaks} discontinuities/gaps split. Camera: ${camera ? `${camera.accepted}/${camera.frames} frames registered; ${d.camera_rejected_observations} observations omitted at failed matches` : r.camera_status}. Filtering jitter proxy ${d.median_raw_second_difference_px?.toFixed(2) ?? "—"} → ${d.median_filtered_second_difference_px?.toFixed(2) ?? "—"} px (smoothness in the working image plane, not accuracy). Road: ${r.road_quality.status}. Ground projection: ${g?.status || "not computed"}.`;
  }
  function workerStatus(state, message) {
    refinementState = state;
    const active = activeRefinement(state);
    $("autoRefine").disabled =
      active || data.track_sampling !== "dense-processed-frames";
    $("autoRefine").textContent = active
      ? "Refining…"
      : ["failed", "cancelled", "disconnected"].includes(state)
        ? "Retry refinement"
        : "Auto refine";
    $("cancelRefinement").hidden = !active;
    $("cancelRefinement").disabled = state === "cancelling";
    $("refinementWork").hidden = !message;
    $("refinementWork").dataset.state = state;
    $("refinementMessage").textContent = message || "";
    $("refinementWork").setAttribute("aria-busy", String(active));
  }
  function scheduleRefinementPoll(delay = 1000) {
    clearTimeout(refinementTimer);
    if (pageActive) refinementTimer = setTimeout(pollRefinement, delay);
  }
  async function refreshRefinement() {
    const fresh = await read(`/api/runs/${run}/reconstruction`);
    if (!pageActive) return false;
    if (JSON.stringify(fresh.binding) !== JSON.stringify(data.binding))
      throw Error(
        "Source observations changed. Reload this replay before applying estimates.",
      );
    data = fresh;
    showRefinement();
    revisionText();
    if (!data.refinement || data.refinement.stale) return false;
    // Reload only the source metadata, not the page/video: the replay clock,
    // playback state and orbit camera remain exactly where the viewer left them.
    if (!dirty) {
      draft = clone(data.calibration);
      fields();
    }
    rebuild(currentGeometry(), !!calibration);
    lastText = -1;
    draw();
    return true;
  }
  async function pollRefinement() {
    if (!pageActive || refinementRequest) return;
    refinementRequest = new AbortController();
    const generation = refinementGeneration;
    const timeout = setTimeout(() => refinementRequest?.abort(), 15000);
    try {
      const status = await read(`/api/runs/${run}/refine`, {
        signal: refinementRequest.signal,
      });
      if (!pageActive || generation !== refinementGeneration) return;
      refinementErrors = 0;
      workerStatus(status.state, status.message);
      if (activeRefinement(status.state)) scheduleRefinementPoll();
      else if (status.state === "complete") {
        if (await refreshRefinement())
          workerStatus(
            "complete",
            "Refinement ready. Updated road and motion estimates are shown without restarting your replay.",
          );
        else
          workerStatus(
            "failed",
            "The finished estimates do not match this calibration or algorithm. Choose Retry refinement to refresh them.",
          );
      } else if (status.state === "idle") {
        if (await refreshRefinement())
          workerStatus(
            "complete",
            "Saved refinement loaded. Original observations remain unchanged.",
          );
        else
          workerStatus(
            "disconnected",
            "The worker is no longer running. Choose Retry refinement to start again.",
          );
      }
    } catch (e) {
      if (!pageActive || generation !== refinementGeneration) return;
      refinementErrors++;
      if (refinementErrors <= 3) {
        workerStatus(
          "processing",
          "Refinement status temporarily unavailable. Reconnecting; playback remains available.",
        );
        scheduleRefinementPoll(refinementErrors * 2000);
      } else
        workerStatus(
          "disconnected",
          `Status connection lost: ${e.message}. Retry reconnects to an existing worker if it is still running.`,
        );
    } finally {
      clearTimeout(timeout);
      refinementRequest = null;
    }
  }
  async function refine() {
    if (activeRefinement(refinementState)) return;
    refinementGeneration++;
    refinementErrors = 0;
    clearTimeout(refinementTimer);
    workerStatus(
      "starting",
      "Starting local camera registration, trajectory filtering and road estimation. You can keep using the replay.",
    );
    try {
      const existing = await read(`/api/runs/${run}/refine`);
      if (activeRefinement(existing.state)) {
        workerStatus(existing.state, existing.message);
        scheduleRefinementPoll(250);
        return;
      }
      const status = await read(`/api/runs/${run}/refine`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Theiatron-Token": token,
        },
        body: JSON.stringify({ binding: data.binding }),
      });
      if (!pageActive) return;
      workerStatus(status.state, status.message);
      scheduleRefinementPoll(250);
    } catch (e) {
      workerStatus("failed", `Automatic refinement unavailable: ${e.message}`);
    }
  }
  async function resumeRefinement() {
    if (data.track_sampling !== "dense-processed-frames") {
      workerStatus(
        "idle",
        "Reanalyse the local clip to retain dense observations before automatic refinement.",
      );
      return;
    }
    try {
      const status = await read(`/api/runs/${run}/refine`);
      workerStatus(status.state, status.message);
      if (activeRefinement(status.state)) scheduleRefinementPoll(250);
      else if (data.refinement && !data.refinement.stale)
        workerStatus(
          "complete",
          "Source-bound automatic estimates loaded from cache.",
        );
      else if (["failed", "cancelled"].includes(status.state))
        workerStatus(
          status.state,
          `${status.message || "Refinement stopped."} Choose Retry refinement when ready.`,
        );
      else await refine();
    } catch (e) {
      workerStatus(
        "disconnected",
        `Cannot check the refinement worker: ${e.message}. Choose Retry refinement to reconnect.`,
      );
    }
  }
  function choose(id) {
    scene.select(id || null);
    $("trackSelect").value = id || "";
    $("jumpTrack").disabled = !id;
    $("followTrack").disabled = !id;
    scene.follow = false;
    $("followTrack").textContent = "Follow";
    lastText = -1;
    draw();
  }
  function draw() {
    if (!scene || !calibration) return;
    const poses = tracks.map((t) => M.sampleTrack(t, time)).filter(Boolean);
    const onRoad = poses.filter(
      (p) => !$("roadOnly").checked || M.inside(p.pixel, calibration.road),
    );
    scene.frame(onRoad);
    overlay.clearRect(0, 0, 1280, 720);
    for (const p of poses) {
      const pixel =
        p.refined && data.refinement?.camera_registration
          ? M.cameraPixel(data.refinement.camera_registration, time, p.pixel)
          : p.pixel;
      if (!pixel) continue;
      const selected = p.id === scene.selected;
      overlay.strokeStyle = selected ? "#ffe583" : "#9affdd";
      overlay.lineWidth = selected ? 4 : 2;
      overlay.beginPath();
      overlay.arc(...pixel, selected ? 13 : 5, 0, Math.PI * 2);
      overlay.stroke();
      if (selected && p.refined) {
        overlay.strokeStyle = "#ff927a";
        overlay.lineWidth = 2;
        overlay.beginPath();
        overlay.arc(...p.rawPixel, 6, 0, Math.PI * 2);
        overlay.stroke();
        overlay.beginPath();
        overlay.moveTo(...p.rawPixel);
        overlay.lineTo(...pixel);
        overlay.stroke();
      }
      if (selected) {
        overlay.fillStyle = "#10252ddd";
        overlay.fillRect(pixel[0] + 15, pixel[1] - 24, 150, 29);
        overlay.fillStyle = "#fff1b7";
        overlay.font = "18px sans-serif";
        overlay.fillText(p.id, pixel[0] + 20, pixel[1] - 4);
      }
    }
    if (Math.abs(time - lastText) > 0.09) {
      lastText = time;
      $("seek").value = time;
      $("clock").textContent = `${clock(time)} / ${clock(data.duration)}`;
      $("visibleCount").textContent = onRoad.length;
      $("displayStatus").textContent =
        `${tracks[0]?.refined ? "Offline robust filtering · stable motion headings" : "Raw anchors · stabilized headings"}. ${poses.length - onRoad.length} outside-road anchors hidden. Gaps and flagged jumps are not bridged. Selected track: mint = estimate, coral = raw.`;
      if (scene.selected) {
        const p = poses.find((p) => p.id === scene.selected);
        $("trackInfo").textContent = p
          ? `${p.id}${p.arrival ? " / " + p.arrival : ""} · ${className(p.classId)}${Number.isFinite(p.confidence) ? ` · mean detector confidence ${(p.confidence * 100).toFixed(0)}% · class agreement ${(p.classConsistency * 100).toFixed(0)}%` : ""}. Sample ${p.sampleTime.toFixed(2)} s · image anchor ${p.pixel.map((v) => Math.round(v)).join(", ")} px. ${p.headingKnown ? "Heading estimated from motion." : "Heading unknown: default model orientation."}${onRoad.includes(p) ? "" : " Outside traced road; hidden."}`
          : `${scene.selected} is not observed at ${time.toFixed(2)} s. No extrapolated vehicle is shown.`;
      } else
        $("trackInfo").textContent =
          data.track_sampling === "dense-processed-frames"
            ? "Every processed-frame observation retained. Detected majority class chooses the model: car 4.5 m, motorcycle 2.1 m, bus 10 m, truck 7.5 m. Sizes are nominal, not measured; colours identify tracks."
            : "Legacy export: nominal 4.5 m cars. This analysis did not retain classes or sizes. Colours identify tracks, not detected paint.";
    }
  }
  function animate(now) {
    const dt = Math.min((now - lastWall) / 1000, 0.1);
    lastWall = now;
    if (playing) {
      if (!mediaFailed && video.readyState >= 2 && !video.seeking)
        time = Math.min(data.duration, video.currentTime + data.video_offset_s);
      else if (mediaFailed)
        time = Math.min(data.duration, time + dt * Number($("speed").value));
      if (time >= data.duration) pause();
    }
    if (!document.hidden) {
      draw();
      scene?.render();
    }
    requestAnimationFrame(animate);
  }
  function revisionText() {
    $("revision").textContent = data.revision
      ? `Draft revision ${data.revision.slice(0, 16)} · source ${data.binding.source_sha256.slice(0, 12)}`
      : "Source-specific initial draft · not yet saved or validated";
  }
  function remember() {
    assistGeneration++;
    if(assistWasDirty!==null)assistWasDirty=true;
    undo.push(clone(draft));
    if (undo.length > 60) undo.shift();
    dirty = true;
  }
  function point() {
    const [kind, index] = selectedPoint.split(":");
    return (kind === "a" ? draft.anchors : draft.road)[Number(index)];
  }
  function fields() {
    $("calibrationLabel").value = draft.label;
    $("widthM").value = draft.width_m;
    $("depthM").value = draft.depth_m;
    const values = [
      ...draft.anchors.map((_, i) => [`a:${i}`, `Anchor ${"ABCD"[i]}`]),
      ...draft.road.map((_, i) => [`r:${i}`, `Road corner ${i + 1}`]),
    ];
    if (!values.some((p) => p[0] === selectedPoint)) selectedPoint = "a:0";
    $("pointSelect").replaceChildren(
      ...values.map(([v, l]) => new Option(l, v)),
    );
    $("pointSelect").value = selectedPoint;
    const p = point();
    $("pointX").value = Math.round(p[0]);
    $("pointY").value = Math.round(p[1]);
    $("undoCalibration").disabled = !undo.length;
    paint();
  }
  function paint() {
    ctx.clearRect(0, 0, 1280, 720);
    if (plate.complete && plate.naturalWidth)
      ctx.drawImage(plate, 0, 0, 1280, 720);
    if (!draft) return;
    const polygon = (pts, fill, stroke) => {
      if (!pts.length) return;
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 3;
      ctx.stroke();
    };
    polygon(draft.road, "#4cdac629", "#82ffe0");
    try {
      const { h, points } = M.roadWorld(draft);
      ctx.strokeStyle = "#82ffe088";
      ctx.lineWidth = 1.5;
      for (const segment of M.groundGrid(points)) {
        const a = M.unproject(h, segment[0]),
          b = M.unproject(h, segment[1]);
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(...a);
        ctx.lineTo(...b);
        ctx.stroke();
      }
      if (Math.abs(h[7]) > 1e-9) {
        const y = (x) => (-((h[6] * x) / 1280 + h[8]) * 720) / h[7];
        ctx.strokeStyle = "#f9c17a";
        ctx.lineWidth = 3;
        ctx.setLineDash([12, 8]);
        ctx.beginPath();
        ctx.moveTo(0, y(0));
        ctx.lineTo(1280, y(1280));
        ctx.stroke();
        ctx.setLineDash([]);
      }
    } catch (_) {
      /* invalid unsaved drafts remain editable */
    }
    polygon(draft.anchors, "#e4bc6630", "#ffd88a");
    [
      ...draft.road.map((p, i) => [p, `r:${i}`, String(i + 1), "#95ffe1"]),
      ...draft.anchors.map((p, i) => [p, `a:${i}`, "ABCD"[i], "#ffda8c"]),
    ].forEach(([p, id, label, color]) => {
      ctx.fillStyle = id === selectedPoint ? "#ffffff" : "#12313b";
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(...p, id[0] === "a" ? 13 : 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.font = "bold 18px sans-serif";
      ctx.lineWidth = 4;
      ctx.strokeStyle = "#112029";
      ctx.strokeText(label, p[0] + 14, p[1] - 11);
      ctx.fillStyle = color;
      ctx.fillText(label, p[0] + 14, p[1] - 11);
    });
    assistGuide.points.forEach((p,i) => {
      ctx.strokeStyle = ctx.fillStyle = i<4 ? "#ffb84f" : "#e784ff";
      ctx.lineWidth=5;
      if (i%2) {ctx.beginPath();ctx.moveTo(...assistGuide.points[i-1]);ctx.lineTo(...p);ctx.stroke();}
      ctx.beginPath();ctx.arc(...p,7,0,Math.PI*2);ctx.fill();
      ctx.font="bold 20px sans-serif";
      ctx.fillText(`${i<4?"A":"B"}${Math.floor((i%4)/2)+1}${i%2?" end":" start"}`,p[0]+12,p[1]+22);
    });
  }
  function openEditor() {
    pause();
    if(assistPreview){discardAssist(true);return;}
    if (!dirty) draft = clone(currentGeometry());
    $("calibration").hidden = false;
    fields();
    assistFields();
  }
  function assistFields() {
    $("assistHint").textContent=assistGuide.message;
    if($("editMode").value==="directions")$("editHint").textContent=assistGuide.message;
    $("assistUndo").disabled=!assistGuide.points.length;
    $("assistAdd").disabled=assistGuide.complete;
    $("assistPreview").disabled=!assistGuide.complete;
    paint();
  }
  $("assistStart").onclick=()=>{
    if(assistWasDirty===null)assistWasDirty=dirty;
    assistGeneration++; assistGuide.reset(); dirty=true;
    $("editMode").value="directions";
    $("editHint").textContent="Choose endpoints on the reference image. A lines are parallel on the real ground; B lines follow a perpendicular ground direction.";
    assistFields();
  };
  $("assistUndo").onclick=()=>{assistGeneration++;assistGuide.undo();assistFields();};
  $("assistAdd").onclick=()=>{
    try{
      assistGuide.add([$("assistX").valueAsNumber,$("assistY").valueAsNumber]);
      if(assistWasDirty===null)assistWasDirty=dirty;
      assistGeneration++;dirty=true;$("editMode").value="directions";assistFields();
    } catch(e){$("assistHint").textContent=e.message;}
  };
  $("assistPreview").onclick=async()=>{
    const generation=++assistGeneration;
    $("assistPreview").disabled=true;
    $("assistHint").textContent="Checking selected directions and click sensitivity…";
    try {
      draft.width_m=$("widthM").valueAsNumber;
      draft.depth_m=$("depthM").valueAsNumber;
      draft.label=$("calibrationLabel").value;
      const request=assistGuide.request(data.binding,data.revision,draft);
      const result=await read(`/api/runs/${run}/reconstruction/assist`,{
        method:"POST",headers:{"Content-Type":"application/json","X-Theiatron-Token":token},body:JSON.stringify(request)
      });
      if (generation!==assistGeneration) return;
      assistPreview={request,result};
      $("calibration").hidden=true;$("assistPreviewBar").hidden=false;
      $("assistSaveStatus").textContent="";
      rebuild(currentGeometry());
    } catch(e) { if (generation===assistGeneration) $("assistHint").textContent=e.message; }
    finally { $("assistPreview").disabled=!assistGuide.complete; }
  };
  function discardAssist(reopen=false) {
    assistGeneration++;assistPreview=null;$("assistPreviewBar").hidden=true;
    rebuild(currentGeometry());
    if(reopen){$("calibration").hidden=false;fields();assistFields();}
  }
  $("assistBack").onclick=()=>discardAssist(true);
  $("assistDiscard").onclick=()=>{
    discardAssist(); assistGuide.reset();assistFields();
    dirty=assistWasDirty??dirty;assistWasDirty=null;
  };
  $("assistSave").onclick=async()=>{
    if(!assistPreview)return;
    const preview=assistPreview;
    for(const id of ["assistSave","assistBack","assistDiscard"])$(id).disabled=true;
    try {
      const result=await read(`/api/runs/${run}/reconstruction/assist/save`,{
        method:"POST",headers:{"Content-Type":"application/json","X-Theiatron-Token":token},body:JSON.stringify(preview.request)
      });
      data.calibration=clone(result.calibration);data.revision=result.revision;data.assistance=result.assistance;
      if(data.refinement)data.refinement.stale=true;
      assistPreview=null;$("assistPreviewBar").hidden=true;
      $("automaticRoad").checked=false;$("perspectiveCorrection").checked=false;
      dirty=false;assistWasDirty=null;undo=[];assistGuide.reset();draft=clone(data.calibration);
      showRefinement();revisionText();rebuild(currentGeometry());
      if(!activeRefinement(refinementState))void refine();
    } catch(e) {$("assistSaveStatus").textContent=e.message;}
    finally {for(const id of ["assistSave","assistBack","assistDiscard"])$(id).disabled=false;}
  };
  $("editAutomaticRoad").onclick = () => {
    if (!data.refinement?.calibration || data.refinement.stale) return;
    remember();
    draft.road = clone(data.refinement.calibration.road);
    draft.label = "Automatic road outline · operator draft";
    selectedPoint = "a:0";
    fields();
    $("calibrationStatus").textContent =
      "Automatic outline copied for review. Projection anchors and dimensions are unchanged. Save only after inspecting the proposed boundary.";
  };
  function imagePoint(event) {
    const r = canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1279, ((event.clientX - r.left) * 1280) / r.width)),
      Math.max(0, Math.min(719, ((event.clientY - r.top) * 720) / r.height)),
    ];
  }
  function nearest(p) {
    const all = [
      ...draft.anchors.map((p, i) => ({ p, id: `a:${i}` })),
      ...draft.road.map((p, i) => ({ p, id: `r:${i}` })),
    ];
    return all
      .map((a) => ({ ...a, d: Math.hypot(a.p[0] - p[0], a.p[1] - p[1]) }))
      .sort((a, b) => a.d - b.d)[0];
  }
  let dragging = false;
  canvas.addEventListener("pointerdown", (event) => {
    const p = imagePoint(event),
      mode = $("editMode").value,
      n = nearest(p),
      near = n.d < (24 * 1280) / canvas.clientWidth;
    if (mode === "directions") {
      if(assistWasDirty===null)assistWasDirty=dirty;
      assistGeneration++;assistGuide.add(p);dirty=true;assistFields();return;
    }
    if (mode === "trace") {
      if (draft.road.length >= 100) return;
      remember();
      draft.road.push(p);
      selectedPoint = `r:${draft.road.length - 1}`;
      fields();
      return;
    }
    if (mode === "remove") {
      if (near && n.id.startsWith("r:") && draft.road.length > 3) {
        remember();
        draft.road.splice(Number(n.id.split(":")[1]), 1);
        fields();
      }
      return;
    }
    if (mode === "add") {
      if (draft.road.length < 3 || draft.road.length >= 100) return;
      let best = { d: Infinity, i: 0 };
      draft.road.forEach((a, i) => {
        const b = draft.road[(i + 1) % draft.road.length],
          dx = b[0] - a[0],
          dy = b[1] - a[1],
          u = Math.max(
            0,
            Math.min(
              1,
              ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy),
            ),
          ),
          d = Math.hypot(p[0] - a[0] - u * dx, p[1] - a[1] - u * dy);
        if (d < best.d) best = { d, i };
      });
      remember();
      draft.road.splice(best.i + 1, 0, p);
      selectedPoint = `r:${best.i + 1}`;
      fields();
      return;
    }
    if (near) {
      remember();
      selectedPoint = n.id;
      dragging = true;
      canvas.setPointerCapture(event.pointerId);
      fields();
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const p = point(),
      next = imagePoint(e);
    p[0] = next[0];
    p[1] = next[1];
    $("pointX").value = Math.round(p[0]);
    $("pointY").value = Math.round(p[1]);
    paint();
  });
  canvas.addEventListener("pointerup", () => {
    dragging = false;
  });
  canvas.addEventListener("pointercancel", () => {
    dragging = false;
  });
  $("editMode").onchange = () => {
    if ($("editMode").value === "trace") {
      remember();
      draft.road = [];
      fields();
    }
    $("editHint").textContent =
      $("editMode").value === "directions" ? assistGuide.message : $("editMode").value === "trace"
        ? "Click around the entire road perimeter. Then switch to Move to adjust the corners."
        : "Drag a coloured anchor or a numbered road corner. Saved source data is unchanged.";
  };
  $("pointSelect").onchange = () => {
    selectedPoint = $("pointSelect").value;
    fields();
  };
  $("applyPoint").onclick = () => {
    const p = [$("pointX").valueAsNumber, $("pointY").valueAsNumber];
    if (
      p.some((v, i) => !Number.isFinite(v) || v < 0 || v > (i ? 719 : 1279))
    ) {
      $("calibrationStatus").textContent =
        "Point must be inside the 1280×720 image.";
      return;
    }
    remember();
    point().splice(0, 2, ...p);
    fields();
  };
  for (const [id, key] of [
    ["widthM", "width_m"],
    ["depthM", "depth_m"],
    ["calibrationLabel", "label"],
  ])
    $(id).onchange = () => {
      remember();
      draft[key] = key === "label" ? $(id).value : $(id).valueAsNumber;
    };
  $("undoCalibration").onclick = () => {
    if (undo.length) {
      draft = undo.pop();
      fields();
    }
  };
  $("resetCalibration").onclick = () => {
    remember();
    draft = clone(data.calibration);
    $("editMode").value = "move";
    fields();
  };
  $("saveCalibration").onclick = async () => {
    assistGeneration++;
    $("saveCalibration").disabled = true;
    try {
      // Read committed form values directly too (keyboard/autofill may not
      // deliver a blur/change before the save action).
      draft.label = $("calibrationLabel").value;
      draft.width_m = $("widthM").valueAsNumber;
      draft.depth_m = $("depthM").valueAsNumber;
      M.roadWorld(draft);
      const result = await read(`/api/runs/${run}/reconstruction`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Theiatron-Token": token,
        },
        body: JSON.stringify({ binding: data.binding, calibration: draft }),
      });
      data.calibration = clone(result.calibration);
      data.revision = result.revision;
      data.assistance = null;
      assistWasDirty=null;assistGuide.reset();
      if (data.refinement) data.refinement.stale = true;
      $("perspectiveCorrection").checked = false;
      $("automaticRoad").checked = false;
      showRefinement();
      rebuild(data.calibration, true);
      revisionText();
      dirty = false;
      undo = [];
      $("calibrationStatus").textContent =
        `Saved draft ${result.revision.slice(0, 12)}. Not a metric accuracy validation.`;
      $("calibration").hidden = true;
      if (!activeRefinement(refinementState)) void refine();
    } catch (e) {
      $("calibrationStatus").textContent = e.message;
    } finally {
      $("saveCalibration").disabled = false;
    }
  };
  $("calibrate").onclick = openEditor;
  $("closeCalibration").onclick = () => {
    assistGeneration++;
    $("calibration").hidden = true;
  };
  $("focus").onclick = () => {
    document.body.classList.toggle("focused");
    $("focus").textContent = document.body.classList.contains("focused")
      ? "Show evidence"
      : "Focus 3D";
    scene.resize();
  };
  document.querySelectorAll("[data-preset]").forEach(
    (b) =>
      (b.onclick = () => {
        scene.preset(b.dataset.preset);
        $("followTrack").textContent = "Follow";
      }),
  );
  $("trackSelect").onchange = () => choose($("trackSelect").value);
  $("jumpTrack").onclick = () => {
    const t = tracks.find((t) => t.id === scene.selected),
      s = t?.segments.find((s) => s.length > 1);
    if (s) {
      pause();
      seek((s[0][0] + s.at(-1)[0]) / 2);
      const pose = M.sampleTrack(t, time);
      const target = new THREE.Vector3(pose.x, 0, pose.z);
      scene.camera.position.add(target.clone().sub(scene.controls.target));
      scene.controls.target.copy(target);
    }
  };
  $("followTrack").onclick = () => {
    scene.follow = !scene.follow;
    $("followTrack").textContent = scene.follow ? "Stop following" : "Follow";
  };
  $("showTrails").onchange = () => {
    scene.paths.visible = $("showTrails").checked;
  };
  $("stabilize").onchange =
    $("automaticRoad").onchange =
    $("perspectiveCorrection").onchange =
      () => {
        rebuild(currentGeometry(), true);
      };
  $("showGroundGrid").onchange = () => {
    if (scene.groundGrid)
      scene.groundGrid.visible = $("showGroundGrid").checked;
  };
  $("autoRefine").onclick = refine;
  $("cancelRefinement").onclick = async () => {
    workerStatus(
      "cancelling",
      "Stopping refinement. Existing observations and saved estimates are retained.",
    );
    try {
      await read(`/api/runs/${run}/refine/cancel`, {
        method: "POST",
        headers: { "X-Theiatron-Token": token },
      });
      scheduleRefinementPoll(250);
    } catch (e) {
      workerStatus(
        "processing",
        `Could not confirm cancellation: ${e.message}. Checking worker status.`,
      );
      scheduleRefinementPoll(1000);
    }
  };
  $("roadOnly").onchange = () => {
    lastText = -1;
    draw();
  };
  $("seek").oninput = () => {
    pause();
    seek(Number($("seek").value));
  };
  $("restart").onclick = () => {
    pause();
    seek(0);
  };
  $("speed").onchange = () => {
    video.playbackRate = Number($("speed").value);
  };
  $("play").onclick = async () => {
    if (playing) {
      pause();
      return;
    }
    if (time >= data.duration - 0.15) seek(0);
    if (!mediaFailed) {
      try {
        await video.play();
      } catch (e) {
        $("videoStatus").textContent =
          `Video playback unavailable: ${e.message}`;
        return;
      }
    }
    playing = true;
    $("play").textContent = "Pause";
    lastWall = performance.now();
  };
  video.addEventListener("ended", () => {
    time = Math.min(data.duration, video.duration + data.video_offset_s);
    pause();
    draw();
  });
  video.addEventListener("error", () => {
    mediaFailed = true;
    $("videoStatus").textContent =
      "Video unavailable. Track-only playback; source synchronization is not available.";
  });
  video.addEventListener("waiting", () => {
    if (playing)
      $("videoStatus").textContent =
        "Buffering source video · replay clock waits with it";
  });
  video.addEventListener("playing", () => {
    $("videoStatus").textContent =
      "Saved detection video · synchronized source clock";
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pause();
  });
  window.addEventListener("beforeunload", (e) => {
    if (dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  window.addEventListener("pagehide", (event) => {
    pageActive = false;
    clearTimeout(refinementTimer);
    refinementRequest?.abort();
    if (!event.persisted) scene?.dispose();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && data) {
      pageActive = true;
      void resumeRefinement();
    }
  });
  try {
    if (!run || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$/.test(run))
      throw Error(
        "Choose a completed video in the workbench, then open Recorded 3D replay. No sample footage is loaded automatically.",
      );
    $("freshLink").href = `/workbench/live.html?video=${encodeURIComponent(run)}`;
    [data, { token }] = await Promise.all([
      read(`/api/runs/${run}/reconstruction`),
      read("/api/health"),
    ]);
    $("back").href = $("compareLink").href =
      `/workbench/?video=${encodeURIComponent(run)}`;
    if (data.counting_available === false) {
      $("back").href = $("freshLink").href;
      $("back").textContent = "Live detection";
      $("demoLink").hidden = true;
      $("signalNotice").textContent = "Detection-only recording · no traffic counts, simulated signals or delay-savings results.";
      $("compareLink").hidden = true;
    }
    $("sourceName").textContent = data.source_name;
    $("sourceIdentity").textContent =
      `SOURCE ${data.binding.source_sha256.slice(0, 12)} · TRACKS ${data.binding.tracks_sha256.slice(0, 12)}`;
    scene = new TrafficScene($("scene"));
    scene.onSelect = choose;
    scene.onOrbit = () => {
      $("followTrack").textContent = "Follow";
    };
    draft = clone(data.calibration);
    plate.onload = paint;
    plate.src = `/out/${run}/plate.jpg`;
    video.src = `/out/${run}/footage.mp4`;
    video.poster = `/out/${run}/plate.jpg`;
    $("seek").max = data.duration;
    revisionText();
    showRefinement();
    try {
      rebuild(currentGeometry());
    } catch (e) {
      fatal(e.message);
      if (data.track_sampling !== "dense-processed-frames") openEditor();
    }
    // Start at an explicitly displayed source timestamp with useful motion,
    // not at a simulated controller departure or an unrelated sample clip.
    time = Math.min(20, data.duration / 2);
    video.addEventListener("loadedmetadata", () => seek(time), { once: true });
    seek(time);
    requestAnimationFrame(animate);
    void resumeRefinement();
  } catch (e) {
    fatal(
      /No such file|Not found/.test(e.message)
        ? "This analysis is missing its recorded source files. Choose a completed video in the workbench. No sample scene has been substituted."
        : e.message,
    );
    $("sourceName").textContent = "Reconstruction unavailable";
    $("sceneStatus").textContent = "No source scene loaded";
    document
      .querySelectorAll("button, input, select")
      .forEach((control) => (control.disabled = true));
  }
})();
