"""Actual generation check for source IDs; retain raw answer in ignored report."""
from datetime import datetime
import json
from pathlib import Path
from core.knowledge_base import KnowledgeBase
from core.rag_service import rag_response
from model_comparison import MeasuredClient, SYSTEM

ROOT = Path(__file__).resolve().parent


class RecordingClient(MeasuredClient):
    def chat(self, *args, **kwargs):
        response = super().chat(*args, **kwargs)
        self.raw_answer = response["answer"]
        return response


def main():
    knowledge = KnowledgeBase(ROOT / "wiki")
    knowledge.reindex()
    client = RecordingClient()
    path = ROOT / "benchmark-results" / ("citation-selection-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    report = {"note": "Two development questions, not independent accuracy measurement. Raw model answer and canonical display answer separated.", "results": []}
    path.parent.mkdir(exist_ok=True)
    for question in ("FastAPI와 Flask의 역할과 차이를 설명해줘.",
                     "FastAPI와 Streamlit의 역할을 알려주고, 왜 둘을 함께 사용하는지도 설명해줘."):
        response = rag_response(question, "qwen3:1.7b", SYSTEM, 3, knowledge, client)
        report["results"].append({"question": question, "raw_model_answer": client.raw_answer, **response})
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report["results"][-1], ensure_ascii=False, indent=2), flush=True)
    print(path, flush=True)


if __name__ == "__main__":
    main()
