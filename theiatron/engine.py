"""Intersection engine: wires arrivals -> controller -> state machine -> queues.

Incremental by design so the same engine serves the live demo (adaptive
driving the lights while a fixed-timer shadow runs on identical arrivals)
and fast offline replay of recorded arrival streams.
"""

from __future__ import annotations

import math
from decimal import Decimal

from .config import ApproachConfig, QueueConfig, SignalConfig
from .controller import Controller, Phase, PhaseStateMachine, SignalState
from .sim import PointQueue


class IntersectionEngine:
    def __init__(
        self,
        controller: Controller,
        signal_cfg: SignalConfig,
        approaches: list[ApproachConfig],
        queue_cfg: QueueConfig,
        t0: float = 0.0,
    ):
        self.controller = controller
        self.sm = PhaseStateMachine(signal_cfg, t0=t0)
        self.phase_of = {a.name: Phase(a.phase) for a in approaches}
        self.queues = {
            a.name: PointQueue(
                QueueConfig(
                    lanes=a.lanes,
                    sat_headway=queue_cfg.sat_headway,
                    startup_lost=queue_cfg.startup_lost,
                )
            )
            for a in approaches
        }
        self._last = t0
        self._sync_greens()
        self.steps: list[dict] = []
        self.lights = {name: [[t0, self.light_for(name)]] for name in self.queues}

    def _sync_greens(self) -> None:
        for name, q in self.queues.items():
            q.set_green(self.sm.is_green(self.phase_of[name]))

    def queues_by_phase(self) -> dict[Phase, list[PointQueue]]:
        out: dict[Phase, list[PointQueue]] = {Phase.NS: [], Phase.EW: []}
        for name, q in self.queues.items():
            out[self.phase_of[name]].append(q)
        return out

    def tick(self, now: float, arrivals: list[tuple[float, str]]) -> None:
        """Advance to `now`, applying arrival events (t, approach_name), t <= now."""
        if not math.isfinite(now) or now < self._last:
            raise ValueError("simulation time must be finite and non-decreasing")
        for t, name in arrivals:
            if not math.isfinite(t) or not 0 <= t <= now:
                raise ValueError("arrival time must be finite and within the simulation horizon")
            if name not in self.queues:
                raise ValueError(f"unknown arrival approach: {name}")
        dt = now - self._last
        want = self.controller.want_switch(now, self.sm, self.queues_by_phase())
        self.sm.step(now, want)
        self._sync_greens()
        for t, name in arrivals:
            self.queues[name].arrive(t)
        for q in self.queues.values():
            q.step(dt, now)
        self._last = now
        self.steps.append({"t": now, "arrivals": [list(event) for event in arrivals]})
        for name in self.queues:
            state = self.light_for(name)
            if state != self.lights[name][-1][1]:
                self.lights[name].append([now, state])

    def run_replay(
        self,
        events: list[tuple[float, str]],
        duration: float,
        dt: float = 0.1,
    ) -> None:
        """Drive to the exact horizon, including the final fractional interval.

        This nominal-cadence replay is for new experiments/legacy event files.
        Exact reproduction of a live run uses its recorded steps instead.
        """
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("replay dt must be finite and positive")
        if not math.isfinite(duration) or duration < self._last:
            raise ValueError("replay duration must be finite and not precede current time")
        for t, name in events:
            if not math.isfinite(t) or t < 0 or name not in self.queues:
                raise ValueError(f"invalid replay event: {(t, name)}")
        events = sorted(events)
        i = 0
        start = self._last
        steps = max(1, math.ceil((duration - start) / dt))
        # Construct nominal timestamps without binary multiplication drift
        # (e.g. 12.3 instead of 12.300000000000002), preserving legacy 0.1s
        # controller boundaries while supporting finer caller cadences.
        start_decimal, dt_decimal = Decimal(str(start)), Decimal(str(dt))
        for k in range(1, steps + 1):
            now = min(float(start_decimal + k * dt_decimal), duration)
            batch = []
            while i < len(events) and events[i][0] <= now:
                batch.append(events[i])
                i += 1
            self.tick(now, batch)
            if now == duration:
                break

    # -- state snapshots for dashboard/metrics ------------------------------

    def light_for(self, name: str) -> str:
        phase = self.phase_of[name]
        if self.sm.is_green(phase):
            return "GREEN"
        if self.sm.state is SignalState.YELLOW and self.sm.active is phase:
            return "YELLOW"
        return "RED"
