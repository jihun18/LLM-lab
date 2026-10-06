"""Compare retrieval modes on unchanged baseline plus new challenge cases."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from statistics import mean
import time

import psutil

from core.search import SearchKnowledge, SEARCH_MODES
from core.config import settings, EMBEDDING_THRESHOLDS
from core.rag_service import grounded_response, source_payload
from rag_evaluation import load_cases, score_retrieval, score_answer, write_reports

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="+", choices=SEARCH_MODES, default=list(SEARCH_MODES))
    parser.add_argument("--answers", action="store_true", help="Also generate and score answers")
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--embedding-model", default=settings.embedding_model)
    parser.add_argument("--case-ids", nargs="+")
    args = parser.parse_args()
    if args.threshold is None:
        args.threshold = (settings.semantic_threshold if args.embedding_model == settings.embedding_model
                          else EMBEDDING_THRESHOLDS.get(args.embedding_model.split(":")[0], 0.65))
    cases = load_cases(ROOT / "rag_evaluation_cases.json") + load_cases(ROOT / "search_evaluation_cases.json")
    if args.case_ids:
        unknown = set(args.case_ids) - {c["id"] for c in cases}
        if unknown:
            parser.error(f"Unknown cases: {sorted(unknown)}")
        cases = [c for c in cases if c["id"] in args.case_ids]
    knowledge = SearchKnowledge(ROOT / "wiki", model=args.embedding_model, threshold=args.threshold)
    knowledge.reindex()
    rows, summaries = [], []
    for mode in args.modes:
        mode_rows = []
        # Index preparation is recorded separately from warm query latency.
        started = time.perf_counter()
        if mode != "bm25":
            knowledge.search("색인 준비", mode=mode)
        preparation = time.perf_counter() - started
        for case in cases:
            started = time.perf_counter()
            results = knowledge.search(case["question"], mode=mode)
            elapsed = time.perf_counter() - started
            row = {"case_id": case["id"], "category": case["category"],
                   "question": case["question"], "model": mode,
                   "retrieved": [f"{r.source}#{r.heading}" for r in results],
                   "retrieved_scores": [r.score for r in results],
                   "search_seconds": round(elapsed, 4),
                   "python_rss_mb": round(psutil.Process().memory_info().rss / 1024**2, 2),
                   **score_retrieval(results, case)}
            if args.answers:
                response = grounded_response(case["question"], args.model,
                    "Wiki 근거만 사용하고 간결하게 답하세요.", results, knowledge.embedding_client) if results else {
                    "answer": "Wiki에서 관련 근거를 찾지 못했습니다.", "elapsed_seconds": 0,
                    "verification": {"method": "no_evidence", "passed": False}}
                response["sources"] = source_payload(results)
                response["elapsed_seconds"] += elapsed
                row.update(answer=response["answer"], elapsed_seconds=response["elapsed_seconds"],
                           **score_answer(response, case))
            print(f"{mode} {case['id']}: Top-1 {row['top1_correct']}, {elapsed:.3f}s", flush=True)
            mode_rows.append(row)
        evidence = [r for r in mode_rows if not next(c for c in cases if c['id']==r['case_id']).get('expect_no_evidence')]
        absent = [r for r in mode_rows if r not in evidence]
        summary = {"model": mode, "cases": len(mode_rows), "threshold": args.threshold,
                   "embedding_model": args.embedding_model,
                   "index_preparation_seconds": round(preparation, 3),
                   "top1_accuracy": round(mean(r['top1_correct'] for r in mode_rows)*100,1),
                   "source_hit_rate": round(mean(r['source_hit'] for r in mode_rows)*100,1),
                   "average_search_seconds": round(mean(r['search_seconds'] for r in mode_rows),4),
                   "evidence_top1_accuracy": round(mean(r['top1_correct'] for r in evidence)*100,1) if evidence else None,
                   "no_evidence_success_rate": round(mean(r['top1_correct'] for r in absent)*100,1) if absent else None,
                   "python_peak_sampled_rss_mb": max(r['python_rss_mb'] for r in mode_rows)}
        if args.answers:
            summary.update(average_answer_score=round(mean(r['answer_score'] for r in mode_rows),1),
                           average_seconds=round(mean(r['elapsed_seconds'] for r in mode_rows),3),
                           latency_pass_rate=round(mean(r['latency_passed'] for r in mode_rows)*100,1))
        summaries.append(summary)
        rows.extend(mode_rows)
    paths = write_reports(ROOT / "benchmark-results", "search-" + datetime.now().strftime("%Y%m%d-%H%M%S"), rows, summaries, not args.answers)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
