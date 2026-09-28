"""Fresh recorded observations for 3D, independent of counting and simulation.

No approach inference, arrival extractor or controller runs here. Completion
means the observations are saved, not that road/metric geometry is validated.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
import shutil
import subprocess

from .artifacts import fingerprint
from .config import VisionConfig
from .io import atomic_json
from .provenance import file_hash, vision_provenance

NAME = 'reconstruction-source.json'
ASSETS = ('recorded-tracks.json', 'plate.jpg', 'footage.mp4')


def load_source(directory: Path) -> dict:
    """Verify the distinct visual artifact; it is never a simulation artifact."""
    paths = [directory/NAME, *(directory/name for name in ASSETS)]
    if directory.is_symlink() or any(p.is_symlink() for p in paths):
        raise ValueError('visual source symlinks are not allowed')
    artifact = json.loads(paths[0].read_text())
    if artifact.get('artifact_id') != fingerprint({k:v for k,v in artifact.items() if k != 'artifact_id'}):
        raise ValueError('visual source checksum mismatch')
    if (artifact.get('schema_version') != 1 or artifact.get('kind') != 'recorded-perception'
            or artifact.get('counting_available') is not False
            or artifact.get('metric_accuracy_validated') is not False
            or artifact.get('plate_mode') != 'first-processed-frame'):
        raise ValueError('unsupported visual source')
    dt, duration, frames = (artifact.get(k) for k in ('cadence_s', 'duration', 'frames'))
    if (type(frames) is not int or not 1 <= frames <= 3600
            or any(type(v) not in {float,int} or not math.isfinite(v) or v <= 0 for v in (dt,duration))
            or not 1/240 <= dt <= 1 or abs(duration-frames*dt) > 1e-6):
        raise ValueError('invalid visual source clock')
    if artifact.get('assets') != {name:file_hash(directory/name) for name in ASSETS}:
        raise ValueError('visual source asset checksum mismatch')
    return artifact


def capture(video: Path, out: Path, *, duration=120., cfg=None, detector_factory=None):
    import cv2
    from .detection import VehicleDetector
    from .feeds import VideoFeed
    from .preview import PreviewPublisher
    from .recorded_tracks import RecordedTracks
    from .refinement import _validate_dense

    cfg = cfg or VisionConfig(imgsz=640)
    if (type(duration) not in {int,float} or not math.isfinite(duration) or not 1 <= duration <= 120
            or not math.isfinite(cfg.process_fps) or not 1 <= cfg.process_fps <= 30):
        raise ValueError('visual capture supports 1–120 seconds at 1–30 FPS')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg: raise ValueError('ffmpeg is required for the browser replay')
    source_sha = file_hash(video)
    def provenance():
        value = vision_provenance(cfg.model)
        value['code_sha256']['theiatron/visual_capture.py'] = file_hash(Path(__file__))
        return value
    before = provenance()
    out.mkdir(parents=True, exist_ok=False)
    feed = VideoFeed(str(video), cfg.process_fps, loop=False)
    writer = None
    dense = RecordedTracks()
    ticks = 0
    preview = PreviewPublisher(out)
    try:
        if not math.isfinite(feed.native_fps) or not 1 <= feed.native_fps <= 240:
            raise ValueError('unsupported source frame rate')
        detector = (detector_factory or VehicleDetector)(cfg)
        writer = cv2.VideoWriter(str(out/'footage-raw.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 1/feed.dt, (1280,720))
        if not writer.isOpened(): raise RuntimeError('cannot encode visual capture')
        for tick in range(1, min(3600, math.floor(duration/feed.dt+1e-6))+1):
            frame, _ = feed.read()
            if frame is None: break
            frame = cv2.resize(frame, (1280,720), interpolation=cv2.INTER_AREA)
            now = round(tick*feed.dt, 6)
            if tick == 1 and not cv2.imwrite(str(out/'plate.jpg'), frame):
                raise RuntimeError('cannot save reference frame')
            detections = detector.track(frame)
            dense.update(now, detections)
            annotated = frame.copy()
            for d in detections:
                x1,y1,x2,y2 = map(int,d.box)
                cv2.rectangle(annotated,(x1,y1),(x2,y2),(85,220,160),2)
                cv2.putText(annotated,f'{d.track_id} {d.conf:.2f}',(x1,max(15,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.45,(85,220,160),1)
            writer.write(annotated)
            preview.publish(annotated, now, 'capturing', source_name=video.name, target_s=duration)
            ticks = tick
            if tick == 1 or tick % 50 == 0: print(f'VISUAL {now:.1f}/{duration:.1f}s', flush=True)
    finally:
        feed.release()
        if writer is not None: writer.release()
    if not ticks: raise ValueError('video contains no decodable sampled frames')
    payload = dense.export({})
    _validate_dense(payload)
    atomic_json(out/'recorded-tracks.json', payload)
    print('VISUAL publishing browser video', flush=True)
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-n',
        '-i',str(out/'footage-raw.mp4'),'-c:v','libx264','-preset','veryfast','-crf','23',
        '-pix_fmt','yuv420p','-movflags','+faststart','-an',str(out/'footage.mp4')],
        check=True, capture_output=True, text=True, timeout=180)
    if file_hash(video) != source_sha or provenance() != before:
        raise ValueError('footage, model or capture code changed during inference')
    result = {'schema_version':1, 'kind':'recorded-perception',
        'source':str(video.resolve()), 'source_sha256':source_sha,
        'duration':round(ticks*feed.dt,6), 'cadence_s':feed.dt, 'frames':ticks,
        'plate_mode':'first-processed-frame', 'counting_available':False,
        'metric_accuracy_validated':False, 'vision':{**asdict(cfg),'classes':list(cfg.classes)}, 'runtime_provenance':before,
        'assets':{name:file_hash(out/name) for name in ASSETS}}
    result['artifact_id'] = fingerprint(result)
    atomic_json(out/NAME, result)
    # Only this worker's staging encode; the verified browser copy is retained.
    (out/'footage-raw.mp4').unlink()
    return result


if __name__ == '__main__':
    import argparse
    from .preview import parent_watchdog
    from .reconstruction import source
    from .refinement import build
    parent_watchdog()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True, type=Path)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    from .reconstruction import _safe
    out = _safe(root,args.run,NAME).parent
    capture(args.video, out)
    print('VISUAL estimating camera and road geometry', flush=True)
    try:
        build(root,args.run,source(root,args.run)['binding'],args.video,
              progress=lambda message: print('VISUAL '+message, flush=True))
    except ValueError as exc:
        # Observations survive insufficient geometric evidence; no placeholder
        # road, arrival counts or benefit claims are manufactured.
        print('VISUAL geometry needs review: '+str(exc), flush=True)
    print('VISUAL capture complete', flush=True)
