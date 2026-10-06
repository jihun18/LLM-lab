from fastapi.testclient import TestClient
import json
import pytest
from urllib.parse import quote

import app as fastapi_module
import flask_app as flask_module
from core.document_ingest import DocumentIngestor
from core.knowledge_base import KnowledgeBase


@pytest.mark.parametrize("framework", ["fastapi", "flask"])
@pytest.mark.parametrize("stream", [False, True])
def test_text_extraction_routes_never_call_llm(monkeypatch, framework, stream):
    module = fastapi_module if framework == "fastapi" else flask_module
    knowledge = KnowledgeBase(module.ROOT / "wiki")
    knowledge.reindex()
    monkeypatch.setattr(module, "knowledge", knowledge)
    def forbidden(*args, **kwargs):
        raise AssertionError("추출 경로에서 LLM 호출")
    monkeypatch.setattr(module.client, "chat", forbidden)
    client = TestClient(module.app) if framework == "fastapi" else module.app.test_client()
    response = client.post("/rag/chat" + ("/stream" if stream else ""),
                           json={"prompt": "자동 검증 결과 화면에 나타나는 네 가지 상태 문구를 적어주세요."})
    assert response.status_code == 200
    if stream:
        body = response.text if framework == "fastapi" else response.get_data(as_text=True)
        events = [json.loads(line) for line in body.splitlines()]
        assert "사람 검토 필요" in next(e["content"] for e in events if "content" in e)
        assert events[-1]["verification"]["method"] == "deterministic_text_extraction"
        assert events[-1]["tokens_per_second"] is None
    else:
        payload = response.json() if framework == "fastapi" else response.get_json()
        assert payload["model"] == "deterministic-text"
        assert len(payload["verification"]["items"]) == 4


def test_fastapi_exposes_expected_routes(monkeypatch):
    monkeypatch.setattr(
        fastapi_module.client,
        "health",
        lambda: {"status": "ok", "ollama_url": "local", "latency_ms": 1.0},
    )
    monkeypatch.setattr(
        fastapi_module.client,
        "list_models",
        lambda: [{"name": "qwen3:1.7b"}],
    )
    test_client = TestClient(fastapi_module.app)
    assert test_client.get("/health").json()["framework"] == "FastAPI"
    model_response = test_client.get("/models")
    assert model_response.status_code == 200
    assert model_response.json()["modes"][0]["label"] == "빠른 모드"
    assert test_client.get("/knowledge/status").status_code == 200
    assert test_client.get("/documents").status_code == 200
    home = test_client.get("/")
    assert home.status_code == 200
    assert "no-store" in home.headers["cache-control"]


def test_flask_exposes_expected_routes(monkeypatch):
    monkeypatch.setattr(
        flask_module.client,
        "health",
        lambda: {"status": "ok", "ollama_url": "local", "latency_ms": 1.0},
    )
    monkeypatch.setattr(
        flask_module.client,
        "list_models",
        lambda: [{"name": "qwen3:1.7b"}],
    )
    test_client = flask_module.app.test_client()
    assert test_client.get("/health").json["framework"] == "Flask"
    model_response = test_client.get("/models")
    assert model_response.status_code == 200
    assert model_response.json["modes"][0]["label"] == "빠른 모드"
    assert test_client.get("/knowledge/status").status_code == 200
    assert test_client.get("/documents").status_code == 200
    home = test_client.get("/")
    assert home.status_code == 200
    assert "no-store" in home.headers["cache-control"]


def test_flask_rag_uses_local_wiki(monkeypatch, tmp_path):
    monkeypatch.setattr(flask_module.client, "chat_with_sources", None)
    (tmp_path / "policy.md").write_text(
        "# 지원정책\n\n청년 AI 개발 지원금은 월 10만원이며 "
        "신청 마감일은 2026년 9월 30일이다.",
        encoding="utf-8",
    )
    local_knowledge = KnowledgeBase(tmp_path)
    local_knowledge.reindex()
    monkeypatch.setattr(flask_module, "knowledge", local_knowledge)
    monkeypatch.setattr(
        flask_module.client,
        "chat",
        lambda prompt, model, system: {
            "model": model,
            "answer": "청년 AI 개발 지원금은 월 10만원이며 신청 마감일은 "
            "2026년 9월 30일입니다.\n[출처: policy.md#지원정책]",
            "elapsed_seconds": 0.1,
            "tokens_per_second": 10.0,
            "eval_count": 10,
        },
    )

    response = flask_module.app.test_client().post(
        "/rag/chat",
        json={"prompt": "청년 AI 개발 지원금은 얼마이고 신청 마감일은 언제야?"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert "10만원" in payload["answer"]
    assert "2026년 9월 30일" in payload["answer"]
    assert payload["sources"][0]["source"] == "policy.md"
    assert payload["verification"]["passed"] is True


def test_document_upload_reindexes_local_wiki(monkeypatch, tmp_path):
    local_knowledge = KnowledgeBase(tmp_path)
    local_knowledge.reindex()
    monkeypatch.setattr(fastapi_module, "documents", DocumentIngestor(tmp_path))
    monkeypatch.setattr(fastapi_module, "knowledge", local_knowledge)
    test_client = TestClient(fastapi_module.app)

    response = test_client.post(
        "/documents/upload",
        headers={"X-Filename": quote("지역 지원.txt")},
        content="지역 지원금은 월 10만원입니다.".encode(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["knowledge"]["files_indexed"] == 1
    assert local_knowledge.search("지역 지원금")
