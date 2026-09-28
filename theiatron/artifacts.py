"""Versioned evidence boundary between simulation, reporting and presentation.

The viewer decorates these results; it must not secretly rerun the simulation.
The backend descriptor separates today's point queue from a future SUMO run:
SUMO will need metric trajectories and trip/insertion metrics, not footage
paths relabelled as simulated vehicle motion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .config import AppConfig
from .engine import IntersectionEngine
from .metrics import comparison_report, summarize

SCHEMA_VERSION = 1
POINT_QUEUE_BACKEND = {"name": "point-queue", "version": 1,
                       "metric": "censored-queue-wait-seconds",
                       "geometry": "illustrative-not-metric"}


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def config_snapshot(cfg: AppConfig) -> dict:
    return json.loads(_canonical(asdict(cfg)))


def scenario_snapshot(engine: IntersectionEngine, duration: float) -> dict:
    summary = summarize(engine, duration)
    vehicles = []
    for name, queue in engine.queues.items():
        cohort = sorted([*queue.departed, *queue.queue], key=lambda v: v.arrival)
        vehicles.extend({"id": f"{name}:{index}", "a": name,
                         "t0": vehicle.arrival, "t1": vehicle.depart}
                        for index, vehicle in enumerate(cohort, 1))
    vehicles.sort(key=lambda v: (v["t0"], v["a"]))
    return {"lights": engine.lights, "vehicles": vehicles, "summary": summary,
            "avg_wait": summary["avg_wait_s"], "p95_wait": summary["p95_wait_s"],
            "served": summary["served"]}


def build_artifact(cfg: AppConfig, adaptive: IntersectionEngine,
                   fixed: IntersectionEngine, duration: float, meta: dict | None = None) -> dict:
    if adaptive.steps != fixed.steps:
        raise ValueError("controllers did not consume identical arrival batches and ticks")
    if adaptive._last != duration or fixed._last != duration:
        raise ValueError("artifact horizon must match both engines' final tick")
    scenarios = {"theiatron": scenario_snapshot(adaptive, duration),
                 "fixed": scenario_snapshot(fixed, duration)}
    _, report = comparison_report(scenarios["theiatron"]["summary"], scenarios["fixed"]["summary"])
    artifact = {"schema_version": SCHEMA_VERSION, "backend": POINT_QUEUE_BACKEND,
                "config": config_snapshot(cfg), "duration": duration,
                "source_meta": meta or {}, "steps": adaptive.steps,
                "scenarios": scenarios, "report": report}
    artifact["artifact_id"] = fingerprint(artifact)
    # Detach from the engines: later ticks cannot mutate a saved result.
    return json.loads(_canonical(artifact))


def save_artifact(artifact: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(artifact, indent=2, allow_nan=False))


def load_artifact(path: str | Path) -> dict:
    artifact = json.loads(Path(path).read_text())
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported simulation artifact schema")
    if (artifact.get('backend') != POINT_QUEUE_BACKEND
            or not isinstance(artifact.get('steps'), list)
            or not isinstance(artifact.get('scenarios'), dict)
            or set(artifact['scenarios']) != {'theiatron', 'fixed'}
            or not isinstance(artifact.get('source_meta'), dict)):
        raise ValueError('not a supported simulation artifact')
    content = {k: v for k, v in artifact.items() if k != "artifact_id"}
    if artifact.get("artifact_id") != fingerprint(content):
        raise ValueError("simulation artifact checksum mismatch; regenerate the run")
    return artifact


def validate_inputs(artifact: dict, events: list, cfg: AppConfig, duration: float) -> None:
    recorded = [tuple(e) for step in artifact["steps"] for e in step["arrivals"]]
    if sorted(recorded) != sorted(events):
        raise ValueError("event stream differs from canonical simulation artifact")
    if config_snapshot(cfg) != artifact["config"] or duration != artifact["duration"]:
        raise ValueError("config or duration differs from canonical simulation artifact")


def replay_artifact(artifact: dict, adaptive: IntersectionEngine, fixed: IntersectionEngine) -> None:
    if artifact["backend"] != POINT_QUEUE_BACKEND:
        raise ValueError("this runner only replays the supported point-queue backend version")
    for step in artifact["steps"]:
        adaptive.tick(step["t"], step["arrivals"])
        fixed.tick(step["t"], step["arrivals"])
    actual = {"theiatron": scenario_snapshot(adaptive, artifact["duration"]),
              "fixed": scenario_snapshot(fixed, artifact["duration"])}
    if actual != artifact["scenarios"]:
        raise ValueError("simulation replay diverged from its recorded results")
