#!/usr/bin/env python3
"""Loopback-only workbench: explicit assets, bounded jobs, durable run history."""
from __future__ import annotations

import argparse
import fcntl
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from theiatron.io import atomic_json
from theiatron.sumo_demo import Scenario, preflight, verify_bundle
from theiatron.site_profiles import from_run, load_profile, revise, source_horizon, validate as validate_profile
from theiatron.recount import counting_source, seal_camera
from theiatron.reconstruction import (source as reconstruction_source, save as save_reconstruction,
                                     live_geometry, preview_assisted, save_assisted)

ROOT = Path(__file__).resolve().parent
UPLOAD_ROOT = ROOT / "out" / "uploads"
JOB_STORE = ROOT / "out" / ".launcher" / "jobs.json"
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm"}
ACTIVE = {"uploading", "queued", "processing", "cancelling"}
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.RLock()
PROCESSES: dict[str, subprocess.Popen] = {}
REFINEMENTS: dict[str, dict] = {}
SESSION_TOKEN = secrets.token_urlsafe(32)
SUMO_STATUS = None
LIVE_SERVICE = None
RUN_FILES = {"timeline.js", "plate.jpg", "footage.mp4", "report.json", "simulation.json", "events.json",
             "manifest.json", "calibration.json", "calibration_overlay.jpg", "preview.jpg", "progress.json",
             "scenario.json", "geometry.json", "latest.json", "demand.json", "frames.jsonl",
             "network.net.xml", "demand.rou.xml", "fixed.tripinfo.xml", "adaptive.tripinfo.xml",
             "fixed.sumo.log", "adaptive.sumo.log"}
RUN_FILES.update({"site-profile.json", "source-observations.json"})
RUN_FILES.add("camera-profile.json")
RUN_FILES.update({'stream-report.json','observations.jsonl'})
RUN_FILES.add('reconstruction-source.json')


def _live_busy():
    return LIVE_SERVICE is not None and LIVE_SERVICE.busy()


def _start_live(data):
    global LIVE_SERVICE
    if not isinstance(data,dict) or set(data)-{'source_run','duration','fps','loop'}:
        raise ValueError('choose a retained source, duration, FPS and loop flag; arbitrary camera URLs are not accepted')
    duration,fps,loop=_live_settings(data)
    source=_retained_source(data.get('source_run'), allow_live_source=True)
    with JOBS_LOCK:
        if any(j['state'] in ACTIVE for j in JOBS.values()) or any(j['state'] in ACTIVE for j in REFINEMENTS.values()) or _live_busy():
            raise ValueError('another processing job is active')
        if LIVE_SERVICE is None:
            from theiatron.live_service import LiveService
            LIVE_SERVICE=LiveService(ROOT)
        return LIVE_SERVICE.start(source,data['source_run'],duration,fps,loop)


def _live_settings(data):
    duration,fps,loop=data.get('duration',120),data.get('fps',10),data.get('loop',False)
    import math
    if type(duration) not in {int,float} or not math.isfinite(duration) or not 1<=duration<=3600:
        raise ValueError('duration must be 1–3600 seconds')
    if type(fps) not in {int,float} or not math.isfinite(fps) or not 1<=fps<=30 or type(loop) is not bool:
        raise ValueError('FPS must be 1–30 and loop must be boolean')
    return duration,fps,loop


def _live_snapshot():
    with JOBS_LOCK:
        value=LIVE_SERVICE.snapshot() if LIVE_SERVICE else {'worker':{'state':'not-started'},'session':None,'busy':False}
        # Upload reservations and full analysis also occupy the one-heavy-job slot.
        value['other_job_busy']=any(j['state'] in ACTIVE for j in JOBS.values()) or any(j['state'] in ACTIVE for j in REFINEMENTS.values())
        value['upload_jobs']=[_public_job(i) for i,j in JOBS.items() if j.get('kind')=='live-source' and j['state'] in ACTIVE]
        value['reconstruction_jobs']=[_public_job(i) for i,j in JOBS.items() if j.get('kind')=='reconstruction' and j['state'] in ACTIVE]
        return value


def _expire_live_upload(run_id):
    with JOBS_LOCK:
        job=JOBS.get(run_id,{})
        if job.get('state')=='uploading' and job.get('stage')=='awaiting-upload':
            _update_job(run_id,state='cancelled',stage='cancelled',finished_at=time.time(),
                        message='Upload reservation expired before any file was received')


def _reserve_live_upload(data):
    if not isinstance(data,dict) or set(data)-{'filename','size_bytes','duration','fps','loop'}:
        raise ValueError('provide filename, size and detection settings only')
    filename=_safe_filename(data.get('filename',''))
    size=data.get('size_bytes')
    if type(size) is not int or not 0<size<=MAX_UPLOAD_BYTES:
        raise ValueError('Video must be nonempty and no larger than 4 GB')
    duration,fps,loop=_live_settings(data)
    run_id=_reserve(filename,'live-source',expected_bytes=size,
                    live_options={'duration':duration,'fps':fps,'loop':loop})
    _update_job(run_id,stage='awaiting-upload',message='Waiting for video upload; no analysis has run')
    timer=threading.Timer(60,_expire_live_upload,args=(run_id,));timer.daemon=True;timer.start()
    return _public_job(run_id)


def _persist():
    # Caller holds JOBS_LOCK. Never publish partially written JSON.
    atomic_json(JOB_STORE, JOBS)


def _load_jobs():
    if JOB_STORE.is_file():
        restored = json.loads(JOB_STORE.read_text())
        with JOBS_LOCK:
            JOBS.update(restored)
            for job in JOBS.values():
                if job["state"] in ACTIVE:
                    job.update(state="interrupted", stage="interrupted", finished_at=time.time(),
                               message="Service restarted before completion. Partial output is not final evidence.")
            _persist()


def _safe_filename(raw: str) -> str:
    name = Path(unquote(raw)).name.strip()
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).stem).strip(" ._")
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ValueError("choose a MOV, MP4, M4V, AVI, MKV, or WebM video")
    return f"{(stem or 'intersection')[:80]}{suffix}"


def _new_run_id(filename: str, stamp: str | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")[:32] or "video"
    return f"ui-{stamp or time.strftime('%Y%m%d-%H%M%S')}-{slug}-{uuid.uuid4().hex[:8]}"


def _progress_for_line(line: str):
    low = line.lower()
    for marker, value, stage, message in (
        ("stage 1/3", 8, "calibrating", "Learning approaches from vehicle motion"),
        ("observed ", 30, "calibrating", "Vehicle trajectories learned"),
        ("stage 2/3", 38, "calibrated", "Candidate geometry; human review still required"),
        ("stage 3/3", 44, "analyzing", "Counting observations and preparing reconstruction assets"),
        ("report:", 88, "building", "Building report and replay"),
        ("wrote ", 94, "building", "Publishing artifacts"),
        ("live run complete:", 98, "building", "Validating artifacts")):
        if low.startswith(marker):
            return value, stage, message
    return None


def _update_job(run_id: str, **changes):
    with JOBS_LOCK:
        JOBS[run_id].update(changes, updated_at=time.time())
        _persist()


def _append_log(run_id: str, line: str):
    with JOBS_LOCK:
        JOBS[run_id]["logs"].append(line)
        del JOBS[run_id]["logs"][:-80]
        _persist()


def _public_job(run_id: str):
    with JOBS_LOCK:
        job = {k: v for k, v in JOBS[run_id].items() if k != "upload_path"}
        job["logs"] = list(job["logs"])
    start = job.get("started_at")
    job["elapsed_s"] = round((job.get("finished_at") or time.time()) - start, 1) if start else 0
    return job


def _retained_source(run_id: str, *, allow_live_source=False, allow_reconstruction=False) -> Path:
    """Resolve only a known completed job's retained upload, never a client path."""
    with JOBS_LOCK:
        if not isinstance(run_id,str): raise ValueError('choose a retained video source')
        job = JOBS.get(run_id, {})
        allowed={'video','live-source'} if allow_live_source else {'video'}
        if allow_live_source or allow_reconstruction: allowed.add('reconstruction')
        if job.get('kind') not in allowed or job.get('state') != 'complete':
            raise ValueError('choose a completed video analysis')
        stored = job.get('upload_path')
    if not stored:
        raise ValueError('raw footage is not retained for this run; upload the source again')
    path = Path(stored)
    if not path.is_absolute() or not path.is_relative_to(UPLOAD_ROOT) or not path.is_file():
        raise ValueError('retained source is unavailable; upload the original footage again')
    cursor = path
    while cursor != ROOT and cursor != cursor.parent:
        if cursor.is_symlink():
            raise ValueError('retained source symlinks are not allowed')
        cursor = cursor.parent
    if not path.resolve().is_relative_to(UPLOAD_ROOT.resolve()):
        raise ValueError('retained source is outside the upload store')
    return path


def _reserve(filename: str, kind: str, **fields) -> str:
    with JOBS_LOCK:
        if any(j["state"] in ACTIVE for j in JOBS.values()) or any(j['state'] in ACTIVE for j in REFINEMENTS.values()) or _live_busy():
            raise ValueError("Another job is active. Finish or cancel it first.")
        run_id, now = _new_run_id(filename), time.time()
        JOBS[run_id] = dict(id=run_id, kind=kind, filename=filename, size_bytes=0,
                            state="uploading" if kind in {"video","live-source"} else "queued", stage="queued", progress=0,
                            message="Job reserved", logs=[], viewer_url=None, created_at=now, updated_at=now, **fields)
        try:
            _persist()
        except OSError:
            JOBS.pop(run_id)
            raise
        return run_id


def _stop_process(proc):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=3)
        except ProcessLookupError:
            pass


def _refinement_worker(run_id, video, attempt=None):
    key='refine-'+run_id
    env={**os.environ,'PYTHONUNBUFFERED':'1','THEIATRON_PARENT_PID':str(os.getpid())}
    proc=None;timer=None
    with JOBS_LOCK:
        state=REFINEMENTS.get(run_id) if attempt is None else attempt
    def owns_attempt():
        return state is not None and REFINEMENTS.get(run_id) is state
    try:
        with JOBS_LOCK:
            if not owns_attempt() or state['state']!='queued':return
            proc=subprocess.Popen([sys.executable,'-m','theiatron.refinement','--run',run_id,'--video',str(video)],
                cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
            PROCESSES[key]=proc;state.update(state='processing',message='Registering camera motion and refining trajectories')
        timer=threading.Timer(600,lambda:_stop_process(proc));timer.daemon=True;timer.start()
        lines=[]
        for line in proc.stdout:
            lines.append(line.strip());lines=lines[-10:]
            with JOBS_LOCK:
                if owns_attempt() and state['state']=='processing':state['message']=line.strip()[:300]
        code=proc.wait()
        with JOBS_LOCK:
            if not owns_attempt() or state['state']!='processing':return
            if code:raise ValueError('Refinement worker failed: '+' '.join(lines[-2:]))
            result=reconstruction_source(ROOT,run_id)['refinement']
            if not result or result['stale']:raise ValueError('Refinement source changed during computation; rerun')
            state.update(state='complete',revision=result['revision'],message='Refined estimates ready; physical scale remains unvalidated')
    except Exception as exc:
        with JOBS_LOCK:
            if owns_attempt() and state['state'] not in {'cancelled','cancelling'}:state.update(state='failed',message=str(exc))
    finally:
        if timer:timer.cancel()
        if proc:_stop_process(proc)
        with JOBS_LOCK:
            if proc is not None and PROCESSES.get(key) is proc:PROCESSES.pop(key,None)


def _start_refinement(run_id,binding):
    video=_retained_source(run_id,allow_reconstruction=True)
    current=reconstruction_source(ROOT,run_id)
    if current['binding']!=binding:raise ValueError('source changed; reload before refining')
    with JOBS_LOCK:
        if any(j['state'] in ACTIVE for j in JOBS.values()) or any(j['state'] in ACTIVE for j in REFINEMENTS.values()) or _live_busy():
            raise ValueError('another processing job is active')
        attempt={'state':'queued','message':'Automatic refinement queued'}
        REFINEMENTS[run_id]=attempt
    threading.Thread(target=_refinement_worker,args=(run_id,video,attempt),daemon=True).start()
    return {'state':'queued','message':'Automatic refinement queued'}


def _cancel_refinement(run_id):
    with JOBS_LOCK:
        state=REFINEMENTS.get(run_id)
        if not state or state['state'] not in ACTIVE:return
        state.update(state='cancelling',message='Stopping refinement worker')
        proc=PROCESSES.get('refine-'+run_id)
    if proc:_stop_process(proc)
    with JOBS_LOCK:state.update(state='cancelled',message='Refinement cancelled; source observations unchanged')


def _cancel(run_id):
    with JOBS_LOCK:
        if run_id not in JOBS:
            raise KeyError(run_id)
        if JOBS[run_id]["state"] not in ACTIVE:
            return
        _update_job(run_id, state="cancelling", stage="cancelling", message="Stopping worker")
        proc = PROCESSES.get(run_id)
    if proc:
        _stop_process(proc)
    _update_job(run_id, state="cancelled", stage="cancelled",
                message="Cancelled; partial results are not final evidence", finished_at=time.time())


def _run_pipeline(run_id: str, port: int):
    with JOBS_LOCK:
        job = dict(JOBS[run_id])
        if job["state"] not in ACTIVE or job["state"] == "cancelling":
            return
        _update_job(run_id, state="processing", stage="starting", progress=4,
                    message="Starting worker", started_at=time.time())
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "THEIATRON_NO_OPEN": "1",
           "THEIATRON_VIEWER_PORT": str(port), "THEIATRON_PARENT_PID": str(os.getpid())}
    if job["kind"] == "sumo":
        command = [sys.executable, "-m", "theiatron.sumo_demo", "--out", f"out/{run_id}"]
        for key, value in job["scenario"].items():
            if value is not None:
                command.extend([f"--{key.replace('_', '-')}", str(value)])
    elif job['kind'] == 'reconstruction':
        command = [sys.executable, '-m', 'theiatron.visual_capture', '--video', job['upload_path'], '--run', run_id]
    elif job.get('camera_revision'):
        command = [sys.executable, '-m', 'theiatron.recount', '--camera-revision', job['camera_revision'],
                   '--video', job['upload_path'], '--out', f'out/{run_id}']
    else:
        command = [sys.executable, "run_demo.py", "--live-demo", "--video", job["upload_path"],
                   "--run-name", run_id, "--headless", "--observe", "120", "--duration", "120", "--result-seconds", "0"]
    timer = None
    try:
        with JOBS_LOCK:
            if JOBS[run_id]["state"] != "processing":
                return
            proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)
            PROCESSES[run_id] = proc
        def timeout():
            _append_log(run_id, "Worker exceeded the 30-minute local runtime limit")
            _stop_process(proc)
        timer = threading.Timer(1800, timeout)
        timer.daemon = True
        timer.start()
        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            _append_log(run_id, line)
            visual_progress = re.match(r'VISUAL ([\d.]+)/([\d.]+)s',line)
            m = re.match(r"(SUMO|RECOUNT) ([\d.]+)/([\d.]+)s", line)
            if visual_progress:
                _update_job(run_id,progress=5+60*float(visual_progress[1])/float(visual_progress[2]),
                            stage='capturing',message=f'Fresh recorded detection · {visual_progress[1]} / {visual_progress[2]} source seconds · no counting calibration')
            elif line.startswith('VISUAL '):
                _update_job(run_id,progress=75,stage='reconstructing',message=line[7:])
            elif m:
                _update_job(run_id, progress=5 + 80 * float(m[2]) / float(m[3]),
                            stage="simulating" if m[1]=='SUMO' else 'recounting',
                            message=(f"Computing both SUMO worlds · {m[2]} / {m[3]} simulated seconds" if m[1]=='SUMO'
                                     else f"Fresh inference on edited count lines · {m[2]} / {m[3]} source seconds"))
            else:
                progress = _progress_for_line(line)
                if progress:
                    _update_job(run_id, progress=progress[0], stage=progress[1], message=progress[2])
        code = proc.wait()
        with JOBS_LOCK:
            if JOBS[run_id]["state"] != "processing":
                return
        if code:
            raise RuntimeError(f"Worker exited {code}. " + " ".join(_public_job(run_id)["logs"][-3:]))
        if job["kind"] == "sumo":
            verify_bundle(ROOT / "out" / run_id)
            report = json.loads((ROOT / "out" / run_id / "report.json").read_text())
            _update_job(run_id, results=report, viewer_url=f"/workbench/?compare={run_id}")
        elif job['kind'] == 'reconstruction':
            current = reconstruction_source(ROOT,run_id)
            refinement = current.get('refinement') or {}
            road = refinement.get('calibration') or {}
            ready = bool(road.get('road') and refinement.get('ground_projection') and not refinement.get('stale'))
            _update_job(run_id,geometry_ready=ready,counting_available=False,
                        geometry_status='estimated-unvalidated' if ready else 'needs-review',
                        viewer_url=f'/workbench/replay.html?video={run_id}')
        else:
            manifest = json.loads((ROOT / "out" / run_id / "manifest.json").read_text())
            if not manifest.get("three_d", {}).get("ready"):
                raise RuntimeError("Video artifacts did not pass the readiness gate")
            _update_job(run_id, results=manifest.get("results", {}), events=manifest.get("events", 0),
                        calibration=manifest.get("calibration", {}), viewer_url=f"/workbench/replay.html?video={run_id}")
        with JOBS_LOCK:
            if JOBS[run_id]["state"] == "processing":
                _update_job(run_id, state="complete", stage="complete", progress=100,
                            message=(('Recorded observations ready; estimated road and 3D available' if ready else
                                      'Recorded observations ready; road geometry needs review') if job['kind']=='reconstruction'
                                     else "Run complete; inspect assumptions in Evidence"), finished_at=time.time())
    except Exception as exc:
        with JOBS_LOCK:
            if JOBS[run_id]["state"] == "processing":
                _update_job(run_id, state="failed", stage="failed", message=str(exc), finished_at=time.time())
    finally:
        if timer:
            timer.cancel()
        with JOBS_LOCK:
            proc = PROCESSES.pop(run_id, None)
        if proc:
            _stop_process(proc)


def _asset(path: str) -> Path | None:
    decoded = unquote(path)
    parts = Path(decoded.lstrip("/")).parts
    if not parts or any(p in {".", ".."} or p.startswith(".") for p in decoded.split("/") if p):
        return None
    if parts[0] in {"launcher", "workbench", "viz"}:
        if path.endswith("/"):
            parts += ("index.html",)
        if Path(parts[-1]).suffix not in {".html", ".css", ".js", ".jpg", ".png", ".mp4"}:
            return None
    elif len(parts) == 3 and parts[0] == "out" and parts[1] != "uploads" and parts[2] in RUN_FILES:
        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", parts[1]):
            return None
    else:
        return None
    candidate = ROOT.joinpath(*parts)
    cursor = candidate
    while cursor != ROOT and cursor != cursor.parent:
        if cursor.is_symlink():
            return None
        cursor = cursor.parent
    return candidate if candidate.is_file() and candidate.resolve().is_relative_to(ROOT.resolve()) else None


def _evidence_zip(run_id):
    with JOBS_LOCK:
        job=JOBS.get(run_id,{})
        if job.get('kind')!='sumo' or job.get('state')!='complete':
            raise ValueError('only completed SUMO evidence can be exported')
    report_path=_asset(f'/out/{run_id}/report.json')
    if not report_path:
        raise ValueError('report unavailable')
    report=json.loads(report_path.read_text())
    # Export only report-registered allowed files, never raw video or the repo.
    from theiatron.sumo_demo import object_hash
    import hashlib
    if object_hash({k:v for k,v in report.items() if k!='artifact_id'})!=report.get('artifact_id'):
        raise ValueError('report checksum mismatch')
    payloads={'report.json':report_path.read_bytes()}
    total=len(payloads['report.json'])
    for name,expected in report['files'].items():
        if Path(name).name!=name:
            raise ValueError('invalid evidence filename')
        path=_asset(f'/out/{run_id}/{name}')
        if not path or total+path.stat().st_size>100*1024*1024:
            raise ValueError('evidence unavailable or exceeds the 100 MB export limit')
        payload=path.read_bytes();total+=len(payload)
        if hashlib.sha256(payload).hexdigest()!=expected:
            raise ValueError('evidence checksum mismatch: '+name)
        payloads[name]=payload
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,payload in payloads.items():archive.writestr(name,payload)
    return output.getvalue()


class LauncherHandler(BaseHTTPRequestHandler):
    server_version = "TheiatronWorkbench/2"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    @property
    def launcher_port(self):
        return int(self.server.server_address[1])

    def _trusted(self, write=False):
        allowed = {f"127.0.0.1:{self.launcher_port}", f"localhost:{self.launcher_port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in allowed or (origin is not None and origin != f"http://{host}"):
            self._send_json({"error": "Local same-origin requests only"}, 403)
            return False
        if write and not secrets.compare_digest(self.headers.get("X-Theiatron-Token", ""), SESSION_TOKEN):
            self._send_json({"error": "Session expired. Reload the workbench."}, 403)
            return False
        return True

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        super().end_headers()

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._trusted():
            return
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/workbench/")
            self.end_headers()
        elif path == "/api/health":
            self._send_json({"ok": True, "service": "theiatron-workbench", "token": SESSION_TOKEN,
                             "sumo": SUMO_STATUS or preflight()})
        elif path == "/api/runs":
            with JOBS_LOCK:
                ids = list(JOBS)[-50:]
            self._send_json([_public_job(i) for i in reversed(ids)])
        elif path == '/api/live':
            self._send_json(_live_snapshot())
        elif path == '/api/live/sources':
            with JOBS_LOCK:
                ids=[i for i,j in JOBS.items() if j.get('kind') in {'video','live-source','reconstruction'} and j['state']=='complete'][-100:]
                self._send_json([_public_job(i) for i in reversed(ids)])
        elif m := re.fullmatch(r'/api/runs/([A-Za-z0-9._-]+)/evidence.zip',path):
            try:
                payload=_evidence_zip(m[1])
                self.send_response(200)
                self.send_header('Content-Type','application/zip')
                self.send_header('Content-Disposition',f'attachment; filename="theiatron-{m[1]}-evidence.zip"')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers()
                if self.command!='HEAD':self.wfile.write(payload)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                self._send_json({'error':str(exc)},400)
        elif m := re.fullmatch(r"/api/profiles/([0-9a-f]{64})", path):
            try:
                self._send_json(load_profile(ROOT, m[1]))
            except (ValueError, OSError) as exc:
                self._send_json({"error": str(exc)}, 404)
        elif m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/live-geometry", path):
            try:
                with JOBS_LOCK:
                    if JOBS.get(m[1],{}).get('kind')=='live-source':
                        raise ValueError('This detection-only upload has no saved road/camera estimates yet. Stop detection and choose Prepare road & saved 3D')
                self._send_json(live_geometry(ROOT, m[1]))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self._send_json({'error': str(exc)}, 400)
        elif m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/reconstruction", path):
            try:
                self._send_json(reconstruction_source(ROOT,m[1]))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self._send_json({'error':str(exc)},400)
        elif m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/refine", path):
            with JOBS_LOCK:
                self._send_json(dict(REFINEMENTS.get(m[1],{'state':'idle','message':'No refinement worker running (or service restarted). Reload to inspect saved estimates.'})))
        elif m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/counting", path):
            try:
                _retained_source(m[1])
                source = counting_source(ROOT,m[1])
                self._send_json({k:v for k,v in source.items() if k not in {'source','config'}} |
                                {'rois':{a['name']:a.get('roi') for a in source['config']['approaches']}})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self._send_json({'error':str(exc)},400)
        elif m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)", path):
            with JOBS_LOCK:
                exists = m[1] in JOBS
            self._send_json(_public_job(m[1]) if exists else {"error": "Run not found"}, 200 if exists else 404)
        elif asset := _asset(path):
            self._send_asset(asset)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _send_asset(self, asset):
        # Workers atomically replace previews. Stat and stream the same inode.
        with asset.open("rb") as stream:
            self._stream_asset(asset, stream)

    def _stream_asset(self, asset, stream):
        size = os.fstat(stream.fileno()).st_size
        start, end = 0, size - 1
        requested = self.headers.get("Range")
        if requested:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not m or not (m[1] or m[2]):
                return self._send_json({"error": "Invalid range"}, 416)
            if m[1]:
                start, end = int(m[1]), min(int(m[2]), end) if m[2] else end
            else:
                start = max(0, size - int(m[2]))
            if start > end or start >= size:
                return self._send_json({"error": "Range outside file"}, 416)
        self.send_response(206 if requested else 200)
        self.send_header("Content-Type", mimetypes.guess_type(asset)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Accept-Ranges", "bytes")
        if requested:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command != "HEAD":
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = stream.read(min(1024 * 1024, remaining))
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)

    def _receive_live_upload(self, run_id, length):
        with JOBS_LOCK:
            job=JOBS.get(run_id,{})
            if job.get('kind')!='live-source' or job.get('state')!='uploading' or job.get('stage')!='awaiting-upload':
                raise ValueError('upload reservation is not awaiting a file')
            if length!=job['expected_bytes']:
                raise ValueError('uploaded size must match the reservation')
            _update_job(run_id,stage='receiving-upload',message='Receiving video; detection starts after transfer')
            filename,options=job['filename'],dict(job['live_options'])
        directory=UPLOAD_ROOT/run_id
        partial=directory/'.uploading'
        partial_owned=False
        try:
            if not UPLOAD_ROOT.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError('upload store is outside the project')
            cursor=UPLOAD_ROOT
            while cursor!=ROOT and cursor!=cursor.parent:
                if cursor.is_symlink(): raise ValueError('upload store symlinks are not allowed')
                cursor=cursor.parent
            directory.mkdir(parents=True,exist_ok=False)
            path=directory/filename
            self.connection.settimeout(30)
            remaining=length
            deadline=time.monotonic()+600
            with partial.open('xb') as output:
                partial_owned=True
                while remaining:
                    if time.monotonic()>deadline: raise ValueError('upload exceeded its ten-minute deadline')
                    with JOBS_LOCK:
                        if JOBS[run_id]['state']!='uploading': raise ValueError('Upload cancelled')
                    chunk=self.rfile.read(min(1024*1024,remaining))
                    if not chunk: raise ValueError('Upload ended early')
                    output.write(chunk);remaining-=len(chunk)
            with JOBS_LOCK:
                if JOBS[run_id]['state']!='uploading': raise ValueError('Upload cancelled')
                partial.replace(path)
                _update_job(run_id,state='complete',stage='retained',progress=100,size_bytes=length,
                            upload_path=str(path),finished_at=time.time(),
                            message='Video retained for fresh detection only; no road analysis or traffic metrics')
                # Keep reservation release and worker admission atomic. Neither
                # a SUMO job nor another upload may take the slot in between.
                source=_public_job(run_id)
                try:
                    live=_start_live({'source_run':run_id,**options})
                    return {'source':source,'live':live,'start_error':None}
                except (ValueError,OSError) as exc:
                    return {'source':source,'live':_live_snapshot(),'start_error':str(exc)}
        except (ValueError,OSError) as exc:
            with JOBS_LOCK:
                if JOBS[run_id]['state']=='uploading':
                    _update_job(run_id,state='failed',stage='failed',message=str(exc),finished_at=time.time())
            raise
        finally:
            if partial_owned: partial.unlink(missing_ok=True)

    def do_POST(self):
        if not self._trusted(write=True):
            self.close_connection = True
            return
        parsed = urlparse(self.path)
        run_id = None
        try:
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))>1:
                raise ValueError('provide one Content-Length; chunked bodies are not supported')
            if parsed.path == '/api/live/uploads':
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=4096: raise ValueError('upload reservation must be at most 4 KB')
                return self._send_json(_reserve_live_upload(json.loads(self.rfile.read(length))),201)
            if m := re.fullmatch(r'/api/live/uploads/([A-Za-z0-9._-]+)/cancel',parsed.path):
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=4096 or json.loads(self.rfile.read(length))!={}:
                    raise ValueError('invalid upload cancellation request')
                with JOBS_LOCK:
                    if JOBS.get(m[1],{}).get('kind')!='live-source':raise ValueError('choose a live upload')
                    _cancel(m[1])
                    current=LIVE_SERVICE.snapshot().get('session') if LIVE_SERVICE else None
                    if current and current.get('source_run')==m[1] and LIVE_SERVICE.busy():
                        LIVE_SERVICE.stop(current['id'])
                    return self._send_json(_live_snapshot())
            if m := re.fullmatch(r'/api/live/uploads/([A-Za-z0-9._-]+)/content',parsed.path):
                length=int(self.headers.get('Content-Length',0))
                return self._send_json(self._receive_live_upload(m[1],length),202)
            if m := re.fullmatch(r'/api/live/sources/([A-Za-z0-9._-]+)/(analyse|reconstruct)',parsed.path):
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=4096 or json.loads(self.rfile.read(length))!={'acknowledge_estimates':True}:
                    raise ValueError('acknowledge estimated geometry before preparing the road')
                source=_retained_source(m[1],allow_live_source=True)
                kind = 'reconstruction' if m[2]=='reconstruct' else 'video'
                run_id=_reserve(source.name,kind,parent_source_run=m[1],upload_path=str(source))
                _update_job(run_id,state='queued',message=('Preparing recorded 3D without counting calibration; geometry remains estimated'
                            if kind=='reconstruction' else 'Analysing traffic directions and arrival counts; calibration gates apply'))
                threading.Thread(target=_run_pipeline,args=(run_id,self.launcher_port),daemon=True).start()
                return self._send_json(_public_job(run_id),202)
            if parsed.path in {'/api/live/start','/api/live/stop'}:
                length=int(self.headers.get('Content-Length',0))
                if not 1<=length<=4096: raise ValueError('invalid continuous session request')
                data=json.loads(self.rfile.read(length))
                if parsed.path.endswith('/start'): return self._send_json(_start_live(data),202)
                if not isinstance(data,dict) or set(data)!={'id'} or LIVE_SERVICE is None:
                    raise ValueError('choose the active continuous session')
                return self._send_json(LIVE_SERVICE.stop(data['id']))
            if m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/refine/cancel", parsed.path):
                _cancel_refinement(m[1])
                with JOBS_LOCK:return self._send_json(dict(REFINEMENTS.get(m[1],{'state':'idle'})))
            if m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/cancel", parsed.path):
                _cancel(m[1])
                return self._send_json(_public_job(m[1]))
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked uploads are not supported")
            length = int(self.headers.get("Content-Length", "0"))
            if m := re.fullmatch(r'/api/runs/([A-Za-z0-9._-]+)/demo-profile',parsed.path):
                if not 0 < length <= 4096:
                    raise ValueError('demo request must be at most 4 KB')
                data=json.loads(self.rfile.read(length))
                if data != {'acknowledge_estimates':True}:
                    raise ValueError('acknowledge estimated geometry and assumed exits')
                with JOBS_LOCK:
                    job=JOBS.get(m[1],{})
                    if job.get('state')!='complete' or job.get('kind')!='video':
                        raise ValueError('choose a completed video analysis')
                from theiatron.demo_profiles import propose
                return self._send_json(propose(ROOT,m[1]),201)
            if m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/refine", parsed.path):
                if not 0 < length <= 4096:
                    raise ValueError('refinement request must be at most 4 KB')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data,dict) or set(data) != {'binding'}:
                    raise ValueError('provide this source binding only')
                return self._send_json(_start_refinement(m[1],data['binding']),202)
            if m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/reconstruction/assist(/save)?", parsed.path):
                if not 0 < length <= 32768:
                    raise ValueError('assisted geometry request must be at most 32 KB')
                data=json.loads(self.rfile.read(length))
                result=save_assisted(ROOT,m[1],data) if m[2] else preview_assisted(ROOT,m[1],data)
                return self._send_json(result,201 if m[2] else 200)
            if m := re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/reconstruction", parsed.path):
                if not 0 < length <= 32768:
                    raise ValueError('reconstruction draft must be at most 32 KB')
                data = json.loads(self.rfile.read(length))
                return self._send_json(save_reconstruction(ROOT,m[1],data),201)
            if parsed.path == "/api/profiles" or re.fullmatch(r"/api/profiles/[0-9a-f]{64}/revisions", parsed.path):
                if not 0 < length <= 32768:
                    raise ValueError("profile request must be at most 32 KB")
                data = json.loads(self.rfile.read(length))
                if parsed.path == "/api/profiles":
                    if not isinstance(data, dict) or set(data) != {'source_run'}:
                        raise ValueError('choose a completed source run')
                    with JOBS_LOCK:
                        source = JOBS.get(data['source_run'], {})
                        if source.get('state') != 'complete' or source.get('kind') != 'video':
                            raise ValueError('choose a completed video analysis from saved runs')
                    profile = from_run(ROOT, data['source_run'])
                else:
                    profile = revise(ROOT, parsed.path.split('/')[3], data)
                return self._send_json(profile, 201)
            if parsed.path == '/api/recounts':
                if not 0 < length <= 8192:
                    raise ValueError('count-line edits must be at most 8 KB')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data,dict) or set(data) != {'source_run','approaches','acknowledge_candidate'}:
                    raise ValueError('choose a source and edit only its counting geometry')
                if data['acknowledge_candidate'] is not True:
                    raise ValueError('acknowledge that edited count lines are still unvalidated candidates')
                source = _retained_source(data['source_run'])
                camera = seal_camera(ROOT,data['source_run'],data['approaches'])
                run_id = _reserve(source.name,'video',camera_revision=camera['revision'],
                                  parent_source_run=data['source_run'],upload_path=str(source))
                _update_job(run_id,state='queued',message='Reusing retained local footage; fresh inference queued')
            elif parsed.path == "/api/compare":
                if not 0 < length <= 2048:
                    raise ValueError("Invalid scenario payload size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('scenario must be an object')
                acknowledged = data.pop('acknowledge_assumptions', False)
                scenario = Scenario(**data)
                profile = None
                if scenario.site_revision:
                    if acknowledged is not True:
                        raise ValueError('acknowledge the draft network assumptions before computing')
                    profile = load_profile(ROOT, scenario.site_revision)
                    validate_profile(profile, runnable=True)
                    if not scenario.generated_demand and scenario.duration != source_horizon(profile['source']):
                        raise ValueError('use the complete source horizon with a step after the last arrival')
                status = SUMO_STATUS or preflight()
                if not status["ready"]:
                    return self._send_json({"error": status["error"]}, 503)
                from dataclasses import asdict
                run_id = _reserve(profile['source']['filename'] + ' · SUMO hypothesis' if profile else "sumo-laboratory", "sumo", scenario=asdict(scenario))
            elif parsed.path == "/api/runs":
                filename = _safe_filename(parse_qs(parsed.query).get("filename", [""])[0])
                if not 0 < length <= MAX_UPLOAD_BYTES:
                    raise ValueError("Video must be nonempty and no larger than 4 GB")
                run_id = _reserve(filename, "video")
                upload_dir = UPLOAD_ROOT / run_id
                upload_dir.mkdir(parents=True, exist_ok=False)
                upload_path, partial = upload_dir / filename, upload_dir / ".uploading"
                try:
                    remaining = length
                    with partial.open("wb") as output:
                        while remaining:
                            if _public_job(run_id)["state"] != "uploading":
                                raise ValueError("Upload cancelled")
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ValueError("Upload ended early")
                            output.write(chunk)
                            remaining -= len(chunk)
                    partial.replace(upload_path)
                finally:
                    partial.unlink(missing_ok=True)
                with JOBS_LOCK:
                    if JOBS[run_id]["state"] != "uploading":
                        raise ValueError("Upload cancelled")
                    _update_job(run_id, state="queued", upload_path=str(upload_path), size_bytes=length)
            else:
                return self._send_json({"error": "Not found"}, 404)
            threading.Thread(target=_run_pipeline, args=(run_id, self.launcher_port), daemon=True).start()
            self._send_json(_public_job(run_id), 202)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            if run_id and _public_job(run_id)["state"] not in {"cancelled", "cancelling"}:
                _update_job(run_id, state="failed", stage="failed", message=str(exc), finished_at=time.time())
            self.close_connection = True
            self._send_json({"error": str(exc)}, 409 if "active" in str(exc) else 400)


def main():
    global SUMO_STATUS
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    args = p.parse_args()
    JOB_STORE.parent.mkdir(parents=True, exist_ok=True)
    with (JOB_STORE.parent / "service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("A workbench is already running against this project.")
        _load_jobs()
        SUMO_STATUS = preflight()
        server = ThreadingHTTPServer((args.host, args.port), LauncherHandler)
        print(f"Theiatron workbench: http://127.0.0.1:{args.port}/workbench/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if LIVE_SERVICE is not None: LIVE_SERVICE.close()
            for run_id in list(PROCESSES):
                if run_id.startswith('refine-') and run_id[7:] in REFINEMENTS:
                    _cancel_refinement(run_id[7:])
                else:
                    _cancel(run_id)
            server.server_close()


if __name__ == "__main__":
    main()
