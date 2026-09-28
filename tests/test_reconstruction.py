import copy
import json

import pytest

from test_site_profiles import make_source
from theiatron.reconstruction import source, save, validate, default_calibration, IMG_0635_SHA


def test_live_geometry_is_source_bound_and_contains_no_saved_vehicle_motion(monkeypatch):
    from theiatron import reconstruction as module
    calibration = default_calibration(IMG_0635_SHA)
    refinement = {'revision': 'revision-1', 'stale': False, 'calibration': calibration,
                  'ground_projection': calibration,
                  'camera_registration': {'frames': [
                      {'frame_index': 2, 'status': 'reference', 'H': [[1,0,0],[0,1,0],[0,0,1]]},
                      {'frame_index': 5, 'status': 'rejected', 'H': None}]}}
    data = {'binding': {'source_run': 'source', 'source_sha256': 'a'*64},
            'image_size': [1280,720], 'calibration': calibration, 'refinement': refinement,
            'plate_reference_supported': True, 'video_offset_s': .1,
            'tracks': {'SECRET_TRACKS': [1,2,3]}}
    monkeypatch.setattr(module, 'source', lambda *args: data)
    result = module.live_geometry(None, 'source')
    assert result['binding'] == data['binding']
    assert result['registration'][1]['H'] is None
    assert result['geometry_revision'] == 'revision-1'
    assert result['projection_kind'] == 'automatic-estimate'
    assert result['registration_cadence_s'] == .1
    assert 'tracks' not in result and 'SECRET_TRACKS' not in json.dumps(result)
    assert result['metric_accuracy_validated'] is False
    refinement['stale'] = True
    with pytest.raises(ValueError, match='Fresh'): module.live_geometry(None, 'source')
    refinement['stale'] = False
    refinement['camera_registration'] = None
    with pytest.raises(ValueError, match='registration'): module.live_geometry(None, 'source')
    refinement['ground_projection'] = None
    refinement['ground_quality'] = {'status':'insufficient-direction-support'}
    with pytest.raises(ValueError, match='Camera perspective is unresolved'): module.live_geometry(None, 'source')


def install_live_registration(root):
    """Synthetic, checksummed registration: no actual camera validation implied."""
    from theiatron import reconstruction, refinement, camera_registration, ground_plane
    from theiatron.artifacts import fingerprint
    from theiatron.provenance import file_hash
    from pathlib import Path
    current = reconstruction.source(root, 'source')
    result = {'binding': current['binding'], 'calibration_revision': current['revision'],
              'input_calibration_sha256': fingerprint(current['calibration']),
              'code_sha256': file_hash(Path(refinement.__file__)),
              'camera_code_sha256': file_hash(Path(camera_registration.__file__)),
              'ground_code_sha256': file_hash(Path(ground_plane.__file__)),
              'ground_projection': None, 'ground_quality': {'status': 'unstable-road-perspective'},
              # Deliberately different automatic road: assistance must win intact.
              'calibration': default_calibration(IMG_0635_SHA),
              'camera_registration': {'frames': [
                  {'frame_index': 2, 'status': 'reference', 'H': [[1,0,0],[0,1,0],[0,0,1]]},
                  {'frame_index': 5, 'status': 'rejected', 'H': None}]},
              'tracks': {'NEVER_SEND_SAVED_MOTION': [1,2,3]}}
    result['revision'] = fingerprint(result)
    directory = root/'out'/'.reconstructions'/current['identity']
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'automatic.json').write_text(json.dumps(result))
    return result


@pytest.fixture
def assisted_live(tmp_path, recorded):
    from theiatron import reconstruction
    from test_assisted_geometry import selection
    (tmp_path/'out'/'source'/'manifest.json').write_text(json.dumps({'three_d': {'plate_mode': 'first-processed-frame'}}))
    lines, base = selection()
    request = {'binding': recorded['binding'], 'base_revision': None, 'calibration': base, 'lines': lines}
    reconstruction.save_assisted(tmp_path, 'source', request)
    install_live_registration(tmp_path)
    return reconstruction.source(tmp_path, 'source')


def test_live_assistance_reproduces_saved_fit_without_automatic_override(tmp_path, assisted_live):
    from theiatron import reconstruction
    from theiatron.provenance import file_hash
    tracks = tmp_path/'out'/'source'/'tracks.json'
    before = file_hash(tracks)
    result = reconstruction.live_geometry(tmp_path, 'source')
    assert result['calibration'] == assisted_live['calibration']
    assert result['projection_kind'] == 'operator-assisted-estimate'
    assert result['calibration_revision'] == assisted_live['revision']
    assert result['registration_revision'] == assisted_live['refinement']['revision']
    assert result['geometry_revision'] not in {result['calibration_revision'], result['registration_revision']}
    assert result['physical_scale_measured'] is False
    assert result['metric_accuracy_validated'] is False
    assert result['projection_assumptions'] == assisted_live['assistance']['quality']['assumptions']
    assert 'tracks' not in result and 'NEVER_SEND_SAVED_MOTION' not in json.dumps(result)
    assert file_hash(tracks) == before


@pytest.mark.parametrize('mutation', ['stale-refinement', 'method', 'code', 'ground-code', 'quality',
                                     'calibration', 'no-registration', 'no-supported-frames', 'composite-plate'])
def test_assisted_live_rejects_stale_or_inconsistent_evidence(monkeypatch, tmp_path, assisted_live, mutation):
    from theiatron import reconstruction
    data = copy.deepcopy(assisted_live)
    if mutation == 'stale-refinement': data['refinement']['stale'] = True
    elif mutation == 'method': data['assistance']['method'] = 'manual-approval'
    elif mutation == 'code': data['assistance']['code_sha256'] = 'old'
    elif mutation == 'ground-code': data['assistance']['ground_code_sha256'] = 'old'
    elif mutation == 'quality': data['assistance']['quality']['sensitivity']['accepted'] -= 1
    elif mutation == 'calibration': data['calibration']['width_m'] += 1
    elif mutation == 'no-registration': data['refinement']['camera_registration'] = None
    elif mutation == 'no-supported-frames': data['refinement']['camera_registration']['frames'] = [
        {'frame_index': 2, 'status': 'rejected', 'H': None}]
    else: data['plate_reference_supported'] = False
    monkeypatch.setattr(reconstruction, 'source', lambda *_: data)
    with pytest.raises(ValueError): reconstruction.live_geometry(tmp_path, 'source')


def test_later_manual_save_does_not_inherit_assisted_live_approval(tmp_path, assisted_live):
    from theiatron import reconstruction
    reconstruction.save(tmp_path, 'source', {'binding': assisted_live['binding'], 'calibration': assisted_live['calibration']})
    with pytest.raises(ValueError, match='Fresh'): reconstruction.live_geometry(tmp_path, 'source')
    install_live_registration(tmp_path)
    with pytest.raises(ValueError, match='Camera perspective is unresolved'):
        reconstruction.live_geometry(tmp_path, 'source')


@pytest.fixture
def recorded(tmp_path):
    make_source(tmp_path)
    (tmp_path/'out'/'source'/'tracks.json').write_text(json.dumps({'counted':[], 'extras':[{'pts':[[1,400,400],[1.1,410,400]]}]}))
    (tmp_path/'out'/'source'/'plate.jpg').write_bytes(b'camera plate')
    return source(tmp_path,'source')


def test_no_sample_geometry_for_unknown_camera(recorded):
    assert recorded['calibration']['road']==[]
    assert recorded['metric_accuracy_validated'] is False
    assert recorded['track_anchor']=='detector-bottom-centre'
    assert recorded['tracks']['extras'][0]['pts'][0]==[1,400,400]
    assert default_calibration(IMG_0635_SHA)['road']
    assert recorded['default_projection_kind']=='unrectified-image-plane'


def test_unknown_camera_preview_does_not_invent_a_horizon_or_reject_frame_edges():
    draft=default_calibration('a'*64)
    draft['road']=[[0,0],[1279,0],[1279,719],[0,719]]
    assert validate(draft)==draft
    anchors=draft['anchors']
    assert anchors[0][0]==anchors[3][0] and anchors[1][0]==anchors[2][0]
    # Uniform pixels per nominal display metre, not metric calibration.
    assert (anchors[1][0]-anchors[0][0])/draft['width_m'] == (anchors[3][1]-anchors[0][1])/draft['depth_m']


def test_ground_below_an_in_image_horizon_is_not_rejected_by_matrix_sign():
    anchors=[[500,400],[780,400],[920,650],[360,650]]
    draft={'anchors':anchors,'road':anchors,'width_m':12,'depth_m':20,'label':'Perspective test'}
    assert validate(draft)==draft
    draft['road']=[[500,100],[780,100],[920,650],[360,650]]
    with pytest.raises(ValueError,match='horizon'):validate(draft)


def test_source_bound_immutable_drafts(tmp_path,recorded):
    calibration=default_calibration(IMG_0635_SHA)
    first=save(tmp_path,'source',{'binding':recorded['binding'],'calibration':calibration})
    assert source(tmp_path,'source')['revision']==first['revision']
    calibration['width_m']=51
    second=save(tmp_path,'source',{'binding':recorded['binding'],'calibration':calibration})
    assert first['revision']!=second['revision']
    directory=tmp_path/'out'/'.reconstructions'/recorded['identity']
    assert json.loads((directory/(first['revision']+'.json')).read_text())==first
    assert source(tmp_path,'source')['calibration']['width_m']==51
    assert second['status']=='draft-unvalidated'
    # A modified source must not silently inherit the old calibration.
    (tmp_path/'out'/'source'/'tracks.json').write_text('{"counted":[],"extras":[]}')
    changed=source(tmp_path,'source')
    assert changed['revision'] is None and changed['identity']!=recorded['identity']
    with pytest.raises(ValueError,match='source changed'):
        save(tmp_path,'source',{'binding':recorded['binding'],'calibration':calibration})


@pytest.mark.parametrize('key,value', [('width_m',True),('depth_m',float('nan')),('width_m',151),
    ('anchors',[[0,0],[100,100],[0,100],[100,0]]),('anchors',[[0,0]]*4),('road',[]),
    ('road',[[0,0],[100,100],[0,100],[100,0]]),('road',[[0,0],[0,0],[100,100]]),
    ('road',[[0,0],[1300,20],[0,600]]),('reviewed',True),('label','')])
def test_invalid_calibration_rejected(key,value):
    draft=default_calibration(IMG_0635_SHA);draft[key]=value
    with pytest.raises(ValueError): validate(draft)


def test_checksum_and_path_guards(tmp_path,recorded):
    result=save(tmp_path,'source',{'binding':recorded['binding'],'calibration':default_calibration(IMG_0635_SHA)})
    path=tmp_path/'out'/'.reconstructions'/recorded['identity']/'latest.json'
    broken=copy.deepcopy(result);broken['calibration']['width_m']+=1;path.write_text(json.dumps(broken))
    with pytest.raises(ValueError,match='checksum'): source(tmp_path,'source')
    with pytest.raises(ValueError): source(tmp_path,'../source')
    with pytest.raises(ValueError): source(tmp_path,'/etc/passwd')
    tracks=tmp_path/'out'/'source'/'tracks.json';tracks.unlink();tracks.symlink_to(path)
    with pytest.raises(ValueError,match='symlink'): source(tmp_path,'source')


def test_dense_recording_keeps_stationary_samples_boxes_classes_and_original_clock(tmp_path,recorded):
    from types import SimpleNamespace
    from theiatron.recorded_tracks import RecordedTracks
    from theiatron.detection import Detection
    dense=RecordedTracks()
    for t,cls in [(0.100046,2),(0.200092,2),(0.300138,7)]:
        dense.update(t,[Detection(12,400.1234,500.5678,(380,440,420,500.5678),cls,.812345)])
    result=dense.export({'north':SimpleNamespace(count_num={12:1})})
    r=result['tracks'][0]
    assert len(r['samples'])==3
    assert r['class_id']==2 and r['class_consistency']==2/3
    assert r['samples'][0]['t']==0.100046
    assert r['samples'][0]['anchor']==[400.1234,500.5678]
    assert r['samples'][2]['class_id']==7
    assert r['samples'][0]['box']==[380,440,420,500.5678]
    (tmp_path/'out'/'source'/'recorded-tracks.json').write_text(json.dumps(result))
    fresh=source(tmp_path,'source')
    assert fresh['track_sampling']=='dense-processed-frames'
    assert fresh['tracks']['counted'][0]['id']=='track:12'
    assert fresh['tracks']['counted'][0]['pts'][0]==[0.100046,400.1234,500.5678]
    assert fresh['identity']!=recorded['identity']
