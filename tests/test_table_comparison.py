from pathlib import Path
import pytest
from core.knowledge_base import KnowledgeBase, SearchResult
from core.table_comparison import deterministic_role_comparison
from core.rag_service import grounded_response, rag_response
from model_comparison import classify_path

TABLE = SearchResult("compare.md", "표", "| 항목 | ToolA | ToolB |\n|---|---|---|\n| 역할 | API | 최소 구현 |\n| API 문서 | 자동 | 별도 필요 |", 1)


def test_table_entities_and_role_cells_are_copied_not_invented():
    answer, check = deterministic_role_comparison("ToolA와 ToolB의 역할과 차이는?", [TABLE])
    assert "ToolA: 역할 — API; API 문서 — 자동" in answer
    assert "ToolB: 역할 — 최소 구현; API 문서 — 별도 필요" in answer
    assert "일반적인 성능이나 기능 한계" in answer
    assert check["passed"] is True


@pytest.mark.parametrize("question", [
    "ToolA와 ToolB의 역할과 차이, 속도는?",
    "ToolA와 ToolB의 역할과 차이, 왜 함께 사용해?",
    "ToolA와 ToolB와 ToolC의 역할 차이는?",
    "ToolA와 ToolB의 역할과 차이 및 메모리를 알려줘",
    "ToolA와 ToolB의 역할과 차이와 사용 포트는?",
    "2026년 ToolA와 ToolB의 역할과 차이는?",
    "ToolA와 ToolB의 역할 차이를 예시로 설명해줘",
    "ToolA와 ToolB의 역할을 알려줘",
])
def test_extra_requests_and_unknown_entities_fall_back(question):
    assert deterministic_role_comparison(question, [TABLE]) is None


def test_conflicting_explicit_tables_fall_back():
    changed = SearchResult("other.md", "표", TABLE.text.replace("최소 구현", "다른 역할"), 1)
    assert deterministic_role_comparison("ToolA와 ToolB의 역할과 차이", [TABLE, changed]) is None


def test_incomplete_or_duplicate_rows_fall_back():
    broken = SearchResult("bad.md", "표", TABLE.text.replace("| API |", "| |"), 1)
    assert deterministic_role_comparison("ToolA와 ToolB의 역할 차이", [broken]) is None
    duplicate = SearchResult("dup.md", "표", TABLE.text + "\n| 역할 | 다른 역할 | 또 다른 역할 |", 1)
    assert deterministic_role_comparison("ToolA와 ToolB의 역할 차이", [duplicate]) is None


@pytest.mark.parametrize("question", ["FastAPI와 Flask의 역할과 차이를 설명해줘.",
                                      "Flask와 FastAPI의 용도는 어떻게 다른지 알려줘."])
def test_real_wiki_retrieval_to_response_calls_no_model(question):
    class NoModel:
        def chat(self, *args):
            raise AssertionError("LLM must not be called")
    knowledge = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    knowledge.reindex()
    response = rag_response(question, "qwen3:1.7b", None, 3, knowledge, NoModel())
    assert response["execution_path"] == "deterministic_role_comparison"
    assert "복잡한 기능" not in response["answer"]
    assert response["sources"][0]["heading"] == "구현 비교"
    assert len(response["sources"]) == 1
    assert classify_path([], response) == "deterministic_role_comparison"


def test_explicit_generation_comparison_bypasses_extraction():
    class Client:
        def chat(self, *args):
            return {"answer": "두 도구의 역할을 비교합니다. [출처: 근거 1]", "elapsed_seconds": 1}
    result = grounded_response("ToolA와 ToolB의 역할 차이는?", "test", None, [TABLE], Client(), allow_text_extraction=False)
    assert result.get("model") != "deterministic-comparison"
