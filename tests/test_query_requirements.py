import pytest
from pathlib import Path
from core.knowledge_base import KnowledgeBase
from core.knowledge_base import SearchResult
from core.query_requirements import role_requirements
from core.rag_service import grounded_response, rag_stream_events
from core.grounding import deterministic_metric_answer

TABLE = SearchResult("tools.md", "비교", "| 항목 | ToolA | ToolB |\n|---|---|---|\n| 역할 | API | UI |", 1)
SPEED = "\n| 프레임워크 | 생성속도 |\n|---|---|\n| ToolA | 5 token/s |\n| ToolB | 6 token/s |"
REASON = "\nToolA와 ToolB는 API와 UI를 분담하기 때문에 함께 사용한다."

class NoModel:
    def chat(self, *args):
        raise AssertionError("must abstain before generation")

class Client:
    def __init__(self, answer):
        self.answer = answer
    def chat(self, *args):
        return {"answer": self.answer + " [출처: 근거 1]", "elapsed_seconds": 1,
                "tokens_per_second": 5, "eval_count": 20}

@pytest.mark.parametrize("question,missing", [
    ("ToolA와 ToolB의 역할과 차이, Django 역할도 알려줘", "Django의 역할"),
    ("ToolA와 ToolB의 역할과 처리 속도", "ToolA의 표 기반 생성속도"),
    ("ToolA와 ToolB의 역할과 왜 함께 쓰는지", "요청한 도구를 함께 사용하는 이유"),
])
def test_missing_requirement_abstains_before_llm(question, missing):
    response = grounded_response(question, "test", None, [TABLE], NoModel())
    assert missing in response["answer"]
    assert response["eval_count"] == 0
    assert response["verification"]["passed"] is False

def test_mention_without_role_is_not_role_evidence():
    result = SearchResult("tools.md", "표", TABLE.text + "\nDjango라는 이름이 언급됨", 1)
    assert "Django의 역할" in role_requirements("ToolA, ToolB, Django의 역할", [result])["missing"]

def test_compound_metric_does_not_silently_extract_only_speed():
    result = SearchResult("tools.md", "표", TABLE.text + SPEED, 1)
    assert deterministic_metric_answer("ToolA와 ToolB의 역할과 속도", [result]) is None

def test_all_requirements_supported_still_use_generation():
    result = SearchResult("tools.md", "표", TABLE.text + REASON, 1)
    response = grounded_response("ToolA와 ToolB의 역할과 왜 함께 쓰는지", "test", None,
                                 [result], Client("ToolA는 API, ToolB는 UI이며 역할 분담을 위해 함께 쓴다."))
    assert response["answer_status"] == "review_required"
    assert "분담" in response["answer"]

def test_missing_reason_in_answer_is_blocked():
    result = SearchResult("tools.md", "표", TABLE.text + REASON, 1)
    response = grounded_response("ToolA와 ToolB의 역할과 왜 함께 쓰는지", "test", None,
                                 [result], Client("ToolA는 API, ToolB는 UI입니다."))
    assert response["answer_status"] == "blocked"
    assert "ToolA는 API" not in response["answer"]

def test_failed_numeric_body_is_not_exposed_in_json_or_stream():
    class Knowledge:
        def search(self, *args):
            return [TABLE]
    response = grounded_response("정책 알려줘", "test", None, [TABLE], Client("지원금은 999만원입니다."))
    assert response["answer_status"] == "blocked"
    assert "999만원" not in response["answer"]
    events = list(rag_stream_events("정책 알려줘", "test", None, 3, Knowledge(), Client("지원금은 999만원입니다.")))
    assert all("999만원" not in event.get("content", "") for event in events)
    assert events[-1]["verification"]["passed"] is False

def test_selected_source_must_cover_entities_not_just_retrieved_set():
    irrelevant = SearchResult("other.md", "메모", "일반 메모", 1)
    response = grounded_response("ToolA와 ToolB의 역할을 예시로 설명해줘", "test", None,
                                 [irrelevant, TABLE], Client("ToolA는 API, ToolB는 UI입니다."))
    assert response["answer_status"] == "blocked"
    assert response["verification"]["method"] == "selected_source_requirements_missing"

@pytest.mark.parametrize("question,missing", [
    ("FastAPI와 Flask의 역할과 차이, 처리 속도도 알려줘.", "표 기반 생성속도"),
    ("FastAPI와 Flask의 역할과 차이, Django의 역할도 알려줘.", "Django의 역할"),
    ("FastAPI와 Streamlit의 역할을 알려주고, 왜 둘을 함께 사용하는지도 설명해줘.", "함께 사용하는 이유"),
])
def test_user_boundary_questions_with_real_bm25_evidence(question, missing):
    knowledge = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    knowledge.reindex()
    response = grounded_response(question, "test", None, knowledge.search(question, 3), NoModel())
    assert missing in response["answer"]
    assert response["execution_path"] == "requirements_abstention"
