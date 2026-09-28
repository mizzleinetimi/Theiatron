/* Presenter workflow. Saved observation/replay and fresh computation stay explicit. */
(async function () {
  "use strict";
  const $ = (id) => document.getElementById(id),
    active = new Set(["uploading", "queued", "processing", "cancelling"]);
  const query = new URLSearchParams(location.search);
  let token,
    jobs = [],
    sourceId = null,
    profile = null,
    job = null,
    result = null,
    frames = [],
    time = 0,
    playing = false,
    currentStep = query.get("step") || "reconstruct",
    scenes = {},
    geometryId = null,
    busy = false,
    generation = 0,
    pollBusy = false,
    serviceReady = false,
    continuousBusy = false,
    lastWall = performance.now(),
    lastLive = null,
    liveFrames = [],
    traceOffset = 0,
    traceTail = "",
    analysisJob = null,
    uploadRequest = null,
    initializing = true;
  const err = (message) => {
    $("error").textContent = message;
    $("error").hidden = !message;
  };
  async function read(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    if (!response.ok)
      throw Error(
        (await response.json().catch(() => ({}))).error ||
          `Request failed (${response.status})`,
      );
    return response.json();
  }
  const write = (url, data) =>
    read(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Theiatron-Token": token,
      },
      body: JSON.stringify(data),
    });
  function url() {
    if (initializing) return;
    if (!sourceId) {
      history.replaceState(
        {},
        "",
        analysisJob
          ? `?step=observe&analysis=${analysisJob.id}`
          : "?step=observe",
      );
      return;
    }
    const q = new URLSearchParams({ video: sourceId, step: currentStep });
    if (job) q.set("compare", job.id);
    history.replaceState({}, "", `?${q}`);
  }
  function buttons() {
    $("compute").disabled =
      !sourceId ||
      !serviceReady ||
      continuousBusy ||
      busy ||
      jobs.some((j) => active.has(j.state));
    $("source").disabled = busy || !!analysisJob;
    $("uploadFile").disabled =
      busy || continuousBusy || jobs.some((j) => active.has(j.state));
    $("cancel").hidden = !job || !active.has(job.state);
    $("cancel").disabled = job?.state === "cancelling";
    const observed = $("demand").value === "observed";
    $("duration").disabled = observed;
    $("scale").disabled = observed;
    $("baselinePolicy").disabled = busy || (!!job && active.has(job.state));
    $("adaptivePolicy").disabled = busy || (!!job && active.has(job.state));
  }
  function chapter(name) {
    currentStep = ["observe", "reconstruct", "compare", "evidence"].includes(
      name,
    )
      ? name
      : "observe";
    for (const id of ["observe", "reconstruct", "compare", "evidence"])
      $(id).hidden = id !== currentStep;
    document
      .querySelectorAll("[data-step]")
      .forEach((b) =>
        b.classList.toggle("selected", b.dataset.step === currentStep),
      );
    if (currentStep !== "observe") $("video").pause();
    // Unload the hidden studio: hidden iframes otherwise continue playback/refinement
    // and hold extra GPU contexts during a comparison. Re-entering loads the same source.
    const studio = $("studio");
    if (currentStep === "reconstruct" && sourceId) {
      const src = `/workbench/replay.html?video=${encodeURIComponent(sourceId)}`;
      if (studio.getAttribute("src") !== src) studio.src = src;
    } else if (studio.hasAttribute("src")) studio.removeAttribute("src");
    if (currentStep === "compare" && !scenes.fixed) {
      try {
        for (const name of ["fixed", "adaptive"])
          scenes[name] = new DemoScene($(name + "Scene"));
      } catch (e) {
        err("3D unavailable: " + e.message);
      }
    }
    for (const s of Object.values(scenes)) s.resize();
    url();
  }
  document
    .querySelectorAll("[data-step]")
    .forEach((b) => (b.onclick = () => chapter(b.dataset.step)));
  document
    .querySelectorAll("[data-next]")
    .forEach((b) => (b.onclick = () => chapter(b.dataset.next)));
  function savedList() {
    const matching = jobs.filter(
      (j) =>
        j.kind === "sumo" &&
        j.state === "complete" &&
        j.results?.source_run === sourceId,
    );
    const key = matching.map((j) => j.id).join(",");
    if ($("saved").dataset.key === key) return;
    $("saved").dataset.key = key;
    $("saved").replaceChildren(
      new Option("Choose a completed experiment", ""),
      ...matching.map(
        (j) =>
          new Option(
            `${j.scenario.generated_demand ? "Generated " + j.scenario.demand : "Recorded arrivals"} · ${j.scenario.duration}s · seed ${j.scenario.seed} · ${j.id.slice(-8)}`,
            j.id,
          ),
      ),
    );
    $("saved").value = job?.state === "complete" ? job.id : "";
  }
  function resetExperiment() {
    job = null;
    profile = null;
    result = null;
    frames = [];
    playing = false;
    time = 0;
    geometryId = null;
    lastLive = null;
    liveFrames = [];
    traceOffset = 0;
    traceTail = "";
    for (const s of Object.values(scenes)) {
      s.dispose();
      s.element.replaceChildren();
    }
    scenes = {};
    for (const name of ["fixed", "adaptive"]) {
      $(name + "Metrics").replaceChildren();
      $(name + "Decision").textContent = "Waiting for simulator state";
    }
    $("mode").textContent = "NO EXPERIMENT LOADED";
    $("outcome").textContent =
      "Fresh computation, not a retimed winning replay.";
    $("resultDetail").textContent =
      "Modelled delay is stopped waiting plus insertion delay, including unfinished vehicles. It is not measured journey-time savings.";
    $("play").disabled = true;
    $("seek").disabled = true;
    $("clock").textContent = "0.0 s";
    $("seek").value = 0;
    $("download").hidden = true;
    $("reportLink").hidden = true;
    $("facts").replaceChildren();
    $("limitations").replaceChildren();
    $("profileInfo").textContent =
      "A source-specific proposal will be created when you compute.";
    $("editProfile").hidden = true;
    $("evidenceResult").textContent =
      "Compute or select an experiment to see its checksummed result.";
    $("jobStatus").textContent = "Choose experiment settings, then compute.";
    $("progress").hidden = true;
  }
  function selectSource(id) {
    const source = jobs.find(
      (j) => j.id === id && j.kind === "video" && j.state === "complete",
    );
    if (!source)
      throw Error(
        "The requested footage is unavailable. No sample has been substituted.",
      );
    generation++;
    sourceId = id;
    resetExperiment();
    $("source").value = id;
    $("livePreview").hidden = true;
    $("video").hidden = false;
    $("observationMode").textContent = "SAVED DETECTION VIDEO";
    $("video").src = `/out/${id}/footage.mp4`;
    $("video").poster = `/out/${id}/plate.jpg`;
    $("sourceName").textContent = source.filename;
    $("sourceDetail").textContent =
      `${source.events ?? "—"} counted crossings · saved local analysis. Tracker fragments are not unique-vehicle ground truth.`;
    $("evidenceSource").textContent = `Source run: ${id}`;
    $("workbench").href = `/workbench/?video=${id}`;
    $("reanalyse").href = `/workbench/?video=${id}`;
    $("continuous").href = `/workbench/live.html?video=${id}`;
    savedList();
    buttons();
    chapter(currentStep);
  }
  $("source").onchange = () => {
    try {
      err("");
      selectSource($("source").value);
    } catch (e) {
      err(e.message);
    }
  };
  $("video").onerror = () =>
    err(
      "Saved detection video is unavailable; use the workbench to inspect or reanalyse this source.",
    );
  $("uploadFile").onchange = () => {
    const file = $("uploadFile").files[0];
    $("uploadFile").value = "";
    if (!file || busy || jobs.some((j) => active.has(j.state))) return;
    err("");
    busy = true;
    buttons();
    generation++;
    resetExperiment();
    sourceId = null;
    chapter("observe");
    $("source").value = "";
    $("sourceName").textContent = file.name;
    $("observationMode").textContent = "UPLOADING · UNANALYSED SOURCE";
    $("sourceDetail").textContent =
      "Uploading to your local service. No video leaves this machine.";
    $("video").removeAttribute("src");
    $("video").hidden = true;
    $("livePreview").hidden = true;
    $("analysisProgress").hidden = false;
    $("analysisProgress").value = 0;
    const xhr = (uploadRequest = new XMLHttpRequest());
    xhr.open("POST", `/api/runs?filename=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("X-Theiatron-Token", token);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        $("analysisProgress").value = (100 * e.loaded) / e.total;
    };
    xhr.onload = () => {
      try {
        const j = JSON.parse(xhr.responseText);
        if (xhr.status !== 202) throw Error(j.error || "Upload failed");
        analysisJob = j;
        jobs.unshift(j);
        url();
        $("cancelAnalysis").hidden = false;
        $("observationMode").textContent =
          "FRESH FILE ANALYSIS · NOT LIVE CAMERA";
      } catch (e) {
        err(e.message);
        $("analysisProgress").hidden = true;
      } finally {
        busy = false;
        uploadRequest = null;
        buttons();
      }
    };
    xhr.onerror = () => {
      err("Upload disconnected. Inspect saved runs in the workbench.");
      busy = false;
      uploadRequest = null;
      buttons();
    };
    xhr.send(file);
  };
  $("cancelAnalysis").onclick = async () => {
    try {
      if (analysisJob)
        analysisJob = await write(`/api/runs/${analysisJob.id}/cancel`, {});
    } catch (e) {
      err(e.message);
    }
  };
  $("demand").onchange = buttons;
  function showProfile(p) {
    profile = p;
    $("profileInfo").textContent =
      `${p.demo_proposal?.basis === "camera-estimated-ground" ? "Shared camera-estimated ground plane" : "Camera-direction sketch"} · ${p.source.events.length} recorded crossings · revision ${p.revision.slice(0, 12)}. ` +
      (
        p.demo_proposal?.notes || [
          "Geometry and routes are unreviewed assumptions.",
        ]
      ).join(" ");
    $("editProfile").hidden = false;
    $("editProfile").href = `/workbench/?profile=${p.revision}`;
  }
  async function loadFrames(id, own) {
    const response = await fetch(`/out/${id}/frames.jsonl`, {
      cache: "no-store",
    });
    if (!response.ok) throw Error("Saved simulator trace is unavailable.");
    const text = await response.text();
    if (own !== generation || job?.id !== id) return;
    frames = text
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line));
    time = frames.at(-1)?.t || 0;
    $("seek").max = time;
    $("seek").value = time;
    $("play").disabled = !frames.length;
    $("seek").disabled = !frames.length;
    $("play").textContent = "Play saved replay";
    $("mode").textContent = "SAVED SIMULATION REPLAY";
  }
  function evidence(r) {
    result = r;
    const names = DemoMath.policyNames(r.scenario);
    $("outcome").textContent = DemoMath.outcome(r);
    $("evidenceResult").textContent = DemoMath.outcome(r);
    $("resultDetail").textContent =
      `${r.scenario.generated_demand ? "Generated traffic, not camera demand." : "Recorded crossing times; incomplete camera coverage."} ` +
      `Delay = stopped waiting + insertion delay. ${names.candidate} versus ${names.baseline}; not measured field benefit.`;
    $("download").href = `/api/runs/${job.id}/evidence.zip`;
    $("download").hidden = false;
    $("reportLink").href = `/out/${job.id}/report.json`;
    $("reportLink").hidden = false;
    $("facts").replaceChildren();
    const f = r.metrics.fixed,
      a = r.metrics.adaptive;
    for (const [key, value] of Object.entries({
      Run: job.id,
      Mode: r.evidence_level,
      Integrity: r.valid
        ? "Simulator diagnostics passed"
        : "Exceptions — do not use as a valid result",
      Demand: `${f.offered} intended vehicles / ${r.scenario.duration}s; identical in both worlds`,
      Policies: `${names.baseline} / ${names.candidate}`,
      Delay: `Baseline ${f.mean_delay_s.toFixed(2)}s / candidate ${a.mean_delay_s.toFixed(2)}s per intended vehicle`,
      Accounting: `Baseline: ${f.arrived} finished + ${f.active} active + ${f.pending} pending; candidate: ${a.arrived} + ${a.active} + ${a.pending}`,
      Source: r.source_run,
      Artifact: r.artifact_id,
    })) {
      const dt = document.createElement("dt"),
        dd = document.createElement("dd");
      dt.textContent = key;
      dd.textContent = value;
      $("facts").append(dt, dd);
    }
    $("limitations").replaceChildren(
      ...r.assumptions.map((note) => {
        const li = document.createElement("li");
        li.textContent = note;
        return li;
      }),
    );
  }
  async function outputs(own) {
    const id = job.id;
    const names = DemoMath.policyNames(job.scenario);
    $("baselineTitle").textContent = names.baseline;
    $("candidateTitle").textContent = names.candidate;
    if (
      geometryId !== id &&
      ["processing", "complete"].includes(job.state) &&
      scenes.fixed
    ) {
      try {
        const geometry = await read(`/out/${id}/geometry.json`);
        if (own !== generation || job?.id !== id) return;
        for (const s of Object.values(scenes)) s.geometry(geometry);
        geometryId = id;
      } catch (e) {
        if (job.state === "complete") throw e;
      }
    }
    if (active.has(job.state)) {
      try {
        const response = await fetch(`/out/${id}/frames.jsonl`, {
          cache: "no-store",
          headers: { Range: `bytes=${traceOffset}-` },
        });
        if (response.status === 416 || response.status === 404) return;
        if (!response.ok) throw Error("Simulator trace stream is unavailable.");
        const bytes = await response.arrayBuffer();
        if (own !== generation || job?.id !== id) return;
        const firstChunk = traceOffset === 0;
        traceOffset += bytes.byteLength;
        const lines = (traceTail + new TextDecoder().decode(bytes)).split("\n");
        traceTail = lines.pop();
        liveFrames.push(
          ...lines.filter(Boolean).map((line) => JSON.parse(line)),
        );
        lastLive = liveFrames.at(-1) || null;
        if (firstChunk && lastLive)
          time = Math.max(
            liveFrames[0].t,
            lastLive.t - 2 * (job.scenario.pace || 1),
          );
      } catch (e) {
        if (job.progress > 10) throw e;
      }
    } else if (job.state === "complete") {
      if (!result) evidence(job.results);
      if (!frames.length) await loadFrames(id, own);
      savedList();
    }
  }
  async function selectExperiment(j) {
    if (j.kind !== "sumo" || !j.scenario?.site_revision)
      throw Error("Choose a footage-linked SUMO experiment.");
    const own = ++generation;
    const p = await read(`/api/profiles/${j.scenario.site_revision}`);
    if (own !== generation) return;
    if (p.source.run_id !== sourceId)
      throw Error("This experiment belongs to a different source.");
    resetExperiment();
    job = j;
    chapter("compare");
    showProfile(p);
    $("demand").value = j.scenario.demand;
    $("seed").value = j.scenario.seed;
    $("scale").value = j.scenario.scale;
    $("duration").value = String(j.scenario.duration);
    $("baselinePolicy").value = j.scenario.baseline_policy || "fixed";
    $("adaptivePolicy").value = j.scenario.adaptive_policy || "pressure-v1";
    buttons();
    await outputs(own);
    url();
    $("jobStatus").textContent =
      j.state === "complete"
        ? "Saved experiment. Press Compute new comparison for fresh simulator work."
        : j.message;
  }
  $("saved").onchange = async () => {
    try {
      const j = jobs.find((j) => j.id === $("saved").value);
      if (j) await selectExperiment(j);
    } catch (e) {
      err(e.message);
    }
  };
  $("compute").onclick = async () => {
    if (busy) return;
    busy = true;
    buttons();
    err("");
    playing = false;
    const own = ++generation;
    try {
      $("jobStatus").textContent =
        "Preparing automatic geometry and explicit route assumptions…";
      const refinement = await read(`/api/runs/${sourceId}/refine`);
      if (active.has(refinement.state))
        throw Error(
          "Automatic reconstruction is still refining. Wait for it to finish, then compute.",
        );
      const p =
        profile ||
        (await write(`/api/runs/${sourceId}/demo-profile`, {
          acknowledge_estimates: true,
        }));
      if (own !== generation) return;
      showProfile(p);
      const observed = $("demand").value === "observed";
      const scenario = {
        site_revision: p.revision,
        generated_demand: !observed,
        demand: $("demand").value,
        scale: observed ? 1 : Number($("scale").value),
        duration: observed
          ? Math.max(
              Math.ceil(p.source.duration),
              Math.floor(Math.max(...p.source.events.map((e) => e.t))) + 1,
            )
          : Number($("duration").value),
        seed: Number($("seed").value),
        baseline_policy: $("baselinePolicy").value,
        adaptive_policy: $("adaptivePolicy").value,
        pace: 6,
        acknowledge_assumptions: true,
      };
      const created = await write("/api/compare", scenario);
      if (own !== generation) return;
      job = created;
      $("mode").textContent = scenario.generated_demand
        ? "COMPUTING · GENERATED TRAFFIC"
        : "COMPUTING · RECORDED ARRIVALS";
      jobs.unshift(job);
      result = null;
      frames = [];
      lastLive = null;
      liveFrames = [];
      traceOffset = 0;
      traceTail = "";
      time = 0;
      geometryId = null;
      for (const s of Object.values(scenes))
        s.frame({ vehicles: [], phase: null, signal: "ALL_RED" });
      for (const name of ["fixed", "adaptive"]) {
        $(name + "Metrics").replaceChildren();
        $(name + "Decision").textContent = "Waiting for the new computation";
      }
      $("play").disabled = true;
      $("seek").disabled = true;
      $("seek").value = 0;
      $("clock").textContent = "0.0 s";
      $("download").hidden = true;
      $("reportLink").hidden = true;
      $("facts").replaceChildren();
      $("limitations").replaceChildren();
      $("evidenceResult").textContent =
        "Fresh experiment in progress. No final result yet.";
      $("outcome").textContent =
        "Computing both controllers against identical inputs…";
      $("resultDetail").textContent = observed
        ? "Recorded crossings on an unvalidated model."
        : "Generated demand on an unvalidated model. Not observed traffic or a field-savings claim.";
      chapter("compare");
      url();
    } catch (e) {
      err(e.message);
      $("jobStatus").textContent =
        "Experiment not started. Inspect the error or use the network editor.";
    } finally {
      busy = false;
      buttons();
    }
  };
  $("cancel").onclick = async () => {
    try {
      job = await write(`/api/runs/${job.id}/cancel`, {});
      buttons();
    } catch (e) {
      err(e.message);
    }
  };
  $("fit").onclick = () =>
    Object.values(scenes).forEach((s) => s.preset("junction"));
  $("play").onclick = () => {
    if (!frames.length) return;
    if (time >= frames.at(-1).t) time = frames[0].t;
    playing = !playing;
    $("play").textContent = playing ? "Pause replay" : "Play saved replay";
  };
  $("seek").oninput = () => {
    playing = false;
    time = Number($("seek").value);
    $("play").textContent = "Play saved replay";
  };
  function draw(frame) {
    if (!frame || !scenes.fixed || !geometryId) return;
    for (const name of ["fixed", "adaptive"]) {
      const world = frame.worlds[name],
        m = world.metrics;
      scenes[name].frame(world);
      const values = [
        [m.mean_delay_s.toFixed(1) + "s", "Mean delay"],
        [Object.values(world.queues).reduce((a, b) => a + b, 0), "Queued"],
        [m.arrived, "Finished"],
        [m.pending, "Pending entry"],
      ];
      $(name + "Metrics").replaceChildren(
        ...values.map(([value, label]) => {
          const d = document.createElement("div"),
            n = document.createElement("strong"),
            l = document.createElement("span");
          n.textContent = value;
          l.textContent = label;
          d.append(n, l);
          return d;
        }),
      );
      $(name + "Decision").textContent =
        `${world.phase} · ${world.signal} · ${world.reason}`;
    }
    $("clock").textContent = `${time.toFixed(1)} s`;
  }
  function animate(now) {
    const dt = Math.min(0.1, (now - lastWall) / 1000);
    lastWall = now;
    if (playing && frames.length) {
      time = Math.min(frames.at(-1).t, time + dt * 2);
      $("seek").value = time;
      if (time >= frames.at(-1).t) {
        playing = false;
        $("play").textContent = "Play saved replay";
      }
    }
    if (!frames.length && liveFrames.length && active.has(job?.state))
      time = Math.min(
        liveFrames.at(-1).t,
        Math.max(liveFrames[0].t, time + dt * (job.scenario.pace || 1)),
      );
    if (currentStep === "compare") {
      draw(
        frames.length
          ? DemoMath.frameAt(frames, time)
          : liveFrames.length
            ? DemoMath.frameAt(liveFrames, time)
            : lastLive,
      );
      for (const s of Object.values(scenes)) s.render();
    }
    requestAnimationFrame(animate);
  }
  async function poll() {
    if (pollBusy) return;
    pollBusy = true;
    try {
      const [latestJobs, liveStatus] = await Promise.all([
        read("/api/runs"),
        read("/api/live"),
      ]);
      jobs = latestJobs;
      continuousBusy = liveStatus.busy;
      $("connection").textContent = continuousBusy
        ? "CONTINUOUS DETECTION ACTIVE · STOP IN LIVE LAB TO COMPUTE"
        : "LOCAL SERVICE CONNECTED";
      if (analysisJob) {
        analysisJob = jobs.find((j) => j.id === analysisJob.id) || analysisJob;
        $("sourceDetail").textContent = analysisJob.message;
        $("analysisProgress").value = analysisJob.progress || 0;
        $("cancelAnalysis").disabled = analysisJob.state === "cancelling";
        if (analysisJob.state === "complete") {
          const id = analysisJob.id;
          $("source").add(
            new Option(`${analysisJob.filename} · ${id.slice(-8)}`, id),
          );
          analysisJob = null;
          $("analysisProgress").hidden = true;
          $("cancelAnalysis").hidden = true;
          currentStep = "reconstruct";
          selectSource(id);
        } else if (!active.has(analysisJob.state)) {
          $("observationMode").textContent = analysisJob.state.toUpperCase();
          $("analysisProgress").hidden = true;
          $("cancelAnalysis").hidden = true;
          analysisJob = null;
        } else if (
          ["calibrating", "calibrated", "analyzing", "building"].includes(
            analysisJob.stage,
          )
        ) {
          // First-pass boxes are useful immediately, before count lines exist.
          // An absent preview during model startup is normal, not a failed job.
          const id = analysisJob.id;
          try {
            const p = await read(`/out/${id}/progress.json`);
            if (analysisJob?.id !== id) return;
            const preview = $("livePreview");
            const age = Math.max(0, Date.now() / 1000 - p.published_at);
            $("observationMode").textContent =
              p.stage === "calibrating"
                ? "FRESH DETECTION · LEARNING ROAD · FILE SOURCE"
                : "COUNTING FILE OBSERVATIONS · NOT LIVE CAMERA";
            $("sourceDetail").textContent =
              `${p.source_time_s.toFixed(1)}s of source · ${age.toFixed(1)}s since last processed preview. ${analysisJob.message}`;
            const key = `${id}:${p.published_at}`;
            if (preview.dataset.key !== key) {
              preview.dataset.key = key;
              preview.onload = () => {
                if (analysisJob?.id === id) preview.hidden = false;
              };
              preview.src = `/out/${id}/preview.jpg?t=${p.published_at}`;
            }
          } catch (_) {
            /* A first preview may not exist yet. Job errors remain visible above. */
          }
        }
      }
      if (job) {
        job = jobs.find((j) => j.id === job.id) || job;
        $("jobStatus").textContent = job.message;
        $("progress").hidden = !active.has(job.state);
        $("progress").value = job.progress || 0;
        if (active.has(job.state))
          $("mode").textContent = job.scenario.generated_demand
            ? "COMPUTING · GENERATED TRAFFIC"
            : "COMPUTING · RECORDED ARRIVALS";
        else if (job.state !== "complete") {
          $("mode").textContent = job.state.toUpperCase();
          $("outcome").textContent =
            "No completed result. Partial state is not final evidence.";
        }
        await outputs(generation);
      }
      savedList();
      buttons();
    } catch (e) {
      $("connection").textContent = "SERVICE NEEDS ATTENTION";
      err(e.message);
    } finally {
      pollBusy = false;
      setTimeout(poll, 750);
    }
  }
  try {
    const h = await read("/api/health");
    token = h.token;
    serviceReady = h.sumo.ready;
    if (!serviceReady) err(h.sumo.error);
    jobs = await read("/api/runs");
    const videos = jobs.filter(
      (j) => j.kind === "video" && j.state === "complete",
    );
    $("source").replaceChildren(
      new Option("Choose analysed footage", ""),
      ...videos.map(
        (j) => new Option(`${j.filename} · ${j.id.slice(-8)}`, j.id),
      ),
    );
    if (query.get("analysis")) {
      const pending =
        jobs.find((j) => j.id === query.get("analysis")) ||
        (await read(`/api/runs/${query.get("analysis")}`));
      if (pending.kind !== "video")
        throw Error("Requested analysis is not a video job.");
      if (pending.state === "complete") selectSource(pending.id);
      else if (active.has(pending.state)) {
        analysisJob = pending;
        $("sourceName").textContent = pending.filename;
        $("observationMode").textContent =
          "FRESH FILE ANALYSIS · NOT LIVE CAMERA";
        $("video").hidden = true;
        $("analysisProgress").hidden = false;
        $("cancelAnalysis").hidden = false;
        currentStep = "observe";
      } else throw Error(`Analysis ${pending.state}: ${pending.message}`);
    } else {
      const id = query.get("video") || videos[0]?.id;
      if (id) selectSource(id);
      else chapter("observe");
    }
    if (query.get("compare")) {
      const j =
        jobs.find((j) => j.id === query.get("compare")) ||
        (await read(`/api/runs/${query.get("compare")}`));
      await selectExperiment(j);
    }
    initializing = false;
    chapter(query.get("step") || currentStep);
    requestAnimationFrame(animate);
    void poll();
  } catch (e) {
    err(e.message);
    $("connection").textContent = "SETUP NEEDS ATTENTION";
    buttons();
  }
})();
