"""Sequential warm-model RAG comparison with frozen retrieval and cold probes."""
import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean
import time

from core.config import settings
from core.ollama_client import OllamaClient
from core.search import SearchKnowledge
from core.rag_service import grounded_response, source_payload
from rag_evaluation import load_cases, score_answer
from answer_review import write_review_sheet

ROOT = Path(__file__).resolve().parent
MODELS = ["qwen3:1.7b", "qwen3:4b-instruct", "qwen2.5:7b-instruct"]
CASE_IDS = ["fresh_mode_table", "fresh_roles", "fresh_badges", "fresh_duplicate",
            "fresh_policy_year", "fresh_future_bench", "legacy_speed"]
SYSTEM = "Wiki 근거만 사용하고 간결하고 정확한 한국어로 답하세요."


class MeasuredClient(OllamaClient):
    def __init__(self):
        super().__init__(timeout=300)
        self.calls = []

    def chat(self, prompt, model=None, system=None, response_format=None):
        payload = self._payload(prompt, model, system, stream=False)
        payload["options"]["seed"] = 42
        if response_format is not None:
            payload["format"] = response_format
        started = time.perf_counter()
        with self._client() as client:
            response = client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        elapsed = time.perf_counter() - started
        timing = {key: data.get(key) for key in ("load_duration", "prompt_eval_duration",
                  "prompt_eval_count", "eval_duration", "eval_count", "total_duration", "done_reason")}
        self.calls.append(timing)
        count, duration = data.get("eval_count", 0), data.get("eval_duration", 0)
        return {"model": data.get("model", model), "answer": data.get("message", {}).get("content", ""),
                "elapsed_seconds": elapsed, "tokens_per_second": round(count/(duration/1e9), 2) if count and duration else None,
                "eval_count": count}

    def unload(self, model):
        with self._client() as client:
            response = client.post("/api/generate", json={"model": model, "keep_alive": 0, "stream": False})
            response.raise_for_status()

    def resident(self):
        with self._client() as client:
            response = client.get("/api/ps")
            response.raise_for_status()
            return response.json().get("models", [])


def classify_path(calls, response):
    if calls:
        return "llm_generation"
    if response.get("execution_path") == "requirements_abstention":
        return "requirements_abstention"
    if response.get("model") == "deterministic-text":
        return "deterministic_text"
    if response.get("model") == "deterministic-comparison":
        return "deterministic_role_comparison"
    return "deterministic_table" if response.get("model") == "deterministic-table" else "no_evidence"


def summarize_rows(rows, model):
    own = [r for r in rows if r["generation_model"] == model]
    generated = [r for r in own if r["execution_path"] == "llm_generation"]
    return {"model": model, "cases": len(own), "generated_cases": len(generated),
            "average_answer_score": round(mean(r["answer_score"] for r in own), 1),
            "average_generation_seconds": round(mean(r["elapsed_seconds"] for r in generated), 3) if generated else None,
            "average_generation_score": round(mean(r["answer_score"] for r in generated), 1) if generated else None,
            "average_tokens_per_second": round(mean(r["tokens_per_second"] for r in generated if r["tokens_per_second"]), 2)
            if any(r["tokens_per_second"] for r in generated) else None,
            "non_generation_cases": len(own)-len(generated)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=MODELS, choices=MODELS)
    args = parser.parse_args()
    client = MeasuredClient()
    installed = {m["name"]: m for m in client.list_models()}
    if any(model not in installed for model in args.models):
        parser.error("모든 비교 모델을 먼저 Ollama에 설치하세요.")
    cases_by_id = {c["id"]: c for c in load_cases(ROOT / "search_independent_cases.json") + load_cases(ROOT / "rag_evaluation_cases.json")}
    cases = [cases_by_id[key] for key in CASE_IDS]
    knowledge = SearchKnowledge(ROOT / "wiki", client, settings.embedding_model, settings.semantic_threshold)
    knowledge.reindex()
    frozen = {c["id"]: knowledge.search(c["question"], mode="hybrid") for c in cases}
    snapshot = {key: [r.to_dict() for r in results] for key, results in frozen.items()}
    path = ROOT / "benchmark-results" / ("model-comparison-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    report = {"protocol": {"search_mode": "hybrid", "embedding_model": settings.embedding_model,
              "threshold": settings.semantic_threshold, "num_ctx": settings.num_ctx, "num_predict": settings.num_predict,
              "temperature": settings.temperature, "seed": 42, "system": SYSTEM,
              "citation_format": "structured_json",
              "retrieval_sha256": sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
              "note": "Precomputed search excluded from per-answer times; one sequential run, not statistical ranking."},
              "installed_models": {model: installed[model] for model in args.models},
              "frozen_retrieval": snapshot, "cold_probes": [], "summary": [], "results": []}
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    path.parent.mkdir(exist_ok=True)
    save()
    try:
        for model in args.models:
            for resident in client.resident():
                if resident["name"].split(":")[0] in {"qwen3", "qwen2.5", "embeddinggemma", "nomic-embed-text"}:
                    client.unload(resident["name"])
            if any(r["name"] == model for r in client.resident()):
                raise RuntimeError("콜드 측정 전 모델이 메모리에 남아 있습니다.")
            print(f"[{model}] cold probe (excluded from warm score)", flush=True)
            before = len(client.calls)
            cold = grounded_response(cases[0]["question"], model, SYSTEM, frozen[cases[0]["id"]], client)
            report["cold_probes"].append({"model": model, "elapsed_seconds": cold["elapsed_seconds"],
                    "timings": client.calls[before:], "answer": cold["answer"]})
            report["resident_after_cold"] = client.resident()
            save()
            print(f"  cold {cold['elapsed_seconds']:.3f}s", flush=True)
            for case in cases:
                results = frozen[case["id"]]
                before = len(client.calls)
                response = grounded_response(case["question"], model, SYSTEM, results, client) if results else {
                    "answer": "Wiki에서 관련 근거를 찾지 못했습니다.", "elapsed_seconds": 0,
                    "verification": {"method": "no_evidence", "passed": False}}
                response.setdefault("sources", source_payload(results))
                timings = client.calls[before:]
                row = {"case_id": case["id"], "question": case["question"], "generation_model": model,
                       "execution_path": classify_path(timings, response), "retrieved": [f"{r.source}#{r.heading}" for r in results],
                       "timings": timings, "tokens_per_second": response.get("tokens_per_second"),
                       **response, **score_answer(response, case)}
                report["results"].append(row)
                print(f"  {case['id']}: {row['execution_path']} {row['elapsed_seconds']:.3f}s score {row['answer_score']}", flush=True)
                save()
            report["summary"].append(summarize_rows(report["results"], model))
            client.unload(model)
            save()
    except Exception as exc:
        report["error"] = str(exc)
        save()
        raise
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    print(path, flush=True)
    print(write_review_sheet(path), flush=True)


if __name__ == "__main__":
    main()
