from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from core.knowledge_base import KnowledgeBase, SearchResult
from core.ollama_client import OllamaClient
from core.rag_service import rag_response


ROOT = Path(__file__).resolve().parent
DEFAULT_MODELS = ["qwen3:1.7b"]
SYSTEM_PROMPT = "Wiki 근거만 사용하고 간결하고 정확한 한국어로 답하세요."


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def select_cases(
    cases: list[dict[str, Any]], case_ids: list[str] | None, max_cases: int | None
) -> list[dict[str, Any]]:
    selected = cases
    if case_ids:
        requested = set(case_ids)
        selected = [case for case in cases if case["id"] in requested]
        missing = requested - {case["id"] for case in selected}
        if missing:
            raise ValueError(f"존재하지 않는 평가 문항: {', '.join(sorted(missing))}")
    if max_cases is not None:
        selected = selected[: max(max_cases, 0)]
    return selected


def _normalized(text: str) -> str:
    return re.sub(r"[\s,]", "", text).lower()


def _expected_sources(case: dict[str, Any]) -> list[tuple[str, str]]:
    expected = [
        (
            str(case.get("expected_source", "")).lower(),
            str(case.get("expected_heading", "")).lower(),
        )
    ]
    expected.extend(
        (str(item["source"]).lower(), str(item["heading"]).lower())
        for item in case.get("acceptable_sources", [])
    )
    return [item for item in expected if item[0] and item[1]]


def _matches_expected(result: SearchResult, case: dict[str, Any]) -> bool:
    actual = (result.source.lower(), result.heading.lower())
    return actual in _expected_sources(case)


def score_retrieval(results: list[SearchResult], case: dict[str, Any]) -> dict[str, Any]:
    if case.get("expect_no_evidence"):
        passed = not results
        return {
            "top1_correct": passed,
            "source_hit": passed,
            "retrieval_score": 100.0 if passed else 0.0,
        }

    top1 = bool(results and _matches_expected(results[0], case))
    source_hit = any(_matches_expected(result, case) for result in results)
    return {
        "top1_correct": top1,
        "source_hit": source_hit,
        "retrieval_score": round((int(top1) + int(source_hit)) / 2 * 100, 1),
    }


def score_answer(response: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    answer = str(response.get("answer", ""))
    if case.get("expect_no_evidence"):
        method = (response.get("verification") or {}).get("method")
        abstained = method in {"no_evidence", "model_abstained"}
        return {
            "keyword_coverage": None,
            "value_coverage": None,
            "citation_correct": not response.get("sources"),
            "abstention_correct": abstained,
            "latency_passed": response.get("elapsed_seconds", 0)
            <= case.get("max_seconds", float("inf")),
            "answer_score": 100.0 if abstained else 0.0,
        }

    normalized_answer = _normalized(answer)
    keywords = case.get("expected_keywords", [])
    values = case.get("expected_values", [])
    keyword_matches = [item for item in keywords if _normalized(item) in normalized_answer]
    value_matches = [item for item in values if _normalized(item) in normalized_answer]
    keyword_coverage = len(keyword_matches) / len(keywords) if keywords else 1.0
    value_coverage = len(value_matches) / len(values) if values else 1.0
    expected_sources = {source for source, _ in _expected_sources(case)}
    returned_sources = {
        source.get("source", "").lower() for source in response.get("sources", [])
    }
    matched_sources = expected_sources & returned_sources
    citation_correct = bool(matched_sources) and any(
        source in answer.lower() for source in matched_sources
    )
    verification_ok = (response.get("verification") or {}).get("passed") is not False
    checks = [keyword_coverage, value_coverage, float(citation_correct), float(verification_ok)]
    return {
        "keyword_coverage": round(keyword_coverage, 3),
        "value_coverage": round(value_coverage, 3),
        "citation_correct": citation_correct,
        "abstention_correct": None,
        "latency_passed": response.get("elapsed_seconds", 0)
        <= case.get("max_seconds", float("inf")),
        "answer_score": round(mean(checks) * 100, 1),
    }


def retrieval_result(
    knowledge: KnowledgeBase, case: dict[str, Any], top_k: int
) -> dict[str, Any]:
    results = knowledge.search(case["question"], top_k)
    return {
        "case_id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "expected_source": case.get("expected_source"),
        "expected_heading": case.get("expected_heading"),
        "retrieved": [f"{item.source}#{item.heading}" for item in results],
        **score_retrieval(results, case),
    }


def full_result(
    knowledge: KnowledgeBase,
    client: OllamaClient,
    model: str,
    case: dict[str, Any],
    top_k: int,
) -> dict[str, Any]:
    retrieval = retrieval_result(knowledge, case, top_k)
    response = rag_response(
        case["question"], model, SYSTEM_PROMPT, top_k, knowledge, client
    )
    return {
        **retrieval,
        "model": model,
        "answer": response["answer"],
        "elapsed_seconds": response["elapsed_seconds"],
        "tokens_per_second": response["tokens_per_second"],
        "verification_method": (response.get("verification") or {}).get("method"),
        **score_answer(response, case),
    }


def summarize(results: list[dict[str, Any]], retrieval_only: bool) -> list[dict[str, Any]]:
    group_key = "retrieval" if retrieval_only else None
    groups = [group_key] if retrieval_only else list(
        dict.fromkeys(item["model"] for item in results)
    )
    summaries = []
    for group in groups:
        rows = results if retrieval_only else [item for item in results if item["model"] == group]
        summary = {
            "model": group,
            "cases": len(rows),
            "top1_accuracy": round(mean(int(row["top1_correct"]) for row in rows) * 100, 1),
            "source_hit_rate": round(mean(int(row["source_hit"]) for row in rows) * 100, 1),
        }
        if not retrieval_only:
            summary.update(
                {
                    "average_answer_score": round(mean(row["answer_score"] for row in rows), 1),
                    "average_seconds": round(mean(row["elapsed_seconds"] for row in rows), 3),
                    "latency_pass_rate": round(mean(int(row["latency_passed"]) for row in rows) * 100, 1),
                }
            )
        summaries.append(summary)
    return summaries


def write_reports(
    output_dir: Path,
    stamp: str,
    results: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    retrieval_only: bool,
) -> list[Path]:
    output_dir.mkdir(exist_ok=True)
    prefix = "rag-retrieval" if retrieval_only else "rag-evaluation"
    json_path = output_dir / f"{prefix}-{stamp}.json"
    csv_path = output_dir / f"{prefix}-{stamp}.csv"
    md_path = output_dir / f"{prefix}-{stamp}.md"
    json_path.write_text(
        json.dumps({"summary": summaries, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    fieldnames = sorted({key for row in results for key in row})
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    lines = ["# PrivAI RAG 평가 보고서", "", "## 요약", ""]
    for row in summaries:
        lines.append(
            f"- {row['model']}: Top-1 {row['top1_accuracy']}%, "
            f"출처 적중 {row['source_hit_rate']}%"
        )
        if not retrieval_only:
            lines.append(
                f"  - 답변 점수 {row['average_answer_score']}, 평균 {row['average_seconds']}초, "
                f"시간 기준 통과 {row['latency_pass_rate']}%"
            )
    lines.extend(["", "## 문항별 결과", ""])
    for row in results:
        lines.extend(
            [
                f"### {row['case_id']} · {row['category']}",
                "",
                f"- 질문: {row['question']}",
                f"- 검색 결과: {', '.join(row['retrieved']) or '없음'}",
                f"- Top-1: {'통과' if row['top1_correct'] else '실패'}",
            ]
        )
        if not retrieval_only:
            lines.extend(
                [
                    f"- 답변 점수: {row['answer_score']}",
                    f"- 시간: {row['elapsed_seconds']}초",
                    "",
                    row["answer"],
                ]
            )
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8-sig")
    return [json_path, csv_path, md_path]


def main() -> None:
    parser = argparse.ArgumentParser(description="PrivAI Wiki RAG 자동 평가")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--cases", default=str(ROOT / "rag_evaluation_cases.json"))
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--case-ids", nargs="+", default=None)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--retrieval-only", action="store_true")
    args = parser.parse_args()

    try:
        cases = select_cases(
            load_cases(Path(args.cases)), args.case_ids, args.max_cases
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not cases:
        raise SystemExit("실행할 RAG 평가 문항이 없습니다.")

    knowledge = KnowledgeBase(ROOT / "wiki")
    knowledge.reindex()
    results: list[dict[str, Any]] = []
    if args.retrieval_only:
        print(f"RAG 검색 평가 시작 ({len(cases)}문항)")
        for index, case in enumerate(cases, start=1):
            result = retrieval_result(knowledge, case, args.top_k)
            results.append(result)
            print(
                f"  {index}/{len(cases)} {case['id']}: "
                f"Top-1 {'통과' if result['top1_correct'] else '실패'}"
            )
    else:
        client = OllamaClient()
        for model in args.models:
            print(f"\n[{model}] RAG 평가 시작 ({len(cases)}문항)")
            for index, case in enumerate(cases, start=1):
                result = full_result(knowledge, client, model, case, args.top_k)
                results.append(result)
                print(
                    f"  {index}/{len(cases)} {case['id']}: "
                    f"검색 {result['retrieval_score']:.1f}, 답변 {result['answer_score']:.1f}, "
                    f"{result['elapsed_seconds']:.2f}s"
                )

    summaries = summarize(results, args.retrieval_only)
    paths = write_reports(
        ROOT / "benchmark-results",
        datetime.now().strftime("%Y%m%d-%H%M%S"),
        results,
        summaries,
        args.retrieval_only,
    )
    print("\n평가 요약")
    for row in summaries:
        print(
            f"  {row['model']}: Top-1 {row['top1_accuracy']}%, "
            f"출처 적중 {row['source_hit_rate']}%"
        )
    for path in paths:
        print(f"결과 저장: {path}")


if __name__ == "__main__":
    main()
