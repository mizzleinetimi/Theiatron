"use strict";
const $ = (id) => document.getElementById(id);
const ACTIVE = new Set(["uploading", "queued", "processing", "cancelling"]);
let token,
  jobs = [],
  compareId = null,
  videoId = null,
  selectedId = null,
  activeId = null,
  sumoReady = false;
let report = null,
  geometryId = null,
  frames = [],
  playing = false,
  replayIndex = 0,
  lastPlay = 0,
  savedFrame = null,
  perspective = false;
let previewStamp = null,
  currentTab = "compare",
  busy = false,
  selectionVersion = 0,
  replayLoaded = null,
  historyKey = "",
  evidenceKey = "";
const views = {};
try {
  views.fixed = new SumoView($("fixedScene"), 0xe4bc81);
  views.adaptive = new SumoView($("adaptiveScene"), 0x87dcbc);
} catch (e) {
  showError("3D rendering unavailable: " + e.message);
}
function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}
function tab(name) {
  currentTab = name;
  for (const id of ["watch", "compare", "evidence"]) $(id).hidden = id !== name;
  document
    .querySelectorAll("[data-tab]")
    .forEach((b) => b.classList.toggle("selected", b.dataset.tab === name));
  Object.values(views).forEach((v) => v.resize());
}
document.querySelectorAll("[data-tab]").forEach(
  (b) =>
    (b.onclick = () => {
      tab(b.dataset.tab);
      if (currentTab === "watch" && videoId) selectedId = videoId;
      if (currentTab === "compare" && compareId) selectedId = compareId;
      selectionVersion++;
      showEvidence();
    }),
);
async function read(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok)
    throw new Error(
      (await r.json().catch(() => ({}))).error ||
        `Request failed (${r.status})`,
    );
  return r.json();
}
async function write(url, data) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Theiatron-Token": token },
    body: JSON.stringify(data),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error);
  return j;
}
function historyList() {
  const key = JSON.stringify(jobs.map((j) => [j.id, j.state]));
  if (historyKey === key) {
    $("history").value = selectedId || "";
    return;
  }
  historyKey = key;
  const previous = $("history").value;
  $("history").replaceChildren(new Option("Choose a run", ""));
  for (const j of jobs.filter((j) => !["live-source","reconstruction"].includes(j.kind)))
    $("history").add(
      new Option(
        `${j.kind === "sumo" ? "SUMO" : "VIDEO"} · ${j.filename} · ${j.state} · ${j.id.slice(-8)}`,
        j.id,
      ),
    );
  $("history").value = selectedId || previous;
}
function status(job) {
  if (!job) return;
  $("jobStatus").textContent = `${job.filename} · ${job.message}`;
  $("log").textContent = (job.logs || []).join("\n");
  $("progress").hidden = !ACTIVE.has(job.state);
  $("progress").value = job.progress || 0;
  showEvidence();
}
function select(job) {
  if (job.kind === "reconstruction") {
    location.href = job.state === "complete"
      ? `/workbench/replay.html?video=${encodeURIComponent(job.id)}`
      : `/workbench/live.html?prepare=${encodeURIComponent(job.id)}`;
    return;
  }
  if (job.kind === "live-source") {
    location.href = `/workbench/live.html?video=${encodeURIComponent(job.id)}`;
    return;
  }
  selectionVersion++;
  selectedId = job.id;
  $("presentDemo").href = job.kind==='video'
    ? `/workbench/demo.html?video=${job.id}`
    : job.results?.source_run
      ? `/workbench/demo.html?video=${job.results.source_run}&compare=${job.id}`
      : '/workbench/demo.html';
  $("error").hidden = true;
  status(job);
  if (job.kind === "sumo") {
    compareId = job.id;
    const observed = !!job.scenario.site_revision;
    $("scenario").hidden = observed;
    $("profileComparison").hidden = !observed;
    $("comparisonNotice").textContent = observed
      ? job.scenario.generated_demand
        ? "Generated traffic on a footage-linked draft network. NOT recorded arrivals or measured site benefit."
        : "Recorded camera arrivals on a draft network hypothesis. Geometry, routes and signal operation are assumptions; improvement headlines are disabled."
      : "Synthetic four-arm laboratory · generated demand · straight movements · ideal queue sensing. Not a benefit claim for your filmed site.";
    $("profileComparisonSource").textContent = observed
      ? `Footage-linked revision ${job.scenario.site_revision.slice(0, 12)} · ${job.scenario.generated_demand?'synthetic population replaces observed demand':'observed timestamps preserved, no demand multiplication'}`
      : "";
    $("baselineTitle").textContent = job.scenario.baseline_policy === 'actuated' ? 'Actuated gap-out baseline' : 'Fixed-time baseline';
    $("candidateTitle").textContent = job.scenario.adaptive_policy === 'service-v2' ? 'Theiatron service v2' : 'Theiatron pressure v1';
    $("fixedDescription").textContent = job.scenario.baseline_policy === 'actuated'
      ? 'Presence and gap-out software comparator'
      : observed
      ? "Exclusive incoming stages · assumed timings"
      : "20 s equal green splits";
    for (const [name, value] of Object.entries(observed ? {} : job.scenario)) {
      const control = $("scenario").elements.namedItem(name);
      if (
        control instanceof HTMLSelectElement &&
        ![...control.options].some((o) => o.value === String(value))
      ) {
        control.add(new Option(String(value), String(value)));
      }
      if (control) control.value = String(value);
    }
    report = job.state === "complete" ? job.results : null;
    geometryId = null;
    frames = [];
    replayLoaded = null;
    playing = false;
    savedFrame = null;
    $("replay").hidden = true;
    $("verdict").textContent = "Loading this comparison…";
    $("simMode").textContent = "LOADING SELECTED RUN";
    $("simClock").textContent = "—";
    $("resultDetail").textContent = "Waiting for this run's own outputs.";
    $("fairness").replaceChildren();
    for (const name of ["fixed", "adaptive"]) {
      $(name + "Metrics").replaceChildren();
      $(name + "Signal").textContent = "Waiting for simulation state";
    }
    Object.values(views).forEach((v) => v.clear());
    tab("compare");
    history.replaceState({}, "", `?compare=${encodeURIComponent(job.id)}`);
  } else {
    videoId = job.id;
    window.TheiatronProfiles?.sourceSelected(job.id);
    window.TheiatronCounting?.sourceSelected(job.id);
    $("createProfile").hidden = job.state !== "complete";
    $("editCounting").hidden = job.state !== "complete";
    previewStamp = null;
    $("legacy").hidden = true;
    $("recordedReplay").hidden = true;
    $("preview").hidden = true;
    $("sourceVideo").hidden = true;
    $("watchEmpty").hidden = false;
    $("counts").replaceChildren();
    $("watchState").textContent = job.message;
    $("watchClock").textContent = "Waiting for this run's own detection frame.";
    tab("watch");
    history.replaceState({}, "", `?video=${encodeURIComponent(job.id)}`);
  }
  historyList();
  showEvidence();
}
$("history").onchange = () => {
  const job = jobs.find((j) => j.id === $("history").value);
  if (job) select(job);
};
$("scenario").onsubmit = async (event) => {
  event.preventDefault();
  $("error").hidden = true;
  $("start").disabled = true;
  try {
    const f = new FormData(event.target);
    const job = await write("/api/compare", {
      demand: f.get("demand"),
      scale: Number(f.get("scale")),
      duration: Number(f.get("duration")),
      seed: Number(f.get("seed")),
      pace: Number(f.get("pace")),
    });
    jobs.unshift(job);
    activeId = job.id;
    select(job);
  } catch (e) {
    showError(e.message);
  } finally {
    $("start").disabled = !!activeId;
  }
};
$("cancel").onclick = async () => {
  if (!activeId) return;
  try {
    await write(`/api/runs/${activeId}/cancel`, {});
  } catch (e) {
    showError(e.message);
  }
};
$("camera").onclick = () => {
  perspective = !perspective;
  Object.values(views).forEach((v) => v.perspective(perspective));
  $("camera").textContent = perspective ? "Top-down view" : "Perspective view";
};
$("videoFile").onchange = async () => {
  const file = $("videoFile").files[0];
  $("videoFile").value = "";
  if (!file) return;
  if (activeId) {
    showError("Finish or cancel the active job first.");
    return;
  }
  $("error").hidden = true;
  tab("watch");
  $("counts").replaceChildren();
  $("legacy").hidden = true;
  $("recordedReplay").hidden = true;
  $("watchEmpty").hidden = true;
  $("preview").hidden = true;
  const local = URL.createObjectURL(file);
  $("sourceVideo").src = local;
  $("sourceVideo").hidden = false;
  $("watchState").textContent = "Uploading · unanalysed source preview";
  $("watchClock").textContent = file.name;
  const xhr = new XMLHttpRequest();
  xhr.open("POST", `/api/runs?filename=${encodeURIComponent(file.name)}`);
  xhr.setRequestHeader("X-Theiatron-Token", token);
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable)
      $("watchState").textContent =
        `Uploading ${Math.round((100 * e.loaded) / e.total)}% · unanalysed source`;
  };
  xhr.onload = () => {
    URL.revokeObjectURL(local);
    try {
      const job = JSON.parse(xhr.responseText);
      if (xhr.status !== 202) throw new Error(job.error);
      jobs.unshift(job);
      activeId = job.id;
      select(job);
    } catch (e) {
      showError(e.message);
    }
  };
  xhr.onerror = () => {
    URL.revokeObjectURL(local);
    showError("Upload disconnected. Check saved runs for its status.");
  };
  xhr.send(file);
};
function metric(parent, value, label, detail) {
  const d = document.createElement("div");
  d.className = "metric";
  const strong = document.createElement("strong");
  strong.textContent = value;
  const span = document.createElement("span");
  span.textContent = label;
  d.append(strong, span);
  if (detail) {
    const sub = document.createElement("span");
    sub.textContent = detail;
    d.append(sub);
  }
  parent.append(d);
}
function draw(frame, mode) {
  savedFrame = frame;
  $("simClock").textContent = `${frame.t.toFixed(1)} s`;
  $("simMode").textContent = mode;
  for (const [name, w] of Object.entries(frame.worlds)) {
    views[name]?.frame(w);
    const m = w.metrics,
      el = $(name + "Metrics");
    el.replaceChildren();
    metric(el, m.mean_delay_s.toFixed(1) + " s", "Mean delay to date");
    metric(el, m.p95_delay_s.toFixed(1) + " s", "p95 delay to date");
    metric(
      el,
      `${m.arrived} / ${m.offered}`,
      "Completed / intended",
      `${m.active} on road · ${m.pending} pending insertion`,
    );
    $(name + "Signal").textContent = `${w.phase} ${w.signal} · ${w.reason}`;
  }
}
function table(headers, rows) {
  const t = document.createElement("table");
  for (const [i, row] of [headers, ...rows].entries()) {
    const tr = t.insertRow();
    for (const val of row) {
      const c = document.createElement(i ? "td" : "th");
      c.textContent = val;
      tr.append(c);
    }
  }
  return t;
}
function result(r) {
  if (!r) return;
  const f = r.metrics.fixed,
    a = r.metrics.adaptive;
  const diff = f.mean_delay_s - a.mean_delay_s;
  const pct = r.reduction_pct;
  $("verdict").textContent = !r.valid
    ? "Run requires inspection — diagnostics failed"
    : r.profile_revision
      ? "Exploratory model complete — no validated savings claim"
      : Math.abs(diff) < 0.0001
        ? "Equal delay in this laboratory run"
        : `${Math.abs(diff).toFixed(1)} s ${diff > 0 ? "less" : "more"} mean delay with Theiatron${pct === null ? "" : ` (${Math.abs(pct).toFixed(1)}%)`}`;
  $("resultDetail").textContent = r.profile_revision
    ? r.scenario.generated_demand
      ? `${f.offered} generated vehicles · ${r.scenario.duration}s synthetic experiment. Camera supplies a network hypothesis, not this demand. No field-savings claim.`
      : `${f.offered} preserved recorded arrivals · ${r.source_duration.toFixed(3)} s observed · ${r.assumed_tail_s.toFixed(3)} s simulation tail · sample ${r.sample_status}. Draft geometry/routes; neither signal policy represents the actual site baseline.`
    : `Final ${r.scenario.duration}-second result (also shown during replay) · stopped + insertion delay. One seed, untuned baseline, not field or journey-time savings.`;
  $("fairness").replaceChildren(
    table(
      [
        "Approach",
        "Baseline mean / p95 delay",
        "Candidate mean / p95 delay",
        "Baseline completed / active / pending",
        "Candidate completed / active / pending",
      ],
      Object.keys(f.per_approach).map((n) => {
        const x = f.per_approach[n],
          y = a.per_approach[n];
        return [
          n,
          `${x.mean_delay_s.toFixed(1)} / ${x.p95_delay_s.toFixed(1)} s`,
          `${y.mean_delay_s.toFixed(1)} / ${y.p95_delay_s.toFixed(1)} s`,
          `${x.arrived} / ${x.active} / ${x.pending}`,
          `${y.arrived} / ${y.active} / ${y.pending}`,
        ];
      }),
    ),
  );
}
async function comparison(job, version) {
  const id = job.id,
    base = `/out/${id}/`;
  if (geometryId !== id) {
    try {
      const geo = await read(base + "geometry.json");
      if (version !== selectionVersion) return;
      Object.values(views).forEach((v) => v.geometry(geo));
      geometryId = id;
    } catch (e) {
      if (job.state === "complete") throw e;
    }
  }
  let latest;
  try {
    latest = await read(base + "latest.json");
  } catch (e) {
    if (job.state === "complete") throw e;
    return;
  }
  if (version !== selectionVersion) return;
  if (job.state === "complete") {
    report = job.results;
    result(report);
    if (replayLoaded !== id) {
      const response = await fetch(base + "frames.jsonl");
      if (!response.ok) throw new Error("Replay unavailable");
      const text = await response.text();
      if (version !== selectionVersion) return;
      frames = text.trim().split("\n").filter(Boolean).map(JSON.parse);
      replayLoaded = id;
      replayIndex = frames.length - 1;
      $("seek").max = frames.length - 1;
      $("seek").value = replayIndex;
      $("replay").hidden = false;
      draw(latest, "COMPLETED SIMULATION");
      showEvidence();
    }
    if (!playing && replayIndex === frames.length - 1)
      draw(latest, "COMPLETED SIMULATION");
  } else {
    const age = Date.now() / 1000 - latest.published_at;
    const mode = ACTIVE.has(job.state)
      ? age > 3
        ? "SIMULATION UPDATE STALE"
        : "SIMULATION RUNNING NOW"
      : `${job.state.toUpperCase()} · PARTIAL OUTPUT`;
    draw(latest, mode);
    $("verdict").textContent = ACTIVE.has(job.state)
      ? "Computing — provisional metrics only."
      : "Run did not complete; no final comparison.";
    $("resultDetail").textContent =
      "Identical intended demand; each controller sees only queues in its own SUMO world.";
  }
  $("simHint").textContent =
    `${job.scenario.duration} s horizon · seed ${job.scenario.seed} · ${job.scenario.demand} · ${job.scenario.scale}× demand · ${job.scenario.pace}× requested wall-clock pace`;
}
async function watch(job, version) {
  let p;
  try {
    p = await read(`/out/${job.id}/progress.json`);
  } catch {
    if (version === selectionVersion) $("watchState").textContent = job.message;
    return;
  }
  if (version !== selectionVersion) return;
  $("watchEmpty").hidden = true;
  $("sourceVideo").hidden = true;
  $("preview").hidden = false;
  if (previewStamp !== p.published_at) {
    $("preview").src = `/out/${job.id}/preview.jpg?t=${p.published_at}`;
    previewStamp = p.published_at;
  }
  const age = Math.max(0, Date.now() / 1000 - p.published_at);
  $("watchState").textContent = ACTIVE.has(job.state)
    ? `${p.stage} · ${age > 3 ? "FRAME STALE" : "fresh detection"}`
    : `${job.state} · saved detection frame`;
  $("watchClock").textContent =
    `${p.source_name} · source ${p.source_time_s.toFixed(1)} s · ${ACTIVE.has(job.state) ? age.toFixed(1) + " s since last processed frame" : "not a live feed"}`;
  $("counts").replaceChildren();
  for (const [key, val] of Object.entries(
    p.arrivals || { detections: p.detections, tracks: p.tracks },
  )) {
    if (val === undefined) continue;
    const row = document.createElement("div");
    row.textContent = `${key}: ${val}`;
    $("counts").append(row);
  }
  if (job.state === "complete") {
    $("createProfile").hidden = false;
    $("editCounting").hidden = false;
    $("legacy").hidden = false;
    $("legacy").href = `/viz/index.html?run=out/${encodeURIComponent(job.id)}`;
    $("recordedReplay").hidden = false;
    $("recordedReplay").href =
      `/workbench/replay.html?video=${encodeURIComponent(job.id)}`;
  }
}
function showEvidence() {
  const job = jobs.find((j) => j.id === selectedId),
    r = job?.results;
  const key = `${job?.id}:${job?.state}:${r?.artifact_id}`;
  if (key === evidenceKey) return;
  evidenceKey = key;
  $("evidenceEmpty").hidden = !!r;
  $("evidenceBody").hidden = !r;
  $("download").hidden = !r;
  if (!r) return;
  $("download").href = `/out/${job.id}/report.json`;
  $("report").textContent = JSON.stringify(r, null, 2);
  const values =
    job.kind === "sumo"
      ? {
          Run: job.id,
          Backend: "Stock SUMO 1.27.1",
          Profile: r.profile_revision
            ? `Draft footage-linked hypothesis · ${r.profile_revision}`
            : "Synthetic fixture · no site review",
          State: r.valid
            ? "Software diagnostics passed"
            : "Diagnostic exception — inspect",
          Horizon: r.scenario.duration + " s",
          Seed: r.scenario.seed,
          Cohort: r.cohort,
          Metric: r.metric,
          Artifact: r.artifact_id,
          ...(r.profile_revision
            ? {
                Source: r.source_run,
                "Video hash": r.source_video_sha256,
                "Impact status": r.impact_status,
                Sample: r.sample_status,
                "Observed counts": JSON.stringify(r.observed_counts),
                "Original detector phases": JSON.stringify(
                  r.observed_phase_counts,
                ),
              }
            : {}),
        }
      : {
          Run: job.id,
          Backend: "Exploratory point-queue model",
          Profile: job.camera_revision
            ? "Edited camera candidate · not reviewed"
            : "Automatic candidate · not reviewed",
          ...(job.camera_revision
            ? {
                "Camera revision": job.camera_revision,
                "Parent source": job.parent_source_run,
              }
            : {}),
          Sample: r.sample_status || "unverified",
          Artifact: r.artifact_id || "legacy",
        };
  $("provenance").replaceChildren();
  for (const [key, val] of Object.entries(values)) {
    const dt = document.createElement("dt"),
      dd = document.createElement("dd");
    dt.textContent = key;
    dd.textContent = val;
    $("provenance").append(dt, dd);
  }
  $("assumptions").replaceChildren();
  for (const note of r.assumptions || [
    "Real footage was processed; camera geometry is an unreviewed automatic estimate.",
    "Counterfactual uses point queues, not SUMO vehicle dynamics.",
    "No measured real-world time savings or hardware performance claim.",
  ]) {
    const li = document.createElement("li");
    li.textContent = note;
    $("assumptions").append(li);
  }
  $("files").replaceChildren();
  const fileRegister = r.files || {
    "simulation.json":
      "Canonical simulation, configuration and runtime fingerprints",
    "events.json": "Observed arrival events and source provenance",
    "report.json": "Completed exploratory comparison",
    "manifest.json": "Media and calibration readiness",
    ...(job.camera_revision
      ? {
          "camera-profile.json":
            "Immutable edited counting geometry and source lineage",
        }
      : {}),
  };
  for (const [name, hash] of Object.entries(fileRegister)) {
    const a = document.createElement("a");
    a.href = `/out/${job.id}/${name}`;
    a.download = name;
    a.textContent = `${name} · ${hash}`;
    $("files").append(a);
  }
}
$("seek").oninput = () => {
  playing = false;
  replayIndex = Number($("seek").value);
  $("play").textContent = "Play saved replay";
  draw(frames[replayIndex], "SAVED REPLAY · NOT LIVE");
  $("replayClock").textContent = frames[replayIndex].t.toFixed(1) + " s";
};
$("play").onclick = () => {
  if (!frames.length) return;
  playing = !playing;
  if (playing && replayIndex >= frames.length - 1) replayIndex = 0;
  lastPlay = performance.now();
  $("play").textContent = playing ? "Pause replay" : "Play saved replay";
};
function animate(now) {
  if (playing && frames.length && now - lastPlay >= 125) {
    lastPlay = now;
    draw(frames[replayIndex], "SAVED REPLAY · 4×");
    $("seek").value = replayIndex;
    $("replayClock").textContent = frames[replayIndex].t.toFixed(1) + " s";
    replayIndex++;
    if (replayIndex >= frames.length) {
      playing = false;
      replayIndex = frames.length - 1;
      $("play").textContent = "Play saved replay";
    }
  }
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);
async function poll() {
  if (busy) return;
  busy = true;
  try {
    jobs = await read("/api/runs");
    activeId = jobs.find((j) => ACTIVE.has(j.state))?.id || null;
    $("start").disabled = !!activeId || !token || !sumoReady;
    $("cancel").hidden = !activeId;
    if (!selectedId) {
      const q = new URLSearchParams(location.search);
      const requested = q.get("compare") || q.get("video");
      const j =
        jobs.find((j) => j.id === requested) ||
        (!requested && !q.has("profile") && !q.has("new") ? jobs.find((j) => !["live-source","reconstruction"].includes(j.kind)) : null);
      if (j) select(j);
      else if (requested)
        throw new Error(
          "The requested run is not available. No sample has been substituted.",
        );
    }
    const job = jobs.find((j) => j.id === selectedId);
    historyList();
    if (job) {
      status(job);
      const version = selectionVersion;
      if (job.kind === "sumo") await comparison(job, version);
      else await watch(job, version);
    }
    $("connection").textContent = "LOCAL SERVICE CONNECTED";
  } catch (e) {
    $("connection").textContent = "SERVICE / RUN NEEDS ATTENTION";
    showError(e.message);
    $("simMode").textContent = "UPDATES UNAVAILABLE";
    if (videoId)
      $("watchState").textContent = "Updates unavailable — last frame is stale";
  } finally {
    busy = false;
    setTimeout(poll, 500);
  }
}
(async () => {
  try {
    if(location.hash==='#watch')tab('watch');
    const health = await read("/api/health");
    token = health.token;
    sumoReady = health.sumo.ready;
    if (!sumoReady) {
      showError(health.sumo.error);
      $("start").disabled = true;
    }
    await poll();
  } catch (e) {
    showError(e.message);
    $("start").disabled = true;
  }
})();
