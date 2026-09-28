"""Single-view ground-plane rectification from scene vanishing directions.

Unlike a guessed four-corner trapezoid, this uses a pinhole camera and scene
vanishing directions. Three orthogonal directions (two horizontal, one vertical)
are preferred; two road-line families can substitute when upright cues are absent
and the estimated shape passes a sensitivity check. Square pixels, a central
principal point, flat ground and orthogonal direction families are assumptions,
not surveyed facts. Absolute scale is inherited from the operator's assumed
reference span. Weak images produce no proposal, never a sample camera.
"""
from __future__ import annotations

from copy import deepcopy
import math

import cv2
import numpy as np

VERSION = 'vanishing-camera-ground-v3-temporal-road-families'


def project(matrix, points):
    p = np.asarray(points, dtype=float)
    q = np.c_[p, np.ones(len(p))] @ np.asarray(matrix, dtype=float).T
    if not np.isfinite(q).all() or np.any(q[:, 2] <= 1e-7):
        raise ValueError('ground projection crosses the camera horizon')
    return q[:, :2] / q[:, 2, None]


def camera_ground(vanishing_x, vanishing_z, focal_px, principal=(640., 360.)):
    """Pixel -> orthonormal ground coordinates at unit camera height.

    Intersect each K^-1 image ray with n.X=1, then express the intersection in
    two orthonormal ground axes. Depth foreshortening is removed, not merely
    rescaled independently in X/Y. The camera horizon is the denominator row.
    """
    if not math.isfinite(focal_px) or not 400 <= focal_px <= 2400:
        raise ValueError('supported focal length is 400–2400 normalized pixels')
    k = np.array([[focal_px, 0, principal[0]], [0, focal_px, principal[1]], [0, 0, 1.]])
    u, v = [np.linalg.solve(k, np.r_[point, 1.]) for point in (vanishing_x, vanishing_z)]
    if abs(np.dot(u,v)/(np.linalg.norm(u)*np.linalg.norm(v))) > .015:
        raise ValueError('vanishing directions are inconsistent with orthogonal ground axes')
    normal = np.cross(u,v)
    normal /= np.linalg.norm(normal)
    if normal @ np.linalg.solve(k, [640, 720, 1]) < 0: normal = -normal
    horizontal = np.cross(normal, [0,0,1.])
    if np.linalg.norm(horizontal) < .05: raise ValueError('near-nadir camera needs another calibration method')
    horizontal /= np.linalg.norm(horizontal)
    if horizontal[0] < 0: horizontal = -horizontal
    depth = np.cross(normal, horizontal)
    return np.stack([horizontal, depth, normal]) @ np.linalg.inv(k)


def _line_data(lines):
    a, b = lines[:, :2], lines[:, 2:]
    length = np.linalg.norm(b-a,axis=1)
    mids = (a+b)/2
    directions = (b-a)/length[:, None]
    homogeneous = np.cross(np.c_[a,np.ones(len(a))], np.c_[b,np.ones(len(b))])
    homogeneous /= np.linalg.norm(homogeneous[:,:2],axis=1)[:,None]
    return length, mids, directions, homogeneous


def _support(vp, data, threshold=1.):
    length, mids, directions, _ = data
    rays = vp[:2] - mids
    distance = np.linalg.norm(rays,axis=1)
    cos = np.sum(rays*directions,axis=1)/np.maximum(distance,1e-9)
    angle = np.degrees(np.arccos(np.clip(np.abs(cos),0,1)))
    angle[distance < 150] = 90
    weights = np.minimum(length,180)*np.maximum(0,1-(angle/threshold)**2)
    return float(weights.sum()), angle < threshold, angle


def _candidates(lines):
    data = _line_data(lines); h = data[3]; candidates = []
    for i in range(len(lines)):
        for j in range(i):
            v = np.cross(h[i],h[j])
            if abs(v[2]) < 1e-6: continue
            v /= v[2]
            if not -800 < v[1] < 300 or abs(v[0]) > 16000: continue
            score, keep, _ = _support(v,data)
            if keep.sum() >= 4: candidates.append((score,v,keep))
    candidates.sort(key=lambda item:item[0],reverse=True)
    chosen = []
    # Do not allow the most heavily textured facade to crowd out the second
    # vanishing family. Orthogonal horizontal VPs straddle the principal point.
    for side in (-1,1):
        group = []
        for item in candidates:
            if (item[1][0]-640)*side < 0: continue
            if all(np.sum(item[2]&g[2])/np.sum(item[2]|g[2]) < .5 for g in group): group.append(item)
            if len(group) == 16: break
        chosen += group
    return chosen, data


def estimate_camera(image, boxes=()):
    if image is None or image.shape[:2] != (720,1280): raise ValueError('camera estimation requires a 1280×720 reference')
    gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    detected = cv2.createLineSegmentDetector().detect(gray)[0]
    if detected is None: return None, {'status':'insufficient-lines'}
    lines = detected.reshape(-1,4).astype(float)
    lengths, mids, _, _ = _line_data(lines)
    angles = np.degrees(np.arctan2(lines[:,3]-lines[:,1],lines[:,2]-lines[:,0]))%180
    keep = lengths > 45
    for x1,y1,x2,y2 in boxes:
        keep &= ~((mids[:,0]>x1-8)&(mids[:,0]<x2+8)&(mids[:,1]>y1-8)&(mids[:,1]<y2+8))
    vertical = lines[keep & (angles>65) & (angles<115)]
    horizontal = lines[keep & ((angles<65)|(angles>115))]
    horizontal = horizontal[np.argsort(-np.linalg.norm(horizontal[:,2:]-horizontal[:,:2],axis=1))[:240]]
    if len(horizontal)<12 or len(vertical)<5: return None, {'status':'insufficient-direction-support'}
    candidates,data = _candidates(horizontal); vertical_data = _line_data(vertical); ranked=[]
    for i,(s1,v1,k1) in enumerate(candidates):
        for s2,v2,k2 in candidates[:i]:
            if (v1[0]-640)*(v2[0]-640) >= 0: continue
            f2 = -float(np.dot(v1[:2]-[640,360],v2[:2]-[640,360]))
            if not 450**2 < f2 < 2000**2: continue
            f = math.sqrt(f2)
            try:h = camera_ground(v1[:2],v2[:2],f)
            except ValueError:continue
            horizon = h[2]/np.linalg.norm(h[2,:2])
            if not -150 < -(horizon[0]*640+horizon[2])/horizon[1] < 275: continue
            k = np.array([[f,0,640],[0,f,360],[0,0,1.]])
            vertical_vp = k @ (h[2] @ k)
            if abs(vertical_vp[2]) < 1e-8: continue
            vertical_vp /= vertical_vp[2]
            sv,kv,ev = _support(vertical_vp,vertical_data)
            if kv.sum()<5 or np.ptp(vertical_data[1][kv,0])<250 or sv<200: continue
            # Geometric mean balances all three direction families, instead of
            # optimizing a large roof alone while neglecting vertical evidence.
            score = (s1*s2*sv)**(1/3)
            ranked.append((score,h,f,v1,v2,vertical_vp,k1,k2,kv,ev))
    if not ranked: return None, {'status':'inconsistent-vanishing-directions'}
    ranked.sort(key=lambda r:r[0],reverse=True)
    score,h,f,v1,v2,vv,k1,k2,kv,ev = ranked[0]
    horizon = h[2]/np.linalg.norm(h[2,:2])
    groups = [horizontal[k1],horizontal[k2],vertical[kv]]
    quality = {
        'status':'camera-plane-candidate','method':VERSION,'focal_px':float(f),
        'horizontal_fov_deg':math.degrees(2*math.atan(640/f)),
        'horizon':horizon.tolist(),'horizon_at_centre_y':float(-(horizon[0]*640+horizon[2])/horizon[1]),
        'vanishing_points':[v1[:2].tolist(),v2[:2].tolist(),vv[:2].tolist()],
        'supporting_line_counts':[len(g) for g in groups],
        'supporting_lines':[g.tolist() for g in groups],
        'vertical_angular_residual_median_deg':float(np.median(ev[kv])),
        'competing_models':sum(r[0]>.98*score for r in ranked),
        'assumptions':['pinhole camera, square pixels and centred principal point',
            'two orthogonal horizontal scene directions and upright structures',
            'one flat road plane; lens distortion is not estimated'],
        'metric_accuracy_validated':False,
    }
    return h,quality


def _fit_vanishing(lines, initial):
    """Angular least squares, not an unweighted far-away line intersection."""
    length,mids,_,h = _line_data(lines)
    vp = np.asarray(initial[:2],float).copy()
    for _ in range(8):
        weight = np.minimum(length,180)/np.maximum(np.linalg.norm(vp-mids,axis=1),150)**2
        a = h[:,:2]*np.sqrt(weight[:,None]); b = -h[:,2]*np.sqrt(weight)
        if np.linalg.cond(a) > 300: return None
        fitted = np.linalg.lstsq(a,b,rcond=None)[0]
        if not np.isfinite(fitted).all() or np.linalg.norm(fitted-[640,360])>30000: return None
        vp = fitted
    return np.r_[vp,1.]


def road_segments(image, road, boxes=(), matrix=None):
    """Native-frame line detection, optionally mapped into a reference plane.

    Detect before warping so resampling/mask borders cannot become evidence.
    Road membership is estimated appearance, not semantic road classification.
    """
    if image is None or image.shape[:2] != (720,1280):
        raise ValueError('road evidence requires a 1280×720 source frame')
    if not road or len(road)<3:return np.empty((0,4))
    gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    detected = cv2.createLineSegmentDetector().detect(gray)[0]
    if detected is None:return np.empty((0,4))
    lines = detected.reshape(-1,4).astype(float)
    length,_,_,_ = _line_data(lines)
    contour = np.asarray(road,np.float32)
    keep = length>35
    for i,(a,b) in enumerate(zip(lines[:,:2],lines[:,2:])):
        if keep[i]:
            samples = np.linspace(a,b,5)
            for x1,y1,x2,y2 in boxes:
                rectangle=(math.floor(x1)-8,math.floor(y1)-8,
                           math.ceil(x2)-math.floor(x1)+17,math.ceil(y2)-math.floor(y1)+17)
                if cv2.clipLine(rectangle,tuple(np.round(a).astype(int)),tuple(np.round(b).astype(int)))[0]:
                    keep[i]=False;break
            if matrix is not None and keep[i]:
                try:
                    mapped=project(matrix,[a,b])
                    lines[i]=mapped.ravel()
                    samples=np.linspace(*mapped,5)
                except ValueError:keep[i]=False
            if keep[i]:
                keep[i]=all(cv2.pointPolygonTest(contour,tuple(p),False)>=0 for p in samples)
    lines=lines[keep]
    if len(lines):lines=lines[np.linalg.norm(lines[:,2:]-lines[:,:2],axis=1)>35]
    lines=lines[np.argsort(-np.linalg.norm(lines[:,2:]-lines[:,:2],axis=1))[:128]]
    return lines


def _road_line_families(image, road, boxes):
    lines=road_segments(image,road,boxes)
    return _families_from_lines(lines),lines


def _families_from_lines(lines):
    """No screen-angle split: overhead ground directions can both be diagonal."""
    if len(lines)<12:return []
    data=_line_data(lines); candidates=[]
    for i in range(len(lines)):
        for j in range(i):
            vp=np.cross(data[3][i],data[3][j])
            if abs(vp[2])<1e-7:continue
            vp/=vp[2]
            if np.linalg.norm(vp[:2]-[640,360])>30000 or (-100<vp[0]<1380 and -100<vp[1]<820):continue
            score,mask,_=_support(vp,data)
            if mask.sum()>=6:candidates.append((score,vp,mask))
    candidates.sort(key=lambda item:item[0],reverse=True)
    selected=[]
    for _,vp,mask in candidates:
        if any(np.sum(mask&row[2])/np.sum(mask|row[2])>=.45 for row in selected):continue
        fitted=vp
        # Refit the consensus after angular reclassification. Scoring a model
        # on a different set from the one fitted can create duplicate, mutually
        # inconsistent hypotheses from the very same road markings.
        for _ in range(8):
            fitted=_fit_vanishing(lines[mask],fitted)
            if fitted is None:break
            score,new_mask,errors=_support(fitted,data)
            if new_mask.sum()<6:
                fitted=None;break
            if np.array_equal(new_mask,mask):break
            mask=new_mask
        else:continue
        if fitted is None:continue
        if mask.sum()<6 or score<220:continue
        if any(np.sum(mask&row[2])/np.sum(mask|row[2])>=.45 for row in selected):continue
        points=lines[mask].reshape(-1,2)
        if cv2.contourArea(cv2.convexHull(points.astype(np.float32)))<8000:continue
        if np.linalg.norm(np.ptp(data[1][mask],axis=0))<180:continue
        selected.append((score,fitted,mask,errors))
        if len(selected)==24:break
    return selected


def _road_pair(vp_a,vp_b,road):
    focal2=-float(np.dot(vp_a[:2]-[640,360],vp_b[:2]-[640,360]))
    if not 450**2<focal2<2000**2:raise ValueError('unsupported road-pair focal estimate')
    focal=math.sqrt(focal2)
    h=camera_ground(vp_a[:2],vp_b[:2],focal)
    denominator=np.c_[road,np.ones(len(road))]@h[2]
    if denominator.min()<=0 or denominator.max()/denominator.min()>6:
        raise ValueError('road pair has an unstable or intersecting horizon')
    return h,focal


def _normalized_shape(h,points):
    """Compare shape up to similarity, without declaring any metre reference."""
    p=project(h,points)
    centre=p.mean(axis=0);p=p-centre
    scale=np.sqrt(np.mean(np.sum(p*p,axis=1)))
    if scale<1e-7:raise ValueError('degenerate road shape')
    return p/scale


def _shape_error(reference,other):
    # Procrustes rotation (not affine alignment): perspective/aspect differences
    # must remain visible in the sensitivity test.
    u,_,vt=np.linalg.svd(other.T@reference)
    rotation=u@vt
    if np.linalg.det(rotation)<0:raise ValueError('reflected road shape')
    return float(np.sqrt(np.mean(np.sum((other@rotation-reference)**2,axis=1))))


def estimate_road_camera(image,road,boxes=()):
    """Two road-direction fallback, with explicit orthogonality assumptions.

    Road paint/curbs substitute for upright architecture, NOT for a survey.
    Endpoint perturbation and line resampling must give stable road shape.
    """
    lines=road_segments(image,road,boxes)
    return estimate_road_lines(lines,road)


def estimate_road_lines(lines,road):
    """The same camera and sensitivity gates for single or temporal evidence."""
    report={'status':'insufficient-road-directions','method':VERSION,
            'evidence':'two-road-direction-families','metric_accuracy_validated':False,
            'reason':'Not enough distinct, spatially distributed road lines to recover two ground directions.'}
    if not road or len(road)<3:return None,report
    lines=np.asarray(lines,dtype=float).reshape(-1,4)
    if len(lines)>128 or not np.isfinite(lines).all():raise ValueError('road line evidence must be finite and bounded to 128 segments')
    if len(lines) and np.any(np.linalg.norm(lines[:,2:]-lines[:,:2],axis=1)<1):raise ValueError('degenerate road line evidence')
    families=_families_from_lines(lines)
    report['road_line_count']=len(lines)
    ranked=[]
    for i,(s,v,k,_) in enumerate(families):
        for t,w,l,_ in families[:i]:
            if np.any(k&l):continue
            try:h,f=_road_pair(v,w,road)
            except ValueError:continue
            ranked.append((math.sqrt(s*t),h,f,v,w,k,l))
    if not ranked:return None,report
    ranked.sort(key=lambda row:row[0],reverse=True)
    _,h,f,v,w,k,l=ranked[0]
    baseline=_normalized_shape(h,road)
    # Several near-equal but geometrically incompatible explanations are not
    # resolved by selecting whichever happens to rank first.
    competing=[r for r in ranked[1:] if r[0]>=ranked[0][0]*.9]
    if any(_shape_error(baseline,_normalized_shape(r[1],road))>.08 for r in competing):
        return None,{**report,'status':'ambiguous-road-directions',
                     'reason':'Similarly supported road-line models imply different road shapes; perspective correction was not applied.'}
    rng=np.random.default_rng(1701);errors=[]
    groups=[lines[k],lines[l]]
    for _ in range(64):
        perturbed=[]
        for group,vp in zip(groups,(v,w)):
            sample=group[rng.integers(0,len(group),len(group))]+rng.normal(0,.5,group.shape)
            perturbed.append(_fit_vanishing(sample,vp))
        if any(p is None for p in perturbed):continue
        try:
            candidate,_=_road_pair(*perturbed,road)
            errors.append(_shape_error(baseline,_normalized_shape(candidate,road)))
        except ValueError:continue
    sensitivity={'trials':64,'accepted':len(errors),
                 'shape_error_p95':float(np.percentile(errors,95)) if errors else None,
                 'note':'Line resampling plus 0.5 px endpoint perturbation; sensitivity diagnostic, not an accuracy confidence interval.'}
    report['sensitivity']=sensitivity
    if len(errors)<52 or np.percentile(errors,95)>.08:
        return None,{**report,'status':'unstable-road-perspective',
                     'reason':f'Road perspective is unstable under line resampling ({len(errors)}/64 supported trials); correction was not applied.'}
    horizon=h[2]/np.linalg.norm(h[2,:2])
    return h,{**report,'status':'camera-plane-candidate','focal_px':f,
        'horizontal_fov_deg':math.degrees(2*math.atan(640/f)),
        'horizon':horizon.tolist(),
        'horizon_at_centre_y':float(-(horizon[0]*640+horizon[2])/horizon[1]) if abs(horizon[1])>1e-9 else None,
        'vanishing_points':[v[:2].tolist(),w[:2].tolist()],
        'supporting_line_counts':[len(g) for g in groups],
        'supporting_lines':[g.tolist() for g in groups],
        'competing_models':len(competing),
        'assumptions':['pinhole camera, square pixels and centred principal point',
                       'two visible road-line families are parallel within each family and mutually orthogonal',
                       'one flat road plane; no lens-distortion estimate or surveyed scale',
                       'road appearance mask and line classification may include incorrect boundaries'],
        'reason':'Road-line perspective candidate; direction orthogonality is assumed, not independently verified.'}


def persistent_road_lines(frames, minimum_frames=3):
    """One segment per repeated marking, not one vote per video frame.

    Greedy collinear/overlap groups are bounded to 21×128 input segments. Each
    frame contributes at most one observation to a group's median endpoints.
    Persistence does not prove a marking is on the ground: static occluders and
    road-mask errors remain possible.
    """
    if not 1<=minimum_frames<=21 or len(frames)>21:
        raise ValueError('temporal road evidence supports at most 21 frames')
    seen=set();parts=[];owners=[]
    for row in frames:
        identity=row['frame_index']
        if type(identity) is not int or identity<0 or identity in seen:
            raise ValueError('temporal evidence needs distinct native frame indices')
        seen.add(identity)
        lines=np.asarray(row['lines'],float).reshape(-1,4)
        if len(lines)>128 or not np.isfinite(lines).all():raise ValueError('invalid temporal road segments')
        if len(lines) and np.any(np.linalg.norm(lines[:,2:]-lines[:,:2],axis=1)<1):
            raise ValueError('degenerate temporal road segments')
        parts.extend(lines);owners.extend([identity]*len(lines))
    if not parts:return np.empty((0,4)),[]
    lines=np.asarray(parts);owners=np.asarray(owners)
    length,_,directions,homogeneous=_line_data(lines)
    available=np.ones(len(lines),bool);result=[];evidence=[]
    endpoints=lines.reshape(-1,2,2)
    for seed in np.argsort(-length):
        if not available[seed]:continue
        direction=directions[seed]
        along=(endpoints-endpoints[seed,0])@direction
        overlap=np.maximum(0,np.minimum(along.max(axis=1),length[seed])-np.maximum(along.min(axis=1),0))
        distance=np.abs(endpoints@homogeneous[seed,:2]+homogeneous[seed,2]).max(axis=1)
        same=(available & (np.abs(directions@direction)>math.cos(math.radians(1))) &
              (distance<=3.) & (overlap/np.minimum(length,length[seed])>=.5))
        group=np.flatnonzero(same);available[group]=False
        distinct=np.unique(owners[group])
        if len(distinct)<minimum_frames:continue
        # Select the longest segment in each frame, then normalize its endpoint
        # direction before taking medians. Duplicate LSD edges cannot add votes.
        chosen=[max(group[owners[group]==identity],key=lambda j:length[j]) for identity in distinct]
        points=np.array([endpoints[j] if directions[j]@direction>=0 else endpoints[j,::-1] for j in chosen])
        median=np.median(points,axis=0)
        if np.linalg.norm(median[1]-median[0])<35:continue
        result.append(median.ravel())
        evidence.append({'line':median.ravel().tolist(),'frames':distinct.tolist()})
        if len(result)==128:break
    return np.asarray(result).reshape(-1,4),evidence


def estimate_temporal_road_camera(frames,road):
    """Require a stable pooled model AND agreement between disjoint time blocks.

    Blocks share the same estimated reference plane, so agreement is not an
    independent accuracy measurement. No single-frame threshold is relaxed.
    """
    report={'status':'insufficient-temporal-road-evidence','method':VERSION,
            'evidence':'temporal-road-direction-families','metric_accuracy_validated':False,
            'reason':'At least six distinct registered frames spanning one second are required.'}
    if len(frames)>21:raise ValueError('temporal road evidence supports at most 21 frames')
    # Validate unique indices and bounded segments even for insufficient input.
    lines,evidence=persistent_road_lines(frames)
    times=[row['t'] for row in frames]
    if any(type(t) not in {float,int} or not math.isfinite(t) for t in times):
        raise ValueError('temporal road timestamps must be finite')
    temporal={'frames':len(frames),'frame_indices':[r['frame_index'] for r in frames],
              'timestamps':times,'input_segments':sum(len(r['lines']) for r in frames),
              'persistent_segments':len(lines),'segments':evidence,
              'note':'Repeated markings count once. Shared registration and geometric assumptions mean time-block agreement is not measured accuracy.'}
    report['temporal']=temporal
    if len(frames)<6 or max(times)-min(times)<1:return None,report
    ordered=sorted(frames,key=lambda row:row['t'])
    if any(a['t']>=b['t'] or a['frame_index']>=b['frame_index'] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('native frame indices and times must advance together')
    h,pooled=estimate_road_lines(lines,road)
    report.update(pooled)
    report.update(evidence='temporal-road-direction-families',temporal=temporal)
    if h is None:
        report['reason']='Multi-frame road evidence: '+report['reason']
        return None,report
    split=len(ordered)//2;blocks=[];errors=[]
    baseline=_normalized_shape(h,road)
    for block in (ordered[:split],ordered[split:]):
        block_lines,_=persistent_road_lines(block)
        candidate,quality=estimate_road_lines(block_lines,road)
        details={'frame_indices':[r['frame_index'] for r in block],
                 'persistent_segments':len(block_lines),'status':quality['status'],
                 'sensitivity':quality.get('sensitivity')}
        error=None
        if candidate is not None:
            try:error=_shape_error(baseline,_normalized_shape(candidate,road))
            except ValueError:pass
        details['shape_disagreement']=error;blocks.append(details)
        if error is not None:errors.append(error)
    temporal['time_blocks']=blocks
    if len(errors)!=2 or max(errors)>.08:
        return None,{**report,'status':'temporal-road-disagreement',
                     'reason':'Earlier and later road evidence do not independently support the same stable shape; correction was not applied.'}
    report['reason']='Repeated road-line candidate with time-block agreement; perpendicular directions and physical scale still require review.'
    return h,report


def calibration_from_camera(unit_h, current, road):
    """Encode the physical projection in the existing editable rectangle schema.

    Only a uniform similarity sets display scale/orientation. The derived anchor
    quadrilateral is the inverse projection of a genuine ground rectangle, not
    a trapezoid guessed from the image silhouette.
    """
    pixel_span = current['anchors'][:2]
    span = project(unit_h,pixel_span)
    direction = span[1]-span[0]; distance = float(np.linalg.norm(direction))
    if distance < .05: raise ValueError('reference span is too small for scale transfer')
    direction /= distance
    rotation = np.array([[direction[0],direction[1]],[-direction[1],direction[0]]])
    uniform_scale = current['width_m']/distance
    center_pixel = np.mean(current['anchors'],axis=0)
    center = project(unit_h,[center_pixel])[0]
    transform = np.eye(3);transform[:2,:2] = rotation*uniform_scale
    transform[:2,2] = -rotation@center*uniform_scale
    h = transform@unit_h
    horizon = h[2]/np.linalg.norm(h[2,:2])
    if np.min(np.c_[road,np.ones(len(road))]@horizon) < 20:
        raise ValueError('visible road is too close to or beyond the estimated horizon')
    projected = project(h,road)
    if np.max(np.linalg.norm(projected,axis=1)) >= 450:
        raise ValueError('rectified footprint exceeds supported range; check scale and horizon')
    inverse = np.linalg.inv(h)
    # Inverse matrices can have an arbitrary homogeneous sign. Choose the
    # representative that maps the ground origin to the visible image.
    if inverse[2,2] < 0: inverse = -inverse
    width,depth = current['width_m']*.45,current['width_m']*.24
    contour = np.asarray(road,np.float32)
    for _ in range(18):
        rect=[[-width/2,-depth/2],[width/2,-depth/2],[width/2,depth/2],[-width/2,depth/2]]
        try: anchors = project(inverse,rect)
        except ValueError: anchors = np.full((4,2),-1.)
        if np.all(anchors>2) and np.all(anchors<[1277,717]) and all(cv2.pointPolygonTest(contour,tuple(p),False)>=0 for p in anchors): break
        width*=.85;depth*=.85
    else: raise ValueError('no usable reference rectangle inside the visible road')
    if min(width,depth)<2: raise ValueError('rectified reference rectangle is too small')
    candidate=deepcopy(current)
    candidate.update(anchors=anchors.tolist(),width_m=float(width),depth_m=float(depth),road=deepcopy(road),
        label='Camera-rectified ground · estimated scale')
    from .reconstruction import validate
    validate(candidate)
    return candidate, {'pixel_to_ground':h.tolist(),'scale':'uniform-transfer-of-existing-assumed-span',
        'scale_reference_pixels':deepcopy(pixel_span),'scale_reference_assumed_m':current['width_m'],
        'derived_anchor_rectangle':True,'physical_scale_measured':False}


def propose(image, current, road, boxes=()):
    h,report=estimate_camera(image,boxes)
    if h is None:
        legacy_status=report['status']
        h,report=estimate_road_camera(image,road,boxes)
        report['architecture_status']=legacy_status
    if h is None: return None,report
    try: candidate,details=calibration_from_camera(h,current,road)
    except ValueError as exc: return None,{**report,'status':'projection-review-needed','reason':str(exc)}
    return candidate,{**report,**details,
        'reason':'Perspective rectified from scene vanishing directions. Camera assumptions and absolute scale still require review.'}
