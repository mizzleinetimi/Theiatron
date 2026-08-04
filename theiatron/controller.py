"""Signal phase state machine and control policies.

The state machine owns every safety invariant (interlock sequence, min/max
green, yellow and all-red clearance). Controllers only answer one question:
"do you want to switch phases now?" — so the invariants are enforced once,
identically, for every policy.
"""

from __future__ import annotations

from enum import Enum

from .config import SignalConfig
from .sim import PointQueue


class Phase(str, Enum):
    NS = "NS"
    EW = "EW"

    @property
    def other(self) -> "Phase":
        return Phase.EW if self is Phase.NS else Phase.NS


class SignalState(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ALL_RED = "ALL_RED"


class PhaseStateMachine:
    """Interlocked two-phase signal: GREEN -> YELLOW -> ALL_RED -> other GREEN."""

    def __init__(self, cfg: SignalConfig, start: Phase = Phase.NS, t0: float = 0.0):
        self.cfg = cfg
        self.active = start
        self.state = SignalState.GREEN
        self.since = t0
        self.switches = 0
        # Why the last green ended: "max_green" (fairness cap) or "policy".
        self.green_end_cause: str | None = None

    def elapsed(self, now: float) -> float:
        return now - self.since

    def is_green(self, phase: Phase) -> bool:
        return self.state is SignalState.GREEN and self.active is phase

    def step(self, now: float, want_switch: bool) -> None:
        el = self.elapsed(now)
        if self.state is SignalState.GREEN:
            force = el >= self.cfg.max_green
            allowed = el >= self.cfg.min_green
            if force or (want_switch and allowed):
                self.green_end_cause = "max_green" if force and not want_switch else "policy"
                self.state = SignalState.YELLOW
                self.since = now
        elif self.state is SignalState.YELLOW:
            if el >= self.cfg.yellow:
                self.state = SignalState.ALL_RED
                self.since = now
        else:  # ALL_RED
            if el >= self.cfg.all_red:
                self.active = self.active.other
                self.state = SignalState.GREEN
                self.since = now
                self.switches += 1


class Controller:
    name = "base"

    def want_switch(
        self,
        now: float,
        sm: PhaseStateMachine,
        queues_by_phase: dict[Phase, list[PointQueue]],
    ) -> bool:
        raise NotImplementedError


class FixedController(Controller):
    """Fixed-timer baseline: equal green splits, blind to demand."""

    name = "fixed"

    def __init__(self, cfg: SignalConfig):
        self.split = cfg.fixed_split

    def want_switch(self, now, sm, queues_by_phase) -> bool:
        return sm.state is SignalState.GREEN and sm.elapsed(now) >= self.split


class AdaptiveController(Controller):
    """Queue-pressure policy with waiting-time anti-starvation term.

    pressure(phase) = sum over its approaches of
        queue_length + wait_weight * accumulated_waiting_seconds

    Every switch costs ~yellow + all_red + startup_lost (~6 s) of capacity,
    so under load the policy serves the active queue until it (nearly)
    drains, then hands green to the phase with demand. Pre-empting an
    actively discharging queue requires opposing pressure to dominate by a
    ratio plus margin — this is what a naive "switch when the other side is
    bigger" rule gets wrong, thrashing away capacity in lost time. The wait
    term grows without bound so a lone vehicle can never be starved, and
    MAX_GREEN bounds worst-case service latency regardless.
    """

    name = "adaptive"

    # Hand over the green only once the active queue has fully drained
    # (or on pre-emption/max-green); every switch costs ~6 s of capacity.
    DRAIN_THRESHOLD = 0

    def __init__(self, cfg: SignalConfig):
        self.w = cfg.wait_weight
        self.hyst = cfg.hysteresis
        self.ratio = cfg.pressure_ratio
        # Why the controller last requested a switch: "drained" | "pressure".
        self.last_reason: str | None = None

    def pressure(self, queues: list[PointQueue], now: float) -> float:
        return sum(len(q.queue) + self.w * q.total_wait(now) for q in queues)

    def want_switch(self, now, sm, queues_by_phase) -> bool:
        if sm.state is not SignalState.GREEN:
            return False
        active_qs = queues_by_phase[sm.active]
        opposing = self.pressure(queues_by_phase[sm.active.other], now)
        if opposing == 0.0:
            return False  # nothing to switch for
        active_len = sum(len(q.queue) for q in active_qs)
        if active_len <= self.DRAIN_THRESHOLD:
            self.last_reason = "drained"
            return True  # active phase (nearly) drained: hand over the green
        active = self.pressure(active_qs, now)
        if opposing > active * self.ratio + self.hyst:
            self.last_reason = "pressure"
            return True
        return False
