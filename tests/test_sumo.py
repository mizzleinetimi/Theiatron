"""Metric, policy and real-binary integration checks (no beneficial-result assertion)."""
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from theiatron.config import SignalConfig
from theiatron.controller import Phase, PhaseStateMachine, SignalState
from theiatron.observations import PhaseObservation, pressure_request
from theiatron.sumo_demo import Scenario, aggregate, final_metrics, preflight, run, verify_bundle


@pytest.mark.parametrize("field,value", [("duration", 0), ("duration", True), ("duration", 301),
    ("seed", -1), ("seed", 1.5), ("seed", True), ("scale", float('nan')),
    ("scale", float('inf')), ("scale", 3), ("pace", -1), ("demand", "../../bad")])
def test_invalid_scenario(field, value):
    with pytest.raises(ValueError):
        Scenario(**{field: value})


def test_common_cohort_keeps_pending_and_unfinished():
    demand = [dict(id="a", approach="north", depart=1), dict(id="b", approach="east", depart=2),
              dict(id="c", approach="south", depart=3), dict(id="future", approach="west", depart=11)]
    records = {"a": dict(wait=3, insertion=1, arrived=True), "b": dict(wait=2, insertion=0, arrived=False)}
    metrics = aggregate(demand, records, 10)
    assert metrics['offered'] == 3
    assert (metrics['arrived'], metrics['active'], metrics['pending']) == (1, 1, 1)
    assert metrics['conserved']
    assert metrics['total_delay_s'] == 13  # 4 + 2 + 7 pending insertion
    assert metrics['p95_delay_s'] == 7
    assert metrics['per_approach']['west']['offered'] == 0


def test_observation_policy_does_not_depend_on_pointqueues():
    cfg = SignalConfig()
    sm = PhaseStateMachine(cfg)
    obs = {Phase.NS: PhaseObservation(0, 0), Phase.EW: PhaseObservation(2, 4)}
    assert pressure_request(sm, obs, cfg) == (True, 'active queue drained')
    sm.step(1, True)
    assert sm.state == SignalState.GREEN  # policy cannot bypass minimum green
    sm.step(12, True)
    assert sm.state == SignalState.YELLOW
    assert not pressure_request(sm, obs, cfg)[0]


def test_missing_tripinfo_vehicle_is_not_counted_as_pending(tmp_path):
    trip = tmp_path / 'trip.xml'
    trip.write_text('<tripinfos/>')
    with pytest.raises(ValueError, match='lost intended'):
        final_metrics(trip, [dict(id='a', approach='east', depart=1)], 10)


@pytest.fixture(scope='module')
def paired_runs(tmp_path_factory):
    status = preflight()
    if not status['ready']:
        import os
        if os.environ.get('THEIATRON_REQUIRE_SUMO') == '1':
            pytest.fail(status['error'])
        pytest.skip(status['error'])
    base = tmp_path_factory.mktemp('sumo')
    scenario = Scenario(duration=60, pace=0)
    results = [(base / name, run(base / name, scenario)) for name in ['first', 'repeat']]
    return results


def test_stock_sumo_pair_is_reproducible(paired_runs):
    (first, a), (second, b) = paired_runs
    assert a['metrics'] == b['metrics']
    assert a['diagnostics'] == b['diagnostics']
    assert (first/'frames.jsonl').read_bytes() == (second/'frames.jsonl').read_bytes()
    assert (first/'network.net.xml').read_bytes() == (second/'network.net.xml').read_bytes()
    assert (first/'demand.rou.xml').read_bytes() == (second/'demand.rou.xml').read_bytes()
    assert a['valid']
    assert a['metrics']['fixed']['offered'] == a['metrics']['adaptive']['offered']
    assert a['metrics']['fixed'] != a['metrics']['adaptive']
    assert all(m['conserved'] for m in a['metrics'].values())
    assert verify_bundle(first)['verified_files'] == 10


def test_final_replay_metrics_are_exact_report_metrics(paired_runs):
    path, report = paired_runs[0]
    last = json.loads((path/'frames.jsonl').read_text().splitlines()[-1])
    latest = json.loads((path/'latest.json').read_text())
    for name in ('fixed', 'adaptive'):
        assert last['worlds'][name]['metrics'] == report['metrics'][name]
        assert latest['worlds'][name]['metrics'] == report['metrics'][name]


def test_signal_clearance_is_in_actual_sumo_frames(paired_runs):
    path, _ = paired_runs[0]
    frames = [json.loads(line) for line in (path/'frames.jsonl').read_text().splitlines()]
    for name in ('fixed', 'adaptive'):
        previous = 'GREEN'
        phase = 'NS'
        entered = .5
        for frame in frames:
            w = frame['worlds'][name]
            if w['signal'] != previous:
                assert (previous, w['signal']) in {('GREEN','YELLOW'),('YELLOW','ALL_RED'),('ALL_RED','GREEN')}
                elapsed = frame['t'] - entered
                assert elapsed >= {'GREEN': 8, 'YELLOW': 3, 'ALL_RED': 1}[previous]
                entered = frame['t']
            if w['phase'] != phase:
                assert previous == 'ALL_RED' and w['signal'] == 'GREEN'
            previous, phase = w['signal'], w['phase']


def test_checksum_tampering_fails_closed(paired_runs, tmp_path):
    import shutil
    path, report = paired_runs[0]
    destination = tmp_path / 'copy'
    shutil.copytree(path, destination)
    (destination/'frames.jsonl').write_text('tampered')
    with pytest.raises(ValueError, match='checksum'):
        verify_bundle(destination)
