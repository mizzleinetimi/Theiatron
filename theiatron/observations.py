"""Policy input independent of a simulator or camera implementation.

This is a software-only two-phase policy, not a roadside controller interface.
"""
from dataclasses import dataclass
from .config import SignalConfig
from .controller import Phase, PhaseStateMachine, SignalState


@dataclass(frozen=True)
class PhaseObservation:
    queued: int
    stopped_seconds: float


def pressure_request(sm: PhaseStateMachine, observations: dict[Phase, PhaseObservation],
                     cfg: SignalConfig) -> tuple[bool, str]:
    if sm.state != SignalState.GREEN:
        return False, "clearance"
    active, other = observations[sm.active], observations[sm.active.other]
    opposing = other.queued + cfg.wait_weight * other.stopped_seconds
    if opposing == 0:
        return False, "no opposing queue"
    if active.queued == 0:
        return True, "active queue drained"
    pressure = active.queued + cfg.wait_weight * active.stopped_seconds
    if opposing > pressure * cfg.pressure_ratio + cfg.hysteresis:
        return True, "opposing queue pressure"
    return False, "serving active queue"
