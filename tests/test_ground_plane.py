import copy

import cv2
import numpy as np
import pytest

from theiatron.ground_plane import (camera_ground, calibration_from_camera, estimate_camera,
    estimate_road_camera, project, _normalized_shape, _shape_error, road_segments,
    persistent_road_lines, estimate_temporal_road_camera)
from theiatron.reconstruction import validate


def camera():
    focal=1000.; pitch=np.radians(9.);yaw=np.radians(35.)
    normal=np.array([0,np.cos(pitch),np.sin(pitch)])
    right=np.array([1.,0,0]);depth=np.cross(normal,right)
    u=right*np.cos(yaw)+depth*np.sin(yaw)
    v=-right*np.sin(yaw)+depth*np.cos(yaw)
    k=np.array([[focal,0,640],[0,focal,360],[0,0,1.]])
    def vp(direction):
        p=k@direction
        return p[:2]/p[2]
    def image(points):
        p=np.array(points)@k.T
        return p[:,:2]/p[:,2,None]
    return focal,normal,right,depth,vp(u),vp(v),image


def test_camera_plane_recovers_equal_near_far_widths_and_true_metric_aspect():
    f,n,x,z,u,v,image=camera()
    world=np.array([[-6,-40],[6,-40],[6,-20],[-6,-20]])
    pixels=image([a*x+b*z+8*n for a,b in world])
    assert np.linalg.norm(pixels[1]-pixels[0]) < np.linalg.norm(pixels[2]-pixels[3])*.6
    h=camera_ground(u,v,f)
    recovered=project(h,pixels)*8
    assert np.allclose(recovered,world,atol=1e-9)
    assert h[2,2] < 0  # camera horizon genuinely lies within the image
    assert np.isclose(np.linalg.norm(recovered[1]-recovered[0]),12)
    assert np.isclose(np.linalg.norm(recovered[2]-recovered[1]),20)


def test_camera_candidate_uses_uniform_scale_and_preserves_source_outline():
    f,n,x,z,u,v,image=camera()
    world=np.array([[-10,-45],[10,-45],[10,-19],[-10,-19]])
    pixels=image([a*x+b*z+8*n for a,b in world]).tolist()
    current={'anchors':pixels,'road':pixels,'width_m':20.,'depth_m':26.,'label':'Synthetic known geometry'}
    before=copy.deepcopy(current)
    candidate,report=calibration_from_camera(camera_ground(u,v,f),current,pixels)
    assert current==before and candidate['road']==pixels
    validate(candidate)
    mapped=project(report['pixel_to_ground'],pixels)
    assert np.allclose(np.linalg.norm(np.roll(mapped,-1,axis=0)-mapped,axis=1),[20,26,20,26])
    assert report['physical_scale_measured'] is False
    assert report['derived_anchor_rectangle'] is True


def test_ground_camera_rejects_bad_intrinsics_nonorthogonal_axes_and_horizon_crossing():
    f,n,x,z,u,v,image=camera()
    with pytest.raises(ValueError): camera_ground(u,v,float('nan'))
    with pytest.raises(ValueError): camera_ground(u,v,600)
    h=camera_ground(u,v,f)
    with pytest.raises(ValueError,match='horizon'): project(h,[[640,20]])


def test_blank_reference_never_gets_a_stock_camera():
    h,report=estimate_camera(np.full((720,1280,3),128,np.uint8))
    assert h is None and report['status']=='insufficient-lines'


def test_parallel_scene_lines_recover_a_ground_camera():
    # Render three exact orthogonal direction families, not traffic silhouettes.
    f,n,x,z,u,v,image=camera()
    frame=np.full((720,1280,3),235,np.uint8)
    rng=np.random.default_rng(22)
    for direction in (x*np.cos(np.radians(35))+z*np.sin(np.radians(35)),
                      -x*np.sin(np.radians(35))+z*np.cos(np.radians(35)),n):
        for _ in range(38):
            point=x*rng.uniform(-20,20)+z*rng.uniform(-45,-18)+n*rng.uniform(1,8)
            endpoints=image([point,point+direction*rng.uniform(2,5)])
            cv2.line(frame,tuple(np.round(endpoints[0]).astype(int)),tuple(np.round(endpoints[1]).astype(int)),(30,30,30),2)
    h,report=estimate_camera(frame)
    assert h is not None
    assert abs(report['focal_px']-f)<f*.12
    assert abs(report['horizon_at_centre_y']-(360-f*np.tan(np.radians(9))))<20
    assert report['metric_accuracy_validated'] is False


def overhead_road(seed=61,pitch_deg=55,noise=0):
    focal=900.;pitch=np.radians(pitch_deg);yaw=np.radians(35.)
    normal=np.array([0,np.cos(pitch),np.sin(pitch)])
    x=np.array([1.,0,0]);z=np.cross(normal,x)
    directions=[x*np.cos(yaw)+z*np.sin(yaw),-x*np.sin(yaw)+z*np.cos(yaw)]
    k=np.array([[focal,0,640],[0,focal,360],[0,0,1.]])
    def image(points):
        p=np.asarray(points)@k.T
        return p[:,:2]/p[:,2,None]
    frame=np.full((720,1280,3),235,np.uint8);rng=np.random.default_rng(seed)
    for direction in directions:
        for _ in range(80):
            point=x*rng.uniform(-20,20)+z*rng.uniform(-22,-3)+normal*24
            ends=image([point,point+direction*rng.uniform(2,5)])+rng.normal(0,noise,(2,2))
            cv2.line(frame,tuple(np.round(ends[0]).astype(int)),tuple(np.round(ends[1]).astype(int)),(20,20,20),2)
    vps=[(k@d)[:2]/(k@d)[2] for d in directions]
    return frame,camera_ground(*vps,focal),[[1,1],[1278,1],[1278,718],[1,718]]


def test_overhead_road_directions_recover_shape_without_building_verticals():
    frame,truth,road=overhead_road()
    h,report=estimate_road_camera(frame,road)
    assert h is not None,report
    assert _shape_error(_normalized_shape(truth,road),_normalized_shape(h,road))<.04
    assert report['evidence']=='two-road-direction-families'
    assert report['sensitivity']['accepted']>=52
    assert report['sensitivity']['shape_error_p95']<=.08
    assert report['metric_accuracy_validated'] is False
    assert 'mutually orthogonal' in ' '.join(report['assumptions'])


def test_missing_road_or_vehicle_only_lines_never_produce_ground_geometry():
    frame,_,road=overhead_road()
    assert estimate_road_camera(frame,[])[0] is None
    assert estimate_road_camera(frame,road,[[0,0,1280,720]])[0] is None
    blank=np.full_like(frame,128)
    assert estimate_road_camera(blank,road)[0] is None


def test_single_parallel_family_does_not_invent_a_second_ground_axis():
    image=np.full((720,1280,3),235,np.uint8)
    for y in range(100,650,25):cv2.line(image,(100,y),(1150,y),(20,20,20),2)
    h,report=estimate_road_camera(image,[[1,1],[1278,1],[1278,718],[1,718]])
    assert h is None


def test_road_fallback_handles_camera_roll_without_screen_angle_categories():
    frame,truth,road=overhead_road(seed=62)
    affine=cv2.getRotationMatrix2D((640,360),12,1)
    rotation=np.vstack([affine,[0,0,1]])
    rolled=cv2.warpAffine(frame,affine,(1280,720),borderValue=(235,235,235))
    h,report=estimate_road_camera(rolled,road)
    assert h is not None,report
    assert _shape_error(_normalized_shape(truth@np.linalg.inv(rotation),road),_normalized_shape(h,road))<.05


def test_noisy_road_lines_do_not_receive_an_unstable_camera():
    frame,_,road=overhead_road(noise=6)
    h,report=estimate_road_camera(frame,road)
    assert h is None,report


def test_projection_dispatch_uses_road_families_only_when_architecture_is_missing(monkeypatch):
    from theiatron import ground_plane as module
    frame,truth,road=overhead_road()
    current={'anchors':[[384,360],[896,360],[896,648],[384,648]],'road':road,
             'width_m':30.,'depth_m':16.875,'label':'Unknown camera'}
    monkeypatch.setattr(module,'estimate_camera',lambda *_:(None,{'status':'insufficient-direction-support'}))
    candidate,report=module.propose(frame,current,road)
    assert candidate is not None and candidate['road']==road
    assert report['architecture_status']=='insufficient-direction-support'
    assert report['physical_scale_measured'] is False
    assert report['sensitivity']['accepted']>=52
    monkeypatch.setattr(module,'estimate_camera',lambda *_:(truth,{'status':'camera-plane-candidate'}))
    def forbidden(*_):raise AssertionError('do not replace an available three-direction estimate')
    monkeypatch.setattr(module,'estimate_road_camera',forbidden)
    assert module.propose(frame,current,road)[0] is not None


def test_native_lines_are_masked_before_reference_projection(monkeypatch):
    # A narrow vehicle between the five old sampling positions must still mask
    # the whole source segment. Its transformed position is not the mask space.
    class Detector:
        def detect(self,_):return (np.array([[[100,200,600,200]],[[100,400,600,400]]],np.float32),)
    monkeypatch.setattr(cv2,'createLineSegmentDetector',lambda:Detector())
    image=np.zeros((720,1280,3),np.uint8)
    road=[[1,1],[1278,1],[1278,718],[1,718]]
    matrix=np.array([[1,0,70],[0,1,15],[0,0,1.]])
    lines=road_segments(image,road,[[152,195,158,205]],matrix)
    assert np.allclose(lines,[[170,415,670,415]])
    assert len(road_segments(image,road,[],matrix))==2


def test_temporal_persistence_counts_frames_not_duplicate_edges():
    line=[100,200,500,205]
    one=[{'frame_index':0,'t':0.,'lines':[line]*20}]
    assert len(persistent_road_lines(one)[0])==0
    frames=one+[{'frame_index':i,'t':float(i),'lines':[line]} for i in (1,2)]
    found,evidence=persistent_road_lines(frames)
    assert np.allclose(found,[line])
    assert evidence[0]['frames']==[0,1,2]
    with pytest.raises(ValueError,match='distinct'):
        persistent_road_lines(frames+[frames[0]])


def test_repeated_occluded_markings_recover_known_shape_and_pass_disjoint_time_blocks():
    frame,truth,road=overhead_road()
    frames=[];rng=np.random.default_rng(31)
    for i in range(12):
        # Different moving occluders: neither copies of one line observation nor
        # a temporal-median image with synthetic seams may supply the evidence.
        x=60+(i%6)*200
        obscured=frame.copy();cv2.rectangle(obscured,(x,180),(x+100,580),(128,128,128),-1)
        lines=road_segments(obscured,road,[[x,180,x+100,580]])
        lines=lines+rng.normal(0,.15,lines.shape)
        frames.append({'frame_index':i*30,'t':float(i),'lines':lines.tolist()})
    h,quality=estimate_temporal_road_camera(frames,road)
    assert h is not None,quality
    assert _shape_error(_normalized_shape(truth,road),_normalized_shape(h,road))<.04
    assert quality['evidence']=='temporal-road-direction-families'
    assert quality['metric_accuracy_validated'] is False
    blocks=quality['temporal']['time_blocks']
    assert len(blocks)==2 and all(b['shape_disagreement']<.08 for b in blocks)
    assert set(blocks[0]['frame_indices']).isdisjoint(blocks[1]['frame_indices'])
    assert quality['temporal']['persistent_segments']<quality['temporal']['input_segments']


def test_temporal_estimate_rejects_pooled_model_without_later_support():
    image,_,road=overhead_road()
    lines=road_segments(image,road).tolist()
    frames=[{'frame_index':i*30,'t':float(i),'lines':lines if i<6 else []} for i in range(12)]
    h,quality=estimate_temporal_road_camera(frames,road)
    assert h is None
    assert quality['status']=='temporal-road-disagreement'
    assert quality['temporal']['time_blocks'][1]['status']=='insufficient-road-directions'


def test_temporal_estimate_rejects_geometrically_different_time_blocks(monkeypatch):
    from theiatron import ground_plane as module
    _,truth,road=overhead_road()
    wrong=np.diag([1.4,1,1])@truth
    calls=iter([truth,truth,wrong])
    monkeypatch.setattr(module,'estimate_road_lines',lambda *_:(next(calls),{'status':'camera-plane-candidate'}))
    frames=[{'frame_index':i*30,'t':float(i),'lines':[]} for i in range(12)]
    h,quality=estimate_temporal_road_camera(frames,road)
    assert h is None and quality['status']=='temporal-road-disagreement'
    assert quality['temporal']['time_blocks'][1]['shape_disagreement']>.08


def test_temporal_short_or_invalid_inputs_never_invent_calibration():
    road=[[1,1],[1278,1],[1278,718],[1,718]]
    assert estimate_temporal_road_camera([],road)[0] is None
    frames=[{'frame_index':i,'t':i*.001,'lines':[]} for i in range(6)]
    assert estimate_temporal_road_camera(frames,road)[0] is None
    frames[-1]['t']=float('nan')
    with pytest.raises(ValueError,match='finite'):estimate_temporal_road_camera(frames,road)
    with pytest.raises(ValueError,match='at most 21'):persistent_road_lines([{}]*22)
