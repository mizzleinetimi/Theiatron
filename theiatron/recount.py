"""Fresh file inference using explicitly edited camera count lines.

This is candidate detector commissioning, not manual ground truth or automatic
site review. A new immutable run is created; no source evidence is overwritten.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import time

from .artifacts import fingerprint, load_artifact
from .config import config_from_dict, save_config
from .io import atomic_json
from .preview import PreviewPublisher, parent_watchdog
from .provenance import file_hash, vision_provenance

ROOT = Path(__file__).resolve().parents[1]
HASH = re.compile(r'[0-9a-f]{64}')


def counting_source(root: Path, run_id: str) -> dict:
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,120}', run_id):
        raise ValueError('invalid counting source')
    path = root/'out'/run_id/'simulation.json'
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('source symlinks are not allowed')
    artifact = load_artifact(path)
    meta = artifact['source_meta']
    if meta.get('kind') != 'live-video-analysis' or not HASH.fullmatch(meta.get('source_sha256','')):
        raise ValueError('a fingerprinted video analysis is required')
    if meta.get('evaluation_scope') not in {'full-fresh-pass', 'full-single-inference-pass', 'manual-candidate-full-pass'}:
        raise ValueError('recount currently supports full-clip analysis only, not an offset evaluation window')
    cfg = config_from_dict(artifact['config'])
    if not 2 <= len(cfg.approaches) <= 4 or not 30 <= artifact['duration'] <= 300:
        raise ValueError('recount supports 2–4 detectors and 30–300 source seconds')
    approaches = [{k: getattr(a,k) for k in ('name','phase','count_line','approach_side')} for a in cfg.approaches]
    return {'source_run':run_id, 'source_artifact_id':artifact['artifact_id'],
            'source_sha256':meta['source_sha256'], 'duration':artifact['duration'],
            'source':meta['source'], 'approaches':approaches, 'config':artifact['config'],
            'review_status':'manual-candidate-unreviewed'}


def seal_camera(root: Path, run_id: str, edits: list) -> dict:
    original = counting_source(root,run_id)
    if not isinstance(edits,list) or len(edits) != len(original['approaches']):
        raise ValueError('preserve the source detector list')
    cfg = deepcopy(original['config'])
    for source, edit in zip(cfg['approaches'], edits):
        if not isinstance(edit,dict) or set(edit) != {'name','phase','count_line','approach_side'} or edit['name'] != source['name']:
            raise ValueError('only count lines, approach-side markers and candidate phase grouping are editable')
        if edit['phase'] not in {'NS','EW'}:
            raise ValueError('candidate phase must be NS or EW')
        line, side = edit['count_line'], edit['approach_side']
        if not isinstance(line,list) or len(line) != 2:
            raise ValueError('count line needs two points')
        for point in [*line, side]:
            if not isinstance(point,list) or len(point) != 2 or any(
                type(v) not in {int,float} or not math.isfinite(v) or not 0 <= v <= bound
                for v,bound in zip(point,(1279,719))):
                raise ValueError('camera points must be finite within the 1280×720 image')
        p,q = line
        length = math.hypot(q[0]-p[0],q[1]-p[1])
        if length < 10:
            raise ValueError('count lines must be at least 10 pixels long')
        distance = abs((q[0]-p[0])*(side[1]-p[1])-(q[1]-p[1])*(side[0]-p[0]))/length
        if distance < 5:
            raise ValueError('place the approach-side marker at least 5 pixels away from the line')
        source.update(deepcopy(edit))
    config_from_dict(cfg)
    profile = {**original,'config':cfg,'approaches':deepcopy(edits)}
    profile['revision'] = fingerprint(profile)
    directory = root/'out'/'.camera-profiles'
    if directory.is_symlink():
        raise ValueError('camera profile symlinks are not allowed')
    target = directory/(profile['revision']+'.json')
    if target.is_symlink():
        raise ValueError('camera profile symlinks are not allowed')
    if not target.exists():
        atomic_json(target,profile)
    return profile


def load_camera(root: Path, revision: str) -> dict:
    if not isinstance(revision,str) or not HASH.fullmatch(revision):
        raise ValueError('invalid camera revision')
    directory = root/'out'/'.camera-profiles'
    path = directory/(revision+'.json')
    if directory.is_symlink() or path.is_symlink():
        raise ValueError('camera profile symlinks are not allowed')
    profile = json.loads(path.read_text())
    if profile.pop('revision',None) != revision or fingerprint(profile) != revision:
        raise ValueError('camera revision checksum mismatch')
    return {**profile,'revision':revision}


def recount(root: Path, revision: str, video: Path, out: Path):
    import cv2
    from run_demo import (_normalize_frame, _harvest_track_artifacts, _export_3d_timeline,
                          _transcode_3d_footage, build_engines, finish)
    from .approach import ArrivalExtractor, TrackRecorder
    from .dashboard import annotate_intersection
    from .detection import VehicleDetector
    from .feeds import VideoFeed
    from .metrics import assess_comparison
    from .recorded_tracks import RecordedTracks

    camera = load_camera(root,revision)
    if file_hash(video) != camera['source_sha256']:
        raise ValueError('retained footage checksum changed; do not reuse its camera profile')
    cfg = config_from_dict(camera['config'])
    for a in cfg.approaches:
        a.video = str(video.resolve())
    provenance = vision_provenance(cfg.vision.model)
    provenance['code_sha256']['theiatron/recount.py'] = file_hash(Path(__file__))
    out.mkdir(parents=True,exist_ok=False)
    atomic_json(out/'camera-profile.json',camera)
    save_config(cfg,out/'config.yaml')
    preview = PreviewPublisher(out)
    feed = VideoFeed(str(video),cfg.vision.process_fps,loop=False)
    writer = None
    now = ticks = 0
    started = time.monotonic()
    try:
        detector = VehicleDetector(cfg.vision)
        extractors = {a.name:ArrivalExtractor(a,cfg.vision.min_track_age) for a in cfg.approaches}
        recorder, claimed = TrackRecorder(), set()
        dense = RecordedTracks()
        adaptive, fixed = build_engines(cfg)
        writer = cv2.VideoWriter(str(out/'footage-raw.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),1/feed.dt,(1280,720))
        if not writer.isOpened():
            raise RuntimeError('cannot encode recount video')
        print('stage 3/3: fresh inference with edited candidate count lines; no automatic recalibration',flush=True)
        # Preserve the source analysis cadence/horizon, without an extra frame
        # caused by repeated six-decimal timestamp accumulation.
        target_ticks = round(camera['duration']/feed.dt)
        for _ in range(target_ticks):
            frame,_ = feed.read()
            if frame is None:
                raise ValueError('retained footage ended before the recorded observation horizon')
            frame = _normalize_frame(frame)
            now = round(now+feed.dt,6)
            ticks += 1
            if ticks == 1 and not cv2.imwrite(str(out/'plate.jpg'),frame):
                raise RuntimeError('cannot save recount scene plate')
            detections = detector.track(frame)
            dense.update(now,detections)
            points = [(d.track_id,d.x,d.y) for d in detections]
            recorder.update(now,points)
            batch = []
            for a in cfg.approaches:
                batch.extend(extractors[a.name].update(now,points,claimed))
            adaptive.tick(now,batch)
            fixed.tick(now,batch)
            annotated = annotate_intersection(frame,detections,extractors,
                {n:adaptive.light_for(n) for n in extractors},{n:len(adaptive.queues[n].queue) for n in extractors})
            preview.publish(annotated,now,'recounting',source_name=video.name,target_s=camera['duration'],
                            arrivals={n:e.total for n,e in extractors.items()},camera_revision=revision)
            writer.write(annotated)
            if ticks % 100 == 0:
                print(f'RECOUNT {now:.1f}/{camera["duration"]:.1f}s',flush=True)
        cv2.imwrite(str(out/'calibration.png'),annotated)
    finally:
        feed.release()
        if writer is not None:
            writer.release()
    if abs(now-camera['duration']) > 1e-5:
        raise ValueError('recount cadence differs from source analysis')
    current = vision_provenance(cfg.vision.model)
    current['code_sha256']['theiatron/recount.py'] = file_hash(Path(__file__))
    if current != provenance or file_hash(video) != camera['source_sha256']:
        raise ValueError('footage, model or source code changed during inference')
    quality = {'label':'manual-candidate-unreviewed','reviewed':False,
               'note':'Edited counting geometry, not manual ground truth or a reviewed signal plan'}
    meta = {'kind':'live-video-analysis','source':str(video.resolve()),'source_sha256':camera['source_sha256'],
            'config':str((out/'config.yaml').resolve()),'model':cfg.vision.model,
            'evaluation_scope':'manual-candidate-full-pass','calibration_observe_s':0,
            'calibration_quality':quality,'camera_revision':revision,
            'parent_source_run':camera['source_run'],'parent_artifact_id':camera['source_artifact_id'],
            'runtime_provenance':provenance}
    report = finish(cfg,adaptive,fixed,now,out,meta)
    atomic_json(out/'tracks.json',_harvest_track_artifacts(extractors,recorder))
    atomic_json(out/'recorded-tracks.json',dense.export(extractors))
    video_ok,message = _transcode_3d_footage(out/'footage-raw.mp4',out/'footage.mp4')
    if not video_ok:
        raise RuntimeError(message)
    timeline_ok,message = _export_3d_timeline(out/'events.json',now,out/'config.yaml',out/'tracks.json',out/'timeline.js')
    if not timeline_ok:
        raise RuntimeError(message)
    manifest = {'source':str(video.resolve()),'source_sha256':camera['source_sha256'],
        'evaluation_duration_s':now,'evaluation_scope':meta['evaluation_scope'],'calibration':quality,
        'camera_revision':revision,'parent_source_run':camera['source_run'],
        'events':sum(e.total for e in extractors.values()),
        'results':{**assess_comparison(report['adaptive'],report['fixed']),
                   'artifact_id':report['artifact_id'],'backend':report['backend']},
        'three_d':{'ready':True,'viewer':f'viz/index.html?run=out/{out.name}'}}
    atomic_json(out/'manifest.json',manifest)
    print(f'live run complete: {out} · {ticks} fresh frames in {time.monotonic()-started:.1f}s',flush=True)
    return manifest


if __name__ == '__main__':
    parent_watchdog()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera-revision',required=True)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    recount(ROOT,args.camera_revision,args.video,args.out)
