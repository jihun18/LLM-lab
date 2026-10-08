"""Strict executable/argument recognition; process ancestry is checked by scopes."""
from pathlib import Path
import os
import re


def is_service_console_host(process, service_pid, *, parent_pid=None):
    """Only a direct Windows system console host; never a name-only exception."""
    if os.name != "nt" or process.name().lower() != "conhost.exe":
        return False
    if (process.ppid() if parent_pid is None else parent_pid) != service_pid:
        return False
    system_root = os.environ.get("SystemRoot")
    if not system_root or not Path(system_root).is_absolute():
        return False
    return Path(process.exe()).resolve() == (Path(system_root) / "System32" / "conhost.exe").resolve()


def is_ollama_runner(service, runner):
    if service.name().lower() != "ollama.exe" or "serve" not in service.cmdline():
        return False
    service_exe = Path(service.exe()).resolve()
    runner_exe = Path(runner.exe()).resolve()
    cmd = runner.cmdline()
    if runner.name().lower() == "ollama.exe":
        return runner_exe == service_exe and "runner" in cmd
    # Observed Ollama 0.40.0 Windows layout. Do not accept arbitrary llama servers.
    expected = service_exe.parent / "lib" / "ollama" / "llama-server.exe"
    if runner.name().lower() != "llama-server.exe" or runner_exe != expected.resolve():
        return False
    if not cmd or Path(cmd[0]).resolve() != runner_exe:
        return False
    values = {}
    for option in ("--model", "--host", "--port"):
        if cmd.count(option) != 1:
            return False
        index = cmd.index(option) + 1
        if index >= len(cmd):
            return False
        values[option] = cmd[index]
    model = Path(values["--model"])
    return (values["--host"] == "127.0.0.1" and values["--port"].isdigit()
            and 0 < int(values["--port"]) < 65536
            and "--offline" in cmd and "--no-webui" in cmd
            and model.is_absolute() and model.parent.name == "blobs"
            and model.parent.parent.name == "models"
            and re.fullmatch(r"sha256-[0-9a-f]{64}", model.name) is not None)
