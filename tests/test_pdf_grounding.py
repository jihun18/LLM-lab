"""General PDF regression fixtures: no competition names/answers in production."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.document_ingest import DocumentIngestor
from core.grounding import (extract_structured_claims, requested_unit,
                            verify_grounded_answer, verify_structured_claims)
from core.knowledge_base import KnowledgeBase, SearchResult
from core.rag_service import grounded_response, rag_stream_events


def result(text, heading="PDF 8페이지"):
    return SearchResult("Uploads/independent.pdf.md", heading, text, 1)


def test_page_citation_not_a_claim_but_real_page_limit_is():
    answer = "참가자는 만 23세 이상이며 3인~5인 팀입니다. [출처: x.md#PDF 8페이지]"
    claims = extract_structured_claims(answer)
    assert "8페이지" not in claims and "23세" in claims and "3인" in claims and "5인" in claims
    check = verify_grounded_answer("참가 자격은?", answer, [result("참가자는 만 23세 이상이며 3인~5인 팀입니다.")])
    assert check["passed"] is True
    assert verify_structured_claims("제안서는 8페이지 이내입니다.", [result("제안서는 6페이지 이내입니다.")])["passed"] is False


@pytest.mark.parametrize("answer", ["포상금은 700만 원입니다.", "포상금은 700만원입니다."])
def test_spaced_amount_not_missed(answer):
    check = verify_structured_claims(answer, [result("포상금은 450만원입니다.")])
    assert check["passed"] is False and check["unsupported_claims"]
    assert "실패" in check["display_label"]


@pytest.mark.parametrize("unit", ["팀", "명", "인", "세", "점", "회"])
def test_counts_are_checked(unit):
    assert verify_structured_claims(f"제한은 17{unit}입니다.", [result(f"제한은 12{unit}입니다.")])["passed"] is False


def test_numbers_do_not_match_inside_larger_numbers():
    assert verify_structured_claims("20만원을 지급합니다.", [result("120만원을 지급합니다.")])["passed"] is False
    assert verify_structured_claims("2명입니다.", [result("12명입니다.")])["passed"] is False


@pytest.mark.parametrize("question", ["본선 행사 날짜와 시작 시간은?", "접수 마감 날짜·시간을 알려줘.", "발표 일정과 시각은?"])
def test_calendar_time_does_not_require_benchmark_table(question):
    assert requested_unit(question) is None
    check = verify_grounded_answer(question, "2031년 8월 9일 16시입니다.", [result("2031. 8. 9. 16시")])
    assert check["passed"] is True


def test_calendar_range_inherits_year_only_from_same_range():
    assert verify_structured_claims("마감은 2031년 8월 19일 16시입니다.", [result("접수 2031. 8. 1.(금) ~ 8. 19.(화) 16시")])["passed"] is True
    assert verify_structured_claims("마감은 2031년 8월 19일입니다.", [result("2031년 대회\n마감 8. 19.")])["passed"] is False


def test_explicit_duration_still_uses_metric_table():
    assert requested_unit("평균 응답시간은 몇 초야?") == "seconds"
    assert requested_unit("행사 페이지 평균 처리시간은?") == "seconds"


@pytest.mark.parametrize("text", [
    "구분       시상 수       금액\n금상        3점        450만원\n은상        5점        250만원",
    "| 구분 | 수 | 금액 |\n|---|---|---|\n| 금상 | 3점 | 450만원 |\n| 은상 | 5점 | 250만원 |",
])
def test_existing_numbers_bound_to_wrong_row_are_rejected(text):
    assert verify_structured_claims("금상은 3점, 250만원이고 은상은 5점, 450만원입니다.", [result(text)])["passed"] is False
    assert verify_structured_claims("금상은 3점, 450만 원이고 은상은 5점, 250만 원입니다.", [result(text)])["passed"] is True


def test_ingest_requests_layout_and_keeps_page_boundaries(monkeypatch, tmp_path):
    import pypdf
    calls = []
    class Page:
        def extract_text(self, **kwargs):
            calls.append(kwargs)
            return "구분       수량       금액\n금상        3점        450만원"
    monkeypatch.setattr(pypdf, "PdfReader", lambda _: SimpleNamespace(is_encrypted=False, pages=[Page(), Page()]))
    ingestor = DocumentIngestor(tmp_path)
    data = ingestor.ingest("독립 안내.pdf", b"fake")
    text = (tmp_path / data["wiki_file"]).read_text(encoding="utf-8-sig")
    assert "## PDF 1페이지" in text and "## PDF 2페이지" in text
    assert "금상        3점        450만원" in text
    assert calls == [{"extraction_mode": "layout"}] * 2


def test_generated_upload_metadata_cannot_win_retrieval(tmp_path):
    (tmp_path / "Uploads").mkdir()
    (tmp_path / "Uploads" / "경진대회.md").write_text(
        "# 경진대회\n\n> 원본 파일: `경진대회.pdf`  \n> 가져온 시각: 2031-01-01 00:00:00  \n> 원본 형식: .pdf · 8페이지\n\n## 문서 내용\n\n## PDF 2페이지\n\n참가자격 만 23세 이상\n\n## PDF 3페이지\n\n금상 3점 450만원",
        encoding="utf-8")
    kb = KnowledgeBase(tmp_path)
    kb.reindex()
    assert len(kb.chunks) == 2 and all(not c.text.startswith("> 원본 파일") for c in kb.chunks)
    assert kb.search("경진대회 금상")[0].heading == "PDF 3페이지"


def test_legitimate_non_upload_metadata_is_not_removed(tmp_path):
    (tmp_path / "metadata.md").write_text("# 원본 관리\n\n> 원본 파일: `안내.pdf`\n원본관리절차", encoding="utf-8")
    kb = KnowledgeBase(tmp_path)
    kb.reindex()
    assert kb.search("원본관리절차")


class FakeModel:
    def __init__(self, answer): self.answer = answer
    def chat_with_sources(self, *args):
        return {"model": "test", "answer": json.dumps({"answer": self.answer, "source_id": 1}, ensure_ascii=False),
                "elapsed_seconds": 0, "eval_count": 8, "tokens_per_second": 1}


def test_structured_unsupported_money_and_counts_do_not_leak_into_stream():
    class Knowledge:
        def search(self, *args): return [result("금상        3점        450만원")]
    events = list(rag_stream_events("시상 수와 상금은?", "test", None, 3, Knowledge(),
                                    FakeModel("금상은 20팀이고 700만 원입니다.")))
    assert events[-1]["verification"]["passed"] is False
    assert "700" not in events[1]["content"] and "20팀" not in events[1]["content"]


def test_known_date_and_unpublished_venue_can_be_shown_together():
    response = grounded_response("본선 발표 날짜와 정확한 장소·시작 시간을 알려줘.", "test", None,
        [result("발표 2031. 8. 9.\n장소와 시간은 추후 공개(장소: 대전)")],
        FakeModel("본선은 2031년 8월 9일 대전이며 정확한 장소와 시작 시간은 추후 공개입니다."))
    assert response["verification"]["passed"] is not False
    assert "대전" in response["answer"] and "추후 공개" in response["answer"]


def test_short_korean_date_is_not_ignored_or_duplicated_inside_full_date():
    check = verify_structured_claims("접수는 2031년 8월 1일부터 8월 19일까지입니다.", [result("접수 2031. 8. 1. ~ 8. 19.")])
    assert check["passed"] is True
    assert check["claims"] == ["2031년 8월 1일", "8월 19일"]
    assert verify_structured_claims("마감은 8월 29일입니다.", [result("2031. 8. 19.")])["passed"] is False


def test_pdf_page_context_is_focused_without_changing_frozen_calls():
    rows = [result("참가자는 만 23세 이상입니다.", "PDF 2페이지"), result("관련 없는 표지", "PDF 1페이지")]
    class Knowledge:
        def search(self, *args): return rows
    class RecordingModel(FakeModel):
        def chat_with_sources(self, prompt, model, system, count):
            self.count = count
            self.prompt = prompt
            return super().chat_with_sources(prompt, model, system, count)
    model = RecordingModel("참가자는 만 23세 이상입니다.")
    from core.rag_service import rag_response
    response = rag_response("참가 자격은?", "test", None, 3, Knowledge(), model)
    assert model.count == 1 and "관련 없는 표지" not in model.prompt
    assert response["context"]["retrieved_count"] == 2 and response["context"]["sent_count"] == 1
    assert response["context"]["selection_policy"] == "uploaded_pdf_primary_page"
    grounded_response("참가 자격은?", "test", None, rows, model, allow_text_extraction=False)
    assert model.count == 2


def test_mixed_documents_are_not_silently_treated_as_one_pdf():
    from core.rag_service import rag_response
    rows = [result("참가자는 만 23세 이상입니다."), SearchResult("other.md", "참가", "다른 자료", 1)]
    class Knowledge:
        def search(self, *args): return rows
    response = rag_response("참가 자격은?", "test", None, 3, Knowledge(), FakeModel("참가자는 만 23세 이상입니다."))
    assert response["context"]["sent_count"] == 2 and response["context"]["mode"] == "full"


def test_pdf_year_anchor_fallback_reports_actual_multi_page_policy():
    from core.rag_service import rag_response
    rows = [result("참가자는 만 23세 이상입니다."), result("2031년 행사 안내", "PDF 1페이지")]
    class Knowledge:
        def search(self, *args): return rows
    response = rag_response("2031년 참가 자격은?", "test", None, 3, Knowledge(), FakeModel("참가자는 만 23세 이상입니다."))
    assert response["context"]["sent_count"] == 2
    assert response["context"]["selection_policy"] == "uploaded_pdf_anchor_preserving"


def test_pdf_named_rows_copy_units_without_turning_points_into_teams():
    from core.pdf_facts import pdf_source_answer
    source = result("구분       수       금액\n금상        3점        450만원\n은상        5점        250만원\n\n※ 포상금은 지역상품권으로 지급합니다.")
    answer, used, check = pdf_source_answer("금상·은상은 몇 팀이며 상금과 지급 방식은?", [source])
    assert "3점" in answer and "5점" in answer and "450만원" in answer and "250만원" in answer
    assert "지역상품권" in answer and "3팀" not in answer and "5팀" not in answer
    assert used == [source] and check["passed"] is None and check["missing_items"]


def test_pdf_conflicting_rows_and_unrecognized_forms_not_fabricated():
    from core.pdf_facts import pdf_source_answer
    sources = [result("금상        3점        450만원\n은상        5점        250만원"), result("금상        4점        600만원", "PDF 9페이지")]
    answer, _, check = pdf_source_answer("금상·은상은 몇 팀이며 상금은?", sources)
    assert "450만원" not in answer and "600만원" not in answer and "원문 값 충돌" in answer
    assert "250만원" in answer and check["passed"] is None
    assert pdf_source_answer("참가팀의 상금은?", [result("설명만 있음")]) is None


def test_pdf_unpublished_fields_copy_correct_contiguous_event_phrase():
    from core.pdf_facts import pdf_source_answer
    source = result("추진 일정\n본선 참가팀 발표      2031. 8. 19.\n본선 발표·시상      2031. 8. 29.\n\n장소 및 시간은 추후 공개(장소: 대전)")
    answer, _, check = pdf_source_answer("경진대회의 본선 발표 날짜와 정확한 행사 장소·시작 시간을 알려줘.", [source])
    assert "2031. 8. 29." in answer and "2031. 8. 19." not in answer
    assert "대전" in answer and "추후 공개" in answer and check["missing_items"]


def test_pdf_absent_quota_does_not_get_an_invented_source_copy():
    from core.pdf_facts import pdf_source_answer
    assert pdf_source_answer("팀별 API 호출 한도는 몇 회야?", [result("플랫폼 사용법을 안내한다.")]) is None


def test_unconfirmed_quota_is_explained_without_leaking_model_number():
    response = grounded_response("API 호출 한도는 몇 회야?", "test", None,
        [result("계정별 API 사용법을 안내한다.")], FakeModel("한도는 777회입니다."))
    assert response["verification"]["passed"] is False
    assert "777" not in response["answer"] and "한도 값을 검색된 근거로 확인하지 못했습니다" in response["answer"]


def test_unpublished_notice_does_not_copy_unrelated_ot_paragraph():
    from core.pdf_facts import pdf_source_answer
    source = result("본선 발표·시상     2031. 8. 29.\n※ 일정은 변경될 수 있음\n❍ OT 안내 영상을 제공한다.\n❍ 장소 및 시간은 추후 공개(장소: 대전)")
    answer, _, _ = pdf_source_answer("경진대회의 본선 발표 날짜와 정확한 장소·시작 시간을 알려줘.", [source])
    assert "OT 안내" not in answer and "대전" in answer


@pytest.mark.parametrize("framework", ["fastapi", "flask"])
@pytest.mark.parametrize("kind", ["rows", "unpublished"])
def test_pdf_copy_actual_api_stream_preserves_partial_sources(framework, kind, monkeypatch):
    from fastapi.testclient import TestClient
    import app
    import flask_app
    module = app if framework == "fastapi" else flask_app
    if kind == "rows":
        source = result("금상        3점        450만원\n은상        5점        250만원")
        question = "금상·은상은 몇 팀이며 상금은?"
    else:
        source = result("본선 발표·시상     2031. 8. 29.\n❍ 장소 및 시간은 추후 공개(장소: 대전)")
        question = "경진대회의 본선 발표 날짜와 정확한 장소·시작 시간을 알려줘."
    monkeypatch.setattr(module, "knowledge", SimpleNamespace(search=lambda *a, **kw: [source]))
    class NoModel:
        def chat(self, *a, **kw): pytest.fail("PDF source-copy must not generate")
    monkeypatch.setattr(module, "client", NoModel())
    client = TestClient(module.app) if framework == "fastapi" else module.app.test_client()
    response = client.post("/rag/chat/stream", json={"prompt": question})
    assert response.status_code == 200
    text = response.text if framework == "fastapi" else response.get_data(as_text=True)
    events = [json.loads(line) for line in text.splitlines()]
    assert events[0]["sources"] and events[-1]["done"] and events[-1]["eval_count"] == 0
    assert events[-1]["verification"]["passed"] is None and events[-1]["verification"]["missing_items"]
    assert ("450만원" if kind == "rows" else "2031. 8. 29.") in events[1]["content"]
