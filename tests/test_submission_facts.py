"""Independent submission fixtures; no event-specific answer keys in readers."""
import json
from types import SimpleNamespace

import pytest

from core.knowledge_base import SearchResult
from core.pdf_facts import pdf_source_answer
from core.rag_service import rag_response, rag_stream_events
from core.submission_facts import asks_submissions


TEXT = """1   추진 일정
접수       2033. 4. 2. ~ 4. 28. 15시

2   신청 방법
❍ 제출 서류: 연구 제안서 1부(PDF 형식, 7페이지 이내)
❍ 1차(접수): 제안서와 실험계획서 제출
- 접수 화면에서 연구윤리 확인·동의 후 재료
  사용 명세 및 안전
  확인서 제출
❍ 2차(선정): 시제품 영상 및 발표자료 제출

3   심사 방법
❍ 발표 점수로 선정
"""


def source(text=TEXT, heading="PDF 2페이지"):
    return SearchResult("Uploads/research.md", heading, text, 1)


class NoModel:
    def chat(self, *args, **kwargs): pytest.fail("submission section copy must not generate")


@pytest.mark.parametrize("question", [
    "접수 마감 날짜·시간과 1차 제출 서류의 형식·분량을 알려줘.",
    "1차 제출자료와 구비서류를 알려줘.",
    "1차에 제출해야 할 서류는 무엇인가요?",
])
def test_wrapped_additional_documents_and_common_requirements_preserved(question):
    answer, used, check = pdf_source_answer(question, [source()])
    assert all(part in answer for part in ("연구 제안서", "실험계획서", "재료\n  사용 명세", "안전\n  확인서", "연구윤리", "7페이지"))
    assert "시제품 영상" not in answer and "발표 점수" not in answer
    assert used and check["passed"] is None and check["missing_items"]
    if "마감" in question:
        assert "4. 28. 15시" in answer


def test_later_stage_does_not_inherit_first_stage_specific_requirements():
    answer, _, _ = pdf_source_answer("2차 제출 서류를 알려줘.", [source()])
    assert "시제품 영상" in answer and "발표자료" in answer
    assert "실험계획서" not in answer and "사용 명세" not in answer
    assert "연구 제안서" in answer  # explicitly common heading before the stages


def test_unspecified_stage_keeps_labels_and_both_lists():
    answer, _, check = pdf_source_answer("제출 서류 전체를 알려줘.", [source()])
    assert "1차(접수)" in answer and "2차(선정)" in answer
    assert "사용 명세" in answer and "시제품 영상" in answer and check["passed"] is None


def test_missing_requested_stage_is_explicit():
    answer, _, check = pdf_source_answer("3차 제출 서류는?", [source()])
    assert "실험계획서" not in answer and "시제품 영상" not in answer
    assert any("3차" in item for item in check["missing_items"])


def test_absent_submission_evidence_does_not_invent_documents():
    answer, used, check = pdf_source_answer("제출 서류는 무엇인가요?", [source("플랫폼 사용법을 안내한다.")])
    assert used == [] and "연구 제안서" not in answer and check["missing_items"]


def test_no_heading_form_retains_following_phase_and_stops_unrelated_bullet():
    text = "❍ 제출 서류: 신청서 1부\n❍ 1차(접수): 신청서 및 경력증명서\n- 개인정보 동의 후 추천서 제출\n❍ 문의: 운영사무국"
    answer, _, _ = pdf_source_answer("1차 제출 서류는?", [source(text)])
    assert "경력증명서" in answer and "추천서" in answer and "운영사무국" not in answer


def test_markdown_sections_and_nested_stage_headings():
    text = "## 제출 서류\n공통 제출 서류: 신청서\n### 1차\n- 초록과 재료명세 제출\n### 2차\n- 시연영상 제출\n## 문의\n문의전용문구"
    answer, _, _ = pdf_source_answer("1차 제출 서류는?", [source(text)])
    assert "재료명세" in answer and "시연영상" not in answer and "문의전용문구" not in answer


def test_missing_schedule_is_not_replaced_with_an_unrelated_date():
    text = TEXT.replace("접수       2033. 4. 2. ~ 4. 28. 15시", "수상 발표       2033. 5. 31.")
    answer, _, check = pdf_source_answer("1차 제출 서류와 접수 마감 날짜는?", [source(text)])
    assert "5. 31." not in answer
    assert any("일정" in item for item in check["missing_items"])


@pytest.mark.parametrize("stream", [False, True])
def test_service_returns_all_supported_submission_text_without_model(stream):
    knowledge = SimpleNamespace(search=lambda *a, **kw: [source()])
    question = "1차 제출 서류와 접수 마감 날짜·시간은?"
    if stream:
        events = list(rag_stream_events(question, "test", None, 3, knowledge, NoModel()))
        answer = events[1]["content"]
        assert events[-1]["done"] and events[-1]["eval_count"] == 0
    else:
        response = rag_response(question, "test", None, 3, knowledge, NoModel())
        answer = response["answer"]
        assert response["answer_status"] == "partial" and response["eval_count"] == 0
    assert "사용 명세" in answer and "안전\n  확인서" in answer


@pytest.mark.parametrize("framework", ["fastapi", "flask"])
def test_actual_api_submission_stream_preserves_missing_and_sources(framework, monkeypatch):
    from fastapi.testclient import TestClient
    import app
    import flask_app
    module = app if framework == "fastapi" else flask_app
    monkeypatch.setattr(module, "knowledge", SimpleNamespace(search=lambda *a, **kw: [source()]))
    monkeypatch.setattr(module, "client", NoModel())
    client = TestClient(module.app) if framework == "fastapi" else module.app.test_client()
    response = client.post("/rag/chat/stream", json={"prompt": "1차 제출 서류와 접수 마감 날짜·시간은?"})
    assert response.status_code == 200
    text = response.text if framework == "fastapi" else response.get_data(as_text=True)
    events = [json.loads(line) for line in text.splitlines()]
    assert events[0]["sources"] and "사용 명세" in events[1]["content"]
    assert events[-1]["done"] and events[-1]["eval_count"] == 0
    assert events[-1]["verification"]["passed"] is None and events[-1]["verification"]["missing_items"]


@pytest.mark.parametrize("question", [
    "기획안 PDF만 내면 접수가 끝나? 다른 자료나 동의 절차도 필요해?",
    "신청서만 제출하면 접수가 완료되나요?",
    "제안서만 보내면 신청이 끝나?",
    "접수할 때 PDF만으로 충분해?",
    "접수에 파일만 내도 돼?",
    "처음 접수할 때 준비해야 하는 파일과 추가 자료를 빠짐없이 알려줘.",
    "접수는 언제까지고, 준비할 서류는 어떤 형식으로 몇 쪽까지 작성해야 해?",
])
def test_submission_paraphrases_copy_additional_resources_without_model(question):
    assert asks_submissions(question)
    knowledge = SimpleNamespace(search=lambda *a, **kw: [source()])
    response = rag_response(question, "test", None, 3, knowledge, NoModel())
    assert "사용 명세" in response["answer"] and "연구윤리" in response["answer"]
    assert "PDF" in response["answer"] and "7페이지" in response["answer"]
    assert response["answer_status"] == "partial" and response["eval_count"] == 0
    assert "PDF만 내면 접수가 끝" not in response["answer"]
    if "언제" in question:
        assert "4. 28. 15시" in response["answer"]


@pytest.mark.parametrize("question", [
    "이것만 하면 돼?",
    "PDF 파일만 올리면 모델 학습이 끝나?",
    "접수 사이트의 PDF 업로드 기능을 구현해줘.",
    "신청서만 내면 끝나는지 말고 서버 설치법을 알려줘.",
    "기획안만 내면 접수가 끝나는지 묻는 게 아니야.",
    "행사 참가 동의만 하면 경품을 받아?",
    "동의서를 제출하면 개인정보가 안전해?",
])
def test_new_intent_does_not_capture_unrelated_or_rejected_submission_questions(question):
    assert asks_submissions(question) is False


def test_source_saying_no_extra_consent_is_not_inverted():
    text = "1 신청 방법\n❍ 제출 서류: 신청서만 제출합니다.\n별도 동의 절차는 필요하지 않습니다."
    answer, _, check = pdf_source_answer("신청서만 내면 접수가 끝나? 동의도 필요해?", [source(text)])
    assert "별도 동의 절차는 필요하지 않습니다" in answer
    assert "필수 동의" not in answer and "추가 서류가 필요합니다" not in answer
    assert check["passed"] is None


@pytest.mark.parametrize("framework", ["fastapi", "flask"])
def test_scoped_api_sufficiency_question_cannot_use_old_model_summary(framework, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from core.knowledge_base import KnowledgeBase
    import app
    import flask_app
    (tmp_path / "Uploads").mkdir()
    (tmp_path / "Uploads" / "research.md").write_text("# 연구 공모\n\n## PDF 2페이지\n\n" + TEXT, encoding="utf-8")
    (tmp_path / "upload-guide.md").write_text("# 접수 업로드\n\nPDF 파일 추가 버튼을 누른다.", encoding="utf-8")
    knowledge = KnowledgeBase(tmp_path)
    knowledge.reindex()
    module = app if framework == "fastapi" else flask_app
    monkeypatch.setattr(module, "knowledge", knowledge)
    monkeypatch.setattr(module, "client", NoModel())
    client = TestClient(module.app) if framework == "fastapi" else module.app.test_client()
    response = client.post("/rag/chat/stream", json={"prompt": "기획안 PDF만 내면 접수가 끝나? 다른 자료나 동의 절차도 필요해?", "source": "Uploads/research.md"})
    assert response.status_code == 200
    raw = response.text if framework == "fastapi" else response.get_data(as_text=True)
    events = [json.loads(line) for line in raw.splitlines()]
    assert "사용 명세" in events[1]["content"] and "연구윤리" in events[1]["content"]
    assert "파일 추가 버튼" not in events[1]["content"]
    assert events[-1]["eval_count"] == 0 and events[-1]["document_scope"]["source"] == "Uploads/research.md"
