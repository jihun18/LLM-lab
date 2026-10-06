"""Select a cosine gate using separate answerability calibration questions only."""
import argparse
import json
from pathlib import Path
from core.search import SearchKnowledge

ROOT = Path(__file__).resolve().parent


def choose_threshold(rows):
    if not rows or {r["has_evidence"] for r in rows} != {True, False}:
        raise ValueError("교정에는 근거 있는 질문과 없는 질문이 모두 필요합니다.")
    scores = sorted(set(r["score"] for r in rows))
    candidates = [scores[0], *[(a+b)/2 for a, b in zip(scores, scores[1:])], scores[-1]+1e-6]
    def metrics(t):
        positive = [r for r in rows if r["has_evidence"]]
        negative = [r for r in rows if not r["has_evidence"]]
        recall = sum(r["score"] >= t for r in positive)/len(positive)
        refusal = sum(r["score"] < t for r in negative)/len(negative)
        return (recall+refusal)/2, refusal, recall
    threshold = max(candidates, key=lambda t: (*metrics(t), t))
    balanced, refusal, recall = metrics(threshold)
    return {"threshold": threshold, "balanced_accuracy": balanced,
            "evidence_recall": recall, "no_evidence_refusal": refusal}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-model", required=True)
    args = parser.parse_args()
    cases = json.loads((ROOT / "search_calibration_cases.json").read_text(encoding="utf-8"))
    knowledge = SearchKnowledge(ROOT / "wiki", model=args.embedding_model, threshold=-1)
    knowledge.reindex()
    rows = []
    for case in cases:
        results = knowledge.search(case["question"], mode="semantic")
        rows.append({**case, "score": results[0].score if results else -1})
        print(rows[-1], flush=True)
    report = {"embedding_model": args.embedding_model, **choose_threshold(rows), "rows": rows}
    path = ROOT / "benchmark-results" / ("calibration-" + args.embedding_model.replace(":", "-") + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
