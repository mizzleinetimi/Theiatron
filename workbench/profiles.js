/* Commissioning UI. Immutable source observations; editable network assumptions. */
(() => {
  let profile = null,
    dirty = false,
    camera = null,
    generation = 0,
    drag = null,
    dragScale = 1;
  const colors = ["#f07d8b", "#96d897", "#76cce8", "#e8bf73"];
  const editor = $("profileEditor");
  const body = $("profileApproaches").querySelector("tbody");
  const status = (text) => {
    $("profileStatus").textContent = text;
  };
  function change() {
    dirty = true;
    $("profileAcknowledged").checked = false;
    status("Unsaved network changes · source events unchanged");
    drawMap();
  }
  function input(value, type, label, update, min, max, step) {
    const field = document.createElement("input");
    field.type = type;
    field.value = value;
    field.setAttribute("aria-label", label);
    if (min !== undefined) field.min = min;
    if (max !== undefined) field.max = max;
    if (step !== undefined) field.step = step;
    field.oninput = () => {
      update(type === "number" ? Number(field.value) : field.value);
      change();
    };
    return field;
  }
  function rows() {
    body.replaceChildren();
    profile.approaches.forEach((a, i) => {
      const tr = body.insertRow();
      const id = tr.insertCell();
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.checked = a.enabled;
      enabled.setAttribute("aria-label", `Enable ${a.id}`);
      enabled.disabled = !!profile.source.counts[a.id];
      enabled.onchange = () => {
        a.enabled = enabled.checked;
        for (const b of profile.approaches)
          if (b.exit === a.id && !a.enabled) b.exit = null;
        rows();
        change();
      };
      id.append(enabled, document.createTextNode(a.id));
      id.style.color = colors[i];
      tr.insertCell().textContent = profile.source.counts[a.id] || 0;
      for (const [k, min, max, step] of [
        ["x", -300, 300, 0.1],
        ["y", -300, 300, 0.1],
        ["lanes", 1, 3, 1],
        ["width", 2.5, 4.5, 0.1],
        ["speed", 3, 16.67, 0.01],
      ]) {
        const field = input(
          a[k],
          "number",
          `${a.id} ${k}`,
          (v) => (a[k] = v),
          min,
          max,
          step,
        );
        field.dataset.arm = a.id;
        field.dataset.key = k;
        field.disabled = !a.enabled;
        tr.insertCell().append(field);
      }
      const exit = document.createElement("select");
      exit.setAttribute("aria-label", `${a.id} assumed exit`);
      exit.add(new Option("Unknown — choose", ""));
      for (const b of profile.approaches)
        if (b.enabled && b.id !== a.id) exit.add(new Option(b.id, b.id));
      exit.value = a.exit || "";
      exit.disabled = !a.enabled;
      exit.onchange = () => {
        a.exit = exit.value || null;
        change();
      };
      tr.insertCell().append(exit);
    });
  }
  function drawCamera() {
    if (!profile || !camera) return;
    const c = $("profileCamera").getContext("2d");
    c.clearRect(0, 0, 1280, 720);
    c.drawImage(camera, 0, 0, 1280, 720);
    c.font = "bold 22px sans-serif";
    profile.source.approaches.forEach((a, i) => {
      const [p, q] = a.count_line;
      c.strokeStyle = colors[i];
      c.fillStyle = colors[i];
      c.lineWidth = 5;
      c.beginPath();
      c.moveTo(...p);
      c.lineTo(...q);
      c.stroke();
      c.fillText(
        `${a.name}: ${profile.source.counts[a.name] || 0}`,
        Math.min(p[0], 1100),
        Math.max(30, p[1] - 12),
      );
      const r = a.approach_side;
      c.beginPath();
      c.arc(r[0], r[1], 7, 0, Math.PI * 2);
      c.fill();
    });
  }
  function scale() {
    return (
      175 /
      Math.max(
        110,
        ...profile.approaches
          .filter((a) => a.enabled)
          .map((a) => Math.max(Math.abs(a.x), Math.abs(a.y))),
      )
    );
  }
  function drawMap() {
    if (!profile) return;
    const canvas = $("profileMap"),
      c = canvas.getContext("2d"),
      s = scale();
    c.fillStyle = "#111e27";
    c.fillRect(0, 0, 600, 430);
    c.strokeStyle = "#253641";
    c.lineWidth = 1;
    for (let x = 0; x < 600; x += 30) {
      c.beginPath();
      c.moveTo(x, 0);
      c.lineTo(x, 430);
      c.stroke();
    }
    for (let y = 0; y < 430; y += 30) {
      c.beginPath();
      c.moveTo(0, y);
      c.lineTo(600, y);
      c.stroke();
    }
    profile.approaches.forEach((a, i) => {
      if (!a.enabled || !Number.isFinite(a.x + a.y)) return;
      const x = 300 + a.x * s,
        y = 215 - a.y * s;
      c.lineWidth = Math.max(5, a.width * a.lanes * 2 * s);
      c.strokeStyle = "#43545d";
      c.beginPath();
      c.moveTo(300, 215);
      c.lineTo(x, y);
      c.stroke();
      c.fillStyle = colors[i];
      c.beginPath();
      c.arc(x, y, 9, 0, Math.PI * 2);
      c.fill();
      c.font = "14px sans-serif";
      c.fillText(a.id, x + 12, y);
      if (a.exit) {
        const b = profile.approaches.find((b) => b.id === a.exit);
        if (b) {
          c.lineWidth = 1.5;
          c.strokeStyle = colors[i];
          c.setLineDash([4, 5]);
          c.beginPath();
          c.moveTo(x, y);
          c.quadraticCurveTo(300, 215, 300 + b.x * s, 215 - b.y * s);
          c.stroke();
          c.setLineDash([]);
        }
      }
    });
    c.fillStyle = "#a9b9c4";
    c.font = "12px sans-serif";
    c.fillText("Assumed metres · no geographic north / homography", 12, 415);
  }
  function show(p) {
    profile = p;
    generation++;
    dirty = false;
    editor.hidden = false;
    $("profileLabel").value = p.label;
    $("profileSide").value = p.traffic_side;
    $("profileAcknowledged").checked = false;
    $("profileSource").textContent =
      `${p.source.filename} · ${p.source.events.length} recorded arrivals · ${p.source.duration.toFixed(3)} s · source ${p.source.artifact_id.slice(0, 12)} · revision ${p.revision.slice(0, 12)}`;
    $("profileReplay").hidden = false;
    $("profileReplay").href = `/workbench/replay.html?video=${encodeURIComponent(p.source.run_id)}`;
    rows();
    $("profileTimings").replaceChildren();
    for (const [key, label] of [
      ["fixed_split", "Fixed green (s)"],
      ["min_green", "Minimum green (s)"],
      ["max_green", "Maximum green (s)"],
      ["yellow", "Yellow (s)"],
      ["all_red", "All red (s)"],
    ]) {
      const el = document.createElement("label");
      el.textContent = label;
      el.append(
        input(
          p.signal[key],
          "number",
          label,
          (v) => (p.signal[key] = v),
          0.5,
          90,
          0.5,
        ),
      );
      $("profileTimings").append(el);
    }
    status("Saved draft · geometry and routes still unreviewed");
    camera = new Image();
    const own = generation;
    camera.onload = () => {
      if (own === generation) drawCamera();
    };
    camera.onerror = () => {
      if (own === generation)
        status(
          "Source plate unavailable; do not treat the network as reviewed.",
        );
    };
    camera.src = `/out/${p.source.run_id}/plate.jpg`;
    drawMap();
    tab("watch");
    history.replaceState({}, "", `?profile=${p.revision}`);
  }
  async function load(revision) {
    try {
      const p = await read(`/api/profiles/${revision}`);
      const job =
        jobs.find((j) => j.id === p.source.run_id) ||
        (await read(`/api/runs/${p.source.run_id}`));
      if (!jobs.some((j) => j.id === job.id)) jobs.push(job);
      select(job);
      show(p);
    } catch (e) {
      showError(e.message);
    }
  }
  async function save() {
    if (!profile) throw new Error("Create or load a profile first.");
    const changes = {
      label: $("profileLabel").value,
      traffic_side: $("profileSide").value,
      approaches: profile.approaches,
      signal: profile.signal,
    };
    const p = await write(
      `/api/profiles/${profile.revision}/revisions`,
      changes,
    );
    // Rebind input handlers to the newly saved object, not the old revision.
    show(p);
    status(`Saved draft revision ${p.revision.slice(0, 12)} · not reviewed`);
    history.replaceState({}, "", `?profile=${p.revision}`);
    return p;
  }
  $("createProfile").onclick = async () => {
    try {
      const p = await write("/api/profiles", { source_run: videoId });
      show(p);
    } catch (e) {
      showError(e.message);
    }
  };
  $("profileLabel").oninput = change;
  $("profileSide").onchange = change;
  $("oppositeExits").onclick = () => {
    if (!profile) return;
    for (const a of profile.approaches) {
      if (!a.enabled) continue;
      const others = profile.approaches.filter(
        (b) => b.enabled && b.id !== a.id,
      );
      a.exit = others.sort(
        (b, c) =>
          (a.x * b.x + a.y * b.y) / Math.hypot(b.x, b.y) -
          (a.x * c.x + a.y * c.y) / Math.hypot(c.x, c.y),
      )[0].id;
    }
    rows();
    change();
    status(
      "Assumed most-opposite exits assigned. These are NOT observed turns; inspect every row.",
    );
  };
  $("saveProfile").onclick = async () => {
    try {
      await save();
    } catch (e) {
      showError(e.message);
    }
  };
  $("runProfile").onclick = async () => {
    if (activeId) {
      showError("Finish or cancel the active job first.");
      return;
    }
    if (!$("profileAcknowledged").checked) {
      showError(
        "Acknowledge the geometry/routing assumptions before running this hypothesis.",
      );
      return;
    }
    $("runProfile").disabled = true;
    try {
      const p = dirty ? await save() : profile;
      if (!p) throw new Error("Load a profile first");
      const job = await write("/api/compare", {
        duration: Math.max(
          Math.ceil(p.source.duration),
          Math.floor(Math.max(...p.source.events.map((e) => e.t))) + 1,
        ),
        seed: 42,
        scale: 1,
        pace: 4,
        demand: "observed",
        site_revision: p.revision,
        acknowledge_assumptions: true,
      });
      jobs.unshift(job);
      activeId = job.id;
      select(job);
    } catch (e) {
      showError(e.message);
    } finally {
      $("runProfile").disabled = false;
    }
  };
  $("editProfile").onclick = () => {
    const job = jobs.find((j) => j.id === compareId);
    if (job?.scenario.site_revision) load(job.scenario.site_revision);
  };
  $("laboratoryMode").onclick = () => {
    selectionVersion++;
    selectedId = null;
    compareId = null;
    geometryId = null;
    report = null;
    savedFrame = null;
    frames = [];
    replayLoaded = null;
    playing = false;
    history.replaceState({}, "", "/workbench/?new=1");
    $("scenario").reset();
    $("scenario").hidden = false;
    $("profileComparison").hidden = true;
    $("comparisonNotice").textContent =
      "Synthetic four-arm laboratory · generated demand · not your filmed site.";
    $("fixedDescription").textContent = "20 s equal green splits";
    $("replay").hidden = true;
    $("simMode").textContent = "NO SIMULATION LOADED";
    $("simClock").textContent = "—";
    $("verdict").textContent = "Choose a laboratory scenario and compute.";
    $("resultDetail").textContent = "";
    $("fairness").replaceChildren();
    $("simHint").textContent = "";
    for (const name of ["fixed", "adaptive"]) {
      $(name + "Metrics").replaceChildren();
      $(name + "Signal").textContent = "Waiting for simulation state";
    }
    Object.values(views).forEach((v) => v.clear());
    historyList();
    showEvidence();
  };
  const canvas = $("profileMap");
  function point(e) {
    const r = canvas.getBoundingClientRect();
    return [
      ((e.clientX - r.left) * 600) / r.width,
      ((e.clientY - r.top) * 430) / r.height,
    ];
  }
  canvas.onpointerdown = (e) => {
    if (!profile) return;
    const p = point(e),
      s = scale();
    drag = profile.approaches.find(
      (a) =>
        a.enabled &&
        Math.hypot(p[0] - 300 - a.x * s, p[1] - 215 + a.y * s) < 18,
    );
    if (drag) {
      dragScale = s;
      canvas.setPointerCapture(e.pointerId);
    }
  };
  canvas.onpointermove = (e) => {
    if (!drag) return;
    const p = point(e),
      s = dragScale;
    drag.x =
      Math.round(Math.max(-300, Math.min(300, (p[0] - 300) / s)) * 10) / 10;
    drag.y =
      Math.round(Math.max(-300, Math.min(300, (215 - p[1]) / s)) * 10) / 10;
    for (const field of body.querySelectorAll("input[data-arm]"))
      if (
        field.dataset.arm === drag.id &&
        ["x", "y"].includes(field.dataset.key)
      )
        field.value = drag[field.dataset.key];
    change();
  };
  canvas.onpointerup = canvas.onpointercancel = () => {
    drag = null;
  };
  window.TheiatronProfiles = {
    load,
    sourceSelected(id) {
      if (profile && profile.source.run_id !== id) {
        editor.hidden = true;
        profile = null;
        generation++;
      }
    },
  };
  const requested = new URLSearchParams(location.search).get("profile");
  if (requested) load(requested);
})();
