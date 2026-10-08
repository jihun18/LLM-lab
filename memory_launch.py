"""Local launcher: discover listening PIDs, optionally prepare an installed model."""
import argparse
from pathlib import Path
import subprocess
import sys

import httpx
import psutil

from core.memory_sampling import MeasurementError
from core.ollama_process import is_ollama_runner

ROOT = Path(__file__).resolve().parent
OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen3:1.7b"


def listener_pid(connections, port):
    matches = [c for c in connections if c.status == psutil.CONN_LISTEN
               and c.laddr.port == port and c.laddr.ip in {"127.0.0.1", "0.0.0.0"}]
    if not matches or any(c.pid is None for c in matches):
        raise MeasurementError(f"{port}번 포트의 프로세스를 확인하지 못했습니다.")
    pids = {c.pid for c in matches}
    if len(pids) != 1:
        raise MeasurementError(f"{port}번 포트의 프로세스가 모호합니다.")
    return pids.pop()


def identify_services(connections, factory=psutil.Process):
    web_pid = listener_pid(connections, 8000)
    service_pid = listener_pid(connections, 11434)
    web, service = factory(web_pid), factory(service_pid)
    if "uvicorn" not in web.cmdline() or "app:app" not in web.cmdline() or Path(web.cwd()).resolve() != ROOT:
        raise MeasurementError("8000번 포트가 이 프로젝트의 FastAPI 서버가 아닙니다.")
    if "ollama" not in service.name().lower() or "serve" not in service.cmdline():
        raise MeasurementError("11434번 포트가 확인된 Ollama 서비스가 아닙니다.")
    return web_pid, service_pid, web.create_time(), service.create_time()


def check_model(client, prepare=False):
    response = client.get("/api/ps")
    response.raise_for_status()
    models = response.json().get("models", [])
    if models:
        if len(models) != 1 or models[0].get("name") != MODEL or not models[0].get("digest"):
            raise MeasurementError("다른 모델 또는 복수 모델이 적재되어 있습니다. 자동 종료하지 않습니다.")
        return
    if not prepare:
        raise MeasurementError("1.7B 모델이 적재되어 있지 않습니다. 명시적인 -PrepareModel 선택이 필요합니다.")
    response = client.get("/api/tags")
    response.raise_for_status()
    if not any(m.get("name") == MODEL for m in response.json().get("models", [])):
        raise MeasurementError("qwen3:1.7b가 설치되어 있지 않습니다. 자동 다운로드하지 않습니다.")
    # Recheck immediately before the explicit load; never unload another model.
    response = client.get("/api/ps")
    response.raise_for_status()
    if response.json().get("models", []):
        raise MeasurementError("모델 상태가 바뀌었습니다. 준비를 중단합니다.")
    print("설치된 1.7B 모델을 준비합니다. 다운로드·다른 모델 종료는 하지 않습니다.", flush=True)
    response = client.post("/api/generate", json={
        "model": MODEL, "prompt": "", "stream": False, "keep_alive": "15m",
        "options": {"num_ctx": 2048, "num_predict": 256, "temperature": 0.3}, "think": False,
    })
    response.raise_for_status()
    if response.json().get("done") is not True:
        raise MeasurementError("모델 준비가 완료되지 않았습니다.")
    check_model(client)


def runner_pid(service):
    candidates = [p for p in service.children(recursive=True)
                  if is_ollama_runner(service, p)]
    if len(candidates) != 1:
        raise MeasurementError("모델 runner를 하나로 확인하지 못했습니다. 추측하지 않습니다.")
    return candidates[0].pid


def main():
    parser = argparse.ArgumentParser(description="로컬 PowerShell용 분리 메모리 측정 실행기")
    parser.add_argument("--prepare-model", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--exclusive-confirmed", action="store_true")
    parser.add_argument("--confirm-interactively", action="store_true")
    args = parser.parse_args()
    try:
        if (args.run or args.prepare_model) and args.confirm_interactively:
            print("측정 중 다른 채팅·업로드·재색인·Ollama 요청을 멈춰주세요.", flush=True)
            args.exclusive_confirmed = input("다른 요청이 없으면 MEASURE를 입력하세요: ").strip() == "MEASURE"
        if (args.run or args.prepare_model) and not args.exclusive_confirmed:
            raise MeasurementError("모델 준비·실측 전에 다른 요청이 없다는 사용자 확인이 필요합니다.")
        web_pid, service_pid, web_created, service_created = identify_services(psutil.net_connections(kind="tcp"))
        with httpx.Client(base_url=OLLAMA_URL, timeout=180) as client:
            check_model(client, args.prepare_model)
        # Loading may take time. Re-identify listeners and pin roots before discovery.
        current = identify_services(psutil.net_connections(kind="tcp"))
        if current != (web_pid, service_pid, web_created, service_created):
            raise MeasurementError("준비 중 서버 프로세스가 변경되었습니다.")
        runner = runner_pid(psutil.Process(service_pid))
        print(f"확인된 PID: 웹 서버 {web_pid}, Ollama 서비스 {service_pid}, runner {runner}", flush=True)
        cmd = [sys.executable, str(ROOT / "memory_benchmark.py"), "--web-pid", str(web_pid),
               "--ollama-pid", str(service_pid), "--runner-pid", str(runner)]
        if args.run:
            cmd += ["--run", "--exclusive-confirmed"]
        return subprocess.run(cmd, cwd=ROOT, check=False).returncode
    except (MeasurementError, psutil.Error, httpx.HTTPError, OSError, ValueError, KeyError, EOFError) as exc:
        print(f"측정 시작 중단: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("다른 프로세스를 종료하거나 실패를 0으로 대체하지 않았습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
