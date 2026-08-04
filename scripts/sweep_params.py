#!/usr/bin/env python3
"""Offline controller parameter sweep over a recorded arrival stream."""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from theiatron.config import SignalConfig, QueueConfig, load_config
from theiatron.controller import AdaptiveController, FixedController
from theiatron.engine import IntersectionEngine
from theiatron.events import load_events
from theiatron.metrics import summarize

events, _ = load_events(sys.argv[1] if len(sys.argv) > 1 else "out/events.json")
DURATION = 180.0
app = load_config("configs/approaches.yaml")


def run(ctrl_cls, cfg, drain=None):
    eng = IntersectionEngine(ctrl_cls(cfg), cfg, app.approaches, QueueConfig())
    if drain is not None:
        eng.controller.DRAIN_THRESHOLD = drain
    eng.run_replay(events, DURATION)
    s = summarize(eng, DURATION)
    return s["avg_wait_s"], s["p95_wait_s"], s["phase_switches"]


base = SignalConfig()
f_avg, f_p95, f_sw = run(FixedController, base)
print(f"fixed baseline: avg={f_avg} p95={f_p95} switches={f_sw}")
print(f"{'min_g':>5} {'drain':>5} {'ratio':>5} {'hyst':>5} {'w':>5} | {'avg':>6} {'p95':>6} {'sw':>3}")

results = []
for min_g, drain, ratio, hyst, w in itertools.product(
    (5.0, 8.0, 12.0), (0, 1, 3), (1.5, 2.5, 4.0), (4.0, 10.0), (0.02, 0.05, 0.1)
):
    cfg = SignalConfig(min_green=min_g, hysteresis=hyst, pressure_ratio=ratio, wait_weight=w)
    avg, p95, sw = run(AdaptiveController, cfg, drain)
    results.append((avg, p95, sw, min_g, drain, ratio, hyst, w))

results.sort()
for avg, p95, sw, min_g, drain, ratio, hyst, w in results[:12]:
    print(f"{min_g:>5} {drain:>5} {ratio:>5} {hyst:>5} {w:>5} | {avg:>6} {p95:>6} {sw:>3}")
print("...")
for avg, p95, sw, min_g, drain, ratio, hyst, w in results[-3:]:
    print(f"{min_g:>5} {drain:>5} {ratio:>5} {hyst:>5} {w:>5} | {avg:>6} {p95:>6} {sw:>3}")
