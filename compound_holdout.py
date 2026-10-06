"""Separate first-run checks. Does not tune production code or change Wiki."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from core.knowledge_base import KnowledgeBase, SearchResult
from core.ollama_client import OllamaClient
from core.rag_service import rag_response, SOURCE_CITATION_PATTERN

ROOT = Path(__file__).resolve().parent

class GenerationNeeded(RuntimeError):
    pass

class OfflineClient:
    def chat(self, *args):
        raise GenerationNeeded("실제 모델 생성이 필요해 오프라인 평가에서 보류")

class FixtureKnowledge:
    def __init__(self, results):
        self.results = results
    def search(self, query, top_k, **kwargs):
        # Controlled evidence, not a retrieval-accuracy benchmark. All explicit
        # conflicting candidates are supplied so the response policy is tested.
        return self.results

def score(case, response):
    body = response["answer"]
    returned = {f"{r['source']}#{r['heading']}" for r in response.get("sources", [])}
    cited = {f"{source.strip()}#{heading.strip()}" for source, heading in SOURCE_CITATION_PATTERN.findall(body)}
    checks = {"required_text": all(text in body for text in case.get("required", [])),
              "forbidden_text_absent": not any(text in body for text in case.get("forbidden", [])),
              "expected_sources": set(case.get("sources", [])) <= returned,
              "citations_match_displayed_sources": cited == returned,
              "expected_status": not case.get("expected_status") or response.get("answer_status") == case["expected_status"],
              "expected_method": not case.get("expected_method") or response.get("verification", {}).get("method") == case["expected_method"],
              "no_sources": not case.get("no_sources") or not returned}
    return {"checks": checks, "status": "pass" if all(checks.values()) else "fail",
            "semantic_review_required": bool(case.get("semantic_review_required"))}

def fingerprint(paths):
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="필요한 경우에만 실제 Ollama 생성")
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--case-ids", nargs="+")
    args = parser.parse_args()
    case_path = ROOT / "compound_holdout_cases.json"
    package = json.loads(case_path.read_text(encoding="utf-8"))
    cases = package["cases"]
    if args.case_ids:
        unknown = set(args.case_ids) - {case["id"] for case in cases}
        if unknown:
            parser.error("알 수 없는 문항: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in args.case_ids]
    knowledge = KnowledgeBase(ROOT / "wiki")
    knowledge.reindex()
    protocol = {"case_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
                "production_sha256": fingerprint(sorted((ROOT / "core").glob("*.py"))),
                "wiki_sha256": fingerprint(sorted((ROOT / "wiki").rglob("*.md"))),
                "mode": "live_if_needed" if args.live else "offline", "requested_model": args.model,
                "search_mode": "bm25", "top_k": 3,
                "warning": "자동 항목 검사는 의미 정확도 점수가 아니다. fixture는 통제 근거 정책 평가로 검색 정확도와 분리한다."}
    client = OllamaClient(timeout=90) if args.live else OfflineClient()
    rows = []
    for case in cases:
        kb = knowledge if case["scope"] == "wiki" else FixtureKnowledge([
            SearchResult(item["source"], item["heading"], item["text"], 1)
            for fixture in case["fixtures"] for item in package["fixtures"][fixture]])
        try:
            response = rag_response(case["question"], args.model, "Wiki 근거만 사용해 한국어로 답하세요.", 3, kb, client)
            row = {"id": case["id"], "scope": case["scope"], "question": case["question"],
                   **score(case, response), "response": response}
        except GenerationNeeded as exc:
            row = {"id": case["id"], "scope": case["scope"], "status": "pending_generation", "reason": str(exc)}
        except Exception as exc:
            row = {"id": case["id"], "scope": case["scope"], "status": "error", "reason": str(exc)}
        rows.append(row)
        print(f"{case['id']} ({case['scope']}): {row['status']}", flush=True)
    summary = {scope: {status: sum(row["scope"] == scope and row["status"] == status for row in rows)
                       for status in ("pass", "fail", "pending_generation", "error")}
               for scope in ("wiki", "fixture")}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = ROOT / "benchmark-results"
    output.mkdir(exist_ok=True)
    report = output / f"compound-holdout-{stamp}.json"
    report.write_text(json.dumps({"protocol": protocol, "summary": summary, "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(f"결과: {report}", flush=True)

if __name__ == "__main__":
    main()
