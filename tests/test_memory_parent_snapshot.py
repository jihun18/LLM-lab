"""Single-table traversal keeps per-sample membership and identity protection."""
import os
import ctypes
from types import SimpleNamespace

import psutil
import pytest

from core.memory_sampling import ProcessScopes, MeasurementError, windows_parent_map
from test_service_console_host import fixture, Proc


def setup(monkeypatch, tmp_path):
    procs = fixture(monkeypatch, tmp_path)
    calls = []
    def parents():
        calls.append(1)
        return {pid: p.parent for pid, p in procs.items()}
    for p in procs.values():
        def forbidden(*args, **kwargs):
            raise AssertionError("must not enumerate again")
        p.children = forbidden
        p.ppid = forbidden
    scopes = ProcessScopes(1, 2, 3, procs.__getitem__, parent_map_factory=parents)
    return procs, calls, scopes


def test_one_fresh_table_per_membership_no_children_or_ppid_queries(monkeypatch, tmp_path):
    p, calls, scopes = setup(monkeypatch, tmp_path)
    assert len(calls) == 1
    sample = scopes.snapshot()
    assert len(calls) == 2
    assert "error" not in sample
    assert sample["membership_backend"] == "single-parent-snapshot-v1"
    assert sample["scopes"]["runner"]["rss_bytes"] == 800
    assert sample["scopes"]["service"]["rss_bytes"] == 200
    assert sample["excluded_service_console_hosts"][0]["pid"] == 4


@pytest.mark.parametrize("kind", ["missing_root", "runner_detached", "unknown", "overlap",
                                     "cycle", "old_child", "root_reused", "host_reused",
                                     "host_removed", "host_added", "host_wrong_path", "denied"])
def test_changed_or_unverifiable_graph_invalidates_sample(monkeypatch, tmp_path, kind):
    p, _, scopes = setup(monkeypatch, tmp_path)
    if kind == "missing_root": del p[1]
    if kind == "runner_detached": p[3].parent = 99
    if kind == "unknown": p[4].label = "unknown.exe"
    if kind == "overlap": p[1].parent = 3
    if kind == "cycle": p[3].parent = 5
    if kind == "old_child": p[5].created = 1
    if kind == "root_reused": p[3].created += 1
    if kind == "host_reused": p[4].created += 1
    if kind == "host_removed": p[4].parent = 99
    if kind == "host_added": p[6] = Proc(6, 2, "conhost.exe", p[4].path)
    if kind == "host_wrong_path": p[4].path = tmp_path / "fake.exe"
    if kind == "denied":
        def denied(): raise psutil.AccessDenied(5)
        p[5].create_time = denied
    if kind == "missing_root":
        # Real psutil reports an exited root, not dict KeyError.
        base = scopes.factory
        def factory(pid):
            if pid not in p: raise psutil.NoSuchProcess(pid)
            return base(pid)
        scopes.factory = factory
    sample = scopes.snapshot()
    assert sample["error"]
    assert all(v["rss_bytes"] is None for v in sample["scopes"].values())


def test_membership_acquisition_failure_is_not_fallback_or_zero(monkeypatch, tmp_path):
    _, _, scopes = setup(monkeypatch, tmp_path)
    def fail(): raise MeasurementError("table unavailable")
    scopes.parent_map_factory = fail
    sample = scopes.snapshot()
    assert "table unavailable" in sample["error"]
    assert sample["scopes"]["runner"]["rss_bytes"] is None


def test_child_identity_changes_during_membership(monkeypatch, tmp_path):
    p, _, scopes = setup(monkeypatch, tmp_path)
    count = []
    def changed():
        count.append(1)
        return 105 if len(count) == 1 else 106
    p[5].create_time = changed
    assert "identity changed during membership" in scopes.snapshot()["error"]


def test_child_reused_between_membership_and_rss_is_rejected(monkeypatch, tmp_path):
    p, _, scopes = setup(monkeypatch, tmp_path)
    original = scopes.members
    def members():
        groups = original()
        p[5].created += 1
        return groups
    scopes.members = members
    sample = scopes.snapshot()
    assert "reused after membership" in sample["error"]
    assert sample["scopes"]["runner"]["rss_bytes"] is None


def test_root_missing_from_table_is_rejected(monkeypatch, tmp_path):
    _, _, scopes = setup(monkeypatch, tmp_path)
    scopes.parent_map_factory = lambda: {2: 0, 3: 2, 4: 2, 5: 3}
    assert "root missing" in scopes.snapshot()["error"]


def test_native_loader_error_is_measurement_error(monkeypatch):
    def fail(*args, **kwargs): raise OSError("cannot load API")
    monkeypatch.setattr(ctypes, "WinDLL", fail, raising=False)
    with pytest.raises(MeasurementError, match="cannot load API"):
        windows_parent_map()


@pytest.mark.skipif(os.name != "nt", reason="Windows native snapshot")
def test_native_table_includes_current_pid_and_parent():
    parents = windows_parent_map()
    assert parents[os.getpid()] == psutil.Process().ppid()


@pytest.mark.parametrize("kind", ["create", "first", "next", "close", "duplicate", "ok"])
@pytest.mark.parametrize("profile", [False, True])
def test_native_api_failures_close_handle_and_never_return_partial_map(monkeypatch, kind, profile):
    calls = []
    class Function:
        def __init__(self, fn): self.fn = fn
        def __call__(self, *args): return self.fn(*args)
    def create(flags, pid):
        assert (flags, pid) == (2, 0)
        return ctypes.c_void_p(-1).value if kind == "create" else 123
    def first(handle, pointer):
        entry = pointer._obj
        assert entry.dwSize == ctypes.sizeof(entry)
        entry.th32ProcessID, entry.th32ParentProcessID = 10, 1
        return kind != "first"
    step = []
    def next_entry(handle, pointer):
        step.append(1)
        return kind == "duplicate" and len(step) == 1
    def close(handle):
        calls.append(handle)
        return kind != "close"
    api = SimpleNamespace(CreateToolhelp32Snapshot=Function(create), Process32FirstW=Function(first),
                          Process32NextW=Function(next_entry), CloseHandle=Function(close))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: api, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5 if kind in ("create", "first", "next") or
                        (kind == "close" and calls) else 18,
                        raising=False)
    records = [] if profile else None
    if kind == "ok": assert windows_parent_map(records) == {10: 1}
    else:
        with pytest.raises(MeasurementError): windows_parent_map(records)
    assert calls == ([] if kind == "create" else [123])
    if profile:
        names = [p['phase'] for p in records]
        assert names == (['api_prepare', 'snapshot_create'] if kind == 'create' else
                         ['api_prepare', 'snapshot_create', 'process_enumeration', 'snapshot_close'])
        failed = [p['phase'] for p in records if not p['completed']]
        expected = {'create': 'snapshot_create', 'first': 'process_enumeration',
                    'next': 'process_enumeration', 'duplicate': 'process_enumeration',
                    'close': 'snapshot_close'}
        assert failed == ([] if kind == 'ok' else [expected[kind]])
        assert all(a['end'] <= b['start'] for a, b in zip(records, records[1:]))
