import pytest
from core.context_budget import select_context
from core.knowledge_base import SearchResult


def test_primary_keeps_complete_table_and_citation_identity():
    table = "| 모델 | 값 |\n|---|---|\n| qwen3:1.7b | 8 |"
    rows = [SearchResult("a.md", "표", table, 1), SearchResult("b.md", "메모", "추가", .5)]
    assert select_context("모델 표", rows, "primary") == rows[:1]
    assert select_context("모델 표", rows, "primary")[0].text == table
    assert select_context("모델 표", rows) == rows


def test_secondary_explicit_anchor_is_not_dropped():
    rows = [SearchResult("a.md", "첫째", "qwen3:1.7b", 1),
            SearchResult("b.md", "둘째", "qwen3:4b-instruct 2026년", .5)]
    assert select_context("qwen3:1.7b와 qwen3:4b-instruct 2026년 비교", rows, "primary") == rows
    assert select_context("빈 질문", [], "primary") == []
    with pytest.raises(ValueError):
        select_context("질문", rows, "unknown")


def test_generated_answer_cannot_cite_a_dropped_context():
    from core.rag_service import grounded_response
    rows = [SearchResult("first.md", "첫째", "첫 번째 근거", 1),
            SearchResult("second.md", "둘째", "보조 근거", .5)]
    class Client:
        def chat(self, prompt, model, system):
            assert "보조 근거" not in prompt
            return {"answer": "답변 [출처: second.md#둘째]", "elapsed_seconds": 1}
    response = grounded_response("설명해줘", "test", None, rows, Client(), context_mode="primary")
    assert response["verification"]["passed"] is False
    assert response["context"]["sent_count"] == 1
    assert [s["source"] for s in response["sources"]] == ["first.md"]


def test_review_sheet_identifies_context_mode(tmp_path):
    import json
    from answer_review import write_review_sheet
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"results": [{"case_id": "one", "question": "질문", "answer": "답변",
                    "context_mode": "primary", "retrieved": [], "elapsed_seconds": 1}]}), encoding="utf-8")
    assert "근거 방식: primary" in write_review_sheet(path).read_text(encoding="utf-8")
