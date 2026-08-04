"""Intersection engine: wires arrivals -> controller -> state machine -> queues.

Incremental by design so the same engine serves the live demo (adaptive
driving the lights while a fixed-timer shadow runs on identical arrivals)
and fast offline replay of recorded arrival streams.
"""

from __future__ import annotations

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
        dt = now - self._last
        want = self.controller.want_switch(now, self.sm, self.queues_by_phase())
        self.sm.step(now, want)
        self._sync_greens()
        for t, name in arrivals:
            self.queues[name].arrive(t)
        for q in self.queues.values():
            q.step(dt, now)
        self._last = now

    def run_replay(
        self,
        events: list[tuple[float, str]],
        duration: float,
        dt: float = 0.1,
    ) -> None:
        """Drive the engine over a recorded arrival stream, offline."""
        events = sorted(events)
        i = 0
        steps = int(duration / dt)
        for k in range(1, steps + 1):
            now = round(k * dt, 6)
            batch = []
            while i < len(events) and events[i][0] <= now:
                batch.append(events[i])
                i += 1
            self.tick(now, batch)

    # -- state snapshots for dashboard/metrics ------------------------------

    def light_for(self, name: str) -> str:
        phase = self.phase_of[name]
        if self.sm.is_green(phase):
            return "GREEN"
        if self.sm.state is SignalState.YELLOW and self.sm.active is phase:
            return "YELLOW"
        return "RED"
