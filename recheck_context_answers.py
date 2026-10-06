"""Offline detection audit; does not regenerate answers or measure new latency."""
import argparse
import json
from pathlib import Path
from core.context_budget import select_context
from core.grounding import verify_grounded_answer
from core.knowledge_base import SearchResult


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    rows = []
    for row in report["results"]:
        evidence = [SearchResult(**r) for r in snapshot["frozen_retrieval"][row["case_id"]]]
        evidence = select_context(row["question"], evidence, row["context_mode"])
        check = verify_grounded_answer(row["question"], row["answer"], evidence)
        rows.append({"model": row["generation_model"], "case_id": row["case_id"],
                     "mode": row["context_mode"], "original_score": row["answer_score"],
                     "verification": check})
        print(row["generation_model"], row["case_id"], row["context_mode"], check["passed"], check["issues"])
    output = args.report.with_name(args.report.stem + "-rechecked.json")
    output.write_text(json.dumps({"note": "Offline detection only. Original answers and timings unchanged; not a new generation experiment.", "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
