import pytest

from core.document_scope import scoped_knowledge
from core.knowledge_base import KnowledgeBase, SearchResult
from core.rag_service import rag_response, rag_stream_events
from core.submission_facts import supplement_submission_evidence


QUESTION = "처음 접수할 때 준비해야 하는 파일과 추가 자료를 빠짐없이 알려줘."
BODY = "1 신청 방법\n❍ 제출 서류: 제안서 및 실험계획서\n- 연구윤리 동의 후 재료 사용 명세 제출"


class NoModel:
    def chat(self, *a, **kw): pytest.fail("no model generation expected")


@pytest.fixture
def knowledge(tmp_path):
    (tmp_path / "Uploads").mkdir()
    (tmp_path / "Uploads" / "research.md").write_text("# 연구 공모\n\n## PDF 2페이지\n\n" + BODY, encoding="utf-8")
    (tmp_path / "guide.md").write_text("# 파일 추가 자료 접수할\n\n앱 화면 파일 업로드 설명", encoding="utf-8")
    kb = KnowledgeBase(tmp_path)
    kb.reindex()
    return kb


@pytest.mark.parametrize("stream", [False, True])
def test_empty_paraphrase_search_recovers_selected_submission_section(knowledge, stream):
    scoped = scoped_knowledge(knowledge, "Uploads/research.md")
    assert scoped.search(QUESTION) == []
    if stream:
        events = list(rag_stream_events(QUESTION, "test", None, 3, knowledge, NoModel(), source="Uploads/research.md"))
        answer, sources = events[1]["content"], events[0]["sources"]
        assert events[-1]["eval_count"] == 0 and events[-1]["document_scope"]["source"] == "Uploads/research.md"
    else:
        response = rag_response(QUESTION, "test", None, 3, knowledge, NoModel(), source="Uploads/research.md")
        answer, sources = response["answer"], response["sources"]
        assert response["answer_status"] == "partial" and response["eval_count"] == 0
        assert 0 < len(response["retrieval_followups"]) <= 2
        assert all(t["reason"] == "selected_submission_empty_search" for t in response["retrieval_followups"])
    assert "재료 사용 명세" in answer and "연구윤리" in answer
    assert "앱 화면" not in answer and all(r["source"] == "Uploads/research.md" for r in sources)


@pytest.mark.parametrize("mode", ["bm25", "semantic", "hybrid"])
def test_followup_budget_mode_dedup_and_source_filter(mode):
    selected = SearchResult("Uploads/research.md", "PDF 2페이지", BODY, 1)
    other = SearchResult("guide.md", "파일", "앱 설명", 999)
    class Knowledge:
        selected_document_source = selected.source
        def __init__(self): self.calls = []
        def search(self, query, count, **kw):
            self.calls.append((query, count, kw))
            return [other, selected, selected]
    kb = Knowledge()
    hits, trace = supplement_submission_evidence(QUESTION, [], kb, mode)
    assert hits == [selected] and len(trace) == 2
    assert all(count == 3 and kw == ({} if mode == "bm25" else {"mode": mode}) for _, count, kw in kb.calls)
    assert sum(t["added_chunks"] for t in trace) == 1


def test_recovery_not_enabled_for_unscoped_or_unrelated_queries():
    class Knowledge:
        def search(self, *a, **kw): pytest.fail("must not expand this query")
    assert supplement_submission_evidence(QUESTION, [], Knowledge(), "bm25") == ([], [])
    kb = Knowledge()
    kb.selected_document_source = "Uploads/research.md"
    assert supplement_submission_evidence("파일 업로드 화면을 구현해줘.", [], kb, "bm25") == ([], [])
    initial = [SearchResult(kb.selected_document_source, "PDF 2페이지", BODY, 1)]
    assert supplement_submission_evidence(QUESTION, initial, kb, "bm25") == (initial, [])


def test_no_submission_section_remains_no_evidence(knowledge):
    path = knowledge.root / "Uploads" / "research.md"
    path.write_text("# 다른 내용\n\n관련 없는 과학 이야기", encoding="utf-8")
    knowledge.reindex()
    response = rag_response(QUESTION, "test", None, 3, knowledge, NoModel(), source="Uploads/research.md")
    assert response["sources"] == [] and response["verification"]["passed"] is False
    assert len(response["retrieval_followups"]) == 2


def test_original_year_guard_survives_recovery(knowledge):
    question = "2047년 " + QUESTION
    response = rag_response(question, "test", None, 3, knowledge, NoModel(), source="Uploads/research.md")
    assert response["verification"]["passed"] is False and response["sources"] == []
    assert all("2047" in t["query"] for t in response["retrieval_followups"])


def test_semantic_empty_gate_not_replaced_by_bm25():
    class Knowledge:
        selected_document_source = "Uploads/research.md"
        def search(self, query, count, **kw):
            assert kw == {"mode": "semantic"}
            return []
    hits, trace = supplement_submission_evidence(QUESTION, [], Knowledge(), "semantic")
    assert hits == [] and len(trace) == 2


@pytest.mark.parametrize("framework", ["fastapi", "flask"])
def test_api_recovery_for_selected_document(knowledge, framework, monkeypatch):
    from fastapi.testclient import TestClient
    import app
    import flask_app
    module = app if framework == "fastapi" else flask_app
    monkeypatch.setattr(module, "knowledge", knowledge)
    monkeypatch.setattr(module, "client", NoModel())
    client = TestClient(module.app) if framework == "fastapi" else module.app.test_client()
    response = client.post("/rag/chat", json={"prompt": QUESTION, "source": "Uploads/research.md"})
    assert response.status_code == 200
    data = response.json() if framework == "fastapi" else response.get_json()
    assert "재료 사용 명세" in data["answer"] and data["eval_count"] == 0
    assert data["document_scope"]["source"] == "Uploads/research.md"
    assert data["retrieval_followups"]
