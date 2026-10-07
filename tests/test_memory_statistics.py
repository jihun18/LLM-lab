from pathlib import Path
import pytest
from core.knowledge_base import KnowledgeBase, SearchResult
from core.memory_requirements import memory_statistics
from core.role_lists import memory_rows
from core.rag_service import rag_response, grounded_response, rag_stream_events
from compound_holdout import FixtureKnowledge

ROLES = SearchResult("roles.md", "역할", "- DataApi: 문서 API\n- ViewUi: 실험 화면", 1)
GENERIC = SearchResult("generic.md", "최대 메모리 기록", "| 도구 | 모델 | RSS |\n|---|---|---|\n| DataApi | mock:2b | 220 MB |\n| ViewUi | mock:2b | 180 MB |", 1)
STATS = SearchResult("stats.md", "실측", "| 모델 | 도구 | 조건 | 최대 RSS | 평균 RSS | 최소 RSS |\n|---|---|---|---|---|---|\n| mock:2b | DataApi | 요청 1 | 240 MB | 200 MB | 160 MB |\n| mock:2b | ViewUi | 요청 1 | 180 MB | 140 MB | 100 MB |", 1)

class NoModel:
    def chat(self, *args):
        raise AssertionError("memory statistics must not be generated")

@pytest.mark.parametrize("statistic", ["최대", "평균", "최소"])
def test_generic_values_cannot_be_relabelled_as_statistics(statistic):
    question = f"DataApi와 ViewUi의 역할과 {statistic} 메모리 사용량도 비교해줘."
    response = rag_response(question, "test", None, 3, FixtureKnowledge([ROLES, GENERIC]), NoModel())
    assert response["answer_status"] == "partial"
    assert "DataApi의 역할: 문서 API" in response["answer"]
    assert f"DataApi의 대상별 {statistic} 메모리 사용량 (검색 근거 부족)" in response["answer"]
    assert "220 MB" not in response["answer"]
    assert response["eval_count"] == 0

@pytest.mark.parametrize("statistic,value,other", [("최대","240 MB","200 MB"),("평균","200 MB","240 MB"),("최소","160 MB","240 MB")])
def test_only_requested_statistic_is_copied_with_conditions(statistic,value,other):
    response = rag_response(f"DataApi와 ViewUi의 업무 및 {statistic} RSS 사용량을 알려줘.", "test", None, 3, FixtureKnowledge([ROLES, STATS]), NoModel())
    assert response["answer_status"] == "source_copied"
    assert value in response["answer"] and other not in response["answer"]
    assert "mock:2b" in response["answer"] and "요청 1" in response["answer"]
    assert f"대상별 {statistic} 메모리 사용량" in response["answer"]

def test_multiple_statistics_are_distinct_requirements():
    maximum = SearchResult("max.md", "측정", "| 도구 | 최대 메모리 사용량 |\n|---|---|\n| DataApi | 240 MB |", 1)
    response = rag_response("DataApi의 역할과 최대·평균·최소 메모리 사용량을 알려줘.", "test", None, 3, FixtureKnowledge([ROLES, maximum]), NoModel())
    assert "240 MB" in response["answer"]
    assert "대상별 평균 메모리 사용량 (검색 근거 부족)" in response["answer"]
    assert "대상별 최소 메모리 사용량 (검색 근거 부족)" in response["answer"]
    assert response["verification"]["passed"] is None

@pytest.mark.parametrize("header", ["최대 허용 메모리 사용량", "최대 평균 RSS", "RSS", "평균 RSS"])
def test_unknown_or_wrong_statistic_header_is_not_guessed(header):
    source = SearchResult("a.md", "최대", f"| 도구 | {header} |\n|---|---|\n| DataApi | 240 MB |", 1)
    assert memory_rows("DataApi", source, "최대") == []

def test_duplicate_statistic_columns_are_ambiguous():
    source = SearchResult("dup.md", "측정", "| 도구 | 최대 RSS | 최대 RSS |\n|---|---|---|\n| DataApi | 240 MB | 300 MB |", 1)
    assert memory_rows("DataApi", source, "최대") == []

def test_conflicting_conditions_remain_unselected():
    other = SearchResult("other.md", "측정", STATS.text.replace("요청 1", "요청 2"), 1)
    response = rag_response("DataApi의 역할과 평균 메모리 사용량을 알려줘.", "test", None, 3, FixtureKnowledge([ROLES, STATS, other]), NoModel())
    assert "평균 메모리 사용량 (원문 값 충돌)" in response["answer"]
    assert "200 MB" not in response["answer"]

@pytest.mark.parametrize("extract", [True, False])
def test_frozen_context_fallback_keeps_statistic_when_extraction_disabled(extract):
    response = grounded_response("DataApi의 최대 RAM 사용량을 알려줘.", "test", None, [GENERIC], NoModel(), allow_text_extraction=extract)
    assert "대상별 최대 메모리 사용량 (검색 근거 부족)" in response["answer"]
    assert "220 MB" not in response["answer"]

def test_followup_keeps_statistic_and_query_limits():
    class Knowledge:
        def __init__(self): self.calls = []
        def search(self, query, count, **kwargs):
            self.calls.append((query,count,kwargs))
            return [ROLES] if len(self.calls) == 1 else [STATS]
    kb = Knowledge()
    response = rag_response("DataApi의 역할과 평균 메모리 사용량을 알려줘.", "test", None, 3, kb, NoModel(), "hybrid")
    assert any("DataApi 평균 메모리 사용량 RSS" == q for q,_,_ in kb.calls)
    assert all(kwargs == {"mode":"hybrid"} for _,_,kwargs in kb.calls)
    assert len(response["retrieval_followups"]) <= 4

def test_maximum_question_becomes_real_wiki_partial_regression():
    kb = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    kb.reindex()
    response = rag_response("FastAPI와 Flask의 역할과 최대 메모리 사용량도 비교해줘.", "test", None, 3, kb, NoModel())
    assert response["answer_status"] == "partial"
    assert "FastAPI의 역할" in response["answer"] and "Flask의 역할" in response["answer"]
    assert "최대 메모리 사용량 (검색 근거 부족)" in response["answer"]

def test_stream_partial_preserves_condition():
    events = list(rag_stream_events("DataApi의 역할 및 최소 RAM 사용량을 알려줘.", "test", None, 3, FixtureKnowledge([ROLES, GENERIC]), NoModel()))
    assert "DataApi의 역할: 문서 API" in events[1]["content"]
    assert "최소 메모리 사용량 (검색 근거 부족)" in events[1]["content"]
    assert events[-1]["eval_count"] == 0

def test_speed_average_is_not_a_memory_average():
    assert memory_statistics("DataApi의 평균 생성속도와 메모리 사용량") == []
    response = rag_response("DataApi의 역할과 평균 속도 및 메모리 사용량을 알려줘.", "test", None, 3, FixtureKnowledge([ROLES, GENERIC]), NoModel())
    assert response["answer_status"] == "partial"  # common guard copies memory only
    assert "평균 메모리 사용량:" not in response["answer"]
    assert "다른 요구는 확인하지 못" in response["answer"]
