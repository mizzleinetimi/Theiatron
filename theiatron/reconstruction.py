"""Source-bound visual reconstruction drafts. Never traffic-impact evidence.

Tracks are detector bottom-centre anchors, not surveyed vehicle centres. The
four-point planar mapping, road trace and nominal dimensions remain assumptions
until independently checked. A draft cannot mark itself as reviewed.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re

from .artifacts import fingerprint, load_artifact
from .io import atomic_json
from .provenance import file_hash

RUN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,120}')

# Manually traced against IMG_0635's plate, NOT a general fallback. Binding to
# the source bytes prevents the first demo's junction leaking into new footage.
IMG_0635_SHA = 'd589e58a8ab46839b81c1870d43c8b254def8b3ab9d9301384f52cd85497ffa5'
IMG_0635_ROAD = [[0,511],[209,448],[245,416],[214,338],[282,332],
    [482,371],[541,373],[564,389],[642,382],[686,344],[789,316],
    [883,303],[973,286],[1050,272],[1085,283],[978,326],[891,359],
    [818,386],[775,411],[812,446],[974,496],[1279,610],[1279,719],
    [851,719],[792,663],[560,613],[428,719],[0,719]]


def _safe(root: Path, run_id: str, name: str) -> Path:
    if not isinstance(run_id, str) or not RUN.fullmatch(run_id):
        raise ValueError('invalid reconstruction source')
    path = root/'out'/run_id/name
    if any(p.is_symlink() for p in [root/'out', path.parent, path]):
        raise ValueError('reconstruction source symlinks are not allowed')
    return path


def default_calibration(source_hash: str) -> dict:
    known = source_hash == IMG_0635_SHA
    # An unknown camera has no justified vanishing point. Keep the provisional
    # display a uniform image-plane similarity, not an invented trapezoid whose
    # horizon can reject an otherwise valid road outline near the image edge.
    return {'anchors': [[280,398],[1130,535],[1120,682],[125,525]] if known else
            [[384,360],[896,360],[896,648],[384,648]],
            'width_m': 50.0 if known else 30.0, 'depth_m': 12.0 if known else 16.875,
            'road': deepcopy(IMG_0635_ROAD) if known else [],
            'label': 'IMG_0635 · hand-traced draft' if known else 'Unrectified image-plane preview · calibration required'}


def _points(value, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f'expected {minimum}–{maximum} camera points')
    for point in value:
        if not isinstance(point,list) or len(point) != 2 or any(
            type(v) not in {float,int} or not math.isfinite(v) or not 0 <= v <= bound
            for v,bound in zip(point,(1279,719))):
            raise ValueError('points must be finite inside the 1280×720 frame')


def validate(calibration: dict) -> dict:
    if not isinstance(calibration,dict) or set(calibration) != {'anchors','width_m','depth_m','road','label'}:
        raise ValueError('edit only the four anchors, dimensions, road outline and label')
    _points(calibration['anchors'],4,4)
    _points(calibration['road'],3,100)
    for key in ('width_m','depth_m'):
        v = calibration[key]
        if type(v) not in {float,int} or not math.isfinite(v) or not 2 <= v <= 150:
            raise ValueError('assumed dimensions must be 2–150 metres')
    if not isinstance(calibration['label'],str) or not 1 <= len(calibration['label']) <= 120:
        raise ValueError('provide a label of 1–120 characters')
    def cross(a,b,c):
        return (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
    quad = calibration['anchors']
    turns = [cross(quad[i],quad[(i+1)%4],quad[(i+2)%4]) for i in range(4)]
    if not (all(v>100 for v in turns) or all(v<-100 for v in turns)):
        raise ValueError('anchors must form a convex quadrilateral in perimeter order')
    road = calibration['road']
    # Proper intersections and collinear overlapping edges are invalid too.
    def intersects(a,b,c,d):
        def orient(p,q,r): return cross(p,q,r)
        def on(p,q,r):
            return min(p[0],q[0])<=r[0]<=max(p[0],q[0]) and min(p[1],q[1])<=r[1]<=max(p[1],q[1])
        u,v,w,x = orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
        return (u*v<0 and w*x<0) or (u==0 and on(a,b,c)) or (v==0 and on(a,b,d)) or (w==0 and on(c,d,a)) or (x==0 and on(c,d,b))
    for i,a in enumerate(road):
        b = road[(i+1)%len(road)]
        if math.dist(a,b)<1:
            raise ValueError('road outline has duplicate adjacent vertices')
        for j in range(i+2,len(road)):
            if i==0 and j==len(road)-1:
                continue
            if intersects(a,b,road[j],road[(j+1)%len(road)]):
                raise ValueError('road outline must not cross itself')
    area = abs(sum(road[i][0]*road[(i+1)%len(road)][1]-road[(i+1)%len(road)][0]*road[i][1] for i in range(len(road))))/2
    if area < 100:
        raise ValueError('road outline is too small')
    # Apply the same bounded planar mapping as the viewer. The HTTP boundary
    # must reject horizon-crossing drafts even when browser validation is bypassed.
    import numpy as np
    width,depth=calibration['width_m'],calibration['depth_m']
    targets=[[-width/2,-depth/2],[width/2,-depth/2],[width/2,depth/2],[-width/2,depth/2]]
    matrix,rhs=[],[]
    for (px,py),(u,v) in zip(quad,targets):
        x,y=px/1280,py/720
        matrix.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]])
        rhs.extend([u,v])
    try:
        h=np.r_[np.linalg.solve(matrix,rhs),1.]
    except np.linalg.LinAlgError as exc:
        raise ValueError('degenerate ground calibration') from exc
    centre=np.mean(quad,axis=0)/[1280,720]
    if h[6]*centre[0]+h[7]*centre[1]+h[8]<0:h=-h
    for px,py in road:
        x,y=px/1280,py/720
        w=h[6]*x+h[7]*y+h[8]
        if w<1e-5 or not math.isfinite(w):
            raise ValueError('road crosses the calibration horizon')
        p=((h[0]*x+h[1]*y+h[2])/w,(h[3]*x+h[4]*y+h[5])/w)
        if not all(math.isfinite(v) for v in p) or math.hypot(*p)>=500:
            raise ValueError('road projection exceeds the supported 500 m radius')
    return deepcopy(calibration)


def source(root: Path, run_id: str) -> dict:
    visual_path = _safe(root,run_id,'reconstruction-source.json')
    visual = visual_path.exists()
    if visual:
        from .visual_capture import load_source
        artifact = load_source(visual_path.parent)
        meta = artifact
        offset = artifact['cadence_s']
        reference_ok = True
    else:
        artifact = load_artifact(_safe(root,run_id,'simulation.json'))
        meta = artifact['source_meta']
        offset = artifact['steps'][0]['t'] if artifact['steps'] else 0
        manifest_path = _safe(root,run_id,'manifest.json')
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        reference_ok = bool(meta.get('camera_revision')) or manifest.get('three_d',{}).get('plate_mode') == 'first-processed-frame'
    if meta.get('kind') not in {'live-video-analysis','recorded-perception'} or not re.fullmatch(r'[0-9a-f]{64}',meta.get('source_sha256','')):
        raise ValueError('choose a fingerprinted video analysis, not a simulation')
    path = _safe(root,run_id,'recorded-tracks.json')
    dense = path.exists()
    if dense:
        payload = json.loads(path.read_text())
        if payload.get('schema_version') != 1 or payload.get('image_size') != [1280,720]:
            raise ValueError('unsupported dense track format')
        if visual and any(t.get('approach') is not None or t.get('count_number') is not None for t in payload['tracks']):
            raise ValueError('visual-only observations must not contain arrival counts')
        raw = {'counted':[], 'extras':[]}
        for track in payload['tracks']:
            counted = track['approach'] is not None
            raw['counted' if counted else 'extras'].append({
                'id':'track:'+track['id'], 'a':track['approach'], 'n':track['count_number'],
                'class_id':track['class_id'], 'class_consistency':track['class_consistency'],
                'mean_confidence':track['mean_confidence'],
                'pts':[[s['t'],*s['anchor']] for s in track['samples']]})
    else:
        path = _safe(root,run_id,'tracks.json')
        raw = json.loads(path.read_text())
        if not isinstance(raw,dict) or not all(isinstance(raw.get(k),list) for k in ('counted','extras')):
            raise ValueError('source has no recorded tracks')
    binding = {'source_run':run_id, 'source_sha256':meta['source_sha256'],
               'source_artifact_id':artifact['artifact_id'], 'tracks_sha256':file_hash(path),
               'plate_sha256':file_hash(_safe(root,run_id,'plate.jpg'))}
    identity = fingerprint(binding)
    directory = root/'out'/'.reconstructions'/identity
    if any(p.is_symlink() for p in [directory.parent,directory,directory/'latest.json']):
        raise ValueError('reconstruction draft symlinks are not allowed')
    saved = None
    if (directory/'latest.json').is_file():
        saved = json.loads((directory/'latest.json').read_text())
        revision = saved.get('revision')
        if saved.get('binding') != binding or fingerprint({k:v for k,v in saved.items() if k!='revision'}) != revision:
            raise ValueError('reconstruction draft checksum mismatch')
        validate(saved['calibration'])
    automatic = None
    auto_path = directory/'automatic.json'
    if auto_path.is_symlink():
        raise ValueError('refinement symlinks are not allowed')
    if auto_path.is_file():
        automatic = json.loads(auto_path.read_text())
        if automatic.get('binding') != binding or fingerprint({k:v for k,v in automatic.items() if k!='revision'}) != automatic.get('revision'):
            raise ValueError('automatic refinement checksum mismatch')
        automatic['stale'] = (automatic.get('code_sha256') != file_hash(Path(__file__).with_name('refinement.py'))
            or automatic.get('camera_code_sha256') != file_hash(Path(__file__).with_name('camera_registration.py'))
            or automatic.get('ground_code_sha256') != file_hash(Path(__file__).with_name('ground_plane.py'))
            or automatic.get('input_calibration_sha256') != fingerprint(saved['calibration'] if saved else default_calibration(meta['source_sha256']))
            or automatic.get('calibration_revision') != (saved['revision'] if saved else None))
    return {'binding':binding, 'identity':identity, 'tracks':raw,
            'duration':artifact['duration'], 'image_size':[1280,720],
            'source_name':Path(meta.get('source','video')).name,
            # Exported MP4 starts at the first analysed frame. Track clock starts
            # one detector tick later. Actual saved cadence is in engine steps.
            'video_offset_s':offset, 'plate_reference_supported':reference_ok,
            'counting_available':not visual,
            'source_kind':'recorded-perception' if visual else 'live-video-analysis',
            'default_projection_kind':'manual-draft' if saved or meta['source_sha256']==IMG_0635_SHA else 'unrectified-image-plane',
            'calibration':saved['calibration'] if saved else default_calibration(meta['source_sha256']),
            'revision':saved['revision'] if saved else None,
            'assistance':deepcopy(saved.get('assistance')) if saved else None,
            'refinement':automatic,
            'status':'draft-unvalidated', 'track_anchor':'detector-bottom-centre',
            'track_sampling':'dense-processed-frames' if dense else 'legacy-thinned',
            'vehicle_dimensions':'class-nominal-unmeasured' if dense else 'generic-unmeasured',
            'metric_accuracy_validated':False}


def live_geometry(root: Path, run_id: str) -> dict:
    """Geometry/camera estimates only. Never sends recorded vehicle trajectories.

    Camera registration is reusable only for the same source bytes AND exact
    native frame index. An absent/rejected frame must not inherit its neighbour.
    """
    current = source(root, run_id)
    refinement = current.get('refinement')
    if not refinement or refinement.get('stale'):
        raise ValueError('Fresh source-specific ground estimates are required; refine this clip in the recorded studio first')
    assistance = current.get('assistance')
    calibration = deepcopy(current['calibration'])
    projection_kind = 'automatic-estimate'
    geometry_revision = refinement['revision']
    if assistance is not None:
        from . import assisted_geometry, ground_plane
        # Only an explicit server-fitted assisted save qualifies. A manual
        # four-anchor draft (or a browser preview) is not equivalent evidence.
        if (not current.get('revision') or not isinstance(assistance, dict)
                or assistance.get('method') != assisted_geometry.METHOD
                or assistance.get('code_sha256') != file_hash(Path(assisted_geometry.__file__))
                or assistance.get('ground_code_sha256') != file_hash(Path(ground_plane.__file__))):
            raise ValueError('Saved assisted perspective needs a fresh guided check and explicit save in Review road')
        # Reproduce the saved fit rather than accepting an approval label.
        reproduced, quality = assisted_geometry.propose(assistance.get('lines'), assistance.get('input_calibration'))
        if reproduced != calibration or quality != assistance.get('quality'):
            raise ValueError('Saved assisted perspective does not reproduce; check and save the directions again')
        projection_kind = 'operator-assisted-estimate'
        geometry_revision = fingerprint({'calibration_revision': current['revision'],
                                         'registration_revision': refinement['revision']})
    elif not refinement.get('ground_projection'):
        reason = (refinement.get('ground_quality') or {}).get('status','unavailable')
        raise ValueError(f'Camera perspective is unresolved ({reason}). The saved image-plane preview is not calibrated ground; live 3D requires a supported ground estimate')
    else:
        if refinement.get('calibration'):
            calibration['road'] = deepcopy(refinement['calibration']['road'])
        for key in ('anchors', 'width_m', 'depth_m', 'label'):
            calibration[key] = deepcopy(refinement['ground_projection'][key])
    registration = refinement.get('camera_registration')
    if not current.get('plate_reference_supported') or not registration or not registration.get('frames'):
        raise ValueError('Source-specific camera registration is required for the live 3D bridge')
    if not any(row.get('status') in {'reference', 'accepted'} and row.get('H') is not None
               for row in registration['frames']):
        raise ValueError('No supported native camera frames; live 3D is unavailable')
    validate(calibration)
    return {'schema_version': 1, 'binding': current['binding'],
            'geometry_revision': geometry_revision, 'calibration': calibration,
            'projection_kind': projection_kind,
            'calibration_revision': current.get('revision'),
            'registration_revision': refinement['revision'],
            'registration_cadence_s': current['video_offset_s'],
            'projection_assumptions': deepcopy(assistance['quality']['assumptions']) if assistance else [],
            'image_size': current['image_size'], 'metric_accuracy_validated': False,
            'physical_scale_measured': False,
            'registration': [{'frame_index': row['frame_index'], 'status': row['status'],
                              'H': row.get('H')} for row in registration['frames']],
            'scope': 'Fresh detections on saved source-bound road and camera estimates. Exact native-frame registration only; no cached trajectories, measured scale or control input.'}


def save(root: Path, run_id: str, payload: dict) -> dict:
    if not isinstance(payload,dict) or set(payload) != {'binding','calibration'}:
        raise ValueError('provide the source binding and calibration draft')
    current = source(root,run_id)
    if payload['binding'] != current['binding']:
        raise ValueError('source changed; reload before saving calibration')
    calibration = validate(payload['calibration'])
    return _persist(root,current,calibration)


def _persist(root, current, calibration, assistance=None):
    result = {'binding':current['binding'],'calibration':calibration,'status':'draft-unvalidated'}
    if assistance is not None:result['assistance']=assistance
    result['revision'] = fingerprint(result)
    directory = root/'out'/'.reconstructions'/current['identity']
    path = directory/(result['revision']+'.json')
    if path.is_symlink():
        raise ValueError('reconstruction revision symlinks are not allowed')
    if not path.exists():
        atomic_json(path,result)
    atomic_json(directory/'latest.json',result)
    return result


def preview_assisted(root: Path, run_id: str, payload: dict) -> dict:
    """Read-only fit: clients supply selections, never their own approval flag."""
    from . import assisted_geometry, ground_plane
    if not isinstance(payload,dict) or set(payload)!={'binding','base_revision','calibration','lines'}:
        raise ValueError('provide source binding, base revision, road draft and four selected lines')
    current=source(root,run_id)
    if payload['binding']!=current['binding']:raise ValueError('source changed; reload before estimating perspective')
    if payload['base_revision']!=current['revision']:raise ValueError('saved draft changed; reload before estimating perspective')
    candidate,quality=assisted_geometry.propose(payload['lines'],payload['calibration'])
    assistance={'method':assisted_geometry.METHOD,'lines':deepcopy(payload['lines']),
                'input_calibration':deepcopy(payload['calibration']),'quality':quality,
                'code_sha256':file_hash(Path(assisted_geometry.__file__)),
                'ground_code_sha256':file_hash(Path(ground_plane.__file__)),
                'metric_accuracy_validated':False}
    return {'binding':current['binding'],'base_revision':current['revision'],
            'calibration':candidate,'assistance':assistance,'status':'unsaved-assisted-estimate'}


def save_assisted(root: Path, run_id: str, payload: dict) -> dict:
    # Recompute from the original lines, not a browser-supplied preview matrix.
    estimate=preview_assisted(root,run_id,payload)
    current=source(root,run_id)
    if current['binding']!=estimate['binding'] or current['revision']!=estimate['base_revision']:
        raise ValueError('source or draft changed during fitting; reload before saving')
    return _persist(root,current,estimate['calibration'],estimate['assistance'])
