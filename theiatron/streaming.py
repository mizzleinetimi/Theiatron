"""Small, dependency-free freshness primitives for continuous perception."""
from collections import deque
from dataclasses import dataclass
import math
import threading
import time


@dataclass(frozen=True)
class Frame:
    image: object
    sequence: int
    epoch: int
    source_time_s: float
    available_at: float
    received_at: float
    frame_index: int | None = None


class LatestFrame:
    """One owned pending frame. Overwrite old work, never queue video history."""
    def __init__(self):
        self.condition = threading.Condition()
        self.frame = None
        self.closed = False
        self.error = None
        self.offered = self.overwritten = self.taken = 0

    def offer(self, frame):
        with self.condition:
            if self.closed:
                return False
            self.offered += 1
            self.overwritten += self.frame is not None
            self.frame = frame
            self.condition.notify()
            return True

    def take(self, timeout=.2):
        with self.condition:
            self.condition.wait_for(lambda: self.frame is not None or self.closed, timeout)
            frame, self.frame = self.frame, None
            self.taken += frame is not None
            return frame

    def close(self, error=None):
        with self.condition:
            self.error = error
            self.closed = True
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            return {'offered': self.offered, 'overwritten': self.overwritten,
                    'taken': self.taken, 'pending': int(self.frame is not None)}


class Latency:
    """Constant-memory 1ms histogram; quantiles are conservative upper bounds."""
    def __init__(self):
        self.bins = [0] * 10001
        self.count = 0
        self.total = self.maximum = 0.

    def add(self, seconds):
        value = seconds * 1000
        if not math.isfinite(value):
            raise ValueError('latency must be finite')
        ms = max(0., value)
        self.bins[min(10000, math.ceil(ms))] += 1
        self.count += 1
        self.total += ms
        self.maximum = max(self.maximum, ms)

    def percentile(self, fraction):
        if not self.count:
            return None
        threshold = math.ceil(self.count * fraction)
        seen = 0
        for upper, count in enumerate(self.bins):
            seen += count
            if seen >= threshold:
                return round(self.maximum, 3) if upper == 10000 else upper

    def snapshot(self):
        return {'samples': self.count, 'mean_ms': round(self.total/self.count, 3) if self.count else None,
                'p50_ms_upper': self.percentile(.5), 'p95_ms_upper': self.percentile(.95),
                'max_ms': round(self.maximum, 3), 'quantiles': '1ms histogram upper bounds; overflow uses maximum'}


class Observations:
    def __init__(self):
        self.age, self.inference, self.queue = Latency(), Latency(), Latency()
        self.completed = deque(maxlen=100)
        self.stale = self.resets = self.deadline_misses = 0

    def add(self, frame, started, finished):
        self.deadline_misses += finished-frame.available_at > .3
        self.age.add(finished-frame.available_at)
        self.queue.add(started-frame.received_at)
        self.inference.add(finished-started)
        self.completed.append(finished)

    def snapshot(self):
        span = self.completed[-1]-self.completed[0] if len(self.completed)>1 else 0
        return {'processed': self.age.count, 'stale_rejected': self.stale, 'tracker_resets': self.resets,
                'observation_deadline_misses': self.deadline_misses,
                'observation_age': self.age.snapshot(), 'inference': self.inference.snapshot(),
                'queue_wait': self.queue.snapshot(),
                'recent_processing_fps': round((len(self.completed)-1)/span, 2) if span else None}


def needs_tracker_reset(previous, frame, gap_s=.5):
    return previous is not None and (previous.epoch != frame.epoch or
        frame.source_time_s-previous.source_time_s > gap_s or frame.source_time_s <= previous.source_time_s)
