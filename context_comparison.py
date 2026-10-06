"""Paired full/primary context experiment using an existing frozen retrieval snapshot."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from statistics import mean

from model_comparison import MeasuredClient, SYSTEM
from core.knowledge_base import SearchResult
from core.config import settings
from core.rag_service import grounded_response
from rag_evaluation import load_cases, score_answer
from answer_review import write_review_sheet

ROOT = Path(__file__).resolve().parent
IDS = ["fresh_mode_table", "fresh_roles", "fresh_badges", "fresh_duplicate"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=["qwen3:1.7b", "qwen2.5:7b-instruct"])
    parser.add_argument("--case-ids", nargs="+", choices=IDS, default=IDS)
    args = parser.parse_args()
    previous = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    frozen = {key: [SearchResult(**r) for r in value] for key, value in previous["frozen_retrieval"].items()}
    cases = {c["id"]: c for c in load_cases(ROOT / "search_independent_cases.json")}
    client = MeasuredClient()
    path = ROOT / "benchmark-results" / ("context-comparison-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    report = {"protocol": {**previous["protocol"], "snapshot": str(args.snapshot),
              "num_ctx": settings.num_ctx, "num_predict": settings.num_predict,
              "temperature": settings.temperature, "system": SYSTEM,
              "case_ids": args.case_ids, "prompt_revision": "role-and-list-contracts-v1",
              "text_extraction": False,
              "citation_format": "structured_json",
              "note": "Paired modes alternate order. Fresh model residency per measured question; model warm-up excluded. No identical prompt warm-up."},
              "warmups": [], "results": [], "summary": []}
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    path.parent.mkdir(exist_ok=True)
    try:
        for model in args.models:
            for index, case_id in enumerate(args.case_ids):
                modes = ["full", "primary"] if index % 2 == 0 else ["primary", "full"]
                for mode in modes:
                    for resident in client.resident():
                        if resident["name"].split(":")[0] in {"qwen3", "qwen2.5", "embeddinggemma", "nomic-embed-text"}:
                            client.unload(resident["name"])
                    # Load the model with an unrelated short prompt; don't prefill test evidence.
                    warm = client.chat("안녕하세요. 한 단어로 인사하세요.", model, SYSTEM)
                    report["warmups"].append({"model": model, "case_id": case_id, "mode": mode,
                                             "elapsed_seconds": warm["elapsed_seconds"]})
                    before = len(client.calls)
                    response = grounded_response(cases[case_id]["question"], model, SYSTEM, frozen[case_id], client, context_mode=mode, allow_text_extraction=False)
                    row = {**response, "case_id": case_id, "question": cases[case_id]["question"],
                           "generation_model": model, "context_mode": mode, "timings": client.calls[before:],
                           "retrieved": [], **score_answer(response, cases[case_id])}
                    row["retrieved"] = [f"{s['source']}#{s['heading']}" for s in response["sources"]]
                    report["results"].append(row)
                    print(f"{model} {case_id} {mode}: {row['elapsed_seconds']:.2f}s score {row['answer_score']}", flush=True)
                    save()
            client.unload(model)
        for model in args.models:
            for mode in ("full", "primary"):
                rows = [r for r in report["results"] if r["generation_model"] == model and r["context_mode"] == mode]
                report["summary"].append({"model": model, "context_mode": mode,
                     "average_seconds": round(mean(r["elapsed_seconds"] for r in rows),3),
                     "average_answer_score": round(mean(r["answer_score"] for r in rows),1),
                     "average_prompt_tokens": round(mean(r["timings"][0]["prompt_eval_count"] for r in rows),1),
                     "average_prefill_seconds": round(mean(r["timings"][0]["prompt_eval_duration"]/1e9 for r in rows),3)})
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
