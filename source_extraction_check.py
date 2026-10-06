"""Local search-to-answer smoke check; refuses accidental model calls."""
from datetime import datetime
import json
from pathlib import Path
from core.knowledge_base import KnowledgeBase
from core.rag_service import rag_response

ROOT = Path(__file__).resolve().parent
QUESTIONS = [
    "FastAPI, Flask, Streamlit을 이 프로젝트에서는 각각 무슨 용도로 사용하나요?",
    "자동 검증 결과 화면에 나타나는 네 가지 상태 문구를 적어주세요.",
    "검증 화면의 상태 문구 4가지를 그대로 적어줘",
]


class NoGeneration:
    def chat(self, *args, **kwargs):
        raise RuntimeError("질문이 원문 추출 범위를 벗어났습니다. 모델 호출은 하지 않았습니다.")


def main():
    knowledge = KnowledgeBase(ROOT / "wiki")
    knowledge.reindex()
    rows = []
    for question in QUESTIONS:
        response = rag_response(question, "qwen3:1.7b", None, 3, knowledge, NoGeneration())
        rows.append({"question": question, **response})
        print(question, response["elapsed_seconds"], response["execution_path"], flush=True)
        print(response["answer"], flush=True)
    path = ROOT / "benchmark-results" / ("source-extraction-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"protocol": {"search_mode": "bm25", "llm_calls": 0,
                    "note": "Source copying, not model generation speed or general factual accuracy."},
                    "results": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
