from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

import core.ollama_process as identity
from core.memory_sampling import ProcessScopes, MeasurementError


class Proc:
    def __init__(self, pid, parent, name, exe):
        self.pid, self.parent, self.label, self.path = pid, parent, name, exe
        self.created = pid + 100
        self.descendants = []
    def name(self): return self.label
    def exe(self): return str(self.path)
    def ppid(self): return self.parent
    def create_time(self): return self.created
    def children(self, recursive): return self.descendants
    def memory_info(self): return SimpleNamespace(rss=self.pid * 100)


def fixture(monkeypatch, tmp_path):
    # Do not patch os.name globally: pathlib would switch to WindowsPath.
    monkeypatch.setattr(identity, "os", SimpleNamespace(name="nt", environ={"SystemRoot": str(tmp_path)}))
    console = tmp_path / "System32" / "conhost.exe"
    procs = {1: Proc(1, 0, "python.exe", tmp_path / "python.exe"),
             2: Proc(2, 0, "ollama.exe", tmp_path / "ollama.exe"),
             3: Proc(3, 2, "llama-server.exe", tmp_path / "llama-server.exe"),
             4: Proc(4, 2, "conhost.exe", console),
             5: Proc(5, 3, "conhost.exe", console)}
    procs[2].descendants = [procs[4], procs[3], procs[5]]
    procs[3].descendants = [procs[5]]
    return procs


def test_direct_console_host_is_explicitly_excluded_runner_console_is_included(monkeypatch, tmp_path):
    p = fixture(monkeypatch, tmp_path)
    scopes = ProcessScopes(1, 2, 3, p.__getitem__)
    sample = scopes.snapshot()
    assert "error" not in sample
    assert sample["scopes"]["service"]["rss_bytes"] == 200
    assert sample["scopes"]["runner"]["rss_bytes"] == 800
    assert sample["excluded_service_console_hosts"][0]["pid"] == 4
    assert scopes.identities["excluded_service_console_hosts"] == {4: 104}


@pytest.mark.parametrize("kind", ["path", "parent", "name", "no_root", "relative_root", "not_windows"])
def test_name_alone_or_wrong_environment_never_authorizes_exclusion(monkeypatch, tmp_path, kind):
    p = fixture(monkeypatch, tmp_path)
    if kind == "path": p[4].path = tmp_path / "fake" / "conhost.exe"
    if kind == "parent": p[4].parent = 99
    if kind == "name": p[4].label = "unrelated.exe"
    if kind == "no_root": identity.os.environ.clear()
    if kind == "relative_root": identity.os.environ["SystemRoot"] = "relative"
    if kind == "not_windows": identity.os.name = "posix"
    with pytest.raises(MeasurementError): ProcessScopes(1, 2, 3, p.__getitem__)


@pytest.mark.parametrize("kind", ["reused", "removed", "added", "denied", "path_changed"])
def test_console_changes_invalidate_sample(monkeypatch, tmp_path, kind):
    p = fixture(monkeypatch, tmp_path)
    scopes = ProcessScopes(1, 2, 3, p.__getitem__)
    if kind == "reused": p[4].created += 1
    if kind == "removed": p[2].descendants.remove(p[4])
    if kind == "added":
        p[6] = Proc(6, 2, "conhost.exe", p[4].path)
        p[2].descendants.append(p[6])
    if kind == "denied":
        def denied(): raise psutil.AccessDenied(4)
        p[4].exe = denied
    if kind == "path_changed": p[4].path = tmp_path / "fake" / "conhost.exe"
    sample = scopes.snapshot()
    assert sample["error"]
    assert all(v["rss_bytes"] is None for v in sample["scopes"].values())


def test_missing_runner_descendant_still_rejected(monkeypatch, tmp_path):
    p = fixture(monkeypatch, tmp_path)
    p[2].descendants.remove(p[5])
    with pytest.raises(MeasurementError): ProcessScopes(1, 2, 3, p.__getitem__)


def test_excluded_console_cannot_overlap_web_scope(monkeypatch, tmp_path):
    p = fixture(monkeypatch, tmp_path)
    p[1].descendants = [p[4]]
    with pytest.raises(MeasurementError): ProcessScopes(1, 2, 3, p.__getitem__)
