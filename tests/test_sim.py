from theiatron.config import QueueConfig
from theiatron.sim import PointQueue


def make_queue(lanes=1, sat_headway=2.0, startup_lost=2.0):
    return PointQueue(QueueConfig(lanes=lanes, sat_headway=sat_headway, startup_lost=startup_lost))


def run(q, duration, dt=0.1, t0=0.0):
    steps = int(duration / dt)
    for k in range(1, steps + 1):
        q.step(dt, t0 + k * dt)


def test_no_discharge_on_red():
    q = make_queue()
    q.set_green(False)
    for t in (0.0, 1.0, 2.0):
        q.arrive(t)
    run(q, 30.0)
    assert len(q.queue) == 3
    assert len(q.departed) == 0


def test_queue_conservation():
    q = make_queue()
    q.set_green(False)
    for t in range(10):
        q.arrive(float(t))
    q.set_green(True)
    run(q, 8.0, t0=10.0)  # enough for lost time + ~3 vehicles
    assert q.arrivals_total == 10
    assert len(q.departed) + len(q.queue) == 10
    assert 0 < len(q.departed) < 10


def test_discharge_saturation_rate_after_lost_time():
    q = make_queue(sat_headway=2.0, startup_lost=2.0)
    q.set_green(False)
    for t in range(20):
        q.arrive(0.0)
    q.set_green(True)
    # 12s of green: 2s lost, 10s effective => 5 vehicles at 1 veh / 2s.
    run(q, 12.0)
    assert len(q.departed) == 5


def test_wait_time_exactness():
    # Car arrives at t=0 on red; green at t=10; lost 2s + 1 headway of 2s
    # => departs at t=14, wait 14s.
    q = make_queue()
    q.set_green(False)
    q.arrive(0.0)
    run(q, 10.0)
    q.set_green(True)
    run(q, 10.0, t0=10.0)
    assert len(q.departed) == 1
    assert abs(q.departed[0].wait() - 14.0) < 0.11  # within one dt


def test_free_flow_zero_wait_on_effective_green():
    q = make_queue()
    q.set_green(True)
    run(q, 5.0)  # burn startup lost time, queue stays empty
    q.arrive(5.0)
    assert len(q.departed) == 1
    assert q.departed[0].wait() == 0.0


def test_idle_green_does_not_bank_unlimited_discharge():
    q = make_queue()
    q.set_green(True)
    run(q, 60.0)  # long empty green
    for _ in range(10):
        q.arrive(60.0)
    # First vehicle free-flows... queue was empty so arrival 1 passes, rest queue.
    q.step(0.1, 60.1)
    # With credit capped at 1, at most ~2 vehicles can leave near-instantly.
    assert len(q.departed) <= 2
