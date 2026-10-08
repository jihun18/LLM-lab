import pytest

import core.memory_sampling as sampling
import memory_benchmark as benchmark
import memory_launch
from test_memory_sampling import fixture
from test_memory_schedule import Clock, Done, Roots


def test_profile_is_opt_in_and_off_never_reads_cpu_clock(monkeypatch):
    p = fixture()
    scope = sampling.ProcessScopes(1, 2, 3, p.__getitem__)
    def forbidden(): pytest.fail("CPU clock read while profiling disabled")
    monkeypatch.setattr(sampling.time, "thread_time", forbidden)
    sample = scope.snapshot()
    assert "timing_profile" not in sample and "error" not in sample


def test_profile_preserves_rss_and_identity_checks():
    p = fixture()
    scope = sampling.ProcessScopes(1, 2, 3, p.__getitem__, profile_timings=True)
    sample = scope.snapshot()
    assert sample["scopes"]["runner"]["rss_bytes"] == 300
    profile = sample["timing_profile"]
    phases = profile["phases"]
    assert [v["phase"] for v in phases].count("membership") == 1
    assert [v["phase"] for v in phases].count("rss_read") == 3
    assert [v["phase"] for v in phases].count("identity_before") == 3
    assert [v["phase"] for v in phases].count("identity_after") == 3
    assert all(v["completed"] and v["thread_cpu_seconds"] >= 0 and v["wall_seconds"] >= 0 for v in phases)
    assert sum(v["wall_seconds"] for v in phases) <= sample["read_end"]-sample["time"]
    assert profile["thread_cpu_seconds"] >= 0
    p[3].created += 1
    assert "error" in scope.snapshot()


def test_failed_phase_is_recorded_without_zero_imputation():
    p = fixture()
    scope = sampling.ProcessScopes(1, 2, 3, p.__getitem__, profile_timings=True)
    p[2].denied = True
    sample = scope.snapshot()
    assert sample["error"] and sample["scopes"]["service"]["rss_bytes"] is None
    assert sample["scopes"]["web"]["rss_bytes"] == 100
    failed = [v for v in sample["timing_profile"]["phases"] if not v["completed"]]
    assert len(failed) == 1 and failed[0]["phase"] == "rss_read"


def test_clock_deltas_are_explicit_not_cpu_percent(monkeypatch):
    wall = iter([10.0, 10.5])
    cpu = iter([2.0, 2.03])
    monkeypatch.setattr(sampling.time, "perf_counter", lambda: next(wall))
    monkeypatch.setattr(sampling.time, "thread_time", lambda: next(cpu))
    records = []
    assert sampling.ProcessScopes._measure(records, "rss_read", lambda: 7) == 7
    assert records[0]["wall_seconds"] == pytest.approx(.5)
    assert records[0]["thread_cpu_seconds"] == pytest.approx(.03)


def test_wait_profile_records_wakeup_and_completion(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(benchmark.time, "thread_time", lambda: 0.0)
    schedule = {"skipped_ticks": 0, "profile_timings": True, "wait_calls": []}
    samples = list(benchmark.periodic_samples(Roots(clock, .04), Done(clock, .3, .025),
                                              .1, 0, schedule, clock))
    waits = schedule["wait_calls"]
    assert len(samples) == 2 and len(waits) == 3
    assert waits[0]["requested_seconds"] == pytest.approx(.1)
    assert waits[0]["wall_seconds"] == pytest.approx(.125)
    assert waits[0]["excess_wait_seconds"] == pytest.approx(.025)
    assert waits[-1]["completed_during_wait"]
    assert waits[-1]["excess_wait_seconds"] is None


def test_wait_cpu_clock_not_called_when_disabled(monkeypatch):
    clock = Clock()
    def forbidden(): pytest.fail("CPU clock read while profiling disabled")
    monkeypatch.setattr(benchmark.time, "thread_time", forbidden)
    schedule = {"skipped_ticks": 0}
    list(benchmark.periodic_samples(Roots(clock, .04), Done(clock, .25), .1, 0, schedule, clock))
    assert "wait_calls" not in schedule


def test_capture_profiles_waits_and_keeps_endpoint_roles():
    p = fixture()
    scope = sampling.ProcessScopes(1, 2, 3, p.__getitem__, profile_timings=True)
    result = benchmark.capture(scope, .01, lambda: None)
    assert result["valid"]
    assert result["samples"][0]["sample_role"] == "start"
    assert result["samples"][-1]["sample_role"] == "end"
    assert all("timing_profile" in s for s in result["samples"])
    assert "wait_calls" in result["sampling_schedule"]


def test_launcher_forwards_profile_flag(monkeypatch):
    from types import SimpleNamespace
    commands = []
    monkeypatch.setattr("sys.argv", ["memory_launch.py", "--profile-timings"])
    monkeypatch.setattr(memory_launch.psutil, "net_connections", lambda **kw: [])
    monkeypatch.setattr(memory_launch, "identify_services", lambda _: (10, 20, 110, 120))
    monkeypatch.setattr(memory_launch, "check_model", lambda *a: None)
    monkeypatch.setattr(memory_launch.psutil, "Process", lambda _: SimpleNamespace())
    monkeypatch.setattr(memory_launch, "runner_pid", lambda _: 30)
    def collect(cmd, **kw):
        commands.append(cmd)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(memory_launch.subprocess, "run", collect)
    assert memory_launch.main() == 0
    assert "--profile-timings" in commands[0]
