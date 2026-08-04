import random

from theiatron.config import ApproachConfig, QueueConfig, SignalConfig
from theiatron.controller import AdaptiveController, FixedController
from theiatron.engine import IntersectionEngine
from theiatron.metrics import comparison_report, summarize

APPROACHES = [
    ApproachConfig(name="north", video="", phase="NS"),
    ApproachConfig(name="south", video="", phase="NS"),
    ApproachConfig(name="east", video="", phase="EW"),
    ApproachConfig(name="west", video="", phase="EW"),
]

DURATION = 600.0


def poisson_arrivals(rate_veh_per_h: float, approach: str, duration: float, rng):
    """Homogeneous Poisson process via exponential inter-arrival times."""
    events = []
    t = 0.0
    rate = rate_veh_per_h / 3600.0
    while True:
        t += rng.expovariate(rate)
        if t >= duration:
            return events
        events.append((round(t, 3), approach))


def asymmetric_demand(seed=42):
    rng = random.Random(seed)
    events = []
    events += poisson_arrivals(600, "north", DURATION, rng)
    events += poisson_arrivals(500, "south", DURATION, rng)
    events += poisson_arrivals(150, "east", DURATION, rng)
    events += poisson_arrivals(100, "west", DURATION, rng)
    return sorted(events)


def run(controller_cls, events):
    cfg = SignalConfig()
    eng = IntersectionEngine(controller_cls(cfg), cfg, APPROACHES, QueueConfig())
    eng.run_replay(events, DURATION)
    return summarize(eng, DURATION)


def test_adaptive_beats_fixed_on_asymmetric_demand():
    events = asymmetric_demand()
    adaptive = run(AdaptiveController, events)
    fixed = run(FixedController, events)
    # The headline claim, with margin: strictly better avg and p95 wait.
    assert adaptive["avg_wait_s"] < fixed["avg_wait_s"] * 0.85
    assert adaptive["p95_wait_s"] < fixed["p95_wait_s"]
    # And it must not achieve that by serving fewer vehicles.
    assert adaptive["served"] >= fixed["served"] * 0.95


def test_identical_demand_replay_determinism():
    events = asymmetric_demand()
    a1 = run(AdaptiveController, events)
    a2 = run(AdaptiveController, events)
    assert a1 == a2


def test_comparison_report_renders():
    events = asymmetric_demand(seed=7)
    adaptive = run(AdaptiveController, events)
    fixed = run(FixedController, events)
    md, data = comparison_report(adaptive, fixed)
    assert "Adaptive vs Fixed" in md
    assert data["avg_wait_reduction_pct"] == round(
        100 * (fixed["avg_wait_s"] - adaptive["avg_wait_s"]) / fixed["avg_wait_s"], 1
    )
