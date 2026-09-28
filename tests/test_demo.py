"""Calibration-free demo: estimated geometry and synthetic demand never become observations."""
import copy
import io
import json
import zipfile

import numpy as np
import pytest

from test_site_profiles import make_source, routed
from theiatron.demo_profiles import propose, ground_mapping
from theiatron.site_profiles import load_profile, revise
from theiatron.sumo_demo import Scenario, generated_profile_demand, preflight, run, verify_bundle


def test_automatic_sketch_preserves_observations_and_does_not_substitute_road(tmp_path):
    before=make_source(tmp_path)
    p=propose(tmp_path,'source')
    assert p['source']==before['source']
    assert p['review_status']=='draft-unreviewed'
    assert p['demo_proposal']['basis']=='camera-direction-sketch'
    assert p['demo_proposal']['road']==[]
    assert all(a['exit'] and a['exit']!=a['id'] for a in p['approaches'])
    assert load_profile(tmp_path,p['revision'])==p
    assert propose(tmp_path,'source')==p
    with pytest.raises(ValueError):
        revise(tmp_path,p['revision'],{'demo_proposal':{}})


def test_proposal_uses_same_ground_mapping_and_preserves_footprint(tmp_path,monkeypatch):
    before=make_source(tmp_path)
    c={'anchors':[[200,100],[1080,100],[1080,680],[200,680]],'width_m':80.,'depth_m':60.,
       'road':[[100,50],[1180,50],[1180,700],[100,700]],'label':'Estimated test plane'}
    binding={'source_run':'source','source_sha256':before['source']['video_sha256']}
    r={'stale':False,'revision':'b'*64,'ground_projection':c,'calibration':c}
    monkeypatch.setattr('theiatron.demo_profiles.source',lambda *_:{'refinement':r,'binding':binding})
    p=propose(tmp_path,'source');g=p['demo_proposal'];project=ground_mapping(c)
    assert g['basis']=='camera-estimated-ground'
    assert len(g['road'])==len(c['road'])
    for original,mapped in zip(c['road'],g['road']):
        expected=project(original)-g['origin_ground']
        assert np.allclose(mapped,[expected[0],-expected[1]],atol=.00001)
    assert p['source']==before['source']
    assert c['road']==r['calibration']['road']
    r['stale']=True
    assert propose(tmp_path,'source')['demo_proposal']['road']==[]


@pytest.mark.parametrize('kwargs',[
    {'site_revision':'a'*64,'demand':'tidal'},
    {'site_revision':'a'*64,'demand':'observed','generated_demand':True},
    {'generated_demand':True},
    {'site_revision':'a'*64,'generated_demand':'true'},
    {'site_revision':'a'*64,'demand':'observed','scale':2},
])
def test_explicit_synthetic_mode_cannot_loosen_observed_contract(kwargs):
    with pytest.raises(ValueError):Scenario(**kwargs)


def test_generated_population_is_reproducible_and_disjoint(tmp_path):
    p=routed(tmp_path,make_source(tmp_path));before=copy.deepcopy(p)
    s=Scenario(duration=90,site_revision=p['revision'],generated_demand=True,demand='tidal',pace=0)
    a=generated_profile_demand(tmp_path,p,s)
    assert a==generated_profile_demand(tmp_path,p,s)
    b=generated_profile_demand(tmp_path,p,Scenario(duration=90,site_revision=p['revision'],generated_demand=True,seed=43,pace=0))
    assert a!=b and p==before
    assert set(e['id'] for e in a).isdisjoint(e['id'] for e in p['source']['events'])
    assert all(0<=e['depart']<90 and e['demand_basis']=='generated-not-observed' for e in a)


def test_real_generated_sumo_evidence_is_separate_from_observed(tmp_path):
    if not preflight()['ready']:pytest.skip('SUMO unavailable')
    make_source(tmp_path);p=propose(tmp_path,'source')
    s=Scenario(duration=60,site_revision=p['revision'],generated_demand=True,demand='balanced',pace=0)
    r=run(tmp_path/'experiment',s,p)
    assert r['evidence_level']=='generated-demand-network-hypothesis'
    assert r['demand_basis']=='generated-not-observed'
    assert r['reduction_pct'] is None
    assert r['impact_status']=='not-validated' and r['assumed_tail_s'] is None
    assert r['observed_counts']==p['source']['counts']
    assert r['metrics']['fixed']['offered']==r['metrics']['adaptive']['offered']
    assert all(m['conserved'] for m in r['metrics'].values())
    assert verify_bundle(tmp_path/'experiment')['artifact_id']==r['artifact_id']


def test_evidence_export_is_complete_and_fails_on_tampering(tmp_path,monkeypatch):
    import launcher_server as server
    from theiatron.sumo_demo import digest,object_hash
    monkeypatch.setattr(server,'ROOT',tmp_path)
    monkeypatch.setattr(server,'JOBS',{'test':{'kind':'sumo','state':'complete'}})
    path=tmp_path/'out/test';path.mkdir(parents=True)
    (path/'demand.json').write_text('[]')
    report={'files':{'demand.json':digest(path/'demand.json')}}
    report['artifact_id']=object_hash(report)
    (path/'report.json').write_text(json.dumps(report))
    with zipfile.ZipFile(io.BytesIO(server._evidence_zip('test'))) as archive:
        assert set(archive.namelist())=={'demand.json','report.json'}
        assert json.loads(archive.read('report.json'))==report
    (path/'demand.json').write_text('[1]')
    with pytest.raises(ValueError,match='checksum'):server._evidence_zip('test')
    (path/'demand.json').unlink();(path/'demand.json').symlink_to(path/'report.json')
    with pytest.raises(ValueError,match='unavailable'):server._evidence_zip('test')
