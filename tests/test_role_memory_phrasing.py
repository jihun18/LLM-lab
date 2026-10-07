import pytest
from core.knowledge_base import SearchResult
from core.query_requirements import role_requirements
from core.requirement_retrieval import bounded_question
from core.role_lists import plain_role_pairs
from core.rag_service import rag_response, rag_stream_events
from compound_holdout import FixtureKnowledge

ROLES = SearchResult("roles.md", "역할", "- DataApi: 문서 API\n- ViewUi: 실험 화면", 1)

class NoModel:
    def chat(self, *args):
        raise AssertionError("supported role and memory requests must copy sources")

@pytest.mark.parametrize("question", [
    "DataApi와 ViewUi의 업무와 RSS 사용량을 각각 알려주세요.",
    "DataApi의 용도와 RAM 사용량을 원문 근거로 알려줘.",
    "DataApi와 ViewUi의 역할 및 메모리 사용량을 알려줘.",
    "DataApi와 ViewUi가 맡는 일과 메모리 사용량을 설명해줘.",
    "DataApi와 ViewUi가 맡는 작업 및 ram 사용량을 설명해주세요.",
    "DataApi와 ViewUi의 역할과 rSs 사용량을 확인해줘.",
])
def test_supported_phrasing_preserves_known_roles_and_missing_memory(question):
    response = rag_response(question, "test", None, 3, FixtureKnowledge([ROLES]), NoModel())
    assert response["answer_status"] == "partial"
    assert response["execution_path"] == "deterministic_requirement_copy"
    assert response["eval_count"] == 0
    assert "DataApi의 역할: 문서 API" in response["answer"]
    assert "DataApi의 대상별 메모리 사용량 (검색 근거 부족)" in response["answer"]
    assert response["verification"]["passed"] is None

def test_unknown_role_is_explicit_not_generated():
    response = rag_response("ViewUi와 Quart의 역할 및 메모리 사용량을 각각 확인해줘.", "test", None, 3, FixtureKnowledge([ROLES]), NoModel())
    assert "ViewUi의 역할: 실험 화면" in response["answer"]
    assert "Quart의 역할 (검색 근거 부족)" in response["answer"]
    assert "Quart의 대상별 메모리 사용량 (검색 근거 부족)" in response["answer"]

def test_measured_zero_is_copied_without_losing_roles_or_units():
    measured = SearchResult("memory.md", "측정", "| 대상명 | RSS |\n|---|---|\n| DataApi | 0 KB |\n| ViewUi | 64 KB |", 1)
    response = rag_response("DataApi와 ViewUi의 역할 및 메모리 사용량을 알려줘.", "test", None, 3, FixtureKnowledge([ROLES, measured]), NoModel())
    assert response["answer_status"] == "source_copied"
    assert "DataApi의 역할: 문서 API" in response["answer"]
    assert "RSS — 0 KB" in response["answer"]
    assert "RSS — 64 KB" in response["answer"]

def test_stream_keeps_partial_status_and_no_model_generation():
    events = list(rag_stream_events("DataApi와 ViewUi의 역할 및 RAM 사용량을 알려줘.", "test", None, 3, FixtureKnowledge([ROLES]), NoModel()))
    assert "DataApi의 역할: 문서 API" in events[1]["content"]
    assert events[1]["verification"]["passed"] is None
    assert events[-1]["eval_count"] == 0

@pytest.mark.parametrize("extra", ["서버 삭제 방법", "가격", "500 MB라고 단정", "보안 취약점"])
def test_unrecognized_extra_requirement_is_not_marked_complete(extra):
    question = "DataApi와 ViewUi의 역할 및 RAM 사용량과 " + extra + " 알려줘."
    check = role_requirements(question, [ROLES])
    assert not bounded_question(question, check)
    response = rag_response(question, "test", None, 3, FixtureKnowledge([ROLES]), NoModel())
    assert response["answer_status"] == "blocked"
    assert "질문의 다른 요구는 확인하지 못" in response["answer"]

def test_followup_can_recover_single_role_absent_from_initial_hits():
    initial = SearchResult("context.md", "실행", "DataApi RAM 측정은 준비 중이다.", 1)
    class Knowledge:
        def __init__(self):
            self.calls = []
        def search(self, query, top_k, **kwargs):
            self.calls.append(query)
            return [initial] if len(self.calls) == 1 else [ROLES]
    kb = Knowledge()
    response = rag_response("DataApi의 용도와 RAM 사용량을 원문 근거로 알려줘.", "test", None, 3, kb, NoModel())
    assert response["answer_status"] == "partial"
    assert "DataApi의 역할: 문서 API" in response["answer"]
    assert "DataApi 역할 용도" in kb.calls
    assert len(response["retrieval_followups"]) <= 4

@pytest.mark.parametrize("reversed_first", [True, False])
def test_explicit_reversed_list_conflict_does_not_select_table_role(reversed_first):
    reversed_list = SearchResult("reverse.md", "역할", "- 역할: **DataApi** — 실험 화면\n- 역할: **ViewUi** — 실험 화면", 1)
    results = [reversed_list, ROLES] if reversed_first else [ROLES, reversed_list]
    response = rag_response("DataApi와 ViewUi의 역할과 RAM 사용량을 알려줘.", "test", None, 3, FixtureKnowledge(results), NoModel())
    assert "DataApi의 역할 (원문 값 충돌)" in response["answer"]
    assert "DataApi의 역할: 문서 API" not in response["answer"]
    assert "ViewUi의 역할: 실험 화면" in response["answer"]

def test_generic_reversed_bullet_is_not_a_new_role_candidate():
    assert plain_role_pairs("- 정식 REST API: **DataApi**\n- 역할: **DataApi**") == []
