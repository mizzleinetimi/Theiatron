/* Never silently replace an invalid/missing selected run with the sample. */
function resolveRun(search) {
  const run = new URLSearchParams(search).get("run");
  if (run !== null && !/^out\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(run)) {
    throw new Error("Invalid run selection. Return to the launcher and select a completed run.");
  }
  return { run, base: run === null ? "." : `../${run}` };
}

function loadTheiatronRun(app, linkId, linkPage) {
  function fail(message) {
    const panel = document.createElement("main");
    panel.style.cssText = "padding:48px;font:20px system-ui;color:#ffb724;position:relative;z-index:100";
    panel.setAttribute("role", "alert");
    panel.textContent = message + " No sample footage was substituted. ";
    const back = document.createElement("a");
    back.href = "../launcher/";
    back.textContent = "Open launcher";
    panel.appendChild(back);
    document.body.replaceChildren(panel);
  }
  let selection;
  try { selection = resolveRun(location.search); }
  catch (error) { fail(error.message); return; }
  const { run, base } = selection;
  window.THEIATRON_FOOTAGE_SRC = `${base}/footage.mp4`;
  window.THEIATRON_PLATE_SRC = `${base}/plate.jpg`;
  document.getElementById(linkId).href = linkPage + (run === null ? "" : `?run=${encodeURIComponent(run)}`);
  const timeline = document.createElement("script");
  timeline.src = `${base}/timeline.js`;
  timeline.onerror = () => fail("The selected run's timeline could not be loaded.");
  timeline.onload = () => {
    if (typeof TIMELINE === "undefined" || !TIMELINE.twin_affine || !TIMELINE.count_lines_tw) {
      fail("The selected run has no usable 3D geometry.");
      return;
    }
    const script = document.createElement("script");
    script.src = app;
    script.onerror = () => fail("The viewer could not be loaded.");
    document.body.appendChild(script);
  };
  document.body.appendChild(timeline);
}
if (typeof module !== "undefined") module.exports = { resolveRun };
