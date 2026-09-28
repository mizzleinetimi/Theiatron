(async function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let token,
    state = null,
    requesting = false,
    imageKey = null,
    connected = false,
    shownSession = null,
    metricsKey = null,
    upload = null,
    sources = [],
    preparation = new URLSearchParams(location.search).get("prepare"),
    preparationChecked = 0;
  const initial = new URLSearchParams(location.search).get("video");
  const liveScene = new LiveSceneView($("liveScene"), $("sceneStatus"), $("geometryStatus"));
  $("show3D").onchange = () => liveScene.setEnabled($("show3D").checked);
  for (const button of document.querySelectorAll("[data-live-view]"))
    button.onclick = () => liveScene.preset(button.dataset.liveView);
  $("retry3D").onclick = () => {
    if ($("source").value) liveScene.load($("source").value);
  };
  async function read(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const r = await fetch(path, { cache: "no-store", ...options, signal: controller.signal });
      const body = await r.json();
      if (!r.ok) throw Object.assign(Error(body.error || `Request failed (${r.status})`), {status:r.status});
      return body;
    } finally { clearTimeout(timeout); }
  }
  const write = (path, body) =>
    read(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Theiatron-Token": token,
      },
      body: JSON.stringify(body),
    });
  function error(message) {
    $("error").textContent = message;
    $("error").hidden = !message;
  }
  function controls() {
    const busy = requesting || state?.busy || state?.other_job_busy;
    $("start").disabled = !connected || busy || !$("source").value;
    $("stop").disabled =
      !connected ||
      requesting ||
      !state?.session ||
      !["starting", "running"].includes(state.session.state);
    for (const id of ["source", "duration", "fps", "loop"])
      $(id).disabled = !!busy;
    $("uploadFile").disabled = !connected || !!busy;
    $("uploadStart").disabled = !connected || !!busy || !$("uploadFile").files?.length;
    $("uploadCancel").hidden = !upload && !state?.upload_jobs?.length;
    const selected = sources.find((j) => j.id === $("source").value);
    $("prepareRoad").hidden = selected?.kind !== "live-source";
    $("prepareRoad").disabled = !connected || !!busy;
    const hasStudio = ["reconstruction", "video"].includes(selected?.kind);
    $("savedReplay").hidden = !hasStudio;
    if (hasStudio)
      $("savedReplay").href = `/workbench/replay.html?video=${encodeURIComponent(selected.id)}`;
    $("back").href = selected?.kind === "video"
      ? `/workbench/demo.html?video=${encodeURIComponent(selected.id)}&step=observe`
      : "/workbench/demo.html";
  }
  function addSource(j) {
    if (!sources.some((s) => s.id === j.id)) sources.push(j);
    if (![...$("source").options].some((o) => o.value === j.id))
      $("source").add(new Option(`${j.filename} · ${j.kind === "live-source" ? "detection-only upload" : j.kind === "reconstruction" ? "visual-only · no counts" : "analysed"} · ${j.id.slice(-8)}`, j.id));
  }
  function display(next) {
    state = next;
    const previous = state.session, w = state.worker;
    // A historical session must not switch a studio deep-link back to its old
    // footage. An actually running session remains visible and owns the controls.
    const s = previous && (["starting", "running", "stopping"].includes(previous.state) ||
      previous.source_run === $("source").value) ? previous : null;
    $("status").textContent =
      w.state === "warming"
        ? "Loading model and warming inference…"
        : s
          ? `Session ${s.state} · worker ${w.state}${w.pid ? " · PID " + w.pid : ""}`
          : `Worker ${w.state}. Choose a clip to start.`;
    if (s) {
      if (shownSession !== s.id) {
        shownSession = s.id;
        if (s.source_run) {
          if (![...$("source").options].some((o) => o.value === s.source_run))
            $("source").add(new Option(`${s.source_name} · active source`, s.source_run));
          $("source").value = s.source_run;
        }
        for (const [id, value] of [
          ["duration", s.duration_limit_s],
          ["fps", s.target_fps],
        ]) {
          if (value !== undefined) {
            if (![...$(id).options].some((o) => o.value === String(value)))
              $(id).add(new Option(String(value), String(value)));
            $(id).value = String(value);
          }
        }
        $("loop").checked = !!s.loop;
      }
      $("sourceName").textContent = s.source_name;
      $("mode").textContent = ["starting", "running", "stopping"].includes(
        s.state,
      )
        ? "FRESH INFERENCE · PACED FILE"
        : `${s.state.toUpperCase()} · NOT A LIVE FEED`;
      const f = LiveMath.freshness(s);
      $("freshness").textContent = f.text;
      $("freshness").classList.toggle("stale", f.stale);
      const m = s.metrics || {},
        buffer = s.buffer || {},
        last = s.last_observation;
      const tiles = [
        [LiveMath.value(m.recent_processing_fps), "Processing FPS"],
        [String(last?.detections.length ?? "—"), "Visible detections"],
        [
          LiveMath.value(m.observation_age?.p50_ms_upper, " ms", 0),
          "p50 observation age",
        ],
        [
          LiveMath.value(m.observation_age?.p95_ms_upper, " ms", 0),
          "p95 observation age",
        ],
        [String(buffer.overwritten ?? 0), "Pending frames replaced"],
        [String(m.stale_rejected ?? 0), "Stale frames rejected"],
        [
          String(m.observation_deadline_misses ?? 0),
          "Observations over 300 ms",
        ],
        [
          String(s.capture_skipped_ticks ?? 0),
          "Overdue source samples skipped",
        ],
        [String(m.tracker_resets ?? 0), "Gap / loop tracker resets"],
        [LiveMath.value(last?.source_time_s, " s"), "Source position"],
        [LiveMath.value(m.inference?.mean_ms, " ms"), "Mean inference time"],
      ];
      const nextMetricsKey = `${s.id}:${s.state}:${s.published_at}:${m.processed}`;
      if (nextMetricsKey !== metricsKey) {
        metricsKey = nextMetricsKey;
        $("metrics").replaceChildren(
          ...tiles.map(([v, label]) => {
            const d = document.createElement("div"),
              n = document.createElement("strong"),
              l = document.createElement("span");
            n.textContent = v;
            l.textContent = label;
            d.append(n, l);
            return d;
          }),
        );
      }
      $("startup").textContent =
        `Model warmup: ${LiveMath.value(w.warmup_s, "s")} · Request to first observation: ${LiveMath.value(s.request_to_first_observation_s, "s")}. Model stays loaded between sessions.`;
      if (s.age_basis)
        $("basis").textContent =
          s.age_basis + ". Inference latency excludes preview delivery.";
      const key = s.id + ":" + s.published_at;
      if (last && s.published_at && imageKey !== key) {
        imageKey = key;
        $("preview").onload = () => {
          if (
            state?.session?.id !== s.id ||
            !state.session.last_observation ||
            imageKey !== key
          )
            return;
          $("preview").hidden = false;
          $("placeholder").hidden = true;
        };
        $("preview").src = `/out/${s.id}/preview.jpg?t=${s.published_at}`;
      }
      if (!last) {
        $("preview").hidden = true;
        $("placeholder").hidden = false;
      }
      $("report").hidden =
        !["complete", "stopped", "failed"].includes(s.state) || !s.finished_at;
      $("report").href = `/out/${s.id}/stream-report.json`;
      if (s.error) error(s.error);
    } else {
      shownSession = imageKey = metricsKey = null;
      $("preview").hidden = true;
      $("placeholder").hidden = false;
      $("metrics").replaceChildren();
      $("mode").textContent = "NO SESSION FOR SELECTED FOOTAGE";
      $("sourceName").textContent = sources.find(j => j.id === $("source").value)?.filename || "No source selected";
      $("freshness").textContent = "Start fresh detection for this clip.";
      $("freshness").classList.remove("stale");
      $("startup").textContent = "";
      $("basis").textContent = "Prepared geometry can be inspected before detection starts. Physical scale remains estimated.";
      $("report").hidden = true;
    }
    liveScene.update(s, connected, $("source").value || null);
    if (w.error) error(w.error);
    controls();
  }
  $("source").onchange = () => state ? display(state) : controls();
  $("uploadFile").onchange = controls;
  $("uploadStart").onclick = async () => {
    const file = $("uploadFile").files?.[0];
    if (!file || requesting || state?.busy || state?.other_job_busy) return;
    requesting = true;
    error("");
    const operation = upload = new LiveUpload({write, token, onProgress: (loaded, total) => {
      $("uploadProgress").value = Math.round(loaded / total * 100);
      $("uploadStatus").textContent = loaded >= total
        ? "File sent. Finalising transfer and starting the detector…"
        : `Uploading locally: ${Math.round(loaded / total * 100)}%`;
    }});
    $("uploadProgress").hidden = false;
    $("uploadProgress").value = 0;
    $("uploadStatus").textContent = "Reserving the local upload slot…";
    controls();
    try {
      const result = await operation.start(file, {
        duration: Number($("duration").value), fps: Number($("fps").value), loop: $("loop").checked,
      });
      addSource(result.source);
      $("source").value = result.source.id;
      history.replaceState({}, "", `?video=${encodeURIComponent(result.source.id)}`);
      display(result.live);
      $("uploadStatus").textContent = "Uploaded. Fresh detection is starting; no road analysis has run. Stop detection to prepare the road and saved 3D.";
      $("uploadFile").value = "";
      if (result.start_error) error(`Video retained, but detection could not start: ${result.start_error}`);
    } catch (e) {
      error(e.message);
      $("uploadStatus").textContent = operation.cancelled
        ? "Upload cancelled. If detection had already started, it is being stopped."
        : "Upload/start did not finish normally. Check the current session before retrying.";
    } finally {
      if (upload === operation) upload = null;
      requesting = false;
      $("uploadProgress").hidden = true;
      // An interrupted response may still have left a complete retained upload.
      // Refresh the library without assuming either success or data loss.
      try { (await read("/api/live/sources")).forEach(addSource); } catch (_) { /* polling exposes connectivity */ }
      controls();
    }
  };
  $("uploadCancel").onclick = async () => {
    try {
      const next = upload ? await upload.cancel()
        : await write(`/api/live/uploads/${state.upload_jobs[0].id}/cancel`, {});
      if (next) display(next);
    } catch (e) { error(`Cancellation needs attention: ${e.message}`); }
  };
  $("prepareRoad").onclick = async () => {
    if (requesting || state?.busy || state?.other_job_busy) return;
    requesting = true; error(""); controls();
    try {
      const job = await write(`/api/live/sources/${encodeURIComponent($("source").value)}/reconstruct`, {acknowledge_estimates: true});
      preparation = job.id;
      history.replaceState({}, "", `?video=${encodeURIComponent($("source").value)}&prepare=${encodeURIComponent(job.id)}`);
      showPreparation(job);
    } catch (e) { error(e.message); }
    finally { requesting = false; controls(); }
  };
  function showPreparation(job) {
    $("roadPreparation").hidden = false;
    $("roadStatus").textContent = `${job.state} · ${job.message}`;
    $("roadProgress").value = job.progress || 0;
    $("roadCancel").hidden = !["queued", "processing", "cancelling"].includes(job.state);
    $("roadCancel").disabled = job.state === "cancelling";
    if (["capturing", "reconstructing"].includes(job.stage)) {
      const preview = $("roadPreviewImage");
      const url = `/out/${encodeURIComponent(job.id)}/preview.jpg?t=${job.updated_at}`;
      if (preview.dataset.url !== url) {
        preview.dataset.url = url;
        preview.onload = () => { $("roadPreview").hidden = false; };
        preview.onerror = () => { $("roadPreview").hidden = true; };
        preview.src = url;
      }
    }
    if (job.state === "complete")
      location.href = `/workbench/replay.html?video=${encodeURIComponent(job.id)}`;
  }
  $("roadCancel").onclick = async () => {
    if (!preparation) return;
    try { showPreparation(await write(`/api/runs/${encodeURIComponent(preparation)}/cancel`, {})); }
    catch (e) { error(`Preparation cancellation needs attention: ${e.message}`); }
  };
  $("start").onclick = async () => {
    requesting = true;
    error("");
    controls();
    try {
      display(
        await write("/api/live/start", {
          source_run: $("source").value,
          duration: Number($("duration").value),
          fps: Number($("fps").value),
          loop: $("loop").checked,
        }),
      );
    } catch (e) {
      error(e.message);
    } finally {
      requesting = false;
      controls();
    }
  };
  $("stop").onclick = async () => {
    requesting = true;
    controls();
    try {
      display(await write("/api/live/stop", { id: state.session.id }));
    } catch (e) {
      error(e.message);
    } finally {
      requesting = false;
      controls();
    }
  };
  async function poll() {
    try {
      const next = await read("/api/live");
      connected = true;
      display(next);
      if (!preparation && next.reconstruction_jobs?.length)
        preparation = next.reconstruction_jobs[0].id;
      if (preparation && performance.now() - preparationChecked > 1500) {
        preparationChecked = performance.now();
        try { showPreparation(await read(`/api/runs/${encodeURIComponent(preparation)}`)); }
        catch (e) { $("roadStatus").textContent = `Reconnecting to preparation: ${e.message}`; }
      }
      $("connection").textContent = "LOCAL WORKER SERVICE CONNECTED";
      controls();
    } catch (e) {
      connected = false;
      liveScene.update(null, false, $("source").value || null);
      $("connection").textContent = "DISCONNECTED — OBSERVATIONS ARE STALE";
      $("freshness").textContent = "Connection lost · preview is not current";
      $("freshness").classList.add("stale");
      error(e.message);
      controls();
    } finally {
      setTimeout(poll, 250);
    }
  }
  try {
    token = (await read("/api/health")).token;
    const jobs = await read("/api/live/sources").catch(async (e) => {
      if (e.status !== 404) throw e;
      return (await read("/api/runs")).filter((j) => j.kind === "video" && j.state === "complete");
    });
    jobs.forEach(addSource);
    if (initial && [...$("source").options].some((o) => o.value === initial))
      $("source").value = initial;
    else if ($("source").options.length > 1) $("source").selectedIndex = 1;
    if ($("source").value)
      $("back").href =
        `/workbench/demo.html?video=${$("source").value}&step=observe`;
    poll();
  } catch (e) {
    error(e.message);
  }
})();
