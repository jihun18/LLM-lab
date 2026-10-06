"""Run the two previously pending questions without modifying production code."""
import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from core.config import settings
from core.knowledge_base import KnowledgeBase
from core.ollama_client import OllamaClient
from core.rag_service import rag_response

ROOT = Path(__file__).resolve().parent
CASES = [
    {"id": "range03", "question": "Flask와 Streamlit의 업무와 응답 속도는 어때?",
     "criteria": "두 역할을 답하고 응답속도와 생성속도 구분. 모르는 근거는 명시. 차단은 안전하지만 답변 완료는 아님."},
    {"id": "range04", "question": "Flask와 Streamlit은 어떤 일을 하며 메모리 사용량도 알려줘.",
     "criteria": "두 역할과 대상별 메모리 요구를 답하거나 부족한 근거를 명시. RAM 용량이나 모델 크기를 도구별 메모리 사용량으로 대체하지 않음."},
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3:1.7b")
    args = parser.parse_args()
    kb = KnowledgeBase(ROOT / "wiki")
    kb.reindex()
    files = sorted((ROOT / "core").glob("*.py")) + sorted((ROOT / "wiki").rglob("*.md"))
    protocol = {"model": args.model, "settings": asdict(settings), "search_mode": "bm25", "top_k": 3,
                "fingerprint": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                "criteria_frozen_before_run": CASES,
                "scope": "두 탐색 질문의 실제 생성 확인. 모델 정답률이나 독립 평가가 아님."}
    client = OllamaClient(timeout=90)
    results = []
    for case in CASES:
        print(f"{case['id']}: 서비스 응답 확인 시작 (필요할 때만 모델 생성)", flush=True)
        try:
            response = rag_response(case["question"], args.model,
                                    "Wiki 근거만 사용하고 간결하고 정확한 한국어로 답하세요.", 3, kb, client)
            results.append({**case, "response": response, "semantic_review": "pending_human_review"})
            print(json.dumps({"id": case["id"], "answer": response["answer"],
                              "answer_status": response.get("answer_status"),
                              "execution_path": response.get("execution_path", "llm_generation"),
                              "eval_count": response.get("eval_count"),
                              "verification": response.get("verification"),
                              "elapsed_seconds": response.get("elapsed_seconds")}, ensure_ascii=False), flush=True)
        except Exception as exc:
            results.append({**case, "error": str(exc)})
            print(f"{case['id']}: 실행 오류 {exc}", flush=True)
    output = ROOT / "benchmark-results"
    output.mkdir(exist_ok=True)
    path = output / f"role-phrase-live-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"protocol": protocol, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"결과: {path}", flush=True)

if __name__ == "__main__":
    main()
