#!/usr/bin/env python3
"""Local, offline launcher for the complete Theiatron video workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
UPLOAD_ROOT = ROOT / "out" / "uploads"
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm"}

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _safe_filename(raw: str) -> str:
    """Return a display-friendly basename that cannot escape its upload dir."""
    name = Path(unquote(raw)).name.strip()
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).stem).strip(" ._")
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError("choose a MOV, MP4, M4V, AVI, MKV, or WebM video")
    if not stem:
        stem = "intersection"
    return f"{stem[:80]}{suffix}"


def _new_run_id(filename: str, stamp: str | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")
    slug = slug[:32] or "video"
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    return f"ui-{stamp}-{slug}-{uuid.uuid4().hex[:5]}"


def _progress_for_line(line: str) -> tuple[int, str, str] | None:
    low = line.lower()
    if "stage 1/3" in low:
        return 8, "calibrating", "Learning approaches from vehicle motion"
    if low.startswith("observed "):
        return 30, "calibrating", "Vehicle trajectories learned"
    if "stage 2/3" in low:
        return 38, "calibrated", "Calibration passed its quality gate"
    if "stage 3/3" in low:
        return 44, "analyzing", "Running fresh detection and controller comparison"
    if low.startswith("report:"):
        return 88, "building", "Building the report and 3D replay"
    if low.startswith("wrote ") and "timeline.js" in low:
        return 94, "building", "3D timeline ready"
    if low.startswith("live run complete:"):
        return 98, "building", "Validating final demo artifacts"
    return None


def _update_job(run_id: str, **changes) -> None:
    with JOBS_LOCK:
        job = JOBS[run_id]
        job.update(changes)
        job["updated_at"] = time.time()


def _append_log(run_id: str, line: str) -> None:
    with JOBS_LOCK:
        logs = JOBS[run_id]["logs"]
        logs.append(line)
        del logs[:-80]


def _public_job(run_id: str) -> dict:
    with JOBS_LOCK:
        job = dict(JOBS[run_id])
        job["logs"] = list(job["logs"])
    started = job.get("started_at")
    finished = job.get("finished_at")
    job["elapsed_s"] = round((finished or time.time()) - started, 1) if started else 0
    job.pop("upload_path", None)
    return job


def _run_pipeline(run_id: str, port: int) -> None:
    with JOBS_LOCK:
        upload_path = JOBS[run_id]["upload_path"]
    _update_job(
        run_id,
        state="processing",
        stage="starting",
        progress=4,
        message="Starting the perception pipeline",
        started_at=time.time(),
    )
    env = os.environ.copy()
    env.update({
        "PYTHONUNBUFFERED": "1",
        "THEIATRON_NO_OPEN": "1",
        "THEIATRON_VIEWER_PORT": str(port),
    })
    command = [
        "bash",
        "scripts/live_demo.sh",
        str(upload_path),
        "--run-name",
        run_id,
    ]
    try:
        proc = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            _append_log(run_id, line)
            progress = _progress_for_line(line)
            if progress:
                value, stage, message = progress
                _update_job(
                    run_id, progress=value, stage=stage, message=message
                )
        return_code = proc.wait()
    except Exception as exc:
        _append_log(run_id, f"launcher error: {exc}")
        _update_job(
            run_id,
            state="failed",
            stage="failed",
            message=f"Could not run the analysis: {exc}",
            finished_at=time.time(),
        )
        return

    manifest_path = ROOT / "out" / run_id / "manifest.json"
    manifest = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    ready = bool(manifest and manifest.get("three_d", {}).get("ready"))
    if return_code == 0 and ready:
        viewer = manifest["three_d"]["viewer"]
        _update_job(
            run_id,
            state="complete",
            stage="complete",
            progress=100,
            message="Your 3D comparison is ready",
            viewer_url=f"/{viewer}",
            results=manifest.get("results", {}),
            calibration=manifest.get("calibration", {}),
            events=manifest.get("events", 0),
            finished_at=time.time(),
        )
        return

    with JOBS_LOCK:
        last_lines = JOBS[run_id]["logs"][-4:]
    detail = next(
        (line for line in reversed(last_lines) if "error" in line.lower()
         or "failed" in line.lower() or "too low" in line.lower()),
        last_lines[-1] if last_lines else "The analysis did not complete",
    )
    _update_job(
        run_id,
        state="failed",
        stage="failed",
        message=detail,
        finished_at=time.time(),
    )


class LauncherHandler(SimpleHTTPRequestHandler):
    server_version = "TheiatronLauncher/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    @property
    def launcher_port(self) -> int:
        return int(self.server.server_address[1])

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def end_headers(self) -> None:
        if self.path.startswith(("/launcher", "/api/")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/launcher/")
            self.end_headers()
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "service": "theiatron-launcher"})
            return
        if parsed.path == "/api/runs":
            with JOBS_LOCK:
                ids = list(JOBS)[-12:]
            self._send_json([_public_job(run_id) for run_id in reversed(ids)])
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)", parsed.path)
        if match:
            run_id = match.group(1)
            with JOBS_LOCK:
                exists = run_id in JOBS
            if not exists:
                self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(_public_job(run_id))
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/runs":
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            raw_name = parse_qs(parsed.query).get("filename", [""])[0]
            filename = _safe_filename(raw_name)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._send_json({"error": "the selected file is empty"}, HTTPStatus.BAD_REQUEST)
            return
        if length > MAX_UPLOAD_BYTES:
            self._send_json({"error": "video is larger than the 4 GB local limit"}, 413)
            return
        with JOBS_LOCK:
            busy = any(job["state"] in {"queued", "processing"} for job in JOBS.values())
        if busy:
            self._send_json(
                {"error": "another video is already being processed"},
                HTTPStatus.CONFLICT,
            )
            return

        run_id = _new_run_id(filename)
        upload_dir = UPLOAD_ROOT / run_id
        upload_dir.mkdir(parents=True, exist_ok=False)
        upload_path = upload_dir / filename
        partial_path = upload_dir / f".{filename}.uploading"
        remaining = length
        try:
            with partial_path.open("wb") as output:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ConnectionError("upload ended before the complete file arrived")
                    output.write(chunk)
                    remaining -= len(chunk)
            partial_path.replace(upload_path)
        except Exception as exc:
            partial_path.unlink(missing_ok=True)
            self._send_json({"error": f"upload failed: {exc}"}, HTTPStatus.BAD_REQUEST)
            return

        now = time.time()
        with JOBS_LOCK:
            JOBS[run_id] = {
                "id": run_id,
                "filename": filename,
                "size_bytes": length,
                "state": "queued",
                "stage": "queued",
                "progress": 2,
                "message": "Video received; analysis is queued",
                "logs": [],
                "viewer_url": None,
                "created_at": now,
                "updated_at": now,
                "upload_path": str(upload_path.resolve()),
            }
        threading.Thread(
            target=_run_pipeline,
            args=(run_id, self.launcher_port),
            daemon=True,
            name=f"theiatron-{run_id}",
        ).start()
        self._send_json(_public_job(run_id), HTTPStatus.ACCEPTED)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), LauncherHandler)
    print(f"Theiatron launcher: http://{args.host}:{args.port}/launcher/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
