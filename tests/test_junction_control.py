from theiatron.config import SignalConfig
from theiatron.controller import SignalState
from theiatron.junction_control import JunctionObservation as O, ServiceStages
from theiatron.benchmark import DEVELOPMENT_SEEDS,EVALUATION_SEEDS,summarize
import json
import pytest


def controller(mode='service-v2'):
    return ServiceStages(['n','e','s','w'],SignalConfig(min_green=8,max_green=40,fixed_split=20,yellow=3,all_red=2),mode)


def test_moving_platoon_is_not_an_empty_approach():
    s=controller();obs={'n':O(0,0,7,1),'e':O(6,60,6,0),'s':O(),'w':O()}
    s.update(8,obs)
    assert s.state==SignalState.GREEN
    s.update(20,obs)
    assert s.state==SignalState.YELLOW and s.next=='e'


def test_gap_out_waits_for_minimum_and_commits_clearance_target():
    s=controller();obs={'n':O(0,0,1,10),'e':O(5,50,5,0),'s':O(),'w':O()}
    s.update(7.5,obs);assert s.state==SignalState.GREEN
    s.update(8,obs);assert s.state==SignalState.YELLOW and s.next=='e'
    obs['s']=O(50,500,50,0)
    s.update(10.5,obs);assert s.state==SignalState.YELLOW
    s.update(11,obs);assert s.state==SignalState.ALL_RED
    s.update(12.5,obs);assert s.state==SignalState.ALL_RED
    s.update(13,obs);assert s.active=='e' and s.state==SignalState.GREEN


def test_maximum_green_and_waiting_approach_bound():
    s=controller();obs={n:O(2,5,3,1) for n in s.names}
    s.update(40,obs);assert s.state==SignalState.YELLOW
    s=controller();s.waiting_since['s']=0
    s.since=72
    s.update(80,obs)
    assert s.state==SignalState.YELLOW and s.next=='s'


def test_actuated_baseline_skips_empty_arms_but_observes_moving_cars():
    s=controller('actuated');obs={'n':O(0,0,4,1),'e':O(),'s':O(4,40,4,0),'w':O()}
    s.update(20,obs);assert s.state==SignalState.GREEN
    obs['n']=O()
    s.update(21,obs);assert s.state==SignalState.YELLOW and s.next=='s'


def test_benchmark_split_is_disjoint_and_regressions_are_retained():
    assert set(DEVELOPMENT_SEEDS).isdisjoint(EVALUATION_SEEDS)
    def row(delay):return {'comparison':'v2 vs fixed','baseline':{'total_delay_s':10,'mean_delay_s':10,'arrived':1,'p95_delay_s':10},
                           'candidate':{'total_delay_s':delay,'mean_delay_s':delay,'arrived':1,'p95_delay_s':delay}}
    r=summarize([row(5),row(20)])['v2 vs fixed']
    assert r['improved']==1 and r['worsened']==1 and r['total_delay_reduction_pct']==-25


def test_evaluation_requires_intact_development_and_frozen_code(tmp_path,monkeypatch):
    from theiatron import benchmark
    from theiatron.sumo_demo import object_hash
    dev=tmp_path/'dev';dev.mkdir()
    manifest={'phase':'develop','code_sha256':{'controller':'old'}}
    manifest['artifact_id']=object_hash(manifest)
    (dev/'benchmark.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(benchmark,'code_identity',lambda: {'controller':'new'})
    with pytest.raises(ValueError,match='code changed after development'):
        benchmark.execute(tmp_path/'evaluation','evaluate',development=dev)
    assert not (tmp_path/'evaluation').exists()
    manifest['phase']='evaluate'
    (dev/'benchmark.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='manifest is not intact'):
        benchmark.execute(tmp_path/'evaluation','evaluate',development=dev)


@pytest.mark.parametrize('baseline',['fixed','actuated'])
def test_real_service_policy_preserves_cohort_clearance_and_version(tmp_path,baseline):
    from test_site_profiles import make_source,routed
    from theiatron.sumo_demo import Scenario,preflight,run,verify_bundle
    if not preflight()['ready']:pytest.skip('SUMO unavailable')
    profile=routed(tmp_path,make_source(tmp_path))
    scenario=Scenario(duration=60,pace=0,demand='heavy',site_revision=profile['revision'],
                      generated_demand=True,baseline_policy=baseline,adaptive_policy='service-v2')
    out=tmp_path/'experiment';report=run(out,scenario,profile)
    assert report['valid'] and report['reduction_pct'] is None
    assert report['policies']=={'fixed':baseline,'adaptive':'service-v2'}
    assert report['controller_comparison']['candidate']=='Theiatron service v2'
    assert report['metrics']['fixed']['offered']==report['metrics']['adaptive']['offered']
    assert verify_bundle(out)['artifact_id']==report['artifact_id']
    frames=[json.loads(l) for l in (out/'frames.jsonl').read_text().splitlines()]
    for name in ('fixed','adaptive'):
        previous='GREEN';phase=frames[0]['worlds'][name]['phase'];entered=0
        minimum={'GREEN':profile['signal']['min_green'],'YELLOW':profile['signal']['yellow'],
                 'ALL_RED':profile['signal']['all_red']}
        for frame in frames:
            world=frame['worlds'][name]
            assert world['policy']==report['policies'][name]
            assert all(world['lane_presence'][n]>=q for n,q in world['queues'].items())
            if world['signal']!=previous:
                assert (previous,world['signal']) in {('GREEN','YELLOW'),('YELLOW','ALL_RED'),('ALL_RED','GREEN')}
                assert frame['t']-entered>=minimum[previous]
                entered=frame['t']
            if world['phase']!=phase:
                assert previous=='ALL_RED' and world['signal']=='GREEN'
            previous,phase=world['signal'],world['phase']
