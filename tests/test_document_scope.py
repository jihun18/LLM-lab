from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from core.document_scope import DocumentScopeError, scoped_knowledge, validate_document_scope
from core.knowledge_base import KnowledgeBase
from core.rag_service import rag_response, rag_stream_events
from core.search import SearchKnowledge


class NoModel:
    def chat(self, *a, **kw): pytest.fail("unexpected model generation")


@pytest.fixture
def kb(tmp_path):
    (tmp_path / "Uploads").mkdir()
    (tmp_path / "Uploads" / "selected.md").write_text(
        "# 연구 공모\n\n## PDF 2페이지\n\n1 제출 서류\n❍ 제출 서류: 연구제안서 및 재료명세\n\n## PDF 3페이지\n\n연구 실험 안내",
        encoding="utf-8")
    (tmp_path / "Uploads" / "other.md").write_text("# 다른 공모\n\n다른문서전용단어만", encoding="utf-8")
    (tmp_path / "guide.md").write_text("# 제출 서류\n\n제출 서류 파일 업로드 화면 파일 파일 파일", encoding="utf-8")
    knowledge = KnowledgeBase(tmp_path)
    knowledge.reindex()
    return knowledge


def test_filter_before_ranking_and_original_index_stays_intact(kb):
    original_chunks = list(kb.chunks)
    original_frequency = kb.document_frequency.copy()
    scoped = scoped_knowledge(kb, "Uploads/selected.md")
    assert all(c.source == "Uploads/selected.md" for c in scoped.chunks)
    assert scoped.search("제출 서류", 1)[0].source == "Uploads/selected.md"
    assert not scoped.search("다른문서전용단어만")
    assert kb.chunks == original_chunks and kb.document_frequency == original_frequency
    assert kb.search("다른문서전용단어만")


@pytest.mark.parametrize("source", ["", "../outside.md", "Uploads/../guide.md", "C:/private.md", "Uploads\\selected.md", "guide.md", "Uploads/missing.md", "Uploads/selected.md\n", "Uploads/a/b.md", 123])
def test_invalid_scope_never_falls_back_to_all(kb, source):
    with pytest.raises(DocumentScopeError):
        rag_response("제출 서류", "test", None, 3, kb, NoModel(), source=source)


def test_scoped_no_evidence_does_not_use_another_document(kb):
    response = rag_response("다른문서전용단어만", "test", None, 3, kb, NoModel(), source="Uploads/selected.md")
    assert response["sources"] == [] and response["verification"]["passed"] is False
    assert response["document_scope"]["source"] == "Uploads/selected.md"


def test_copy_and_stream_follow_same_scope(kb):
    events = list(rag_stream_events("제출 서류 알려줘", "test", None, 3, kb, NoModel(), source="Uploads/selected.md"))
    assert "재료명세" in events[1]["content"]
    assert all(s["source"] == "Uploads/selected.md" for s in events[0]["sources"])
    assert events[0]["document_scope"]["source"] == events[-1]["document_scope"]["source"] == "Uploads/selected.md"


def test_followup_retrieval_cannot_escape_document(kb):
    (kb.root / "Uploads" / "selected.md").write_text("# 도구\n\n| 항목 | ToolA | ToolB |\n|---|---|---|\n| 역할 | 검색 API | 확인 UI |", encoding="utf-8")
    (kb.root / "guide.md").write_text("# 속도\n\n| 도구 | 생성속도 |\n|---|---|\n| ToolA | 99 token/s |\n| ToolB | 88 token/s |", encoding="utf-8")
    kb.reindex()
    response = rag_response("ToolA와 ToolB의 역할과 속도를 알려줘.", "test", None, 3, kb, NoModel(), source="Uploads/selected.md")
    assert "99" not in response["answer"] and "88" not in response["answer"]
    assert response["retrieval_followups"]
    assert all(s["source"] == "Uploads/selected.md" for s in response["sources"])


@pytest.mark.parametrize("mode", ["bm25", "semantic", "hybrid"])
def test_all_search_modes_apply_scope_before_search(kb, mode):
    class Embedder:
        def __init__(self): self.inputs = []
        def embed(self, texts, model):
            self.inputs.extend(texts)
            return [[1, 0] for _ in texts]
    embedder = Embedder()
    knowledge = SearchKnowledge(kb.root, embedder, threshold=0)
    knowledge.reindex()
    scoped = scoped_knowledge(knowledge, "Uploads/selected.md")
    results = scoped.search("제출 서류", 1, mode=mode)
    assert results and all(r.source == "Uploads/selected.md" for r in results)
    assert not any("다른문서전용" in text or "guide.md" in text for text in embedder.inputs)
    assert len(knowledge.chunks) == len(kb.chunks)


def test_simultaneous_scopes_do_not_mutate_each_other(kb):
    def search(source):
        scoped = scoped_knowledge(kb, source)
        return {c.source for c in scoped.chunks}
    sources = ["Uploads/selected.md", "Uploads/other.md"] * 3
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(search, sources))
    assert all(found == {source} for source, found in zip(sources, results))
    assert {c.source for c in kb.chunks} == {"Uploads/selected.md", "Uploads/other.md", "guide.md"}


@pytest.mark.parametrize("framework", ["fastapi", "flask"])
@pytest.mark.parametrize("stream", [False, True])
def test_api_selected_document_and_invalid_choice(kb, framework, stream, monkeypatch):
    from fastapi.testclient import TestClient
    import app
    import flask_app
    module = app if framework == "fastapi" else flask_app
    monkeypatch.setattr(module, "knowledge", kb)
    monkeypatch.setattr(module, "client", NoModel())
    client = TestClient(module.app) if framework == "fastapi" else module.app.test_client()
    endpoint = "/rag/chat/stream" if stream else "/rag/chat"
    response = client.post(endpoint, json={"prompt": "제출 서류 알려줘", "source": "Uploads/selected.md"})
    assert response.status_code == 200
    if stream:
        text = response.text if framework == "fastapi" else response.get_data(as_text=True)
        events = [json.loads(line) for line in text.splitlines()]
        assert events[-1]["document_scope"]["source"] == "Uploads/selected.md"
        assert "재료명세" in events[1]["content"]
    else:
        data = response.json() if framework == "fastapi" else response.get_json()
        assert data["document_scope"]["source"] == "Uploads/selected.md"
        assert "재료명세" in data["answer"]
    response = client.post(endpoint, json={"prompt": "제출 서류 알려줘", "source": "Uploads/missing.md"})
    assert response.status_code == 400
