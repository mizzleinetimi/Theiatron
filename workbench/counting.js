/* Fresh-inference commissioning. No mutation of an existing source run. */
(() => {
  let original = null,
    edits = null,
    plate = null,
    generation = 0;
  const canvas = $("countingCanvas"),
    body = $("countingFields").querySelector("tbody");
  const colours = ["#f07d8b", "#96d897", "#76cce8", "#e8bf73"];
  function changed() {
    $("countingAcknowledged").checked = false;
    $("countingStatus").textContent =
      "Edited candidate · no new counts until fresh inference completes";
    draw();
  }
  function rows() {
    body.replaceChildren();
    edits.forEach((a, i) => {
      const row = body.insertRow();
      row.insertCell().textContent = a.name;
      const phase = document.createElement("select");
      phase.setAttribute("aria-label", `${a.name} candidate group`);
      for (const p of ["NS", "EW"]) phase.add(new Option(p, p));
      phase.value = a.phase;
      phase.onchange = () => {
        a.phase = phase.value;
        changed();
      };
      row.insertCell().append(phase);
      const points = [...a.count_line, a.approach_side];
      points.forEach((point, p) =>
        point.forEach((value, d) => {
          const field = document.createElement("input");
          field.type = "number";
          field.value = value;
          field.min = 0;
          field.max = d === 0 ? 1279 : 719;
          field.step = 1;
          field.setAttribute(
            "aria-label",
            `${a.name} ${["start", "end", "side"][p]} ${["x", "y"][d]}`,
          );
          field.oninput = () => {
            points[p][d] = Number(field.value);
            changed();
          };
          row.insertCell().append(field);
        }),
      );
      row.style.color = colours[i];
    });
  }
  function draw() {
    if (!edits || !plate?.complete || !plate.naturalWidth) return;
    const c = canvas.getContext("2d");
    c.clearRect(0, 0, 1280, 720);
    c.drawImage(plate, 0, 0, 1280, 720);
    edits.forEach((a, i) => {
      const [p, q] = a.count_line,
        side = a.approach_side;
      c.strokeStyle = colours[i];
      c.fillStyle = colours[i];
      c.lineWidth = a.name === $("countingArm").value ? 6 : 3;
      const roi = original.rois[a.name];
      if (roi?.length) {
        c.setLineDash([10, 6]);
        c.beginPath();
        c.moveTo(...roi[0]);
        for (const point of roi.slice(1)) c.lineTo(...point);
        c.closePath();
        c.stroke();
        c.setLineDash([]);
      }
      c.beginPath();
      c.moveTo(...p);
      c.lineTo(...q);
      c.stroke();
      for (const point of [p, q, side]) {
        c.beginPath();
        c.arc(...point, 8, 0, Math.PI * 2);
        c.fill();
      }
      c.beginPath();
      c.moveTo(...side);
      c.lineTo((p[0] + q[0]) / 2, (p[1] + q[1]) / 2);
      c.setLineDash([5, 5]);
      c.stroke();
      c.setLineDash([]);
      c.font = "bold 23px sans-serif";
      c.fillText(a.name, Math.min(p[0] + 10, 1140), Math.max(p[1] - 12, 25));
    });
  }
  $("editCounting").onclick = async () => {
    const id = videoId,
      own = ++generation;
    try {
      const source = await read(`/api/runs/${id}/counting`);
      if (own !== generation || videoId !== id) return;
      original = source;
      edits = structuredClone(source.approaches);
      $("countingSource").textContent =
        `Source ${id} · ${source.duration.toFixed(3)} s · artifact ${source.source_artifact_id.slice(0, 12)} · retained footage verified again by worker`;
      $("countingArm").replaceChildren(
        ...edits.map((a) => new Option(a.name, a.name)),
      );
      $("countingEditor").hidden = false;
      $("countingAcknowledged").checked = false;
      $("countingStatus").textContent =
        "Source geometry loaded · unchanged until you edit it";
      rows();
      plate = new Image();
      plate.onload = () => {
        if (own === generation) draw();
      };
      plate.onerror = () =>
        showError("Source plate unavailable; cannot place count lines.");
      plate.src = `/out/${id}/plate.jpg`;
      $("countingEditor").scrollIntoView({
        block: "start",
        behavior: "smooth",
      });
    } catch (e) {
      showError(e.message);
    }
  };
  $("countingArm").onchange = draw;
  canvas.onclick = (e) => {
    if (!edits) return;
    const r = canvas.getBoundingClientRect(),
      a = edits.find((a) => a.name === $("countingArm").value),
      p = Number($("countingPoint").value);
    const point = [
      Math.max(
        0,
        Math.min(1279, Math.round(((e.clientX - r.left) * 1280) / r.width)),
      ),
      Math.max(
        0,
        Math.min(719, Math.round(((e.clientY - r.top) * 720) / r.height)),
      ),
    ];
    if (p === 2) a.approach_side = point;
    else a.count_line[p] = point;
    rows();
    changed();
  };
  $("resetCounting").onclick = () => {
    if (!original) return;
    edits = structuredClone(original.approaches);
    rows();
    changed();
  };
  $("closeCounting").onclick = () => {
    $("countingEditor").hidden = true;
  };
  $("startRecount").onclick = async () => {
    if (!original || activeId) {
      showError(
        "Choose a completed clip and finish or cancel the active job first.",
      );
      return;
    }
    if (!$("countingAcknowledged").checked) {
      showError(
        "Acknowledge that the edited count lines remain unvalidated candidates.",
      );
      return;
    }
    $("startRecount").disabled = true;
    try {
      const job = await write("/api/recounts", {
        source_run: original.source_run,
        approaches: edits,
        acknowledge_candidate: true,
      });
      jobs.unshift(job);
      activeId = job.id;
      select(job);
    } catch (e) {
      showError(e.message);
    } finally {
      $("startRecount").disabled = false;
    }
  };
  window.TheiatronCounting = {
    sourceSelected(id) {
      if (original?.source_run !== id) {
        original = null;
        edits = null;
        generation++;
        $("countingEditor").hidden = true;
      }
    },
  };
})();
