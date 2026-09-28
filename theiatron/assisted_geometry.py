"""Operator-selected directions, never automatic or surveyed calibration."""
from copy import deepcopy
import math

import numpy as np

from .ground_plane import (_road_pair, _normalized_shape, _shape_error,
                           calibration_from_camera)

METHOD = 'operator-road-directions-v1'


def _vanishing(pair):
    points=np.asarray(pair,float)
    equations=np.cross(np.c_[points[:,0],np.ones(2)],np.c_[points[:,1],np.ones(2)])
    vp=np.cross(*equations)
    if abs(vp[2])<1e-7:raise ValueError('Selected lines are parallel in the image; their perspective is not identifiable. Use longer, clearly converging ground edges.')
    vp=vp/vp[2]
    if not np.isfinite(vp).all() or np.linalg.norm(vp[:2]-[640,360])>30000:
        raise ValueError('Selected directions converge too far away for a stable camera estimate.')
    return vp


def propose(lines,calibration):
    """Two lines along each of two ASSUMED perpendicular ground directions."""
    from .reconstruction import validate
    validate(calibration)
    if not isinstance(lines,list) or len(lines)!=4:
        raise ValueError('Mark four ground lines: two parallel lines for direction A, then two for perpendicular direction B.')
    for line in lines:
        if not isinstance(line,list) or len(line)!=2:raise ValueError('Each line needs two endpoints')
        for p in line:
            if not isinstance(p,list) or len(p)!=2 or any(type(v) not in {int,float} or not math.isfinite(v) or not 0<=v<=bound for v,bound in zip(p,(1279,719))):
                raise ValueError('Line endpoints must be finite pixels inside the reference image')
        if np.linalg.norm(np.subtract(*line))<80:
            raise ValueError('Use ground edges at least 80 image pixels long for stable direction estimates.')
    values=np.asarray(lines,float)
    # Reject repeated or nearly coincident lines, which carry no convergence evidence.
    for pair in (values[:2],values[2:]):
        normal=np.cross(np.r_[pair[0,0],1.],np.r_[pair[0,1],1.])
        distance=np.abs(np.c_[pair[1],np.ones(2)]@normal)/np.linalg.norm(normal[:2])
        if distance.max()<20:raise ValueError('Separate the two lines in each direction; do not mark the same edge twice.')
    vps=[_vanishing(values[:2]),_vanishing(values[2:])]
    h,focal=_road_pair(*vps,calibration['road'])
    baseline=_normalized_shape(h,calibration['road']);rng=np.random.default_rng(1701);errors=[]
    for _ in range(64):
        perturbed=values+rng.normal(0,1.,values.shape)
        try:
            test,_=_road_pair(_vanishing(perturbed[:2]),_vanishing(perturbed[2:]),calibration['road'])
            errors.append(_shape_error(baseline,_normalized_shape(test,calibration['road'])))
        except ValueError:continue
    p95=float(np.percentile(errors,95)) if errors else None
    if len(errors)<52 or p95>.08:
        raise ValueError(f'Selected directions are too sensitive to a 1-pixel click change ({len(errors)}/64 supported trials). Use longer, more widely separated ground edges; no correction was applied.')
    candidate,details=calibration_from_camera(h,calibration,calibration['road'])
    candidate['label']='Operator-assisted perspective · estimated scale'
    return candidate,{'method':METHOD,'status':'assisted-estimate-unvalidated',
        'input_lines':deepcopy(lines),'focal_px':focal,
        'sensitivity':{'trials':64,'accepted':len(errors),'shape_error_p95':p95,
                       'note':'1-pixel endpoint perturbation only; not independent accuracy validation.'},
        'assumptions':['Operator-selected lines lie on one flat road plane',
                       'Lines are parallel within each pair; the two directions are perpendicular',
                       'Pinhole camera with square pixels and centred principal point',
                       'Physical scale remains assumed; lens distortion is not estimated'],
        'metric_accuracy_validated':False,**details}
