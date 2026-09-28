import copy
import json
import math
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from run_demo import _evaluation_window, build_engines, finish, run_replay
from theiatron.artifacts import (build_artifact, load_artifact, replay_artifact,
                                save_artifact, validate_inputs)
from theiatron.config import AppConfig, ApproachConfig, QueueConfig, save_config
from theiatron.events import load_events, save_events
from theiatron.metrics import assess_comparison, summarize


@pytest.fixture
def cfg():
    return AppConfig(queue=QueueConfig(sat_headway=4, startup_lost=5), approaches=[
        ApproachConfig(name=name, phase=phase, video="moved-source.mov",
                       count_line=[[100, 120], [180, 120]] if phase == "NS"
                       else [[220, 80], [220, 160]],
                       approach_side=[140, 60] if phase == "NS" else [280, 120])
        for name, phase in (("north", "NS"), ("south", "NS"), ("east", "EW"), ("west", "EW"))
    ])


def irregular_run(cfg):
    adaptive, fixed = build_engines(cfg)
    events = []
    # Deliberately not a 10Hz clock: reproduces the actual camera-cadence bug.
    for k in range(1, 410):
        t = round(k * 0.100047, 6)
        batch = [(t, "east" if k % 4 == 0 else "north")] if k % 7 == 0 else []
        events.extend(batch)
        adaptive.tick(t, batch)
        fixed.tick(t, batch)
    return adaptive, fixed, t, events


def read_timeline(path):
    return json.loads(path.read_text().removeprefix("const TIMELINE = ").removesuffix(";\n"))


def test_event_precision_is_lossless(tmp_path):
    events = [(1.030049999, "north"), (2.3456789123, "east")]
    save_events(events, tmp_path / "events.json")
    assert load_events(tmp_path / "events.json")[0] == events


def test_replay_includes_final_fraction_and_exact_boundary(cfg):
    adaptive, fixed = build_engines(cfg)
    for engine in (adaptive, fixed):
        engine.run_replay([(0, "north"), (1.03, "east"), (1.05, "north"), (1.051, "south")], 1.05)
        assert summarize(engine, 1.05)["arrivals"] == 3
        assert engine.steps[-1]["t"] == 1.05


def test_zero_horizon_counts_zero_time_event(cfg):
    engine, _ = build_engines(cfg)
    engine.run_replay([(0, "north")], 0)
    assert summarize(engine, 0)["arrivals"] == 1


@pytest.mark.parametrize("duration,dt", [(-1, .1), (math.inf, .1), (math.nan, .1),
                                         (1, 0), (1, -.1), (1, math.nan)])
def test_replay_rejects_invalid_clocks(cfg, duration, dt):
    engine, _ = build_engines(cfg)
    with pytest.raises(ValueError):
        engine.run_replay([], duration, dt)


def test_invalid_tick_does_not_mutate_engine(cfg):
    engine, _ = build_engines(cfg)
    engine.tick(1, [(1, "north")])
    before = copy.deepcopy(engine.steps)
    for now, events in ((.5, []), (2, [(3, "east")]), (2, [(2, "unknown")])):
        with pytest.raises(ValueError):
            engine.tick(now, events)
        assert engine.steps == before


def test_artifact_exact_replay_and_snapshot_isolation(cfg, tmp_path):
    adaptive, fixed, duration, events = irregular_run(cfg)
    artifact = build_artifact(cfg, adaptive, fixed, duration)
    save_artifact(artifact, tmp_path / "simulation.json")
    recorded = load_artifact(tmp_path / "simulation.json")
    validate_inputs(recorded, events, cfg, duration)
    a2, f2 = build_engines(cfg)
    replay_artifact(recorded, a2, f2)
    assert summarize(a2, duration) == summarize(adaptive, duration)
    assert build_artifact(cfg, a2, f2, duration) == artifact
    adaptive.tick(duration + 1, [])
    assert artifact == recorded


def test_artifact_checksum_and_input_mismatches_fail_closed(cfg, tmp_path):
    adaptive, fixed, duration, events = irregular_run(cfg)
    artifact = build_artifact(cfg, adaptive, fixed, duration)
    for changed_events, changed_cfg, changed_duration in (
        (events[:-1], cfg, duration), (events, cfg, duration + .1),
        (events, AppConfig(approaches=cfg.approaches), duration),
    ):
        with pytest.raises(ValueError):
            validate_inputs(artifact, changed_events, changed_cfg, changed_duration)
    artifact["duration"] += 1
    save_artifact(artifact, tmp_path / "simulation.json")
    with pytest.raises(ValueError, match="checksum"):
        load_artifact(tmp_path / "simulation.json")


def test_mismatched_batches_cannot_be_published(cfg):
    adaptive, fixed = build_engines(cfg)
    adaptive.tick(1, [(1, "north")])
    fixed.tick(1, [(1, "east")])
    with pytest.raises(ValueError, match="identical arrival"):
        build_artifact(cfg, adaptive, fixed, 1)


def test_cli_replay_uses_snapshot_after_source_and_config_move(cfg, tmp_path):
    adaptive, fixed, duration, _ = irregular_run(cfg)
    first = tmp_path / "first"
    second = tmp_path / "second"
    finish(cfg, adaptive, fixed, duration, first, {"config": "/missing/config.yaml"})
    run_replay(SimpleNamespace(replay=str(first / "events.json"), config=None, duration=None, out=second))
    assert json.loads((first / "report.json").read_text()) == json.loads((second / "report.json").read_text())
    assert (first / "simulation.json").read_bytes() == (second / "simulation.json").read_bytes()


def test_export_decorates_canonical_result_without_running_an_engine(cfg, tmp_path, monkeypatch):
    adaptive, fixed, duration, events = irregular_run(cfg)
    report = finish(cfg, adaptive, fixed, duration, tmp_path)
    config_path = tmp_path / "config.yaml"
    save_config(cfg, config_path)
    timeline_path = tmp_path / "timeline.js"
    monkeypatch.setattr(sys, "argv", ["export_timeline.py", str(tmp_path / "events.json"),
                                      str(duration), str(config_path), str(tmp_path / "tracks.json"),
                                      str(timeline_path)])

    def forbidden(*args, **kwargs):
        raise AssertionError("canonical export must never run a simulation")

    monkeypatch.setattr("theiatron.engine.IntersectionEngine", forbidden)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/export_timeline.py"), run_name="__main__")
    payload = read_timeline(timeline_path)
    artifact = load_artifact(tmp_path / "simulation.json")
    assert payload["artifact_id"] == report["artifact_id"]
    assert payload["evidence_source"] == "canonical-simulation"
    for key, name in (("theiatron", "adaptive"), ("fixed", "fixed")):
        assert payload[key]["avg_wait"] == report[name]["avg_wait_s"]
        assert payload[key]["lights"] == artifact["scenarios"][key]["lights"]
        assert [(v["t0"], v["a"]) for v in payload[key]["vehicles"]] == sorted(events)
        assert [v["t1"] for v in payload[key]["vehicles"]] == [v["t1"] for v in artifact["scenarios"][key]["vehicles"]]
    assert payload["comparison"]["headline"] == report["headline"]


def test_legacy_export_uses_actual_queue_config_and_tail(cfg, tmp_path):
    from run_demo import _export_3d_timeline
    events = [(0, "north"), (1.03, "east"), (7.05, "north")]
    duration = 7.05
    save_events(events, tmp_path / "events.json")
    save_config(cfg, tmp_path / "config.yaml")
    ok, message = _export_3d_timeline(tmp_path / "events.json", duration, tmp_path / "config.yaml",
                                    tmp_path / "tracks.json", tmp_path / "timeline.js")
    assert ok, message
    payload = read_timeline(tmp_path / "timeline.js")
    adaptive, fixed = build_engines(cfg)
    for engine, key in ((adaptive, "theiatron"), (fixed, "fixed")):
        engine.run_replay(events, duration)
        assert payload[key]["summary"] == summarize(engine, duration)
    assert payload["arrivals"] == 3
    assert payload["evidence_source"] == "legacy-recomputed"


def test_sample_guard_requires_both_phases(cfg):
    a, f = build_engines(cfg)
    for engine in (a, f):
        engine.run_replay([(i, "north") for i in range(20)], 60)
    result = assess_comparison(summarize(a, 60), summarize(f, 60))
    assert result["sample_status"] == "inconclusive"
    assert "both signal phases" in " ".join(result["sample_reasons"])


@pytest.mark.parametrize("adaptive_wait,fixed_wait,headline", [
    (2, 4, "50.0% LESS WAITING"), (4, 2, "100.0% MORE WAITING"),
    (2, 2, "EQUAL MODELED WAIT"), (2, 0, "MORE WAITING (FIXED = 0s)"),
])
def test_honest_headlines(cfg, adaptive_wait, fixed_wait, headline):
    a, f, duration, _ = irregular_run(cfg)
    sa, sf = summarize(a, duration), summarize(f, duration)
    sa["avg_wait_s"], sf["avg_wait_s"] = adaptive_wait, fixed_wait
    result = assess_comparison(sa, sf)
    assert result["headline"] == headline
    assert result["sample_status"] == "ready"


def test_unseen_scope_never_silently_rewinds():
    with pytest.raises(ValueError, match="Not enough unseen"):
        _evaluation_window("unseen", 60, 59, 30)
    assert _evaluation_window("full", 60, 59, 90) == (True, 60)
    assert _evaluation_window("unseen", 100, 30, 90) == (False, 70)


def test_missing_canonical_artifact_cannot_silently_use_legacy_fallback(cfg, tmp_path):
    from run_demo import _export_3d_timeline
    save_events([(1, "north")], tmp_path / "events.json", {"simulation_artifact": "simulation.json"})
    save_config(cfg, tmp_path / "config.yaml")
    ok, message = _export_3d_timeline(tmp_path / "events.json", 30, tmp_path / "config.yaml",
                                    tmp_path / "tracks.json", tmp_path / "timeline.js")
    assert not ok
    assert "canonical simulation.json is missing" in message
    assert not (tmp_path / "timeline.js").exists()


def test_t_junction_does_not_invent_unobserved_exit(cfg, tmp_path):
    from run_demo import _export_3d_timeline
    cfg.approaches = [a for a in cfg.approaches if a.name != "west"]
    save_events([(1, "east")], tmp_path / "events.json")
    save_config(cfg, tmp_path / "config.yaml")
    ok, message = _export_3d_timeline(tmp_path / "events.json", 30, tmp_path / "config.yaml",
                                    tmp_path / "tracks.json", tmp_path / "timeline.js")
    assert ok, message
    vehicle = read_timeline(tmp_path / "timeline.js")["theiatron"]["vehicles"][0]
    assert vehicle["exit"] is None
    assert vehicle["exit_source"] == "unknown"


def test_replay_into_existing_output_never_overwrites_evidence(cfg, tmp_path):
    adaptive, fixed, duration, _ = irregular_run(cfg)
    finish(cfg, adaptive, fixed, duration, tmp_path)
    original = {name: (tmp_path / name).read_bytes() for name in
                ("events.json", "report.json", "simulation.json")}
    run_replay(SimpleNamespace(replay=str(tmp_path / "events.json"), config=None,
                               duration=1, out=tmp_path))
    assert original == {name: (tmp_path / name).read_bytes() for name in original}
    new_run, = tmp_path.glob("replay-*/simulation.json")
    assert load_artifact(new_run)["duration"] == 1
