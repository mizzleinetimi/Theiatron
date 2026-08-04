"""Point-queue model: the simulated half of the co-simulation.

Vision supplies real arrival events; this module simulates how a queue at
the stop line responds to the signal. Arrivals accumulate while the light
is red and discharge at saturation flow while it is green, after a
startup lost time. Recorded vehicles cannot react to our simulated light,
so this is the standard honest stand-in for closed-loop actuation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .config import QueueConfig


@dataclass
class Vehicle:
    arrival: float
    depart: float | None = None

    def wait(self, now: float | None = None) -> float:
        """Time spent in queue; censored at `now` if still queued."""
        end = self.depart if self.depart is not None else now
        if end is None:
            raise ValueError("still queued: pass `now` for a censored wait")
        return end - self.arrival


class PointQueue:
    """Vertical queue for one approach, driven by measured arrivals."""

    def __init__(self, cfg: QueueConfig | None = None):
        self.cfg = cfg or QueueConfig()
        self.queue: deque[Vehicle] = deque()
        self.departed: list[Vehicle] = []
        self.max_queue = 0
        self._green = False
        self._lost_remaining = 0.0
        self._credit = 0.0

    @property
    def green(self) -> bool:
        return self._green

    def set_green(self, green: bool) -> None:
        if green and not self._green:
            # Fresh green: pay startup lost time before any discharge.
            self._lost_remaining = self.cfg.startup_lost
            self._credit = 0.0
        self._green = green

    def _flowing(self) -> bool:
        return self._green and self._lost_remaining <= 0.0

    def arrive(self, t: float) -> None:
        if self._flowing() and not self.queue and self._credit >= 1.0:
            # Effective green, no queue ahead, capacity available: free-flow
            # pass with zero wait. Consuming credit keeps a burst of
            # simultaneous arrivals bounded by saturation flow.
            self._credit -= 1.0
            self.departed.append(Vehicle(t, t))
            return
        self.queue.append(Vehicle(t))
        self.max_queue = max(self.max_queue, len(self.queue))

    def step(self, dt: float, now: float) -> None:
        """Advance the queue by `dt` seconds ending at time `now`."""
        if not self._green or dt <= 0:
            return
        if self._lost_remaining > 0.0:
            used = min(self._lost_remaining, dt)
            self._lost_remaining -= used
            dt -= used
            if dt <= 0:
                return
        self._credit += dt * self.cfg.lanes / self.cfg.sat_headway
        while self._credit >= 1.0 and self.queue:
            veh = self.queue.popleft()
            veh.depart = now
            self.departed.append(veh)
            self._credit -= 1.0
        if not self.queue:
            # An idle green must not bank unlimited discharge capacity.
            self._credit = min(self._credit, 1.0)

    # -- inspection helpers -------------------------------------------------

    def total_wait(self, now: float) -> float:
        return sum(now - v.arrival for v in self.queue)

    @property
    def arrivals_total(self) -> int:
        return len(self.queue) + len(self.departed)
