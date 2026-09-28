"""Automatic, explicitly unvalidated demo proposals. Never surveyed geometry.

The reconstructed footprint and procedural SUMO arms share one estimated ground
plane. Lane counts, arm extensions, speeds and most-opposite exits are hypotheses;
the footprint is context, not a constraint that SUMO lanes are guaranteed to fit.
"""
from copy import deepcopy
import math

import numpy as np

from .reconstruction import source, validate as validate_calibration
from .site_profiles import from_run, _seal, validate


def ground_mapping(calibration):
    c = validate_calibration(calibration)
    w, d = c['width_m'], c['depth_m']
    target = [[-w/2,-d/2],[w/2,-d/2],[w/2,d/2],[-w/2,d/2]]
    rows, rhs = [], []
    for (x,y),(u,v) in zip(c['anchors'],target):
        rows.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]])
        rhs.extend([u,v])
    h = np.r_[np.linalg.solve(rows,rhs),1].reshape(3,3)
    if (h @ np.r_[np.mean(c['anchors'],axis=0),1])[2] < 0:
        h = -h

    def project(point):
        p = h @ [*point,1]
        if p[2] < 1e-5:
            raise ValueError('candidate approach crosses the camera horizon')
        p = p[:2]/p[2]
        if not np.all(np.isfinite(p)) or np.linalg.norm(p) >= 500:
            raise ValueError('candidate approach exceeds the supported ground plane')
        return p
    return project


def propose(root, run_id):
    profile = from_run(root,run_id)
    original_revision = profile['revision']
    proposal = {'basis':'camera-direction-sketch', 'road':[], 'origin_ground':[0.,0.],
                'notes':['One lane each way, 3.2 m lanes, 8.33 m/s limit and most-opposite exits are assumed.',
                         'Procedural lanes extend beyond the visible footprint; they are not detected lane boundaries.']}
    try:
        recorded = source(root,run_id)
    except (OSError, ValueError, KeyError):
        recorded = None
    if recorded:
        r = recorded['refinement']
        if r and not r['stale'] and r.get('ground_projection') and r.get('calibration'):
            c = deepcopy(r['ground_projection'])
            c['road'] = deepcopy(r['calibration']['road'])
            try:
                project = ground_mapping(c)
                markers = [project(a['approach_side']) for a in profile['source']['approaches']]
                centre = np.mean([project(np.mean(a['count_line'],axis=0))
                                  for a in profile['source']['approaches']],axis=0)
                candidate = deepcopy(profile)
                for arm, marker in zip(candidate['approaches'],markers):
                    delta = marker-centre
                    length = float(np.linalg.norm(delta))
                    if length < 1:
                        raise ValueError('candidate approach has no usable direction')
                    # A visible crop is not a network boundary. Add approach storage
                    # explicitly, without stretching the reconstructed road polygon.
                    delta *= max(60., min(150., length+35.))/length
                    arm.update(x=round(float(delta[0]),3),y=round(float(-delta[1]),3))
                assign_exits(candidate)
                validate(candidate,runnable=True)
                profile = candidate
                road = [project(p)-centre for p in c['road']]
                proposal.update(basis='camera-estimated-ground', binding=recorded['binding'],
                                refinement_revision=r['revision'], projection=c,
                                origin_ground=centre.tolist(),
                                road=[[round(float(p[0]),5),round(float(-p[1]),5)] for p in road])
            except (ValueError, np.linalg.LinAlgError) as exc:
                proposal['notes'].append('Ground-plane seed rejected: '+str(exc))
        else:
            proposal['notes'].append('No current accepted camera estimate; using the source count-marker directions only.')
    else:
        proposal['notes'].append('Recorded reconstruction unavailable; using source count-marker directions only.')
    assign_exits(profile)
    validate(profile,runnable=True)  # Refuse ambiguous arms; never substitute a stock site.
    profile['parent_revision'] = original_revision
    profile['label'] = (profile['source']['filename']+' · automatic demo hypothesis')[:120]
    profile['demo_proposal'] = proposal
    return _seal(root,profile)


def assign_exits(profile):
    arms = [a for a in profile['approaches'] if a['enabled']]
    for a in arms:
        a['exit'] = min((b for b in arms if b['id']!=a['id']),
                        key=lambda b:(a['x']*b['x']+a['y']*b['y'])/math.hypot(b['x'],b['y']))['id']
