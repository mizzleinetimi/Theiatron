from theiatron.config import ApproachConfig, QueueConfig, SignalConfig
from theiatron.controller import (
    AdaptiveController,
    FixedController,
    Phase,
    PhaseStateMachine,
    SignalState,
)
from theiatron.engine import IntersectionEngine

CFG = SignalConfig()  # defaults: max 45, yellow 3, all-red 1, split 30

APPROACHES = [
    ApproachConfig(name="north", video="", phase="NS"),
    ApproachConfig(name="south", video="", phase="NS"),
    ApproachConfig(name="east", video="", phase="EW"),
    ApproachConfig(name="west", video="", phase="EW"),
]


def step_sm(sm, until, dt=0.1, want=False, t0=0.0):
    t = t0
    while t < until:
        t = round(t + dt, 6)
        sm.step(t, want)
    return t


def test_min_green_respected():
    sm = PhaseStateMachine(CFG)
    # Demand a switch immediately: nothing may happen before min_green.
    before = round(CFG.min_green - 0.1, 6)
    step_sm(sm, before, want=True)
    assert sm.state is SignalState.GREEN and sm.active is Phase.NS
    step_sm(sm, CFG.min_green + 0.2, want=True, t0=before)
    assert sm.state is SignalState.YELLOW


def test_max_green_forces_switch():
    sm = PhaseStateMachine(CFG)
    step_sm(sm, 44.9, want=False)
    assert sm.state is SignalState.GREEN
    step_sm(sm, 45.2, want=False, t0=44.9)
    assert sm.state is SignalState.YELLOW


def test_yellow_allred_interlock_sequence():
    sm = PhaseStateMachine(CFG)
    states = []
    t = 0.0
    while t < 60.0:
        t = round(t + 0.1, 6)
        sm.step(t, True)
        states.append((sm.state, sm.active))
        # Invariant: at no instant may both phases be green.
        green_ns = sm.is_green(Phase.NS)
        green_ew = sm.is_green(Phase.EW)
        assert not (green_ns and green_ew)
    seq = [s for s, _ in states]
    y = seq.index(SignalState.YELLOW)
    r = seq.index(SignalState.ALL_RED)
    g2 = next(i for i, (s, a) in enumerate(states) if s is SignalState.GREEN and a is Phase.EW)
    assert y < r < g2
    # Durations: yellow == 3.0s, all-red == 1.0s (within one dt).
    assert abs((r - y) * 0.1 - CFG.yellow) < 0.15
    assert abs((g2 - r) * 0.1 - CFG.all_red) < 0.15


def test_fixed_cycle_timing():
    eng = IntersectionEngine(FixedController(CFG), CFG, APPROACHES, QueueConfig())
    switch_times = []
    prev = eng.sm.switches
    t = 0.0
    while t < 140.0:
        t = round(t + 0.1, 6)
        eng.tick(t, [])
        if eng.sm.switches != prev:
            switch_times.append(t)
            prev = eng.sm.switches
    # Green 30 + yellow 3 + all-red 1 = 34s per half-cycle.
    assert len(switch_times) >= 3
    gaps = [b - a for a, b in zip(switch_times, switch_times[1:])]
    for gap in gaps:
        assert abs(gap - 34.0) < 0.5


def test_no_starvation_under_heavy_cross_demand():
    eng = IntersectionEngine(AdaptiveController(CFG), CFG, APPROACHES, QueueConfig())
    lone_arrival = 5.0
    served_at = None
    t = 0.0
    while t < 120.0 and served_at is None:
        t = round(t + 0.1, 6)
        arrivals = [(t, "north")] if int(t * 10) % 5 == 0 else []  # heavy NS: 2 veh/s
        if abs(t - lone_arrival) < 0.05:
            arrivals.append((t, "east"))
        eng.tick(t, arrivals)
        if eng.queues["east"].departed:
            served_at = t
    assert served_at is not None
    # Bounded by max_green + yellow + all_red + discharge, with margin.
    assert served_at - lone_arrival < CFG.max_green + CFG.yellow + CFG.all_red + 10.0


def test_gap_out_switches_when_active_drains():
    eng = IntersectionEngine(AdaptiveController(CFG), CFG, APPROACHES, QueueConfig())
    # NS starts green and has nothing; one car waits on EW.
    eng.tick(1.0, [(1.0, "east")])
    t = 1.0
    while t < 30.0 and not eng.queues["east"].departed:
        t = round(t + 0.1, 6)
        eng.tick(t, [])
    # Served shortly after min_green + yellow + all_red, far before max_green.
    assert eng.queues["east"].departed
    assert t < 25.0
