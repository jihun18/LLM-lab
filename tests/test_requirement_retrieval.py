from pathlib import Path
import pytest
from core.knowledge_base import KnowledgeBase, SearchResult
from core.requirement_retrieval import supplement_role_evidence, requirement_source_answer
from core.rag_service import rag_response, rag_stream_events

ROLE = SearchResult("roles.md", "比較", "| 항목 | ToolA | ToolB |\n|---|---|---|\n| 역할 | API | UI |", 1)
SPEED = SearchResult("speed.md", "실측", "| 프레임워크 | 모델 | 생성속도 |\n|---|---|---|\n| ToolA | small:1b | 5 token/s |\n| ToolB | small:1b | 6 token/s |", 1)

class NoModel:
    def chat(self, *args):
        raise AssertionError("source-copy must not call a model")

def test_targeted_followup_recovers_speed_and_preserves_mode():
    class Knowledge:
        def __init__(self):
            self.calls = []
        def search(self, query, count, **kwargs):
            self.calls.append((query, count, kwargs))
            return [SPEED, ROLE]
    knowledge = Knowledge()
    combined, trace = supplement_role_evidence("ToolA와 ToolB의 역할과 처리 속도도 알려줘.", [ROLE], knowledge, "hybrid")
    assert len(combined) == 2
    assert len(trace) == 2
    assert all(call[2] == {"mode": "hybrid"} for call in knowledge.calls)
    answer, used, check = requirement_source_answer("ToolA와 ToolB의 역할과 속도", combined)
    assert "small:1b" in answer and "5 token/s" in answer and "6 token/s" in answer
    assert "당시 모델 생성 실측" in answer
    assert len(used) == 2 and not check["missing_items"]

def test_unknown_target_is_explicit_partial_not_silently_dropped():
    answer, _, check = requirement_source_answer("ToolA와 ToolB의 역할과 차이, Django의 역할도 알려줘.", [ROLE])
    assert "ToolA의 역할: API" in answer
    assert "Django의 역할 (검색 근거 부족)" in answer
    assert "질문 전체가 해결된 것은 아닙니다" in answer
    assert check["passed"] is None

def test_reason_is_never_inferred_from_roles():
    answer, _, check = requirement_source_answer("ToolA와 ToolB의 역할을 알려주고, 왜 둘을 함께 사용하는지도 설명해줘.", [ROLE])
    assert "이유의 원문 (검색 근거 부족)" in answer
    assert check["missing_items"]

def test_conflicting_speed_rows_not_arbitrarily_selected():
    conflicting = SearchResult("other.md", "실측", SPEED.text.replace("5 token/s", "9 token/s"), 1)
    answer, _, check = requirement_source_answer("ToolA와 ToolB의 역할과 속도", [ROLE, SPEED, conflicting])
    assert "5 token/s" not in answer and "9 token/s" not in answer
    assert "ToolA의 기록된 생성속도 행 (원문 값 충돌)" in check["missing_items"]

@pytest.mark.parametrize("extra", ["CPU사용률도", "포트도", "예시도", "2026년", "token/s도"])
def test_unhandled_requirements_cannot_be_omitted(extra):
    question = f"ToolA와 ToolB의 역할과 속도 {extra} 알려줘"
    assert requirement_source_answer(question, [ROLE, SPEED]) is None

@pytest.mark.parametrize("question,expected", [
    ("FastAPI와 Flask의 역할과 차이, 처리 속도도 알려줘.", "11.75 token/s"),
    ("FastAPI와 Flask의 역할과 차이, Django의 역할도 알려줘.", "Django의 역할 (검색 근거 부족)"),
    ("FastAPI와 Streamlit의 역할을 알려주고, 왜 둘을 함께 사용하는지도 설명해줘.", "이유의 원문 (검색 근거 부족)"),
])
def test_real_wiki_recovers_or_explicitly_marks_partial(question, expected):
    knowledge = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    knowledge.reindex()
    response = rag_response(question, "qwen3:4b-instruct", None, 3, knowledge, NoModel())
    assert response["execution_path"] == "deterministic_requirement_copy"
    assert expected in response["answer"]
    assert len(response["retrieval_followups"]) <= 4
    assert response["eval_count"] == 0
    assert response["sources"]

def test_partial_response_is_preserved_in_stream():
    class Knowledge:
        def search(self, *args, **kwargs):
            return [ROLE]
    events = list(rag_stream_events("ToolA와 ToolB의 역할, Django의 역할도 알려줘", "test", None, 3, Knowledge(), NoModel()))
    assert "Django" in events[1]["content"]
    assert events[-1]["verification"]["missing_items"]
