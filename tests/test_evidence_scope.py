import json
from pathlib import Path
from core.evidence_scope import unsupported_query_anchors
from core.knowledge_base import SearchResult
from core.grounding import deterministic_metric_answer
from core.rag_service import grounded_response
from core.search import SearchKnowledge

RESULT = SearchResult("note.md", "結果", "2026년 qwen3:4b-instruct 평균 시간 16초", 1)


def test_exact_models_and_years_not_shared_family_or_filename():
    assert unsupported_query_anchors("qwen3:32b 2028년", [RESULT]) == ["2028", "qwen3:32b"]
    assert unsupported_query_anchors("qwen3:32b의 실측", [RESULT]) == ["qwen3:32b"]
    assert not unsupported_query_anchors("2026년 QWEN3:4B-INSTRUCT", [RESULT])
    assert unsupported_query_anchors("2026년", [SearchResult("2026.md", "2026", "내용", 1)])


def test_missing_scope_never_calls_llm():
    class NoLLM:
        def chat(self, *args):
            raise AssertionError("must abstain before generation")
    response = grounded_response("2028년 지원금", "test", None, [RESULT], NoLLM())
    assert response["verification"]["method"] == "no_evidence"
    assert response["sources"] == []


def test_unknown_model_never_uses_other_table_row():
    result = SearchResult("table.md", "표", "| 모델 | 평균 시간 |\n|---|---|\n| qwen3:4b-instruct | 16초 |", 1)
    assert deterministic_metric_answer("qwen3:32b 평균 시간", [result]) is None
    assert "qwen3:4b-instruct" in deterministic_metric_answer("qwen3:4b-instruct 평균 시간", [result])[0]


def test_exact_row_is_used_even_if_other_model_shares_family():
    result = SearchResult("table.md", "표", "| 모델 | 평균 시간 |\n|---|---|\n| qwen3:4b-instruct | 16초 |\n| qwen3:1.7b | 8초 |", 1)
    answer = deterministic_metric_answer("qwen3:1.7b 평균 시간", [result])[0]
    assert "8 초" in answer
    assert "16 초" not in answer


def test_bm25_scope_guard(tmp_path):
    (tmp_path / "note.md").write_text("# 지원금\n\n2026년 지원금 금액 10만원 신청", encoding="utf-8")
    knowledge = SearchKnowledge(tmp_path)
    knowledge.reindex()
    assert knowledge.search("2026년 지원금 금액 신청")
    assert not knowledge.search("2028년 지원금 금액 신청")


def test_independent_questions_are_separate_from_calibration():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "search_independent_cases.json").read_text(encoding="utf-8"))
    calibration = json.loads((root / "search_calibration_cases.json").read_text(encoding="utf-8"))
    assert len({c["id"] for c in cases}) == len(cases) == 12
    assert not {c["question"] for c in cases} & {c["question"] for c in calibration}
    assert sum(bool(c.get("expect_no_evidence")) for c in cases) == 5


def test_review_sheet_accepts_windows_bom_and_does_not_invent_human_scores(tmp_path):
    from answer_review import write_review_sheet
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"results": [{"case_id": "one", "question": "질문",
                    "answer": "답변", "retrieved": [], "elapsed_seconds": 1}]}), encoding="utf-8-sig")
    text = write_review_sheet(path).read_text(encoding="utf-8")
    assert "정답성(0/1/2): ___" in text
    assert "답변" in text
