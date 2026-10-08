from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from core.ollama_process import is_ollama_runner
from memory_launch import runner_pid


def fixture(tmp_path):
    service_exe = tmp_path / "Ollama" / "ollama.exe"
    runner_exe = service_exe.parent / "lib" / "ollama" / "llama-server.exe"
    model = tmp_path / "models" / "blobs" / ("sha256-" + "a" * 64)
    service = SimpleNamespace(pid=20, name=lambda: "ollama.exe", exe=lambda: str(service_exe),
                              cmdline=lambda: [str(service_exe), "serve"])
    cmd = [str(runner_exe), "--model", str(model), "--port", "58898", "--host", "127.0.0.1",
           "--no-webui", "--offline", "-c", "2048", "-np", "1"]
    runner = SimpleNamespace(pid=30, name=lambda: "llama-server.exe", exe=lambda: str(runner_exe),
                             cmdline=lambda: cmd)
    service.children = lambda recursive: [runner]
    return service, runner, cmd


def test_observed_windows_llamacpp_layout(tmp_path):
    service, runner, _ = fixture(tmp_path)
    assert is_ollama_runner(service, runner)
    assert runner_pid(service) == 30


@pytest.mark.parametrize("change", ["exe", "argv_exe", "name", "service", "host", "port",
                                   "missing_value", "duplicate_model", "relative_model", "model_hash",
                                   "offline", "webui"])
def test_unconfirmed_llama_server_is_not_accepted(tmp_path, change):
    service, runner, cmd = fixture(tmp_path)
    if change == "exe": runner.exe = lambda: str(tmp_path / "llama-server.exe")
    if change == "argv_exe": cmd[0] = str(tmp_path / "llama-server.exe")
    if change == "name": runner.name = lambda: "unrelated.exe"
    if change == "service": service.cmdline = lambda: ["ollama", "run"]
    if change == "host": cmd[cmd.index("--host") + 1] = "0.0.0.0"
    if change == "port": cmd[cmd.index("--port") + 1] = "70000"
    if change == "missing_value": cmd[:] = cmd[:cmd.index("--port") + 1]
    if change == "duplicate_model": cmd.extend(["--model", cmd[2]])
    if change == "relative_model": cmd[2] = "models/blobs/sha256-" + "a" * 64
    if change == "model_hash": cmd[2] = str(Path(cmd[2]).with_name("sha256-invalid"))
    if change == "offline": cmd.remove("--offline")
    if change == "webui": cmd.remove("--no-webui")
    assert not is_ollama_runner(service, runner)


def test_same_ollama_executable_runner_still_supported(tmp_path):
    service, runner, _ = fixture(tmp_path)
    runner.name = lambda: "ollama.exe"
    runner.exe = service.exe
    runner.cmdline = lambda: [service.exe(), "runner"]
    assert is_ollama_runner(service, runner)
    runner.exe = lambda: str(tmp_path / "other" / "ollama.exe")
    assert not is_ollama_runner(service, runner)


def test_access_denied_is_not_silently_skipped(tmp_path):
    service, runner, _ = fixture(tmp_path)
    def denied(): raise psutil.AccessDenied(runner.pid)
    runner.exe = denied
    with pytest.raises(psutil.AccessDenied): runner_pid(service)
