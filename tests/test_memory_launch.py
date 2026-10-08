from types import SimpleNamespace
import httpx
import psutil
import pytest

from core.memory_sampling import MeasurementError
from memory_launch import listener_pid, identify_services, check_model, runner_pid, ROOT, MODEL


def listener(pid=10, port=8000, ip="127.0.0.1", status=psutil.CONN_LISTEN):
    return SimpleNamespace(pid=pid, status=status, laddr=SimpleNamespace(ip=ip, port=port))


def test_unique_listener():
    assert listener_pid([listener(), listener(ip="0.0.0.0")], 8000) == 10


@pytest.mark.parametrize("connections", [[], [listener(None)], [listener(), listener(11)],
                         [listener(ip="192.168.0.2")], [listener(status="ESTABLISHED")]])
def test_missing_or_ambiguous_listener_rejected(connections):
    with pytest.raises(MeasurementError):
        listener_pid(connections, 8000)


class Proc:
    def __init__(self, pid, name, cmd, cwd=ROOT):
        self.pid, self._name, self._cmd, self._cwd = pid, name, cmd, cwd
        self.descendants = []
    def name(self): return self._name
    def cmdline(self): return self._cmd
    def cwd(self): return str(self._cwd)
    def create_time(self): return self.pid + 100
    def exe(self): return str(ROOT / self._name)
    def children(self, recursive): return self.descendants


def processes():
    return {10: Proc(10, "python.exe", ["python", "-m", "uvicorn", "app:app"]),
            20: Proc(20, "ollama.exe", ["ollama", "serve"])}


def test_services_pin_creation_times():
    p = processes()
    assert identify_services([listener(), listener(20, 11434)], p.__getitem__) == (10, 20, 110, 120)


@pytest.mark.parametrize("wrong", ["web", "cwd", "service"])
def test_wrong_service_identity_rejected(wrong):
    p = processes()
    if wrong == "web": p[10]._cmd = ["unrelated"]
    if wrong == "cwd": p[10]._cwd = ROOT.parent
    if wrong == "service": p[20]._cmd = ["ollama", "run"]
    with pytest.raises(MeasurementError):
        identify_services([listener(), listener(20, 11434)], p.__getitem__)


def model_client(active, installed=True, changed=False, done=True, model=MODEL):
    calls = []
    ps_reads = 0
    loaded = False
    def handler(request):
        nonlocal ps_reads, loaded
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/ps":
            ps_reads += 1
            models = active
            if loaded: models = [{"name": model, "digest": "abc"}]
            if changed and ps_reads == 2: models = [{"name": "other"}]
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": model}] if installed else []})
        if request.url.path == "/api/generate":
            import json
            data = json.loads(request.content)
            assert data["model"] == model and data["prompt"] == "" and data["keep_alive"] == "15m"
            assert data["options"]["num_ctx"] == 2048
            loaded = done
            return httpx.Response(200, json={"done": done})
        raise AssertionError(request.url)
    return httpx.Client(base_url="http://localhost", transport=httpx.MockTransport(handler)), calls


def test_default_never_loads():
    client, calls = model_client([])
    with client, pytest.raises(MeasurementError): check_model(client)
    assert calls == [("GET", "/api/ps")]


def test_existing_model_is_not_reloaded():
    client, calls = model_client([{"name": MODEL, "digest": "abc"}])
    with client: check_model(client, True)
    assert calls == [("GET", "/api/ps")]


@pytest.mark.parametrize("active", [[{"name": "other"}], [{"name": MODEL}],
                         [{"name": MODEL, "digest": "abc"}, {"name": "other"}]])
def test_other_or_unverified_models_not_touched(active):
    client, calls = model_client(active)
    with client, pytest.raises(MeasurementError): check_model(client, True)
    assert all(method == "GET" for method, _ in calls)


@pytest.mark.parametrize("option", ["uninstalled", "changed"])
def test_no_download_or_overwriting_changed_state(option):
    client, calls = model_client([], installed=option != "uninstalled", changed=option == "changed")
    with client, pytest.raises(MeasurementError): check_model(client, True)
    assert all(method == "GET" for method, _ in calls)


def test_explicit_load_of_installed_model():
    client, calls = model_client([])
    with client: check_model(client, True)
    assert calls.count(("POST", "/api/generate")) == 1


def test_incomplete_load_rejected():
    client, calls = model_client([], done=False)
    with client, pytest.raises(MeasurementError): check_model(client, True)


def test_runner_requires_one_verified_candidate():
    service = processes()[20]
    with pytest.raises(MeasurementError): runner_pid(service)
    service.descendants = [Proc(30, "ollama.exe", ["ollama", "runner"])]
    assert runner_pid(service) == 30
    service.descendants.append(Proc(31, "ollama.exe", ["ollama", "runner"]))
    with pytest.raises(MeasurementError): runner_pid(service)


@pytest.mark.parametrize("args", [["--run"], ["--prepare-model"],
                                  ["--run", "--confirm-interactively"]])
def test_consent_required_before_process_or_network_work(monkeypatch, args):
    import memory_launch
    monkeypatch.setattr("sys.argv", ["memory_launch.py", *args])
    monkeypatch.setattr("builtins.input", lambda _: "NO")
    monkeypatch.setattr(memory_launch.psutil, "net_connections", lambda **kwargs: pytest.fail("unexpected process work"))
    assert memory_launch.main() == 1


@pytest.mark.parametrize("run", [False, True])
def test_launcher_forwards_confirmed_scope_to_collector(monkeypatch, run):
    import memory_launch
    calls = []
    monkeypatch.setattr("sys.argv", ["memory_launch.py", *(["--run", "--exclusive-confirmed"] if run else [])])
    monkeypatch.setattr(memory_launch.psutil, "net_connections", lambda **kwargs: [])
    monkeypatch.setattr(memory_launch, "identify_services", lambda _: (10, 20, 110, 120))
    monkeypatch.setattr(memory_launch, "check_model", lambda *args: None)
    monkeypatch.setattr(memory_launch.psutil, "Process", lambda _: processes()[20])
    monkeypatch.setattr(memory_launch, "runner_pid", lambda _: 30)
    def collect(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(memory_launch.subprocess, "run", collect)
    assert memory_launch.main() == 7
    assert calls[0][2:8] == ["--web-pid", "10", "--ollama-pid", "20", "--runner-pid", "30"]
    assert ("--run" in calls[0]) == run


def test_changed_listener_identity_blocks_collection(monkeypatch):
    import memory_launch
    states = iter([(10, 20, 110, 120), (10, 20, 111, 120)])
    monkeypatch.setattr("sys.argv", ["memory_launch.py"])
    monkeypatch.setattr(memory_launch.psutil, "net_connections", lambda **kwargs: [])
    monkeypatch.setattr(memory_launch, "identify_services", lambda _: next(states))
    monkeypatch.setattr(memory_launch, "check_model", lambda *args: None)
    monkeypatch.setattr(memory_launch.subprocess, "run", lambda *a, **k: pytest.fail("unexpected collection"))
    assert memory_launch.main() == 1
