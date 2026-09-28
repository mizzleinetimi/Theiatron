"""Offline reconstruction estimates, separate from immutable detections/counts.

Robust image-space RTS smoothing, discontinuity rejection, automatic road support
from motion + GrabCut. Smoothness is not localization accuracy. Never joins IDs
or edits the arrival stream. All returned geometry remains a candidate.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import threading

import numpy as np

from .artifacts import fingerprint
from .io import atomic_json
from .provenance import file_hash

LOCK = threading.Lock()
VERSION = 'registered-robust-rts-road-v3'
MAX_TRACKS = 1000
MAX_SAMPLES = 100_000


def _number(value):
    return type(value) in {int, float} and math.isfinite(value)


def _validate_track(track):
    """Reject corrupt observations before NumPy or clamping can conceal them."""
    if not isinstance(track, dict) or not isinstance(track.get('id'), str) or not 1 <= len(track['id']) <= 100:
        raise ValueError('dense tracks require a bounded string identity')
    for key in ('class_consistency', 'mean_confidence'):
        value = track.get(key)
        if not _number(value) or not 0 <= value <= 1:
            raise ValueError('dense track confidence must be finite in [0, 1]')
    if type(track.get('class_id')) is not int or track['class_id'] < 0:
        raise ValueError('dense tracks require a nonnegative class identity')
    approach, count = track.get('approach'), track.get('count_number')
    if approach is not None and (not isinstance(approach, str) or not 1 <= len(approach) <= 100):
        raise ValueError('invalid dense track approach')
    if (approach is None and count is not None) or (approach is not None and (type(count) is not int or count < 1)):
        raise ValueError('counted track identity must preserve its approach and number')
    samples = track.get('samples')
    if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_SAMPLES:
        raise ValueError('dense tracks require 1–100000 samples')
    previous = -math.inf
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('invalid dense observation')
        t, anchor, box, confidence = (sample.get(k) for k in ('t', 'anchor', 'box', 'confidence'))
        if not _number(t) or t < 0 or t <= previous:
            raise ValueError('dense tracks must have finite, strictly increasing observations')
        if not isinstance(anchor, list) or len(anchor) != 2 or not all(_number(v) for v in anchor):
            raise ValueError('dense anchors must have two finite coordinates')
        if not isinstance(box, list) or len(box) != 4 or not all(_number(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError('dense boxes must have four finite, correctly ordered coordinates')
        if not _number(confidence) or not 0 <= confidence <= 1:
            raise ValueError('dense confidence must be finite in [0, 1]')
        previous = t


def _validate_dense(payload):
    if not isinstance(payload, dict) or payload.get('schema_version') != 1 or payload.get('image_size') != [1280, 720]:
        raise ValueError('unsupported dense track format')
    tracks = payload.get('tracks')
    if not isinstance(tracks, list) or len(tracks) > MAX_TRACKS:
        raise ValueError('automatic refinement supports at most 1000 tracks')
    total = 0
    identities = set()
    for track in tracks:
        _validate_track(track)
        total += len(track['samples'])
        if total > MAX_SAMPLES:
            raise ValueError('automatic refinement supports at most 100000 samples')
        if track['id'] in identities:
            raise ValueError('duplicate dense track identity')
        identities.add(track['id'])


def _rts(times, positions, noise, acceleration):
    """Constant-velocity Kalman forward pass and Rauch–Tung–Striebel backpass."""
    n=len(times); filtered=[]; covariances=[]; predictions=[]; predicted_cov=[]; transitions=[]
    state=np.r_[positions[0], [0.,0.]]
    covariance=np.diag([noise[0]**2]*2+[acceleration**2]*2)
    obs=np.eye(4)[:2]
    for i in range(n):
        dt=times[i]-times[i-1] if i else 0.
        transition=np.eye(4);transition[0,2]=transition[1,3]=dt
        drive=np.array([[dt*dt/2,0],[0,dt*dt/2],[dt,0],[0,dt]])
        predicted=transition@state
        pcov=transition@covariance@transition.T+(acceleration**2)*(drive@drive.T)
        innovation=positions[i]-obs@predicted
        residual=obs@pcov@obs.T+np.eye(2)*noise[i]**2
        gain=np.linalg.solve(residual,obs@pcov).T
        state=predicted+gain@innovation
        # Joseph form maintains positive semidefinite covariance.
        left=np.eye(4)-gain@obs
        covariance=left@pcov@left.T+noise[i]**2*gain@gain.T
        filtered.append(state.copy());covariances.append(covariance.copy())
        predictions.append(predicted);predicted_cov.append(pcov);transitions.append(transition)
    smoothed=np.array(filtered)
    for i in range(n-2,-1,-1):
        gain=np.linalg.solve(predicted_cov[i+1],transitions[i+1]@covariances[i]).T
        smoothed[i]=filtered[i]+gain@(smoothed[i+1]-predictions[i+1])
    return smoothed[:,:2]


def filter_track(track):
    _validate_track(track)
    samples=track['samples']
    times=np.array([s['t'] for s in samples],dtype=float)
    raw=np.array([s['anchor'] for s in samples],dtype=float)
    sizes=np.array([max(8.,s['box'][3]-s['box'][1]) for s in samples])
    confidence=np.array([max(.1,min(1.,s['confidence'])) for s in samples])
    if not len(times) or not np.isfinite(raw).all() or not np.isfinite(times).all() or np.any(np.diff(times)<=0):
        raise ValueError('dense tracks must have finite, strictly increasing observations')
    clean=raw.copy(); outliers=np.zeros(len(times),dtype=bool)
    # Hampel-like local residual test against neighbours, scaled to object size.
    # Reject isolated excursions; sustained displacement becomes a segment break.
    for i in range(1,len(times)-1):
        if times[i+1]-times[i-1]>.61 or samples[i].get('break_before') or samples[i+1].get('break_before'): continue
        u=(times[i]-times[i-1])/(times[i+1]-times[i-1])
        interpolation=raw[i-1]*(1-u)+raw[i+1]*u
        excursion=np.linalg.norm(raw[i]-interpolation)
        neighbours=np.linalg.norm(raw[i+1]-raw[i-1])
        if excursion>max(10.,sizes[i]*.22) and excursion>neighbours*1.5:
            clean[i]=interpolation;outliers[i]=True
    cuts=[0]
    for i in range(1,len(times)):
        dt=times[i]-times[i-1]
        # Conservative discontinuity gate in pixels/object height, not m/s.
        jump=np.linalg.norm(clean[i]-clean[i-1])
        if samples[i].get('break_before') or dt>.61 or jump>max(35.,min(sizes[i],sizes[i-1])*max(.7,dt*3)):
            cuts.append(i)
    cuts.append(len(times)); filtered=clean.copy()
    segments=[]
    for start,end in zip(cuts,cuts[1:]):
        if end-start>=4:
            noise=np.maximum(2.,sizes[start:end]*.07)/np.sqrt(confidence[start:end])
            noise[outliers[start:end]]*=8
            filtered[start:end]=_rts(times[start:end],clean[start:end],noise,max(8.,float(np.median(sizes[start:end]))*.32))
        segments.append((start,end))
    # Do not position-lock short low-displacement windows: slow moving traffic
    # is observationally compatible with noise and snapping creates plateaus.
    # Display heading can be held at low speed without altering recorded motion.
    locked=0
    before=[];after=[]
    for start,end in segments:
        if end-start>=5:
            before.extend(np.linalg.norm(np.diff(raw[start:end],n=2,axis=0),axis=1).tolist())
            after.extend(np.linalg.norm(np.diff(filtered[start:end],n=2,axis=0),axis=1).tolist())
    return {'id':'track:'+track['id'], 'a':track['approach'],'n':track['count_number'],
        'class_id':track['class_id'],'class_consistency':track['class_consistency'],
        'mean_confidence':track['mean_confidence'],
        'pts':[[float(t),round(float(x),5),round(float(y),5)] for t,(x,y) in zip(times,filtered)],
        'raw_pts':[[float(t),float(x),float(y)] for t,(x,y) in zip(times,raw)],
        'breaks':[float(times[i]) for i in cuts[1:-1]],
        'outlier_times':times[outliers].tolist(),
        'diagnostics':{'isolated_outliers':int(outliers.sum()),'breaks':len(cuts)-2,'stationary_samples':locked,
            'raw_second_difference_px':before,'filtered_second_difference_px':after}}


def road_proposal(frame, dense, refined):
    """Automatic appearance proposal seeded by traffic support, not a road classifier."""
    import cv2
    h,w=frame.shape[:2]
    if (w,h)!=(1280,720): frame=cv2.resize(frame,(1280,720));h,w=720,1280
    image=cv2.resize(frame,(640,360)); support=np.zeros((360,640),np.uint8)
    ids={t['id']:t for t in dense['tracks']}; moving=0
    for track in refined:
        p=np.array(track['pts'])
        if len(p)<12 or np.linalg.norm(p[-1,1:]-p[0,1:])<45: continue
        moving+=1; native=ids[track['id'][len('track:'):]]
        widths=[s['box'][2]-s['box'][0] for s in native['samples']]
        width=int(np.clip(np.median(widths)*.33,8,38))
        breaks=set(track['breaks']); segment=[]
        for t,x,y in p:
            if t in breaks:
                if len(segment)>1:cv2.polylines(support,[np.array(segment,np.int32)],False,255,width)
                segment=[]
            segment.append([int(x/2),int(y/2)])
        if len(segment)>1: cv2.polylines(support,[np.array(segment,np.int32)],False,255,width)
    if moving<4 or np.count_nonzero(support)<1500:
        return None,{'status':'insufficient-motion','moving_tracks':moving}
    envelope=cv2.dilate(support,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(61,61)))
    # Exclude detections present in the reference plate from sure-road seeds.
    occupied=np.zeros_like(support)
    for track in dense['tracks']:
        if track['samples'] and track['samples'][0]['t']<.21:
            x1,y1,x2,y2=track['samples'][0]['box']
            cv2.rectangle(occupied,(int(x1/2)-2,int(y1/2)-2),(int(x2/2)+2,int(y2/2)+2),255,-1)
    lab=cv2.cvtColor(image,cv2.COLOR_BGR2LAB)
    candidates=(support>0)&(occupied==0)
    samples=lab[candidates].astype(float)
    if len(samples)<300:return None,{'status':'insufficient-visible-road','moving_tracks':moving}
    median=np.median(samples,axis=0)
    # Road seeds favour the central appearance distribution; do not force every
    # tracker point (a box may touch a pedestrian, vehicle or pavement) to road.
    distance=np.sqrt(np.sum(((lab.astype(float)-median)/np.array([40,13,13]))**2,axis=2))
    mask=np.full((360,640),cv2.GC_BGD,np.uint8)
    mask[envelope>0]=cv2.GC_PR_BGD
    mask[(support>0)&(distance<1.8)]=cv2.GC_PR_FGD
    sure=candidates&(distance<.9);mask[sure]=cv2.GC_FGD
    if np.count_nonzero(sure)<100:return None,{'status':'ambiguous-road-appearance','moving_tracks':moving}
    cv2.setRNGSeed(1701)
    cv2.grabCut(image,mask,None,np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),3,cv2.GC_INIT_WITH_MASK)
    road=np.uint8((mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD))*255
    # Traffic traversing an occluder supports ground behind it. The first-frame
    # pole/vehicle silhouette must not become a permanent notch in the road.
    road[support > 0] = 255
    road=cv2.morphologyEx(road,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(35,35)))
    road=cv2.morphologyEx(road,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(13,13)))
    road=np.uint8(cv2.GaussianBlur(road,(17,17),0)>127)*255
    contours,_=cv2.findContours(road,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not contours:return None,{'status':'no-road-component','moving_tracks':moving}
    best=max(contours,key=cv2.contourArea)
    filled=np.zeros_like(road);cv2.drawContours(filled,[best],-1,255,-1)
    coverage=float(np.count_nonzero((filled>0)&(support>0))/max(1,np.count_nonzero(support)))
    fraction=float(np.count_nonzero(filled)/filled.size)
    if coverage<.65 or not .03<fraction<.75:
        return None,{'status':'road-proposal-rejected','motion_support_coverage':coverage,'area_fraction':fraction,'moving_tracks':moving}
    epsilon=3.5
    polygon=cv2.approxPolyDP(best,epsilon,True).reshape(-1,2)
    while len(polygon)>95:
        epsilon*=1.2;polygon=cv2.approxPolyDP(best,epsilon,True).reshape(-1,2)
    polygon=np.clip(polygon*2,[0,0],[1279,719]).tolist()
    return polygon,{'status':'automatic-candidate','method':'motion-seeded-GrabCut','moving_tracks':moving,
        'motion_support_coverage':coverage,'area_fraction':fraction,
        'boundary_regularization':'70px closing, 26px opening, 7px contour tolerance in reference image; occluded ground is inferred',
        'note':'Coverage measures seed support, not road-boundary accuracy. Occluded edges are inferred; no semantic segmentation or lane survey.'}


def road_background(video, registration, payload, plate):
    """Vehicle-masked temporal appearance in the reference plane, for CV only.

    This is not shown as a recorded frame and never changes calibration anchors.
    Memory is bounded to 21 half-resolution samples; unseen pixels use the plate.
    """
    import cv2
    import warnings
    frames=[f for f in registration['frames'] if f.get('H') is not None]
    indices=np.unique(np.linspace(0,len(frames)-1,min(21,len(frames))).astype(int))
    boxes={}
    for track in payload['tracks']:
        for sample in track['samples']:boxes.setdefault(sample['t'],[]).append(sample['box'])
    cap=cv2.VideoCapture(str(video)); layers=[]
    try:
        for index in indices:
            row=frames[index]
            cap.set(cv2.CAP_PROP_POS_FRAMES,row['frame_index'])
            ok,frame=cap.read()
            if not ok:continue
            frame=cv2.resize(frame,(640,360),interpolation=cv2.INTER_AREA)
            visible=np.full((360,640),255,np.uint8)
            for box in boxes.get(row['t'],[]):
                x1,y1,x2,y2=np.array(box)/2
                cv2.rectangle(visible,(int(x1)-3,int(y1)-3),(int(x2)+3,int(y2)+3),0,-1)
            h=np.diag([.5,.5,1])@np.array(row['H'])@np.diag([2,2,1])
            image=cv2.warpPerspective(frame,h,(640,360)).astype(np.float32)
            valid=cv2.warpPerspective(visible,h,(640,360),flags=cv2.INTER_NEAREST)
            image[valid==0]=np.nan;layers.append(image)
    finally:cap.release()
    if not layers:return plate,{'samples':0,'status':'reference-frame-only'}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        background=np.nanmedian(np.stack(layers),axis=0)
    known=np.isfinite(background).all(axis=2)
    fallback=cv2.resize(plate,(640,360),interpolation=cv2.INTER_AREA)
    background[~known]=fallback[~known]
    return cv2.resize(background.astype(np.uint8),(1280,720)),{
        'samples':len(layers),'status':'vehicle-masked-registered-temporal-median',
        'visible_reference_fraction':float(known.mean()),
        'note':'Appearance estimate for road proposal only; not a captured evidence frame.'}


def perspective_proposal(dense, road):
    """Estimate an image horizon from within-track relative box-height changes.

    The scale gradient is observable only if consistent vehicles move in depth.
    Car turning, truncation and occlusion break the model; fail closed rather
    than project a horizon through the road or present weak fits as calibrated.
    """
    rows=[]; groups=[]
    for track in dense['tracks']:
        if track['class_id']!=2 or track['class_consistency']<.8:continue
        samples=[s for s in track['samples'] if s['confidence']>.65 and s['box'][0]>2 and s['box'][2]<1277 and s['box'][3]<717]
        if len(samples)<15:continue
        xy=np.array([s['anchor'] for s in samples])/np.array([1280,720])
        heights=np.array([s['box'][3]-s['box'][1] for s in samples])
        if np.ptp(xy[:,1])<.05 or np.percentile(heights,90)/np.percentile(heights,10)<1.3:continue
        ratio=heights/np.median(heights);centre=np.median(xy,axis=0)
        block=np.c_[xy-ratio[:,None]*centre,1-ratio]
        rows.extend(block[::3]);groups.extend([track['id']]*len(block[::3]))
    report={'status':'reference-needed','metric_scale':'unobservable-without-reference',
            'supporting_tracks':len(set(groups)), 'note':'A single uncalibrated view cannot establish absolute metres. No high-precision claim.'}
    if len(set(groups))<5:return None,{**report,'reason':'Too few consistent vehicles with depth/size variation.'}
    a=np.array(rows);weights=np.ones(len(a))
    if np.linalg.matrix_rank(a[:, :2]) < 2 or np.linalg.cond(a[:, :2]) > 1000:
        return None,{**report,'reason':'Vehicle-size cues do not constrain a stable two-dimensional horizon.'}
    for _ in range(8):
        fitted=np.linalg.lstsq(a[:,:2]*np.sqrt(weights[:,None]),-a[:,2]*np.sqrt(weights),rcond=None)[0]
        residual=a[:,:2]@fitted+a[:,2]
        sigma=max(.025,float(np.median(np.abs(residual)))*1.4826)
        weights=np.minimum(1.,1.5*sigma/np.maximum(np.abs(residual),1e-8))
    horizon=np.r_[fitted,1.]
    values=np.c_[np.array(road)/[1280,720],np.ones(len(road))]@horizon
    if np.median(values)<0:horizon=-horizon;values=-values
    report.update(relative_size_residual_median=float(np.median(np.abs(residual))),horizon=horizon.tolist())
    if values.min()<.08 or values.max()/values.min()>12 or np.median(np.abs(residual))>.15:
        return None,{**report,'reason':'Vehicle-size cues imply an unstable horizon or disagree with the visible road. A measured ground reference is needed.'}
    # Rectify projective depth up to an unknown affine transform. Metric aspect,
    # camera intrinsics and absolute scale remain unresolved, explicitly.
    return horizon,{**report,'status':'projective-candidate','reason':'Projective depth estimated; metric aspect and scale are still unresolved.'}


def temporal_road_evidence(video, registration, payload, road):
    """Sample native frames, mask detections, then map only line endpoints.

    Never use a composite image or a rejected/missing registration as geometric
    evidence. No interpolation or new registration method is introduced here.
    """
    import cv2
    from .ground_plane import road_segments
    rows=[r for r in registration['frames'] if r.get('status') in {'accepted','reference'} and r.get('H') is not None]
    selected=np.unique(np.linspace(0,len(rows)-1,min(12,len(rows))).astype(int)) if rows else []
    boxes={}
    for track in payload['tracks']:
        for sample in track['samples']:boxes.setdefault(round(sample['t'],6),[]).append(sample['box'])
    cap=cv2.VideoCapture(str(video));frames=[];failed=[]
    try:
        for index in selected:
            row=rows[index]
            cap.set(cv2.CAP_PROP_POS_FRAMES,row['frame_index'])
            ok,frame=cap.read()
            # Refuse a decoder that returns a different frame than requested.
            if not ok or abs(cap.get(cv2.CAP_PROP_POS_FRAMES)-(row['frame_index']+1))>.5:
                failed.append(row['frame_index']);continue
            frame=cv2.resize(frame,(1280,720),interpolation=cv2.INTER_AREA)
            lines=road_segments(frame,road,boxes.get(round(row['t'],6),[]),row['H'])
            frames.append({'frame_index':row['frame_index'],'t':row['t'],'lines':lines.tolist()})
    finally:cap.release()
    return frames,{'requested_frames':len(selected),'decoded_frames':len(frames),
                   'failed_frame_indices':failed,'sampling':'up to 12 exact native frames across accepted registrations',
                   'registration_revision':registration.get('revision')}


def temporal_ground_proposal(video, registration, payload, current, road):
    from .ground_plane import estimate_temporal_road_camera, calibration_from_camera
    frames,capture=temporal_road_evidence(video,registration,payload,road)
    h,quality=estimate_temporal_road_camera(frames,road)
    quality['capture']=capture
    if h is None:return None,quality
    try:candidate,details=calibration_from_camera(h,current,road)
    except ValueError as exc:return None,{**quality,'status':'projection-review-needed','reason':str(exc)}
    return candidate,{**quality,**details}


def compensate_tracks(payload, registration):
    """Only accepted camera states enter the reference plane; preserve raw evidence."""
    from .camera_registration import registration_at, transform_point
    compensated = deepcopy(payload)
    compensated['tracks'] = []
    omitted = 0
    for track in payload['tracks']:
        output = deepcopy(track); output['samples'] = []; gap = False
        for sample in track['samples']:
            state = registration_at(registration, sample['t'])
            point = transform_point(state['H'], sample['anchor']) if state else None
            box = sample['box']
            corners = [transform_point(state['H'], xy) for xy in
                       ([box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]])] if state else []
            if point is None or not corners or any(p is None for p in corners) or any(
                abs(p[0]) > 2560 or abs(p[1]) > 1440 for p in [point, *corners]):
                omitted += 1; gap = True; continue
            native = deepcopy(sample)
            native['anchor'] = point
            native['box'] = [min(p[0] for p in corners), min(p[1] for p in corners),
                             max(p[0] for p in corners), max(p[1] for p in corners)]
            native['break_before'] = gap; gap = False
            output['samples'].append(native)
        if output['samples']: compensated['tracks'].append(output)
    return compensated, omitted


def build(root: Path, run_id: str, binding: dict, video: Path | None = None, progress=None):
    from .reconstruction import source, _safe, validate
    current=source(root,run_id)
    if current['binding']!=binding:raise ValueError('source changed; reload before automatic refinement')
    path=_safe(root,run_id,'recorded-tracks.json')
    if not path.is_file():raise ValueError('dense observations required; recount this local clip first')
    from . import camera_registration
    from . import ground_plane
    code_sha = file_hash(Path(__file__))
    camera_code = file_hash(Path(camera_registration.__file__))
    ground_code = file_hash(Path(ground_plane.__file__))
    if video is not None:
        video = Path(video)
        uploads = (root/'out'/'uploads').resolve()
        if not video.resolve().is_relative_to(uploads) or any(p.is_symlink() for p in [video, *video.parents] if p != root.parent):
            raise ValueError('refinement requires retained local upload footage without symlinks')
        if file_hash(video) != binding['source_sha256']:
            raise ValueError('retained footage checksum changed')
    identity=fingerprint({'binding':binding,'calibration':current['calibration'],
        'calibration_revision':current['revision'],'version':VERSION,'code':code_sha,
        'camera_code':camera_code,'ground_code':ground_code,'retained_video':video is not None})
    directory=root/'out'/'.reconstructions'/current['identity']
    target=directory/(identity+'.refinement.json')
    if target.is_symlink() or (directory/'automatic.json').is_symlink():raise ValueError('refinement symlinks are not allowed')
    if target.is_file():
        result=json.loads(target.read_text())
        if result.get('binding') != binding or fingerprint({k:v for k,v in result.items() if k!='revision'})!=result.get('revision'):raise ValueError('refinement checksum mismatch')
        atomic_json(directory/'automatic.json',result);return result
    import cv2
    payload=json.loads(path.read_text());_validate_dense(payload)
    registration = None; omitted = 0
    camera_status = 'unavailable-no-retained-video'
    if video is not None:
        # Historical auto-calibration plates are composites of moving views;
        # their coordinates do not equal the first analysed frame.
        if current['plate_reference_supported']:
            cadence = current['video_offset_s']
            cache_key = fingerprint({'binding':binding,'camera_code':camera_code,'cadence':cadence})
            camera_path = directory/(cache_key+'.camera.json')
            if camera_path.is_symlink(): raise ValueError('camera cache symlinks are not allowed')
            if camera_path.is_file():
                registration = json.loads(camera_path.read_text())
                if fingerprint({k:v for k,v in registration.items() if k!='revision'}) != registration.get('revision'):
                    raise ValueError('camera cache checksum mismatch')
                if registration.get('cache_identity') != cache_key: raise ValueError('camera cache source identity mismatch')
                if progress: progress('Camera registration loaded from source-bound cache')
            else:
                registration = camera_registration.register_camera(video, payload, process_fps=1/cadence,
                    progress=(lambda done,total: progress(f'Camera registration {done}/{total} frames')) if progress else None)
                registration['cache_identity'] = cache_key
                for frame in registration['frames']:
                    frame['inverse_H'] = np.linalg.inv(frame['H']).tolist() if frame.get('H') is not None else None
                registration['revision'] = fingerprint(registration)
                if file_hash(video) != binding['source_sha256']: raise ValueError('retained footage changed during registration')
                atomic_json(camera_path, registration)
            camera_status = 'background-registered-estimate'
        else:
            camera_status = 'unsupported-composite-reference-recount-required'
    working, omitted = compensate_tracks(payload,registration) if registration else (payload,0)
    if registration and not working['tracks']: raise ValueError('No observations have usable camera registration')
    if progress: progress('Filtering trajectories and proposing the road surface')
    processed=[filter_track(t) for t in working['tracks']]
    originals = {t['id']: t for t in payload['tracks']}
    for track in processed:
        track['raw_pts'] = [[s['t'], *s['anchor']] for s in originals[track['id'][6:]]['samples']]
        track['coordinate_frame'] = 'reference-image' if registration else 'source-image'
    plate=cv2.imread(str(_safe(root,run_id,'plate.jpg')))
    if plate is None:raise ValueError('reference plate could not be decoded')
    background,background_quality=road_background(video,registration,payload,plate) if registration else (plate,{'status':'reference-frame-only'})
    polygon,road_quality=road_proposal(background,working,processed)
    road_quality['background']=background_quality
    candidate=deepcopy(current['calibration'])
    if polygon:
        candidate['road']=polygon;candidate['label']='Automatic road surface · draft projection'
        try:validate(candidate)
        except ValueError as exc:
            polygon=None;road_quality['status']='projection-review-needed';road_quality['reason']=str(exc)
    horizon,perspective=perspective_proposal(working,polygon or candidate['road']) if (polygon or candidate['road']) else (None,{'status':'reference-needed','reason':'No usable road surface.'})
    if progress:progress('Estimating ground-plane perspective from static scene directions')
    first_boxes=[s['box'] for t in payload['tracks'] for s in t['samples'] if abs(s['t']-current['video_offset_s'])<1e-6]
    ground,ground_quality=ground_plane.propose(plate,current['calibration'],polygon or candidate['road'],first_boxes) if (polygon or candidate['road']) else (None,{'status':'no-road-surface'})
    if ground is None and registration and video is not None and (polygon or candidate['road']):
        if progress:progress('Checking repeated road markings across registered native frames')
        single_frame=ground_quality
        ground,ground_quality=temporal_ground_proposal(video,registration,payload,current['calibration'],polygon or candidate['road'])
        ground_quality['single_frame']=single_frame
    # Keep the operator's known projection when metric rectification is not
    # identifiable. Do not silently turn a size-based projective estimate into m.
    refined={'counted':[],'extras':[]};before=[];after=[];outliers=breaks=locked=0
    for p in processed:
        d=p.pop('diagnostics');before+=d['raw_second_difference_px'];after+=d['filtered_second_difference_px']
        outliers+=d['isolated_outliers'];breaks+=d['breaks'];locked+=d['stationary_samples']
        refined['counted' if p['a'] is not None else 'extras'].append(p)
    result={'binding':binding,'calibration_revision':current['revision'],'algorithm':VERSION,'code_sha256':code_sha,
        'input_calibration_sha256':fingerprint(current['calibration']),
        'camera_code_sha256':camera_code, 'camera_status':camera_status, 'camera_registration':registration,
        'ground_code_sha256':ground_code,'ground_projection':ground,'ground_quality':ground_quality,
        'tracks':refined,'road':polygon,'road_quality':road_quality,'perspective':perspective,
        'calibration':candidate if polygon else None,
        'diagnostics':{'samples':sum(len(t['samples']) for t in payload['tracks']),
            'isolated_outliers':outliers,'segment_breaks':breaks,'stationary_samples':locked,
            'camera_rejected_observations':omitted,
            'median_raw_second_difference_px':float(np.median(before)) if before else None,
            'median_filtered_second_difference_px':float(np.median(after)) if after else None,
            'metric':'image-space smoothness proxy, not accuracy or field performance'},
        'status':'automatic-estimates-unvalidated','metric_accuracy_validated':False}
    latest = source(root,run_id)
    if file_hash(Path(__file__)) != code_sha or file_hash(Path(camera_registration.__file__)) != camera_code or file_hash(Path(ground_plane.__file__)) != ground_code:
        raise ValueError('refinement code changed during computation; rerun')
    if video is not None and file_hash(video) != binding['source_sha256']:
        raise ValueError('retained footage changed during refinement; rerun')
    if latest['binding'] != binding or latest['revision'] != current['revision'] or latest['calibration'] != current['calibration']:
        raise ValueError('source or calibration changed during refinement; rerun')
    result['revision']=fingerprint(result)
    atomic_json(target,result);atomic_json(directory/'automatic.json',result)
    return result


if __name__ == '__main__':
    import argparse
    from .preview import parent_watchdog
    from .reconstruction import source
    parent_watchdog()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--video', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with LOCK:
        result = build(root,args.run,source(root,args.run)['binding'],args.video,
                       progress=lambda message: print(message,flush=True))
    print('Refinement ready: '+result['revision'],flush=True)
