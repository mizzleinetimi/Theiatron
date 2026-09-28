"""Resident single-camera detector. JSON-line IPC; no signal actuation or video export.

Workbench accepts retained paced files only. The standalone CLI also accepts
an explicitly supplied RTSP environment variable, never a browser-provided URL.
RTSP timestamps are host read-completion proxies, NOT sensor capture timestamps.
"""
import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import queue
import signal
import sys
import threading
import time

from .io import atomic_bytes, atomic_json
from .streaming import Frame, LatestFrame, Observations, needs_tracker_reset


def emit(event, **fields):
    print('THEIATRON_STREAM '+json.dumps({'event': event, **fields}, allow_nan=False), flush=True)


class ResidentDetector:
    def __init__(self, cfg):
        import numpy as np
        from .detection import VehicleDetector
        self.detector = VehicleDetector(cfg)
        self.detector.track(np.zeros((720, 1280, 3), dtype=np.uint8))
        self.reset()

    def reset(self):
        # Keep the warm predictor and exactly one registration of tracking
        # callbacks. Clearing predictor re-registers callbacks in Ultralytics.
        predictor = self.detector.model.predictor
        for tracker in predictor.trackers:
            tracker.reset()
        predictor.vid_path = [None] * len(predictor.trackers)

    def track(self, image):
        return self.detector.track(image)


class FileCapture:
    kind = 'paced-file'
    age_basis = 'Scheduled file presentation to inference completion; not hardware capture latency'

    def __init__(self, source, fps, loop=False):
        from .feeds import VideoFeed
        self.feed = VideoFeed(source, fps, loop=False)
        self.loop = loop
        self.skipped = self.epoch = 0
        self.dt = self.feed.dt

    def capture(self, mailbox, stop):
        import cv2
        start = time.monotonic()
        ordinal = sequence = 0
        try:
            while not stop.is_set():
                # If decode was delayed, skip overdue samples instead of slowly
                # catching up a backlog. Normal native-to-target sampling is not
                # counted as a dropped target frame.
                overdue = max(0, math.floor((time.monotonic()-start)/self.dt)-ordinal-1)
                for _ in range(overdue * self.feed.skip):
                    if stop.is_set(): return
                    if not self.feed.cap.grab(): break
                ordinal += overdue
                self.skipped += overdue
                image, _ = self.feed.read()
                if image is None:
                    if not self.loop: break
                    self.feed.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.epoch += 1
                    ordinal = 0
                    start = time.monotonic()
                    # A corrupt/empty looping clip must not spin forever.
                    image, _ = self.feed.read()
                    if image is None: raise ValueError('no readable frames in source')
                ordinal += 1
                source_time = ordinal * self.dt
                deadline = start + source_time
                image = cv2.resize(image, (1280, 720))
                if stop.wait(max(0, deadline-time.monotonic())): break
                sequence += 1
                frame_index = round(self.feed.cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                mailbox.offer(Frame(image, sequence, self.epoch, source_time, deadline, time.monotonic(), frame_index))
        except Exception as exc:
            mailbox.close(str(exc))
        finally:
            self.feed.release()
            mailbox.close(mailbox.error)


class RtspCapture:
    kind = 'rtsp'
    age_basis = 'Host read completion to inference completion; upstream camera/network buffering is unmeasured'

    def __init__(self, source, fps, loop=False):
        import cv2
        from urllib.parse import urlsplit
        if urlsplit(source).scheme not in {'rtsp', 'rtsps'} or not urlsplit(source).hostname:
            raise ValueError('camera source must be an explicit RTSP URL')
        self.cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000])
        if not self.cap.isOpened(): raise ValueError('camera open failed; inspect access/connectivity locally')
        self.dt = 1/fps
        self.skipped = 0

    def capture(self, mailbox, stop):
        import cv2
        start = previous = time.monotonic()
        sequence = 0
        try:
            while not stop.is_set():
                ok, image = self.cap.read()
                received = time.monotonic()
                if not ok: raise ValueError('camera read failed or timed out; stream stopped')
                if received-previous < self.dt: continue
                previous = received
                sequence += 1
                mailbox.offer(Frame(cv2.resize(image, (1280, 720)), sequence, 0,
                                    received-start, received, received))
        except Exception:
            # Decoder errors can contain credentials. Do not publish exception URLs.
            mailbox.close('camera read failed or timed out; stream stopped')
        finally:
            self.cap.release()
            mailbox.close(mailbox.error)


def annotate(image, detections, namespace):
    import cv2
    result = image.copy()
    for d in detections:
        x1,y1,x2,y2 = map(round,d.box)
        cv2.rectangle(result,(x1,y1),(x2,y2),(110,235,140),2)
        cv2.putText(result,f'{namespace}:{d.track_id} {d.conf:.2f}',(x1,max(18,y1-5)),
                    cv2.FONT_HERSHEY_SIMPLEX,.45,(110,235,140),1,cv2.LINE_AA)
    return result


def run_session(request, detector, stop, provenance, warm_s, capture_factory=None):
    import cv2
    out = Path(request['out'])
    out.mkdir(parents=True, exist_ok=False)
    started_wall, started = time.time(), time.monotonic()
    source_kind = request.get('source_kind', 'paced-file')
    snapshot = {'schema_version':1, 'id':request['id'], 'state':'starting',
        'source_kind':source_kind, 'source_run':request.get('source_run'),
        'source_name':request.get('source_name','Explicit camera'),
        'target_fps':request['fps'], 'duration_limit_s':request['duration'], 'loop':request.get('loop',False),
        'started_at':started_wall, 'worker_pid':os.getpid(), 'worker_warmup_s':round(warm_s,3),
        'model_loads_in_worker':1, 'provenance':provenance,
        'scope':'Continuous perception only; no rebuilt 3D road, arrival-count validation or signal actuation'}
    atomic_json(out/'latest.json',snapshot)
    capture = None
    capture_thread = None
    mailbox = LatestFrame()
    metrics = Observations()
    last = None
    first_s = None
    tracking_epoch = 0
    finished_reason = 'source-ended'
    next_publish = 0
    state = 'complete'
    error = None
    try:
        detector.reset()
        from .provenance import file_hash
        if source_kind == 'paced-file': snapshot['source_sha256'] = file_hash(request['source'])
        factory = capture_factory or (FileCapture if source_kind=='paced-file' else RtspCapture)
        capture = factory(request['source'],request['fps'],request.get('loop',False))
        snapshot['age_basis'] = capture.age_basis
        capture_thread = threading.Thread(target=capture.capture,args=(mailbox,stop),daemon=True)
        capture_thread.start()
        with (out/'observations.jsonl').open('x') as trace:
            while not stop.is_set():
                if time.monotonic()-started >= request['duration']:
                    finished_reason = 'duration-limit'; break
                frame = mailbox.take()
                if frame is None:
                    if mailbox.closed: break
                    continue
                now = time.monotonic()
                if now-frame.available_at > .3:
                    metrics.stale += 1
                    continue
                if needs_tracker_reset(last,frame):
                    detector.reset(); tracking_epoch += 1; metrics.resets += 1
                inference_start = time.monotonic()
                detections = detector.track(frame.image)
                finished = time.monotonic()
                metrics.add(frame,inference_start,finished)
                if first_s is None: first_s = finished-started
                namespace = f"{request['id']}:{tracking_epoch}"
                row = {'sequence':frame.sequence, 'source_epoch':frame.epoch,
                       'frame_index':frame.frame_index,
                       'source_time_s':round(frame.source_time_s,6), 'namespace':namespace,
                       'completed_at':time.time(), 'age_ms':round((finished-frame.available_at)*1000,3),
                       'inference_ms':round((finished-inference_start)*1000,3),
                       'detections':[asdict(d) for d in detections]}
                trace.write(json.dumps(row,allow_nan=False)+'\n')
                last = frame
                snapshot.update(state='running',last_observation=row,
                    first_observation_s=round(first_s,3), metrics=metrics.snapshot(), buffer=mailbox.snapshot())
                if finished >= next_publish:
                    visual = cv2.resize(annotate(frame.image,detections,str(tracking_epoch)),(960,540))
                    ok,jpeg = cv2.imencode('.jpg',visual,[cv2.IMWRITE_JPEG_QUALITY,80])
                    if not ok: raise ValueError('preview encoding failed')
                    atomic_bytes(out/'preview.jpg',jpeg.tobytes())
                    snapshot.update(published_at=time.time(),elapsed_s=round(time.monotonic()-started,3),
                                    capture_skipped_ticks=capture.skipped,
                                    preview_age_ms=round((time.monotonic()-frame.available_at)*1000,3))
                    atomic_json(out/'latest.json',snapshot)
                    trace.flush()
                    next_publish = finished+.2
            if mailbox.error: raise ValueError(mailbox.error)
            if source_kind=='paced-file' and file_hash(request['source'])!=snapshot['source_sha256']:
                raise ValueError('source changed during session')
            root=Path(__file__).resolve().parents[1]
            if any(file_hash(root/p)!=sha for p,sha in provenance.get('stream_code_sha256',{}).items()):
                raise ValueError('stream code changed during session; restart worker')
            if stop.is_set(): state='stopped';finished_reason='operator-stop'
            if metrics.age.count == 0 and state != 'stopped':
                raise ValueError('no fresh observations produced')
    except Exception as exc:
        state,error = 'failed',str(exc) if source_kind=='paced-file' else 'camera session failed; inspect local connectivity'
    finally:
        stop.set()
        if capture_thread:
            capture_thread.join(timeout=4)
            if capture_thread.is_alive():
                # Never reuse a detector while a capture thread is unresponsive.
                emit('fatal',id=request['id'],message='capture did not stop within deadline')
                os._exit(2)
        snapshot.update(state=state,error=error,finished_reason=finished_reason,
            finished_at=time.time(),elapsed_s=round(time.monotonic()-started,3),
            metrics=metrics.snapshot(),buffer=mailbox.snapshot(),
            capture_skipped_ticks=capture.skipped if capture else 0)
        atomic_json(out/'latest.json',snapshot)
        from .provenance import file_hash
        snapshot['files'] = {name:file_hash(out/name) for name in ('observations.jsonl','preview.jpg') if (out/name).is_file()}
        from .artifacts import fingerprint
        snapshot['artifact_id'] = fingerprint(snapshot)
        atomic_json(out/'stream-report.json',snapshot)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/intersection.yaml')
    parser.add_argument('--ipc',action='store_true')
    parser.add_argument('--source',help='local file, paced at source speed')
    parser.add_argument('--camera-env',help='name of environment variable containing an explicit RTSP URL')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--duration',type=float,default=120)
    parser.add_argument('--fps',type=float,default=10)
    parser.add_argument('--loop',action='store_true')
    args=parser.parse_args()
    from .config import load_config
    from .preview import parent_watchdog
    from .provenance import vision_provenance,file_hash
    parent_watchdog()
    cfg=load_config(args.config)
    provenance=vision_provenance(cfg.vision.model)
    root=Path(__file__).resolve().parents[1]
    provenance['stream_code_sha256']={p:file_hash(root/p) for p in
        ('theiatron/streaming.py','theiatron/live_worker.py','theiatron/live_service.py')}
    provenance['vision_config']=asdict(cfg.vision)
    begin=time.monotonic()
    detector=ResidentDetector(cfg.vision)
    warm_s=time.monotonic()-begin
    emit('ready',warmup_s=round(warm_s,3),pid=os.getpid())
    if not args.ipc:
        if not args.out or bool(args.source)==bool(args.camera_env):
            parser.error('specify --out and exactly one of --source or --camera-env')
        if not math.isfinite(args.duration) or not 1<=args.duration<=3600 or not math.isfinite(args.fps) or not 1<=args.fps<=30:
            parser.error('duration must be 1–3600 seconds; FPS 1–30')
        stop=threading.Event()
        signal.signal(signal.SIGTERM,lambda *_:stop.set())
        signal.signal(signal.SIGINT,lambda *_:stop.set())
        request={'id':args.out.name,'source':args.source or os.environ.get(args.camera_env,''),
                 'source_kind':'rtsp' if args.camera_env else 'paced-file',
                 'source_name':'Explicit camera' if args.camera_env else Path(args.source).name,
                 'out':str(args.out),'duration':args.duration,'fps':args.fps,'loop':args.loop}
        result=run_session(request,detector,stop,provenance,warm_s)
        raise SystemExit(0 if result['state'] in {'complete','stopped'} else 1)
    requests=queue.Queue(maxsize=1)
    controls={}
    lock=threading.Lock()
    shutdown=threading.Event()
    def receive():
        try:
            for line in sys.stdin:
                command=json.loads(line)
                with lock:
                    if command['action']=='start':
                        if controls: raise ValueError('worker already has an admitted session')
                        control=threading.Event();controls[command['id']]=control
                        requests.put_nowait((command,control))
                    elif command['action']=='stop':
                        control=controls.get(command['id'])
                        if control: control.set()
                    elif command['action']=='shutdown': break
        except Exception:
            emit('fatal',message='invalid worker command or closed input')
        finally:
            with lock:
                for event in controls.values():event.set()
            shutdown.set()
    threading.Thread(target=receive,daemon=True).start()
    while not shutdown.is_set():
        try: request,stop=requests.get(timeout=.2)
        except queue.Empty: continue
        emit('started',id=request['id'])
        result=run_session(request,detector,stop,provenance,warm_s)
        with lock:controls.pop(request['id'],None)
        emit('finished',id=request['id'],state=result['state'])


if __name__=='__main__':main()
