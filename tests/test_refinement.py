"""Automatic reconstruction estimates must preserve observations and uncertainty."""
import copy
import json

import cv2
import numpy as np
import pytest

from test_site_profiles import make_source
from theiatron import refinement
from theiatron.reconstruction import source, save


def track(points, times=None, identity='1', counted=True):
    points = np.asarray(points, dtype=float)
    times = np.arange(len(points)) / 10 if times is None else times
    return {
        'id': identity, 'approach': 'north' if counted else None,
        'count_number': 1 if counted else None, 'class_id': 2,
        'class_consistency': 1., 'mean_confidence': .9,
        'samples': [
            {'t': float(t), 'anchor': [float(x), float(y)],
             'box': [float(x-25), float(y-60), float(x+25), float(y)],
             'confidence': .9, 'class_id': 2}
            for t, (x, y) in zip(times, points)
        ],
    }


def payload(tracks):
    return {'schema_version': 1, 'image_size': [1280, 720], 'tracks': tracks}


def coordinates(result):
    return np.asarray(result['pts'])[:, 1:]


def test_camera_compensation_preserves_evidence_and_splits_a_single_rejected_frame():
    native = track([[100+i*3, 500] for i in range(8)], times=np.arange(1,9)/10)
    dense = payload([native]); original = copy.deepcopy(dense)
    registration = {'frames': [dict(t=s['t'], status='accepted',
        H=[[1,0,-i*3],[0,1,0],[0,0,1]]) for i,s in enumerate(native['samples'])]}
    registration['frames'][3].update(status='rejected', H=None)
    compensated, omitted = refinement.compensate_tracks(dense, registration)
    assert dense == original and omitted == 1
    samples = compensated['tracks'][0]['samples']
    assert all(s['anchor'] == [100.,500.] for s in samples)
    assert all(s['box'] == [75.,440.,125.,500.] for s in samples)
    assert samples[3]['t'] == .5 and samples[3]['break_before']
    filtered = refinement.filter_track(compensated['tracks'][0])
    assert filtered['breaks'] == [.5]
    assert len(filtered['pts']) == 7


def test_unsupported_camera_projection_never_falls_back_to_raw():
    dense = payload([track([[100,500]], times=[.1])])
    for h in (None, [[1,0,1e6],[0,1,0],[0,0,1]], [[1,0,0],[0,1,0],[0,0,-1]]):
        compensated, omitted = refinement.compensate_tracks(dense,
            {'frames':[dict(t=.1,status='accepted',H=h)]})
        assert omitted == 1 and compensated['tracks'] == []


@pytest.mark.parametrize('kind', ['linear', 'turn'])
def test_rts_reduces_jitter_without_straightening_a_real_turn(kind):
    times = np.arange(101) / 10
    truth = np.c_[100+10*times, 300+3*times] if kind == 'linear' else np.c_[
        200+70*np.sin(times/5), 350+70*(1-np.cos(times/5))]
    noisy = truth + np.random.default_rng(39).normal(0, 3, truth.shape)
    result = refinement.filter_track(track(noisy, times))
    estimated = coordinates(result)
    raw_rmse = np.sqrt(np.mean((noisy-truth)**2))
    estimated_rmse = np.sqrt(np.mean((estimated-truth)**2))
    assert estimated_rmse < raw_rmse * .5
    assert np.max(np.linalg.norm(estimated-truth, axis=1)) < 5
    assert result['breaks'] == []
    assert np.allclose(np.asarray(result['pts'])[:, 0], times)


def test_slow_motion_is_not_snapped_into_stationary_plateaus():
    times = np.arange(101) / 10
    truth = np.c_[100+times, 300+times*.2]
    result = refinement.filter_track(track(truth, times))
    estimated = coordinates(result)
    assert np.all(np.diff(estimated[:, 0]) > .01)
    assert np.linalg.norm((estimated[-1]-estimated[0])-(truth[-1]-truth[0])) < .5
    assert result['diagnostics']['stationary_samples'] == 0


def test_stationary_jitter_reduction_does_not_claim_ground_accuracy():
    truth = np.tile([400., 500.], (101, 1))
    noisy = truth + np.random.default_rng(192).normal(0, 3, truth.shape)
    result = refinement.filter_track(track(noisy))
    assert np.sqrt(np.mean((coordinates(result)-truth)**2)) < 1.3
    before = result['diagnostics']['raw_second_difference_px']
    after = result['diagnostics']['filtered_second_difference_px']
    assert np.median(after) < np.median(before) * .1


def test_isolated_excursion_rejected_but_original_samples_unchanged():
    times = np.arange(101) / 10
    points = np.c_[100+10*times, 300+3*times]
    points[51] += [150, -120]
    original = track(points, times)
    before = copy.deepcopy(original)
    result = refinement.filter_track(original)
    assert original == before
    assert result['outlier_times'] == [5.1]
    assert result['breaks'] == []
    assert result['raw_pts'][51] == [5.1, *points[51]]
    assert np.linalg.norm(coordinates(result)[51]-[151, 315.3]) < 2
    assert (result['id'], result['a'], result['n']) == ('track:1', 'north', 1)


def test_gaps_and_sustained_identity_jumps_create_independent_segments():
    local = np.arange(20) / 10
    times = np.r_[local, local+2, local+6]
    x = np.r_[100+local*20, 500+local*20, 800+local*20]
    points = np.c_[x, np.full(len(x), 500.)]
    result = refinement.filter_track(track(points, times))
    assert result['breaks'] == [2., 6.]
    assert result['diagnostics']['breaks'] == 2
    assert result['outlier_times'] == []
    assert np.max(np.linalg.norm(coordinates(result)-points, axis=1)) < 2
    # Nothing invents intermediate observations through an occluded gap.
    assert len(result['pts']) == len(times)
    assert not any(3.9 < p[0] < 6 for p in result['pts'])


def test_short_track_is_preserved_and_no_identity_is_joined():
    original = track([[200, 400], [202, 401], [204, 402]], identity='legacy:12', counted=False)
    result = refinement.filter_track(original)
    assert result['pts'] == result['raw_pts']
    assert result['id'] == 'track:legacy:12'
    assert result['a'] is None and result['n'] is None


@pytest.mark.parametrize('key,value', [
    ('confidence', float('nan')), ('confidence', float('inf')),
    ('confidence', -.1), ('confidence', 1.1), ('confidence', True),
    ('box', [0, 0, 30, float('nan')]), ('box', [0, 40, 30, 20]),
    ('box', [20, 0, 20, 40]), ('box', [20, 0, 30]),
    ('anchor', [float('inf'), 400]), ('anchor', [100]),
    ('t', float('nan')), ('t', -.1), ('t', 0.), ('t', True),
])
def test_malformed_observations_fail_closed(key, value):
    original = track([[100+i, 400] for i in range(8)])
    original['samples'][4][key] = value
    with pytest.raises(ValueError):
        refinement.filter_track(original)


@pytest.mark.parametrize('samples', [[], None, 'not observations'])
def test_missing_observations_fail_closed(samples):
    original = track([[100, 400]])
    original['samples'] = samples
    with pytest.raises(ValueError):
        refinement.filter_track(original)


def perspective_tracks(same_line=False):
    result = []
    for i in range(6):
        x = 640 if same_line else 150+i*150
        points = [[x, y] for y in np.linspace(350, 650, 50)]
        native = track(points, identity=str(i))
        for sample in native['samples']:
            y = sample['anchor'][1]
            sample['box'] = [float(x-20), y-(y-200)*.2, float(x+20), y]
        result.append(native)
    return result


def test_projective_size_cues_never_establish_absolute_metres():
    polygon = [[100, 320], [1100, 320], [1100, 700], [100, 700]]
    horizon, report = refinement.perspective_proposal(payload(perspective_tracks()), polygon)
    assert horizon is not None
    assert report['status'] == 'projective-candidate'
    assert report['metric_scale'] == 'unobservable-without-reference'
    # Synthetic depth data was generated against the image horizon y = 200.
    assert abs(-horizon[2]/horizon[1]*720-200) < 1e-6


def test_degenerate_or_missing_perspective_support_remains_uncalibrated():
    polygon = [[560, 400], [740, 400], [740, 690], [560, 690]]
    for tracks in ([], perspective_tracks()[:4], perspective_tracks(same_line=True)):
        horizon, report = refinement.perspective_proposal(payload(tracks), polygon)
        assert horizon is None
        assert report['status'] == 'reference-needed'
        assert report['metric_scale'] == 'unobservable-without-reference'


def test_a_horizon_crossing_the_road_is_rejected():
    horizon, report = refinement.perspective_proposal(payload(perspective_tracks()),
        [[100, 100], [1100, 100], [1100, 700], [100, 700]])
    assert horizon is None
    assert report['status'] == 'reference-needed'


def test_no_road_geometry_is_invented_without_motion_support():
    frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
    native = track([[400, 500]]*30)
    polygon, report = refinement.road_proposal(frame, payload([native]), [refinement.filter_track(native)])
    assert polygon is None
    assert report['status'] == 'insufficient-motion'


def test_motion_supported_road_is_only_a_bounded_appearance_candidate():
    frame = np.full((720, 1280, 3), [25, 120, 30], dtype=np.uint8)
    cv2.rectangle(frame, (100, 380), (1180, 680), (90, 90, 90), -1)
    natives = [track([[x, 440+i*50] for x in np.linspace(150, 1100, 80)],
        identity=f'legacy:{i}') for i in range(4)]
    refined = [refinement.filter_track(t) for t in natives]
    polygon, report = refinement.road_proposal(frame, payload(natives), refined)
    assert polygon and 3 <= len(polygon) <= 95
    assert all(0 <= x <= 1279 and 0 <= y <= 719 for x, y in polygon)
    assert report['status'] == 'automatic-candidate'
    assert report['motion_support_coverage'] >= .65
    assert 'not road-boundary accuracy' in report['note']


@pytest.fixture
def dense_source(tmp_path):
    make_source(tmp_path)
    directory = tmp_path/'out'/'source'
    native = track([[400+i, 500] for i in range(30)])
    (directory/'recorded-tracks.json').write_text(json.dumps(payload([native])))
    cv2.imwrite(str(directory/'plate.jpg'), np.full((720, 1280, 3), 100, np.uint8))
    return source(tmp_path, 'source')


def test_build_is_source_bound_cached_and_does_not_edit_observations(tmp_path, dense_source, monkeypatch):
    calls = []
    polygon = [[250, 420], [1000, 420], [1050, 650], [200, 650]]
    def proposal(*_):
        calls.append(True)
        return copy.deepcopy(polygon), {'status': 'automatic-candidate'}
    monkeypatch.setattr(refinement, 'road_proposal', proposal)
    directory = tmp_path/'out'/'source'
    original = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    first = refinement.build(tmp_path, 'source', dense_source['binding'])
    repeated = refinement.build(tmp_path, 'source', dense_source['binding'])
    assert repeated == first
    assert len(calls) == 1
    assert first['metric_accuracy_validated'] is False
    assert first['status'] == 'automatic-estimates-unvalidated'
    assert first['perspective']['metric_scale'] == 'unobservable-without-reference'
    assert {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()} == original
    calibration = copy.deepcopy(first['calibration'])
    calibration['width_m'] = 45
    saved = save(tmp_path, 'source', {'binding': dense_source['binding'], 'calibration': calibration})
    edited = refinement.build(tmp_path, 'source', dense_source['binding'])
    assert len(calls) == 2
    assert edited['calibration']['width_m'] == 45
    assert edited['revision'] != first['revision']
    assert edited['calibration_revision'] == saved['revision']
    assert edited['tracks'] == first['tracks']


def test_changed_source_binding_and_tampered_cache_are_rejected(tmp_path, dense_source, monkeypatch):
    monkeypatch.setattr(refinement, 'road_proposal', lambda *_: (None, {'status': 'insufficient-motion'}))
    result = refinement.build(tmp_path, 'source', dense_source['binding'])
    cache = tmp_path/'out'/'.reconstructions'/dense_source['identity']
    target = next(cache.glob('*.refinement.json'))
    damaged = copy.deepcopy(result)
    damaged['diagnostics']['samples'] += 100
    target.write_text(json.dumps(damaged))
    with pytest.raises(ValueError, match='checksum'):
        refinement.build(tmp_path, 'source', dense_source['binding'])
    (tmp_path/'out'/'source'/'plate.jpg').write_bytes(b'changed reference')
    with pytest.raises(ValueError, match='source changed'):
        refinement.build(tmp_path, 'source', dense_source['binding'])


def test_refinement_cache_symlinks_are_rejected(tmp_path, dense_source):
    cache = tmp_path/'out'/'.reconstructions'/dense_source['identity']
    cache.mkdir(parents=True)
    (cache/'automatic.json').symlink_to(tmp_path/'elsewhere.json')
    with pytest.raises(ValueError, match='symlink'):
        refinement.build(tmp_path, 'source', dense_source['binding'])


def test_track_and_total_observation_budgets_fail_closed(monkeypatch):
    natives = [track([[100+i, 400] for i in range(4)], identity=str(n)) for n in range(3)]
    monkeypatch.setattr(refinement, 'MAX_TRACKS', 2)
    with pytest.raises(ValueError, match='at most 1000 tracks'):
        refinement._validate_dense(payload(natives))
    monkeypatch.setattr(refinement, 'MAX_TRACKS', 1000)
    monkeypatch.setattr(refinement, 'MAX_SAMPLES', 10)
    with pytest.raises(ValueError, match='at most 100000 samples'):
        refinement._validate_dense(payload(natives))
    with pytest.raises(ValueError, match='duplicate'):
        refinement._validate_dense(payload([natives[0], natives[0]]))


def test_temporal_evidence_uses_only_exact_accepted_native_frames(monkeypatch):
    from theiatron import ground_plane
    requested=[];segments=[];released=[]
    class Capture:
        index=0
        def set(self,key,value):self.index=value;requested.append(value)
        def read(self):return True,np.zeros((720,1280,3),np.uint8)
        def get(self,key):return self.index+1 if self.index!=5 else 1234
        def release(self):released.append(True)
    monkeypatch.setattr(cv2,'VideoCapture',lambda _:Capture())
    def detect(frame,road,boxes,matrix):
        segments.append((boxes,matrix))
        return np.array([[100,200,500,200]])
    monkeypatch.setattr(ground_plane,'road_segments',detect)
    identity=np.eye(3).tolist()
    registration={'revision':'test-registration','frames':[
        {'frame_index':i,'t':float(i),'H':identity,'status':'accepted'} for i in range(7)]}
    registration['frames'][1]['status']='rejected'  # even a retained H must not enter
    registration['frames'][2]['H']=None
    dense=payload([track([[400,500]],times=[3.])])
    before=copy.deepcopy((dense,registration))
    frames,capture=refinement.temporal_road_evidence('unused',registration,dense,[[0,0],[1200,0],[1200,700]])
    assert [r['frame_index'] for r in frames]==[0,3,4,6]
    assert requested==[0,3,4,5,6]
    assert capture['failed_frame_indices']==[5]
    assert capture['registration_revision']=='test-registration'
    assert segments[1][0]==[dense['tracks'][0]['samples'][0]['box']]
    assert segments[1][1]==identity
    assert (dense,registration)==before and released==[True]


def test_temporal_camera_rejection_never_constructs_a_projection(monkeypatch):
    from theiatron import ground_plane
    monkeypatch.setattr(refinement,'temporal_road_evidence',lambda *_:([],{'decoded_frames':0}))
    def forbidden(*_):raise AssertionError('a rejected camera has no usable projection')
    monkeypatch.setattr(ground_plane,'calibration_from_camera',forbidden)
    candidate,quality=refinement.temporal_ground_proposal('unused',{},payload([]),{},[])
    assert candidate is None
    assert quality['status']=='insufficient-temporal-road-evidence'
    assert quality['capture']['decoded_frames']==0


def test_temporal_projection_preserves_final_geometry_guards(monkeypatch):
    from theiatron import ground_plane
    monkeypatch.setattr(refinement,'temporal_road_evidence',lambda *_:([],{'decoded_frames':12}))
    monkeypatch.setattr(ground_plane,'estimate_temporal_road_camera',lambda *_:(np.eye(3),{'status':'camera-plane-candidate'}))
    def invalid(*_):raise ValueError('reference rectangle unsupported')
    monkeypatch.setattr(ground_plane,'calibration_from_camera',invalid)
    candidate,quality=refinement.temporal_ground_proposal('unused',{},payload([]),{},[])
    assert candidate is None and quality['status']=='projection-review-needed'
    assert quality['reason']=='reference rectangle unsupported'
