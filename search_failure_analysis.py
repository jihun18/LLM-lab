"""Diagnose gates separately from ranking without changing evaluation labels."""
import argparse
import json
from pathlib import Path
from core.search import SearchKnowledge
from core.config import settings
from rag_evaluation import load_cases, score_retrieval

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=settings.semantic_threshold)
    args = parser.parse_args()
    knowledge = SearchKnowledge(ROOT / "wiki", model=settings.embedding_model, threshold=args.threshold)
    knowledge.reindex()
    cases = load_cases(ROOT / "rag_evaluation_cases.json") + load_cases(ROOT / "search_evaluation_cases.json")
    rows = []
    for case in cases:
        results = knowledge.search(case["question"], mode="hybrid")
        if score_retrieval(results, case)["top1_correct"]:
            continue
        knowledge.threshold = -1
        raw = knowledge.search(case["question"], top_k=5, mode="semantic")
        lexical = knowledge.search(case["question"], top_k=5, mode="bm25")
        knowledge.threshold = args.threshold
        row = {"id": case["id"], "question": case["question"],
               "expected": f"{case.get('expected_source')}#{case.get('expected_heading')}",
               "failure_type": "gate_rejection" if not results else "ranking_or_label",
               "raw_semantic": [r.to_dict() for r in raw],
               "lexical": [r.to_dict() for r in lexical],
               "hybrid": [r.to_dict() for r in results]}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    path = ROOT / "benchmark-results" / "search-failures.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
