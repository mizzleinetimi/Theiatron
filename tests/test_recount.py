"""Camera commissioning inputs are immutable candidates, never user file paths."""
import copy
import json

import pytest
from test_site_profiles import make_source
from theiatron.recount import counting_source, seal_camera, load_camera


@pytest.fixture
def source(tmp_path):
    make_source(tmp_path)
    return counting_source(tmp_path,'source')


def test_camera_edits_do_not_change_original_or_inference_settings(tmp_path,source):
    first = seal_camera(tmp_path,'source',source['approaches'])
    edits = copy.deepcopy(source['approaches'])
    edits[0]['count_line'][0][0] += 10
    edited = seal_camera(tmp_path,'source',edits)
    assert first['revision'] != edited['revision']
    assert load_camera(tmp_path,first['revision']) == first
    assert edited['config']['vision'] == source['config']['vision']
    assert edited['config']['approaches'][0]['count_line'] == edits[0]['count_line']
    assert edited['source_artifact_id'] == source['source_artifact_id']
    assert edited['review_status'] == 'manual-candidate-unreviewed'
    assert counting_source(tmp_path,'source') == source


@pytest.mark.parametrize('key,value', [('name','other'),('video','/etc/passwd'),
    ('phase','invalid'),('count_line',[[1,1],[2,2]]),('count_line',[[0,0],[1300,719]]),
    ('approach_side',[640,100]),('approach_side',[True,50]),('approach_side',[1,float('nan')]),
    ('count_line',[]),('approach_side',None)])
def test_bad_counting_edits_rejected(tmp_path,source,key,value):
    edits = copy.deepcopy(source['approaches'])
    edits[0][key] = value
    with pytest.raises(ValueError):
        seal_camera(tmp_path,'source',edits)


def test_order_length_checksum_and_symlink_guards(tmp_path,source):
    edits = copy.deepcopy(source['approaches'])
    for a in edits:
        a['approach_side'][1] += 10
    with pytest.raises(ValueError):
        seal_camera(tmp_path,'source',edits[:2])
    with pytest.raises(ValueError):
        seal_camera(tmp_path,'source',list(reversed(edits)))
    good = seal_camera(tmp_path,'source',edits)
    path = tmp_path/'out'/'.camera-profiles'/(good['revision']+'.json')
    changed = json.loads(path.read_text());changed['duration']+=1
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError,match='checksum'):
        load_camera(tmp_path,good['revision'])
    with pytest.raises(ValueError):
        counting_source(tmp_path,'../../outside')


def test_single_inference_full_clip_is_recountable_but_unseen_offset_is_not(tmp_path,source):
    from theiatron.artifacts import fingerprint,load_artifact,save_artifact
    path=tmp_path/'out'/'source'/'simulation.json'
    artifact=load_artifact(path)
    for scope in ('full-single-inference-pass','unseen'):
        artifact['source_meta']['evaluation_scope']=scope
        artifact.pop('artifact_id')
        artifact['artifact_id']=fingerprint(artifact)
        save_artifact(artifact,path)
        if scope=='unseen':
            with pytest.raises(ValueError,match='offset evaluation window'):
                counting_source(tmp_path,'source')
        else:
            assert counting_source(tmp_path,'source')['duration']==source['duration']


def test_recount_runs_fresh_detector_with_edited_lines_and_keeps_parent(tmp_path,source,monkeypatch):
    import numpy as np
    import theiatron.recount as worker
    import run_demo
    from theiatron.detection import Detection
    from theiatron.artifacts import load_artifact
    video=tmp_path/'clip.mov';video.write_bytes(b'local video placeholder')
    raw_hash=worker.file_hash
    monkeypatch.setattr(worker,'file_hash',lambda p: 'a'*64 if p==video else raw_hash(p))
    monkeypatch.setattr(worker,'vision_provenance',lambda _: {'code_sha256':{}})
    class Feed:
        dt=1
        def __init__(self,*a,**k): self.closed=False
        def read(self): return np.zeros((720,1280,3),dtype=np.uint8),False
        def release(self): self.closed=True
    calls=[]
    class Detector:
        def __init__(self,*a): self.n=0;calls.append(self)
        def track(self,frame):
            self.n+=1
            y=[140,120,90][min(2,self.n-1)]
            return [Detection(1,640,y,(630,y-20,650,y),2,.9)]
    class Writer:
        def __init__(self,*a): pass
        def isOpened(self): return True
        def write(self,frame): pass
        def release(self): pass
    monkeypatch.setattr('theiatron.feeds.VideoFeed',Feed)
    monkeypatch.setattr('theiatron.detection.VehicleDetector',Detector)
    monkeypatch.setattr('cv2.VideoWriter',Writer)
    monkeypatch.setattr(run_demo,'_transcode_3d_footage',lambda *a: (True,'mocked encoding'))
    monkeypatch.setattr(run_demo,'_export_3d_timeline',lambda *a: (True,'mocked export'))
    before=load_artifact(tmp_path/'out'/'source'/'simulation.json')
    first=seal_camera(tmp_path,'source',source['approaches'])
    manifest=worker.recount(tmp_path,first['revision'],video,tmp_path/'first')
    assert manifest['events']==1 and calls[0].n==35
    dense=json.loads((tmp_path/'first'/'recorded-tracks.json').read_text())
    assert len(dense['tracks'][0]['samples'])==35
    assert dense['tracks'][0]['class_id']==2
    artifact=load_artifact(tmp_path/'first'/'simulation.json')
    assert artifact['source_meta']['camera_revision']==first['revision']
    assert artifact['source_meta']['parent_artifact_id']==source['source_artifact_id']
    assert artifact['scenarios']['theiatron']['vehicles'][0]['t0']==3
    edits=copy.deepcopy(source['approaches'])
    edits[0]['count_line']=[[620,200],[660,200]]
    edits[0]['approach_side']=[640,210]
    second=seal_camera(tmp_path,'source',edits)
    manifest=worker.recount(tmp_path,second['revision'],video,tmp_path/'second')
    assert manifest['events']==0 and len(calls)==2 and calls[1].n==35
    assert load_artifact(tmp_path/'out'/'source'/'simulation.json')==before


def test_recount_rejects_changed_raw_footage_before_inference(tmp_path,source):
    from theiatron.recount import recount
    profile=seal_camera(tmp_path,'source',source['approaches'])
    video=tmp_path/'clip.mov';video.write_bytes(b'not the fingerprinted source')
    with pytest.raises(ValueError,match='footage checksum'):
        recount(tmp_path,profile['revision'],video,tmp_path/'failed')
    assert not (tmp_path/'failed').exists()
