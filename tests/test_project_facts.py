"""User's ten-question run is development regression, not a new holdout."""
from pathlib import Path
import json

import pytest

from core.knowledge_base import KnowledgeBase, SearchResult
from core.project_facts import intent, project_source_answer, supplement_project_evidence
from core.rag_service import rag_response, rag_stream_events, SOURCE_CITATION_PATTERN
from core.grounding import deterministic_metric_answer


QUESTIONS = [
    "이 프로젝트에서 FastAPI, Flask, Streamlit은 각각 어떤 역할이야?",
    "Streamlit의 실행 포트와 화면 구성은 어떻게 기록되어 있어?",
    "FastAPI와 Flask의 API 문서 제공 방식은 어떻게 달라?",
    "기록된 Flask와 Streamlit의 생성속도와 전체 시간을 각각 알려줘.",
    "그 생성속도 기록만 보면 Flask가 Streamlit보다 성능이 좋다고 결론 내려도 돼?",
    "FastAPI와 Flask의 역할을 설명하고, Django의 역할도 알려줘.",
    "FastAPI와 Streamlit의 역할, 그리고 둘이 실제로 통신하는 방식을 설명해줘.",
    "이 프로젝트에서 사용하는 모델과 기본 모델을 알려줘.",
    "모델을 USB로 옮긴 뒤에도 이전 속도 측정 결과를 그대로 적용해도 돼?",
    "지금까지 확인된 사실과 아직 검증하지 않은 내용을 나눠서 이 프로젝트를 요약해줘.",
]


class NoModel:
    def chat(self, *args, **kwargs):
        pytest.fail("bounded source answer must not generate")


@pytest.fixture(scope="module")
def kb():
    knowledge = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    knowledge.reindex()
    return knowledge


@pytest.mark.parametrize("index", range(10))
@pytest.mark.parametrize("stream", [False, True])
def test_ten_question_regression(index, stream, kb):
    if stream:
        events = list(rag_stream_events(QUESTIONS[index], "test", None, 3, kb, NoModel()))
        answer, sources, check = events[1]["content"], events[0]["sources"], events[-1]["verification"]
        assert events[-1]["done"] and events[-1]["eval_count"] == 0
    else:
        result = rag_response(QUESTIONS[index], "test", None, 3, kb, NoModel())
        answer, sources, check = result["answer"], result["sources"], result["verification"]
        assert result["eval_count"] == 0
    assert check["method"] == "deterministic_requirement_copy"
    expected = [
        ["FastAPI의 역할: 주력 REST API", "Flask의 역할", "Streamlit의 역할"],
        ["실행 포트: 8501", "화면: Streamlit 기본 UI"],
        ["자동 `/docs`", "별도 필요"],
        ["5.003초", "12.61 token/s", "4.953초", "11.24 token/s", "qwen3:1.7b"],
        ["전체 시간 차이는 프레임워크만의 차이가 아니다", "결론 내릴 수 없습니다"],
        ["FastAPI의 역할: 주력 REST API", "Flask의 역할: 최소 비교군", "Django의 역할 (검색 근거 부족)"],
        ["FastAPI의 역할", "Streamlit의 역할", "실제 통신·연동 구조", "추정하지 않습니다"],
        ["qwen3:1.7b", "qwen3:4b-instruct", "qwen2.5:7b-instruct", "기본 모드 결정", "설치된 전체 모델 목록"],
        ["USB 이전 후", "그대로 적용할 수 있다고 답하지 않습니다", "재현성 판단 근거"],
        ["FastAPI의 역할", "모델 모드", "프로젝트 전체의 최신 검증 완료·미완료 목록"],
    ][index]
    assert all(text in answer for text in expected), answer
    if index == 1:
        assert "privAI.html" not in answer
    if index == 8:
        assert "token/s" not in answer and "13.99" not in answer
    if index in {4, 5, 6, 8, 9}:
        assert check["passed"] is None and check["missing_items"]
    else:
        assert check["passed"] is True and not check["missing_items"]
    assert {(s.strip(), h.strip()) for s, h in SOURCE_CITATION_PATTERN.findall(answer)} == {
        (r["source"], r["heading"]) for r in sources}


TABLE = SearchResult("custom.md", "비교", "| 항목 | CedarApi | MapleView |\n|---|---|---|\n| 역할 | 검색 API | 검토 UI |\n| 실행 포트 | 1234 | 5678 |\n| 화면 | 첫 화면 | 별도 화면 |", 1)


def test_reader_uses_evidence_not_framework_constants():
    answer, used, check = project_source_answer("MapleView의 실행 포트와 화면 구성은 어떻게 기록되어 있어?", [TABLE])
    assert "5678" in answer and "별도 화면" in answer and "1234" not in answer
    assert used == [TABLE] and check["passed"] is True


def test_conflicting_or_missing_cells_never_choose_first():
    other = SearchResult("other.md", "비교", TABLE.text.replace("5678", "9876"), 1)
    answer, _, check = project_source_answer("MapleView의 실행 포트와 화면 구성은 어떻게 기록되어 있어?", [TABLE, other])
    assert "5678" not in answer and "9876" not in answer and "원문 값 충돌" in answer
    assert "별도 화면" in answer and check["passed"] is None
    answer, _, check = project_source_answer("Absent의 실행 포트와 화면 구성은 어떻게 기록되어 있어?", [TABLE])
    assert not check["passed"] and "검색 근거 부족" in answer


def test_role_list_conflict_is_not_bypassed():
    other = SearchResult("other.md", "역할", "- CedarApi: 검토 UI", 1)
    answer, _, check = project_source_answer("CedarApi와 MapleView은 각각 어떤 역할이야?", [TABLE, other])
    assert "CedarApi의 역할 (원문 값 충돌)" in answer
    assert "CedarApi의 역할: 검색 API" not in answer and check["passed"] is None


@pytest.mark.parametrize("extra", ["CPU 사용률", "최대 메모리", "연결 예제", "보안 설정", "비용"])
def test_unknown_extra_requirement_not_accepted_as_complete(extra):
    assert intent(f"MapleView의 실행 포트와 {extra}도 알려줘.") is None
    assert project_source_answer(f"MapleView의 실행 포트와 {extra}도 알려줘.", [TABLE]) is None


def test_followup_empty_initial_and_selected_mode_budget():
    class Knowledge:
        def __init__(self): self.calls = []
        def search(self, query, count, **kwargs):
            self.calls.append((query, count, kwargs))
            return [TABLE]
    knowledge = Knowledge()
    results, trace = supplement_project_evidence(QUESTIONS[-1], [], knowledge, "hybrid")
    assert results == [TABLE] and 0 < len(trace) <= 4
    assert all(count == 3 and kw == {"mode": "hybrid"} for _, count, kw in knowledge.calls)


@pytest.mark.parametrize("index", [3, 4, 8])
def test_metric_shortcut_must_not_swallow_compound_or_judgement(index):
    result = SearchResult("speed.md", "측정", "| 모드 | 평균 생성속도 |\n|---|---|\n| 빠른 모드 | 13.99 token/s |", 1)
    assert deterministic_metric_answer(QUESTIONS[index], [result]) is None


def test_explicit_missing_year_still_blocks_copy(kb):
    response = rag_response("2042년 " + QUESTIONS[1], "test", None, 3, kb, NoModel())
    assert response["verification"]["passed"] is False and response["sources"] == []


@pytest.mark.parametrize("framework", ["fastapi", "flask"])
@pytest.mark.parametrize("index", [1, 3, 5, 6, 8])
def test_actual_api_stream_contract(framework, index, kb, monkeypatch):
    from fastapi.testclient import TestClient
    import app
    import flask_app
    module = app if framework == "fastapi" else flask_app
    monkeypatch.setattr(module, "knowledge", kb)
    monkeypatch.setattr(module, "client", NoModel())
    client = TestClient(module.app) if framework == "fastapi" else module.app.test_client()
    response = client.post("/rag/chat/stream", json={"prompt": QUESTIONS[index]})
    assert response.status_code == 200
    text = response.text if framework == "fastapi" else response.get_data(as_text=True)
    events = [json.loads(line) for line in text.splitlines()]
    assert events[-1]["done"] and events[-1]["eval_count"] == 0
    check = events[-1]["verification"]
    assert check["method"] == "deterministic_requirement_copy"
    assert bool(check["missing_items"]) == (index in {5, 6, 8})


@pytest.mark.parametrize("question", [
    "MapleView의 실행 포트와 생성속도와 전체 시간을 알려줘.",
    "기본 모델과 화면 구성을 알려줘.",
])
def test_unsupported_combinations_not_marked_complete(question):
    assert project_source_answer(question, [TABLE]) is None


def test_compound_role_and_field_preserves_both():
    answer, _, check = project_source_answer("MapleView의 역할과 실행 포트를 알려줘.", [TABLE])
    assert "검토 UI" in answer and "5678" in answer and check["passed"] is True


def test_single_measurement_not_mislabeled_average():
    table = SearchResult("speed.md", "실측", "| 프레임워크 | 생성속도 |\n|---|---|\n| Flask | 12.61 token/s |", 1)
    answer, _ = deterministic_metric_answer("Flask 생성속도 알려줘", [table])
    assert "평균" not in answer and "12.61" in answer


def test_conflicting_measurement_rows_not_arbitrarily_selected(kb):
    rows = kb.search("Flask Streamlit 전체 시간 생성속도", 3)
    changed = [SearchResult(r.source + ".conflict", r.heading, r.text.replace("5.003초", "8.003초"), r.score)
               for r in rows if "5.003초" in r.text]
    assert changed
    answer, _, check = project_source_answer(QUESTIONS[3], rows + changed)
    assert "5.003초" not in answer and "8.003초" not in answer
    assert "Flask의 기록된 측정 행 (원문 값 충돌)" in check["missing_items"]


def test_empty_initial_summary_can_recover_evidence(kb):
    class Knowledge:
        def search(self, question, count, **kwargs):
            return [] if question == QUESTIONS[-1] else kb.search(question, count, **kwargs)
    response = rag_response(QUESTIONS[-1], "test", None, 3, Knowledge(), NoModel())
    assert "FastAPI의 역할" in response["answer"] and response["answer_status"] == "partial"
