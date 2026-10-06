from pathlib import Path
import pytest
from core.knowledge_base import KnowledgeBase, SearchResult
from core.query_requirements import asks_project_role, role_requirements
from core.rag_service import rag_response
from core.requirement_retrieval import requirement_source_answer

@pytest.mark.parametrize("question", ["무엇을 담당하며", "담당하는 일", "어떤 일을", "역할", "용도"])
def test_bounded_role_paraphrases(question):
    assert asks_project_role(question)

@pytest.mark.parametrize("question", ["담당자 연락처", "무엇을 설치해", "어떤 모델 속도", "응답속도만 알려줘"])
def test_unrelated_words_are_not_role_requests(question):
    assert not asks_project_role(question)

def test_failed_holdout_becomes_partial_regression_not_general_speed_claim():
    class NoModel:
        def chat(self, *args):
            raise AssertionError("source-copy must not generate")
    knowledge = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    knowledge.reindex()
    response = rag_response("Flask와 Streamlit은 무엇을 담당하며 응답 속도는 어때?", "test", None, 3, knowledge, NoModel())
    assert response["execution_path"] == "deterministic_requirement_copy"
    assert response["answer_status"] == "partial"
    assert response["verification"]["passed"] is None
    assert "12.61 token/s" in response["answer"] and "11.24 token/s" in response["answer"]
    assert "참고할 생성속도 기록만" in response["answer"]
    assert "동일 조건 비교 근거" in response["answer"]
    assert response["retrieval_followups"]

def test_paraphrase_does_not_silently_drop_memory_request():
    source = SearchResult("roles.md", "표", "| 항목 | AppA | AppB |\n|---|---|---|\n| 역할 | API | UI |", 1)
    assert role_requirements("AppA와 AppB는 무엇을 담당하며 응답 속도는 어때?", [source])
    answer, _, check = requirement_source_answer("AppA와 AppB는 무엇을 담당하며 메모리도 알려줘", [source])
    assert "AppA의 대상별 메모리 사용량 (검색 근거 부족)" in answer
    assert check["passed"] is None
