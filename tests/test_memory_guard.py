from pathlib import Path
import pytest
from core.knowledge_base import KnowledgeBase, SearchResult
from core.rag_service import rag_response, grounded_response, rag_stream_events
from core.memory_requirements import named_targets
from compound_holdout import FixtureKnowledge

ROLES = SearchResult("roles.md", "도구", "- DataApi: 문서 API\n- ViewUi: 실험 화면", 1)

class NoModel:
    def chat(self, *args):
        raise AssertionError("memory requests must not generate unsupported prose")

@pytest.mark.parametrize("question", [
    "DataApi의 역할과 메모리 사용량도 알려줘.",
    "DataApi와 ViewUi가 맡는 작업과 메모리 사용량을 설명해줘.",
    "DataApi가 하는 기능을 자세하게 설명하고 메모리 사용량도 비교해줘.",
    "DataApi 메모리 사용량은?", "이 도구의 메모리 사용량은?", "DataApi RSS는 얼마인가요?",
])
def test_memory_guard_is_independent_of_count_and_role_phrasing(question):
    response = rag_response(question, "test", None, 3, FixtureKnowledge([ROLES]), NoModel())
    assert response["eval_count"] == 0
    assert response["answer_status"] in {"partial", "blocked"}
    assert "메모리" in response["answer"] and "근거" in response["answer"]
    assert "작업 관리자 전체 메모리 사용량에 해당" not in response["answer"]

@pytest.mark.parametrize("extract", [True, False])
def test_frozen_context_memory_guard_cannot_be_disabled(extract):
    response = grounded_response("DataApi 기능과 메모리 사용량", "test", None, [ROLES], NoModel(), allow_text_extraction=extract)
    assert response["execution_path"] == "memory_requirements_guard"
    assert response["eval_count"] == 0

def test_memory_rows_only_fallback_does_not_claim_whole_question_complete():
    measured = SearchResult("mem.md", "RSS", "| 도구 | 모델 | RSS |\n|---|---|---|\n| DataApi | demo:2b | 210 MB |", 1)
    response = rag_response("DataApi의 기능을 자세히 설명하고 메모리 사용량도 알려줘", "test", None, 3, FixtureKnowledge([measured]), NoModel())
    assert "210 MB" in response["answer"] and "demo:2b" in response["answer"]
    assert response["answer_status"] == "partial"
    assert "다른 요구는 확인하지 못" in response["answer"]

def test_memory_guard_empty_search_and_stream_are_safe():
    events = list(rag_stream_events("DataApi 메모리 사용량", "test", None, 3, FixtureKnowledge([]), NoModel()))
    assert events[-1]["eval_count"] == 0
    assert events[1]["verification"]["method"] == "memory_requirements_guard"
    assert "확인하지 못" in events[1]["content"]

def test_ram_rss_are_metrics_not_targets():
    assert named_targets("DataApi의 RAM 사용량과 RSS") == ["DataApi"]

@pytest.mark.parametrize("question", [
    "FastAPI와 Flask가 맡는 작업과 메모리 사용량을 설명해줘.",
    "Streamlit의 역할과 메모리 사용량도 알려주세요.",
])
def test_two_newly_failed_questions_become_partial_regressions(question):
    kb = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    kb.reindex()
    response = rag_response(question, "test", None, 3, kb, NoModel())
    assert response["answer_status"] == "partial"
    assert response["execution_path"] == "deterministic_requirement_copy"
    assert "대상별 메모리 사용량 (검색 근거 부족)" in response["answer"]
    assert "기록된 생성속도" not in response["answer"]

def test_numeric_matching_does_not_verify_whole_generated_answer():
    source = SearchResult("metric.md", "기록", "기록된 처리량은 12 token/s이다.", 1)
    class Client:
        def chat(self, *args):
            return {"answer":"기록된 처리량은 12 token/s입니다.\n[출처: metric.md#기록]", "elapsed_seconds":0.1,"eval_count":10,"tokens_per_second":10}
    response = grounded_response("기록 내용을 설명해줘", "test", None, [source], Client())
    assert response["answer_status"] == "review_required"
    assert response["verification"]["numeric_verification"]["passed"] is True
    assert "수치 근거만 확인" in response["verification"]["display_label"]
