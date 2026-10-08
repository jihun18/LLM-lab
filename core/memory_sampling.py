"""Scoped RSS sampling. No process launches, guesses, zero imputation or Wiki writes."""
import math
import os
import time
import psutil
from .ollama_process import is_service_console_host


class MeasurementError(RuntimeError):
    pass


def windows_parent_map():
    """One fresh, read-only Toolhelp process snapshot; never cache membership.

    Microsoft: tlhelp32 PROCESSENTRY32W / CreateToolhelp32Snapshot.
    Only process IDs and parent IDs come from this table, not trusted paths/RSS.
    """
    try:
        return _windows_parent_map()
    except OSError as exc:
        raise MeasurementError(f"process snapshot API failed: {exc}") from exc


def _windows_parent_map():
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        getattr(api, name).argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        getattr(api, name).restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.CreateToolhelp32Snapshot(0x00000002, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise MeasurementError(f"process snapshot failed: WinError {ctypes.get_last_error()}")
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        if not api.Process32FirstW(handle, ctypes.byref(entry)):
            raise MeasurementError(f"process enumeration failed: WinError {ctypes.get_last_error()}")
        parents = {}
        while True:
            if entry.th32ProcessID in parents:
                raise MeasurementError("duplicate PID in process snapshot")
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            if not api.Process32NextW(handle, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES only.
                    raise MeasurementError(f"process enumeration failed: WinError {ctypes.get_last_error()}")
                break
        return parents
    finally:
        if not api.CloseHandle(handle):
            raise MeasurementError(f"snapshot close failed: WinError {ctypes.get_last_error()}")


def summarize(samples):
    """Left-held time weighted average; endpoints belong to this window only."""
    if len(samples) < 2 or any(s.get("error") or s.get("rss_bytes") is None for s in samples):
        return {"valid": False, "reason": "missing samples or process read error"}
    times = [s["time"] for s in samples]
    values = [s["rss_bytes"] for s in samples]
    if not all(math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        return {"valid": False, "reason": "invalid sample times"}
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values):
        return {"valid": False, "reason": "invalid RSS values"}
    intervals = [b-a for a, b in zip(times, times[1:])]
    duration = times[-1]-times[0]
    average = sum(v*dt for v, dt in zip(values, intervals))/duration
    return {"valid": True, "duration_seconds": duration, "sample_count": len(samples),
            "sampled_min_bytes": min(values), "sampled_max_bytes": max(values),
            "time_weighted_mean_bytes": average,
            "min_interval_seconds": min(intervals), "max_interval_seconds": max(intervals),
            "sampling_delayed": max(intervals) > 0.25}


class ProcessScopes:
    """Caller-confirmed roots. Pin identities; reject overlapping process trees."""
    def __init__(self, web_pid, service_pid, runner_pid, process_factory=psutil.Process, profile_timings=False,
                 parent_map_factory=None):
        self.factory = process_factory
        self.parent_map_factory = parent_map_factory
        if self.parent_map_factory is None and os.name == "nt" and process_factory is psutil.Process:
            self.parent_map_factory = windows_parent_map
        self.membership_backend = "single-parent-snapshot-v1" if self.parent_map_factory else "psutil-children"
        self.profile_timings = profile_timings
        self.roots = {"web": web_pid, "service": service_pid, "runner": runner_pid}
        if len(set(self.roots.values())) != 3 or any(p <= 0 for p in self.roots.values()):
            raise MeasurementError("three distinct positive process IDs are required")
        try:
            self.identities = {name: self.factory(pid).create_time() for name,pid in self.roots.items()}
            self.members()
        except psutil.Error as exc:
            raise MeasurementError(type(exc).__name__) from exc

    def members(self):
        roots = {name: self.factory(pid) for name,pid in self.roots.items()}
        for name, proc in roots.items():
            if proc.create_time() != self.identities[name]:
                raise MeasurementError("root process identity changed: " + name)
        parents = None
        self.member_created = {}
        if self.parent_map_factory is not None:
            parents = self.parent_map_factory()
            children = {}
            for pid, parent in parents.items():
                children.setdefault(parent, []).append(pid)
            objects = {p.pid: p for p in roots.values()}
            created = {p.pid: self.identities[name] for name, p in roots.items()}
            if not objects.keys() <= parents.keys():
                raise MeasurementError("root missing from process snapshot")

            def tree(root):
                pending, found, seen = [root.pid], [], {root.pid}
                while pending:
                    parent = pending.pop()
                    for pid in sorted(children.get(parent, [])):
                        if pid in seen:
                            raise MeasurementError("cyclic or duplicate process ancestry")
                        seen.add(pid)
                        if pid not in objects:
                            objects[pid] = self.factory(pid)
                            created[pid] = objects[pid].create_time()
                        if created[pid] < created[parent]:
                            raise MeasurementError("child predates parent; possible reused parent PID")
                        found.append(objects[pid])
                        pending.append(pid)
                return found

            web = [roots["web"], *tree(roots["web"])]
            runner = [roots["runner"], *tree(roots["runner"])]
            descendants = tree(roots["service"])
            for pid, proc in objects.items():
                if self.factory(pid).create_time() != created[pid]:
                    raise MeasurementError("process identity changed during membership verification")
            self.member_created = created
        else:
            web = [roots["web"], *roots["web"].children(recursive=True)]
            runner = [roots["runner"], *roots["runner"].children(recursive=True)]
            descendants = roots["service"].children(recursive=True)
        service_children = {p.pid for p in descendants}
        runner_ids = {p.pid for p in runner}
        if not runner_ids.issubset(service_children):
            raise MeasurementError("confirmed runner tree is missing from service descendants")
        excluded = []
        for proc in descendants:
            if proc.pid in runner_ids:
                continue
            created = proc.create_time()
            if not is_service_console_host(proc, roots["service"].pid,
                                           parent_pid=parents[proc.pid] if parents is not None else None):
                raise MeasurementError(f"unconfirmed extra service descendant: PID {proc.pid}")
            if self.factory(proc.pid).create_time() != created:
                raise MeasurementError("console host PID changed during verification")
            excluded.append({"pid": proc.pid, "created": created, "executable": proc.exe(),
                             "reason": "verified direct system console host; service scope is root only"})
        excluded_ids = {p["pid"]: p["created"] for p in excluded}
        if "excluded_service_console_hosts" in self.identities:
            if excluded_ids != self.identities["excluded_service_console_hosts"]:
                raise MeasurementError("excluded service console host membership changed")
        else:
            self.identities["excluded_service_console_hosts"] = excluded_ids
        self.excluded_service_console_hosts = excluded
        groups = {"web": web, "service": [roots["service"]], "runner": runner}
        seen = set(excluded_ids)
        for procs in groups.values():
            for p in procs:
                if p.pid in seen:
                    raise MeasurementError("overlapping or duplicate process membership")
                seen.add(p.pid)
        return groups

    @staticmethod
    def _measure(records, phase, operation):
        if records is None:
            return operation()
        started = time.perf_counter()
        cpu_start = time.thread_time()
        completed = False
        try:
            result = operation()
            completed = True
            return result
        finally:
            cpu_end = time.thread_time()
            ended = time.perf_counter()
            records.append({"phase": phase, "start": started, "end": ended,
                            "wall_seconds": ended-started,
                            "thread_cpu_seconds": cpu_end-cpu_start, "completed": completed})

    def snapshot(self):
        started = time.perf_counter()
        cpu_start = time.thread_time() if self.profile_timings else None
        records = [] if self.profile_timings else None
        values = {name: {"rss_bytes": None} for name in self.roots}
        try:
            groups = self._measure(records, "membership", self.members)
            for scope, procs in groups.items():
                members = []
                for proc in procs:
                    created = self._measure(records, "identity_before", proc.create_time)
                    if proc.pid in self.member_created and created != self.member_created[proc.pid]:
                        raise MeasurementError("process reused after membership verification")
                    rss = self._measure(records, "rss_read", proc.memory_info).rss
                    after = self._measure(records, "identity_after", lambda: self.factory(proc.pid).create_time())
                    if after != created:
                        raise MeasurementError("process reused during sample")
                    members.append({"pid": proc.pid, "created": created, "rss_bytes": rss})
                values[scope] = {"rss_bytes": sum(p["rss_bytes"] for p in members), "members": members}
            # Sequential process reads are not atomic. Keep acquisition width.
            sample = {"time": started, "scopes": values,
                      "membership_backend": self.membership_backend,
                      "excluded_service_console_hosts": self.excluded_service_console_hosts}
        except (psutil.Error, MeasurementError) as exc:
            sample = {"time": started, "error": type(exc).__name__ + ": " + str(exc), "scopes": values}
        if records is not None:
            cpu_end = time.thread_time()
            sample["read_end"] = time.perf_counter()
            sample["timing_profile"] = {"version": "collector-phase-v1", "phases": records,
                                        "thread_cpu_seconds": cpu_end-cpu_start}
        else:
            sample["read_end"] = time.perf_counter()
        return sample


def scope_summaries(samples):
    return {scope: summarize([{**s["scopes"][scope], "time": s["time"], "error": s.get("error")}
                              for s in samples]) for scope in ("web", "service", "runner")}
