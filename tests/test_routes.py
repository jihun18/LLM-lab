from fastapi.testclient import TestClient
from urllib.parse import quote

import app as fastapi_module
import flask_app as flask_module
from core.document_ingest import DocumentIngestor
from core.knowledge_base import KnowledgeBase


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
    assert test_client.get("/models").status_code == 200
    assert test_client.get("/knowledge/status").status_code == 200
    assert test_client.get("/documents").status_code == 200
    assert test_client.get("/").status_code == 200


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
    assert test_client.get("/models").status_code == 200
    assert test_client.get("/").status_code == 200


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
