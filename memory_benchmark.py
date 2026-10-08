"""Default: read-only preflight. --run explicitly enables warm request measurement."""
import argparse
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import threading
import time

import httpx
import psutil
from core.memory_sampling import MeasurementError, ProcessScopes, scope_summaries
from core.ollama_process import is_ollama_runner

ROOT = Path(__file__).resolve().parent
WEB_URL = "http://127.0.0.1:8000"
OLLAMA_URL = "http://127.0.0.1:11434"
SUPPORTED_MODELS = ("qwen3:1.7b", "qwen3:4b-instruct", "qwen2.5:7b-instruct")


def select_protocol(base, model):
    if model not in SUPPORTED_MODELS:
        raise MeasurementError("unsupported measurement model")
    protocol = copy.deepcopy(base)
    protocol["model"] = model
    if model != SUPPORTED_MODELS[0]:
        protocol["request"]["note"] = "Existing OllamaClient instruct path: no /no_think suffix; think=False."
    validate_protocol(protocol)
    return protocol


def validate_protocol(p):
    expected = {"protocol_id":"memory-rss-warm-v1", "sampling_interval_ms":100,
                "measured_requests":5, "warmup_requests":1, "concurrent_requests":1,
                "warm_idle_baseline_seconds":5, "minimum_idle_between_requests_seconds":3}
    if p.get("model") not in SUPPORTED_MODELS or any(p.get(k) != v for k,v in expected.items()):
        raise MeasurementError("unsupported protocol settings")
    r = p["request"]
    if (r["endpoint"],r["stream"],r["rag"],r["think"],r["num_ctx"],r["num_predict"],r["temperature"]) != ("/chat",False,False,False,2048,256,0.3):
        raise MeasurementError("unsupported request settings")


def get_json(client, path):
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def preflight(args, protocol, web_client, ollama_client):
    roots = ProcessScopes(args.web_pid, args.ollama_pid, args.runner_pid)
    web = psutil.Process(args.web_pid)
    cmd = web.cmdline()
    if "uvicorn" not in cmd or "app:app" not in cmd or Path(web.cwd()).resolve() != ROOT:
        raise MeasurementError("web PID is not this project's single FastAPI server")
    if not is_ollama_runner(psutil.Process(args.ollama_pid), psutil.Process(args.runner_pid)):
        raise MeasurementError("Ollama service/runner executable and command identity not confirmed")
    if any(p.pid == psutil.Process().pid for procs in roots.members().values() for p in procs):
        raise MeasurementError("measurement client belongs to measured scope")
    # Read only the allowed configuration keys; never persist environment dumps.
    env = web.environ()
    effective = {"num_ctx":int(env.get("OLLAMA_NUM_CTX","2048")),
                 "num_predict":int(env.get("OLLAMA_NUM_PREDICT","256")),
                 "temperature":float(env.get("OLLAMA_TEMPERATURE","0.3")),
                 "ollama_url":env.get("OLLAMA_URL",OLLAMA_URL).rstrip("/")}
    if any(effective[k] != protocol["request"][k] for k in ("num_ctx","num_predict","temperature")) or effective["ollama_url"] != OLLAMA_URL:
        raise MeasurementError("web server effective settings differ from protocol")
    source_files = [ROOT/"app.py", ROOT/"memory_benchmark.py", *sorted((ROOT/"core").glob("*.py"))]
    # Collector-only helpers are not imported by app.py; still hash them below.
    if any(path.stat().st_mtime > web.create_time() for path in source_files if path.name not in {"memory_sampling.py","memory_benchmark.py","ollama_process.py"}):
        raise MeasurementError("server predates source files; restart before measuring")
    health = get_json(web_client,"/health")
    if health.get("framework") != "FastAPI" or health.get("status") != "ok":
        raise MeasurementError("FastAPI/Ollama health check failed")
    active = get_json(ollama_client,"/api/ps").get("models",[])
    if len(active) != 1 or active[0].get("name") != protocol["model"] or not active[0].get("digest"):
        raise MeasurementError("exactly the selected model must already be loaded; no automatic unloading/loading")
    sample = roots.snapshot()
    if sample.get("error"):
        raise MeasurementError(sample["error"])
    return roots, {"effective_options":effective, "root_identities":roots.identities, "model_digest":active[0]["digest"],
                   "ollama_version":get_json(ollama_client,"/api/version"), "preflight_sample":sample,
                   "code_sha256":{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in source_files}}


def periodic_samples(roots, done, interval, anchor, schedule, clock=time.perf_counter):
    """Absolute deadlines; skip expired slots instead of burst catch-up reads."""
    tick = 1
    while not done.is_set():
        deadline = anchor + tick * interval
        now = clock()
        skipped = 0
        if now > deadline:
            next_tick = math.floor((now - anchor) / interval) + 1
            skipped = next_tick - tick
            tick = next_tick
            deadline = anchor + tick * interval
            schedule["skipped_ticks"] += skipped
        if done.wait(max(0.0, deadline - clock())):
            break
        sample = roots.snapshot()
        sample["sample_role"] = "periodic"
        sample["schedule"] = {"tick": tick, "target_time": deadline,
                              "lateness_seconds": max(0.0, sample["time"] - deadline),
                              "skipped_ticks_before": skipped}
        yield sample
        tick += 1


def capture(roots, interval, action):
    """Serial samples, endpoints included; network action runs in a separate thread."""
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("sampling interval must be finite and positive")
    samples = [roots.snapshot()]
    samples[0]["sample_role"] = "start"
    schedule = {"scheduler": "absolute-deadline-v2", "target_interval_seconds": interval,
                "anchor_time": samples[0]["time"], "skipped_ticks": 0}
    done = threading.Event()
    outcome = {}
    def worker():
        try:
            outcome["action_start"] = time.perf_counter()
            outcome["response"] = action()
        except Exception as exc:
            outcome["error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            outcome["action_end"] = time.perf_counter()
            done.set()
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        for sample in periodic_samples(roots, done, interval, samples[0]["time"], schedule):
            samples.append(sample)
    finally:
        thread.join()
    samples.append(roots.snapshot())
    samples[-1]["sample_role"] = "end"
    summaries = scope_summaries(samples)
    return {"samples":samples,"summary":summaries,"outcome":outcome,"sampling_schedule":schedule,
            "valid": not outcome.get("error") and all(s["valid"] for s in summaries.values()),
            "window_note":"pre-request sample through post-response sample; endpoint read latency included"}


def request_generation(client, protocol):
    request = protocol["request"]
    response = client.post("/chat",json={"model":protocol["model"],"prompt":request["prompt"],"system":request["system"]})
    response.raise_for_status()
    data = response.json()
    if not data.get("answer","").strip() or data.get("eval_count",0) <= 0 or data.get("model") != protocol["model"]:
        raise MeasurementError("missing actual model generation")
    return data


def main():
    parser = argparse.ArgumentParser(description="분리 RSS 수집: 기본은 읽기 전용 사전 확인")
    parser.add_argument("--web-pid",type=int,required=True)
    parser.add_argument("--ollama-pid",type=int,required=True)
    parser.add_argument("--runner-pid",type=int,required=True)
    parser.add_argument("--model", choices=SUPPORTED_MODELS, default=SUPPORTED_MODELS[0])
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--exclusive-confirmed",action="store_true",help="다른 요청·업로드·재색인이 없음을 사용자 확인")
    args = parser.parse_args()
    path = ROOT/"memory_measurement_protocol.json"
    base_bytes = path.read_bytes()
    protocol = select_protocol(json.loads(base_bytes), args.model)
    effective_bytes = json.dumps(protocol, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    protocol_bytes = base_bytes if args.model == SUPPORTED_MODELS[0] else effective_bytes
    report = {"status":"preflight", "sampling_scheduler":"absolute-deadline-v2",
              "protocol":protocol, "protocol_sha256":hashlib.sha256(protocol_bytes).hexdigest(),
              "base_protocol_sha256":hashlib.sha256(base_bytes).hexdigest(),
              "effective_protocol_sha256":hashlib.sha256(effective_bytes).hexdigest(),
              "protocol_hash_format":"base-file-bytes" if args.model == SUPPORTED_MODELS[0] else "canonical-json",
              "python":platform.python_version(),"os":platform.platform(),"psutil":psutil.__version__,
              "git_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
              "git_changes":subprocess.check_output(["git","status","--porcelain","--untracked-files=no"],cwd=ROOT,text=True),
              "warnings":["RSS sum can double-count shared pages", "sample maximum is not instantaneous peak",
                          "other simultaneous requests cannot be automatically ruled out", "single sequential PID reads are not atomic"],
              "trials":[]}
    try:
        validate_protocol(protocol)
        with httpx.Client(base_url=WEB_URL,timeout=180) as web, httpx.Client(base_url=OLLAMA_URL,timeout=10) as ollama:
            roots, metadata = preflight(args,protocol,web,ollama)
            report.update(metadata)
            if args.run:
                if not args.exclusive_confirmed:
                    raise MeasurementError("--run requires --exclusive-confirmed")
                report["warmup"] = request_generation(web,protocol)
                roots.snapshot()  # identity is checked again by every capture
                report["baseline"] = capture(roots,0.1,lambda:time.sleep(5))
                if not report["baseline"]["valid"]:
                    raise MeasurementError("invalid baseline; stopped")
                for trial in range(1,6):
                    if trial > 1: time.sleep(3)
                    roots, current = preflight(args,protocol,web,ollama)
                    if (current["model_digest"] != metadata["model_digest"] or current["code_sha256"] != metadata["code_sha256"]
                            or current["root_identities"] != metadata["root_identities"]):
                        raise MeasurementError("model or source changed during experiment")
                    result = capture(roots,0.1,lambda:request_generation(web,protocol))
                    result["trial"] = trial
                    report["trials"].append(result)
                    print(f"trial {trial}: {'valid' if result['valid'] else 'invalid'}",flush=True)
                    if not result["valid"]:
                        raise MeasurementError("invalid trial retained; no automatic retry")
                    try:
                        _, after = preflight(args,protocol,web,ollama)
                        if any(after[k] != metadata[k] for k in ("model_digest","code_sha256","root_identities")):
                            raise MeasurementError("source/model/process changed at end of trial")
                    except (MeasurementError,psutil.Error,httpx.HTTPError,ValueError,KeyError) as exc:
                        result["valid"] = False
                        result["post_check_error"] = type(exc).__name__ + ": " + str(exc)
                        raise
                report["status"] = "completed"
            else:
                report["status"] = "preflight_passed_no_generation"
    except (MeasurementError,psutil.Error,httpx.HTTPError,ValueError,KeyError) as exc:
        report["status"] = "blocked_or_incomplete"
        report["error"] = type(exc).__name__ + ": " + str(exc)
        print(report["error"],flush=True)
    finally:
        output = ROOT/"benchmark-results"/f"memory-rss-{datetime.now(timezone(timedelta(hours=9))):%Y%m%d-%H%M%S-%f}.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"{report['status']}: {output}",flush=True)
    return 0 if report["status"] in {"completed","preflight_passed_no_generation"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
