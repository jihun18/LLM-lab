import pytest
from core.knowledge_base import SearchResult
from core.role_lists import memory_rows
from core.rag_service import rag_response, grounded_response, rag_stream_events
from core.table_comparison import deterministic_role_comparison
from compound_holdout import FixtureKnowledge

TABLE = SearchResult("table.md", "역할", "| 항목 | DocApi | ViewUi |\n|---|---|---|\n| 역할 | 문서 API | 실험 화면 |", 1)
LIST = SearchResult("list.md", "역할", "- DocApi: 실험 화면\n- ViewUi: 실험 화면", 1)

class NoModel:
    def chat(self, *args):
        raise AssertionError("conflicts must not generate")

@pytest.mark.parametrize("results", [[TABLE, LIST], [LIST, TABLE]])
def test_compound_conflict_does_not_depend_on_result_order(results):
    r = rag_response("DocApi와 ViewUi의 역할과 메모리 사용량", "test", None, 3, FixtureKnowledge(results), NoModel())
    assert r["answer_status"] == "partial"
    assert "DocApi의 역할 (원문 값 충돌)" in r["answer"]
    assert "DocApi의 역할: 문서 API" not in r["answer"]
    assert "ViewUi의 역할: 실험 화면" in r["answer"]

def test_simple_comparison_and_frozen_context_do_not_bypass_conflict():
    q = "DocApi와 ViewUi의 역할과 차이"
    assert deterministic_role_comparison(q, [TABLE, LIST]) is None
    r = grounded_response(q, "test", None, [TABLE, LIST], NoModel(), allow_text_extraction=False)
    assert r["execution_path"] == "role_conflict_guard"
    assert r["eval_count"] == 0

def test_all_roles_conflict_stream_shows_notice_instead_of_selected_roles():
    bad = SearchResult("bad.md", "역할", "- DocApi: 실험 화면\n- ViewUi: 문서 API", 1)
    events = list(rag_stream_events("DocApi와 ViewUi의 역할과 차이", "test", None, 3, FixtureKnowledge([TABLE,bad]), NoModel()))
    assert "원문 값 충돌" in events[1]["content"]
    assert events[-1]["eval_count"] == 0

@pytest.mark.parametrize("a,b", [("최소 비교군","최소 구현 비교"),("빠른 데모 UI","빠른 AI UI")])
def test_only_documented_wording_pairs_remain_compatible(a,b):
    table = SearchResult("a.md","역할",f"| 항목 | DocApi | ViewUi |\n|---|---|---|\n| 역할 | {a} | 실험 화면 |",1)
    listing = SearchResult("b.md","역할",f"- DocApi: {b}\n- ViewUi: 실험 화면",1)
    r = rag_response("DocApi와 ViewUi의 역할과 메모리 사용량", "test", None, 3, FixtureKnowledge([table,listing]), NoModel())
    assert f"DocApi의 역할: {a}" in r["answer"]
    assert "역할 (원문 값 충돌)" not in r["answer"]

def test_second_identity_column_preserves_first_condition():
    source = SearchResult("mem.md","측정","| 모델 | 도구 | RSS |\n|---|---|---|\n| demo:3b | DocApi | 240 MB |",1)
    assert memory_rows("DocApi",source) == ["모델 — demo:3b; RSS — 240 MB"]

@pytest.mark.parametrize("value", ["245760 KiB", "240 MiB", "0.25 GiB"])
def test_binary_memory_units_remain_literal(value):
    source = SearchResult("mem.md","측정",f"| RSS | tool | 모델 |\n|---|---|---|\n| {value} | DocApi | demo:3b |",1)
    assert value in memory_rows("DocApi",source)[0]

@pytest.mark.parametrize("headers,row", [
    ("이름 | RSS", "DocApi | 240 MB"),
    ("도구 | 대상 | RSS", "DocApi | DocApi | 240 MB"),
    ("도구 | RSS", "DocApiPro | 240 MB"),
    ("도구 | RSS", "DocApi | 20%"),
])
def test_unknown_ambiguous_or_unmatched_identity_is_not_guessed(headers,row):
    separator="|".join("---" for _ in headers.split("|"))
    source=SearchResult("mem.md","측정",f"| {headers} |\n|{separator}|\n| {row} |",1)
    assert memory_rows("DocApi",source) == []
