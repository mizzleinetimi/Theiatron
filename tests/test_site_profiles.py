"""Footage-to-SUMO contract: never invent observations or reviewed evidence."""
import copy
import json
from pathlib import Path

import pytest

from run_demo import build_engines
from theiatron.artifacts import build_artifact, save_artifact
from theiatron.config import AppConfig, ApproachConfig, SignalConfig
from theiatron.controller import SignalState
from theiatron.observations import PhaseObservation
from theiatron.site_profiles import from_run, load_profile, revise, validate, source_horizon, IncomingStages
from theiatron.sumo_demo import Scenario, preflight, run, verify_bundle


def make_source(root):
    names = ['north', 'south', 'east', 'west']
    points = [[640, 100], [640, 620], [1100, 360], [180, 360]]
    cfg = AppConfig(approaches=[ApproachConfig(name=n, video='clip.mov',
        phase='NS' if n in names[:2] else 'EW', count_line=[[p[0]-20,p[1]],[p[0]+20,p[1]]],
        approach_side=[p[0],p[1]+10]) for n,p in zip(names,points)])
    adaptive, fixed = build_engines(cfg)
    events = [(round(1.123456 + i*2, 6), names[i%2]) for i in range(14)]
    # One at the exact integer horizon must not disappear from the cohort.
    events.append((35, 'north'))
    for engine in (adaptive, fixed):
        engine.run_replay(events, 35)
    artifact = build_artifact(cfg, adaptive, fixed, 35,
        {'kind':'live-video-analysis', 'source':'clip.mov', 'source_sha256':'a'*64,
         'evaluation_scope':'full-fresh-pass'})
    path = root/'out'/'source'
    path.mkdir(parents=True, exist_ok=True)
    save_artifact(artifact, path/'simulation.json')
    return from_run(root, 'source')


def routed(root, p):
    arms = copy.deepcopy(p['approaches'])
    opposite = {'north':'south','south':'north','east':'west','west':'east'}
    for a in arms:
        a['exit'] = opposite[a['id']]
    return revise(root, p['revision'], {'approaches':arms})


@pytest.fixture
def profile(tmp_path):
    return make_source(tmp_path)


def test_revisions_preserve_source_and_are_immutable(tmp_path, profile):
    new = routed(tmp_path, profile)
    assert new['revision'] != profile['revision']
    assert new['parent_revision'] == profile['revision']
    assert new['source'] == profile['source']
    assert load_profile(tmp_path, profile['revision']) == profile
    assert load_profile(tmp_path, new['revision']) == new
    assert source_horizon(new['source']) == 36
    validate(new, runnable=True)
    with pytest.raises(ValueError, match='explicit assumed exit'):
        validate(profile, runnable=True)


@pytest.mark.parametrize('changes', [{'review_status':'reviewed'}, {'source':{}}, {'assumptions':[]},
    {'source_checksum':'a'*64}, {'unknown':'ignored'}])
def test_cannot_edit_evidence_or_remove_limitations(tmp_path, profile, changes):
    with pytest.raises(ValueError):
        revise(tmp_path, profile['revision'], changes)


@pytest.mark.parametrize('key,value', [('enabled',False), ('x',True), ('y',float('nan')),
    ('x',301), ('lanes',1.5), ('width',8), ('speed',50), ('exit','north'), ('exit','missing')])
def test_bad_network_edits_rejected(tmp_path, profile, key, value):
    arms = copy.deepcopy(profile['approaches'])
    arms[0][key] = value
    with pytest.raises(ValueError):
        revise(tmp_path, profile['revision'], {'approaches':arms})


def test_draft_can_store_close_arms_but_cannot_run_them(tmp_path, profile):
    p = routed(tmp_path, profile)
    arms = copy.deepcopy(p['approaches'])
    arms[2].update(x=2, y=100)
    p = revise(tmp_path, p['revision'], {'approaches':arms})
    with pytest.raises(ValueError, match='25 degrees'):
        validate(p, runnable=True)


def test_checksum_and_source_tampering_detected(tmp_path, profile):
    p = copy.deepcopy(profile)
    p['source']['events'][0]['t'] += 1
    with pytest.raises(ValueError, match='source observations'):
        validate(p)
    path = tmp_path/'out'/'.profiles'/(profile['revision']+'.json')
    p = json.loads(path.read_text())
    p['approaches'][0]['x'] += 1
    path.write_text(json.dumps(p))
    with pytest.raises(ValueError, match='checksum'):
        load_profile(tmp_path, profile['revision'])
    with pytest.raises(ValueError):
        load_profile(tmp_path, '../../source')


@pytest.mark.parametrize('params', [{'demand':'observed'}, {'site_revision':'a'*64},
    {'demand':'observed','site_revision':'a'*64,'scale':2}, {'site_revision':'../source'}])
def test_observed_scenario_does_not_fall_back_or_multiply(params):
    with pytest.raises(ValueError):
        Scenario(**params)


def test_exclusive_stages_enforce_clearance_and_commit_target():
    cfg = SignalConfig(min_green=2,max_green=8,fixed_split=4,yellow=1,all_red=1,hysteresis=0)
    sm = IncomingStages(['a','b','c'], cfg, 'adaptive')
    obs = {'a':PhaseObservation(0,0),'b':PhaseObservation(3,3),'c':PhaseObservation(1,1)}
    sm.update(1, obs)
    assert sm.is_green('a')
    sm.update(2, obs)
    assert sm.state == SignalState.YELLOW and sm.next == 'b'
    assert not any(sm.is_green(n) for n in sm.names)
    obs['c'] = PhaseObservation(100,100)
    sm.update(2.5, obs)
    assert sm.state == SignalState.YELLOW and sm.next == 'b'
    sm.update(3, obs)
    assert sm.state == SignalState.ALL_RED
    sm.update(3.5, obs)
    assert not any(sm.is_green(n) for n in sm.names)
    sm.update(4, obs)
    assert sm.is_green('b') and sum(sm.is_green(n) for n in sm.names) == 1
    sm.update(12, obs)
    assert sm.state == SignalState.YELLOW and sm.green_end_cause == 'max_green'


def test_real_sumo_preserves_recorded_cohort_and_suppresses_claim(tmp_path, profile):
    status = preflight()
    if not status['ready']:
        import os
        if os.environ.get('THEIATRON_REQUIRE_SUMO') == '1':
            pytest.fail(status['error'])
        pytest.skip(status['error'])
    p = routed(tmp_path, profile)
    scenario = Scenario(duration=36, pace=0, demand='observed', site_revision=p['revision'])
    output = tmp_path/'comparison'
    report = run(output, scenario, p)
    demand = json.loads((output/'demand.json').read_text())
    assert [(d['id'],d['approach'],d['depart']) for d in demand] == [
        (e['id'],e['approach'],e['t']) for e in p['source']['events']]
    assert report['source_artifact_id'] == p['source']['artifact_id']
    assert report['review_status'] == 'draft-unreviewed'
    assert report['sample_status'] == 'inconclusive'  # two arms, only one source signal axis
    assert report['observed_phase_counts'] == {'NS':15,'EW':0}
    assert report['reduction_pct'] is None and report['impact_status'] == 'not-validated'
    assert report['valid']
    assert all(m['offered'] == 15 and m['conserved'] for m in report['metrics'].values())
    latest = json.loads((output/'latest.json').read_text())
    replay = json.loads((output/'frames.jsonl').read_text().splitlines()[-1])
    for name in ('fixed','adaptive'):
        assert replay['worlds'][name]['metrics'] == latest['worlds'][name]['metrics'] == report['metrics'][name]
    assert verify_bundle(output)['verified_files'] == 12


@pytest.mark.parametrize('arms_count,side', [(2,'right'), (3,'left')])
def test_supported_custom_layouts_use_actual_routes(tmp_path, profile, arms_count, side):
    status = preflight()
    if not status['ready']:
        import os
        if os.environ.get('THEIATRON_REQUIRE_SUMO') == '1':
            pytest.fail(status['error'])
        pytest.skip(status['error'])
    p = routed(tmp_path, profile)
    arms = copy.deepcopy(p['approaches'])
    for i,a in enumerate(arms):
        a['enabled'] = i < arms_count
        if i >= 2:
            a['exit'] = 'south'
    p = revise(tmp_path,p['revision'],{'approaches':arms,'traffic_side':side})
    scenario = Scenario(duration=36,pace=0,demand='observed',site_revision=p['revision'])
    report = run(tmp_path/'custom',scenario,p)
    assert report['valid']
    assert len(report['metrics']['fixed']['per_approach']) == arms_count
    assert report['metrics']['fixed']['offered'] == 15
    # A changed network creates different evidence but never new observations.
    assert json.loads((tmp_path/'custom'/'source-observations.json').read_text()) == profile['source']
