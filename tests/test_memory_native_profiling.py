import ctypes
from types import SimpleNamespace

import pytest
import core.memory_sampling as sampling
from test_service_console_host import fixture


def test_api_prepare_error_recorded_before_acquiring_handle(monkeypatch):
    def fail(): raise OSError('API unavailable')
    monkeypatch.setattr(sampling, '_prepare_windows_api', fail)
    records = []
    with pytest.raises(sampling.MeasurementError, match='API unavailable'):
        sampling.windows_parent_map(records)
    assert len(records) == 1
    assert records[0]['phase'] == 'api_prepare' and not records[0]['completed']


def test_native_off_never_reads_cpu_clock(monkeypatch):
    def forbidden(): pytest.fail('CPU clock read with profiling OFF')
    monkeypatch.setattr(sampling.time, 'thread_time', forbidden)
    # An early failure is still an OFF call and must not read the CPU clock.
    def fail(): raise OSError('API unavailable')
    monkeypatch.setattr(sampling, '_prepare_windows_api', fail)
    with pytest.raises(sampling.MeasurementError): sampling.windows_parent_map()


def test_native_phases_are_nested_once_and_preserve_rss(monkeypatch, tmp_path):
    procs = fixture(monkeypatch, tmp_path)
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', ctypes.c_uint32), ('th32ProcessID', ctypes.c_uint32),
                    ('th32ParentProcessID', ctypes.c_uint32)]
    closed, created = [], []
    entries = []
    def create(flags, pid):
        created.append(1)
        entries[:] = list(procs.values())
        return 123
    def next_entry(handle, ptr):
        if not entries: return False
        p = entries.pop(0)
        ptr._obj.th32ProcessID = p.pid
        ptr._obj.th32ParentProcessID = p.parent
        return True
    def close(handle): closed.append(handle); return True
    api = SimpleNamespace(CreateToolhelp32Snapshot=create, Process32FirstW=next_entry,
                          Process32NextW=next_entry, CloseHandle=close)
    monkeypatch.setattr(sampling, '_prepare_windows_api', lambda: (ctypes, api, Entry))
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 18, raising=False)
    scopes = sampling.ProcessScopes(1, 2, 3, procs.__getitem__, profile_timings=True,
                                    parent_map_factory=sampling.windows_parent_map)
    sample = scopes.snapshot()
    assert 'error' not in sample and sample['scopes']['runner']['rss_bytes'] == 800
    profile = sample['timing_profile']
    phases = profile['parent_snapshot_phases']
    assert [p['phase'] for p in phases] == ['api_prepare', 'snapshot_create',
                                          'process_enumeration', 'snapshot_close']
    parent = next(p for p in profile['membership_phases'] if p['phase'] == 'parent_snapshot')
    assert all(parent['start'] <= p['start'] <= p['end'] <= parent['end'] for p in phases)
    assert sum(p['wall_seconds'] for p in phases) <= parent['wall_seconds']
    assert len(created) == len(closed) == 2  # Constructor and one sample, not extra queries.
    again = scopes.snapshot()['timing_profile']['parent_snapshot_phases']
    assert again is not phases and len(again) == 4


def test_injected_parent_factory_is_not_given_new_arguments(monkeypatch, tmp_path):
    procs = fixture(monkeypatch, tmp_path)
    scopes = sampling.ProcessScopes(1, 2, 3, procs.__getitem__, profile_timings=True,
                                    parent_map_factory=lambda: {pid: p.parent for pid, p in procs.items()})
    sample = scopes.snapshot()
    assert 'error' not in sample
    assert sample['timing_profile']['parent_snapshot_phases'] == []
