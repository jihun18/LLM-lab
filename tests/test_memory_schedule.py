import pytest

from memory_benchmark import capture, periodic_samples


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


class Done:
    def __init__(self, clock, end, wake_delay=0):
        self.clock, self.end, self.wake_delay = clock, end, wake_delay
    def is_set(self): return self.clock.now >= self.end
    def wait(self, timeout):
        if self.clock.now + timeout >= self.end:
            self.clock.now = self.end
            return True
        self.clock.now += timeout + self.wake_delay
        if self.clock.now >= self.end:
            return True
        return False


class Roots:
    def __init__(self, clock, cost): self.clock, self.cost = clock, cost
    def snapshot(self):
        started = self.clock.now
        self.clock.now += self.cost
        return {"time": started, "read_end": self.clock.now}


def collect(cost=0.04, end=0.45, wake_delay=0, start=0):
    clock = Clock()
    clock.now = start
    schedule = {"skipped_ticks": 0}
    samples = list(periodic_samples(Roots(clock, cost), Done(clock, end, wake_delay),
                                    0.1, 0.0, schedule, clock))
    return samples, schedule


def test_read_cost_does_not_accumulate_into_interval():
    samples, schedule = collect()
    assert [s["time"] for s in samples] == pytest.approx([0.1, 0.2, 0.3, 0.4])
    assert schedule["skipped_ticks"] == 0
    assert all(s["sample_role"] == "periodic" for s in samples)


def test_overrun_skips_slots_without_burst_reads():
    samples, schedule = collect(cost=0.15, end=0.7)
    assert [s["time"] for s in samples] == pytest.approx([0.1, 0.3, 0.5])
    assert [s["schedule"]["tick"] for s in samples] == [1, 3, 5]
    assert schedule["skipped_ticks"] == 3


def test_initial_endpoint_read_cost_can_skip_expired_slots():
    samples, schedule = collect(start=0.26)
    assert [s["time"] for s in samples] == pytest.approx([0.3, 0.4])
    assert samples[0]["schedule"]["skipped_ticks_before"] == 2


def test_late_wakeup_is_recorded_not_hidden():
    samples, _ = collect(wake_delay=0.025)
    assert samples[0]["time"] == pytest.approx(0.125)
    assert samples[0]["schedule"]["target_time"] == pytest.approx(0.1)
    assert samples[0]["schedule"]["lateness_seconds"] == pytest.approx(0.025)


def test_completion_during_wait_prevents_periodic_read():
    samples, _ = collect(end=0.05)
    assert samples == []


@pytest.mark.parametrize("interval", [0, -0.1, float("nan"), float("inf")])
def test_invalid_interval_rejected_before_sampling(interval):
    class NoReads:
        def snapshot(self): pytest.fail("unexpected snapshot")
    with pytest.raises(ValueError): capture(NoReads(), interval, lambda: None)
