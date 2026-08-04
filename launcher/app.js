const fileInput = document.getElementById("fileInput");
const dropZone = document.getElementById("dropZone");
const pickerPanel = document.getElementById("pickerPanel");
const runPanel = document.getElementById("runPanel");
const runKicker = document.getElementById("runKicker");
const runTitle = document.getElementById("runTitle");
const runMeta = document.getElementById("runMeta");
const percent = document.getElementById("percent");
const progressBar = document.getElementById("progressBar");
const runLog = document.getElementById("runLog");
const errorMessage = document.getElementById("errorMessage");
const chooseAgain = document.getElementById("chooseAgain");
const openResult = document.getElementById("openResult");
const resultSummary = document.getElementById("resultSummary");
const stageItems = [...document.querySelectorAll(".stages li")];

let pollTimer = null;
let activeRun = null;

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
  return `${value.toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}

function resetPicker() {
  clearTimeout(pollTimer);
  activeRun = null;
  fileInput.value = "";
  runPanel.hidden = true;
  pickerPanel.hidden = false;
  errorMessage.hidden = true;
  chooseAgain.hidden = true;
  openResult.hidden = true;
  resultSummary.hidden = true;
  history.replaceState({}, "", "/launcher/");
}

function setStage(stage) {
  const order = ["upload", "calibrating", "analyzing", "building"];
  const normalized = stage === "calibrated" ? "calibrating" : stage;
  const current = normalized === "complete" ? order.length : order.indexOf(normalized);
  stageItems.forEach((item, index) => {
    item.classList.toggle("done", current > index);
    item.classList.toggle("active", current === index);
  });
}

function renderJob(job) {
  activeRun = job.id;
  pickerPanel.hidden = true;
  runPanel.hidden = false;
  errorMessage.hidden = true;
  runKicker.textContent = job.state === "complete" ? "DEMO READY" : "PROCESSING REAL FOOTAGE";
  runTitle.textContent = job.message || "Analyzing footage";
  runMeta.textContent = `${job.filename} · ${formatBytes(job.size_bytes)} · ${Math.round(job.elapsed_s || 0)}s elapsed`;
  percent.textContent = `${Math.round(job.progress || 0)}%`;
  progressBar.style.width = `${job.progress || 0}%`;
  setStage(job.stage);
  runLog.textContent = (job.logs || []).slice(-8).join("\n") || "Waiting for the first analysis update…";
  runLog.scrollTop = runLog.scrollHeight;

  if (job.state === "complete") {
    const results = job.results || {};
    const reduction = Number(results.avg_wait_reduction_pct || 0);
    const direction = reduction >= 0 ? "lower" : "higher";
    resultSummary.textContent = `${job.events} arrivals analyzed · ${Math.abs(reduction).toFixed(1)}% ${direction} modeled average wait on this sample.`;
    resultSummary.hidden = false;
    openResult.href = job.viewer_url;
    openResult.hidden = false;
    chooseAgain.hidden = false;
    history.replaceState({}, "", `/launcher/?run=${encodeURIComponent(job.id)}`);
    return;
  }
  if (job.state === "failed") {
    runKicker.textContent = "FOOTAGE NEEDS ATTENTION";
    percent.textContent = "—";
    showError(job.message || "This video could not produce a reliable demo.");
    chooseAgain.hidden = false;
  }
}

async function pollRun(runId) {
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("The run is no longer available");
    const job = await response.json();
    renderJob(job);
    if (job.state === "complete") {
      pollTimer = setTimeout(() => { window.location.href = job.viewer_url; }, 1400);
    } else if (job.state !== "failed") {
      pollTimer = setTimeout(() => pollRun(runId), 900);
    }
  } catch (error) {
    showError(error.message);
    chooseAgain.hidden = false;
  }
}

function upload(file) {
  if (!file) return;
  const allowed = [".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm"];
  const suffix = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!allowed.includes(suffix)) {
    showError("Choose a MOV, MP4, M4V, AVI, MKV, or WebM video.");
    return;
  }
  if (file.size > 4 * 1024 * 1024 * 1024) {
    showError("This video is larger than the 4 GB local limit.");
    return;
  }

  pickerPanel.hidden = true;
  runPanel.hidden = false;
  runKicker.textContent = "COPYING FOOTAGE";
  runTitle.textContent = "Receiving your video";
  runMeta.textContent = `${file.name} · ${formatBytes(file.size)}`;
  setStage("upload");
  runLog.textContent = "Copying the selected file into this local run…";

  const request = new XMLHttpRequest();
  request.open("POST", `/api/runs?filename=${encodeURIComponent(file.name)}`);
  request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
  request.upload.onprogress = (event) => {
    if (!event.lengthComputable) return;
    const value = Math.max(1, Math.round((event.loaded / event.total) * 100));
    percent.textContent = `${value}%`;
    progressBar.style.width = `${value}%`;
  };
  request.onload = () => {
    let payload = {};
    try { payload = JSON.parse(request.responseText); } catch (_) {}
    if (request.status < 200 || request.status >= 300) {
      showError(payload.error || "The video could not be uploaded.");
      chooseAgain.hidden = false;
      return;
    }
    activeRun = payload.id;
    history.replaceState({}, "", `/launcher/?run=${encodeURIComponent(payload.id)}`);
    renderJob(payload);
    pollRun(payload.id);
  };
  request.onerror = () => {
    showError("The local launcher could not receive the video.");
    chooseAgain.hidden = false;
  };
  request.send(file);
}

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener("change", () => upload(fileInput.files[0]));
["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
  event.preventDefault(); dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
  event.preventDefault(); dropZone.classList.remove("dragging");
}));
dropZone.addEventListener("drop", (event) => upload(event.dataTransfer.files[0]));
chooseAgain.addEventListener("click", resetPicker);

const requestedRun = new URLSearchParams(location.search).get("run");
if (requestedRun && /^[A-Za-z0-9._-]+$/.test(requestedRun)) {
  pickerPanel.hidden = true;
  runPanel.hidden = false;
  pollRun(requestedRun);
}
