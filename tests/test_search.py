import pytest
from core.search import SearchKnowledge, embedding_input
from search_calibration import choose_threshold


class FakeEmbedder:
    def __init__(self):
        self.documents = 0

    def embed(self, texts, model):
        vectors = []
        for text in texts:
            if text.startswith("search_document:"):
                self.documents += 1
            vectors.append([1, 0] if "메모리" in text or "RAM" in text else [0, 1])
        return vectors


def test_semantic_cache_and_changed_document(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    path = root / "ram.md"
    path.write_text("# 사양\n\nRAM은 16GB다.", encoding="utf-8")
    client = FakeEmbedder()
    knowledge = SearchKnowledge(root, client)
    knowledge.reindex()
    assert knowledge.search("메모리", mode="semantic")[0].source == "ram.md"
    assert not knowledge.search("없음", mode="semantic")
    assert client.documents == 1
    reloaded = SearchKnowledge(root, client)
    reloaded.reindex()
    reloaded.search("메모리", mode="semantic")
    assert client.documents == 1
    path.write_text("# 사양\n\nRAM은 32GB다.", encoding="utf-8")
    reloaded.reindex()
    assert "32GB" in reloaded.search("메모리", mode="hybrid")[0].text
    assert client.documents == 2


def test_bm25_does_not_call_embedding_service(tmp_path):
    (tmp_path / "note.md").write_text("# RAM\n\nRAM 16GB", encoding="utf-8")
    client = FakeEmbedder()
    knowledge = SearchKnowledge(tmp_path, client)
    knowledge.reindex()
    assert knowledge.search("RAM")
    assert client.documents == 0
    with pytest.raises(ValueError):
        knowledge.search("RAM", mode="unknown")


def test_model_specific_prefixes_and_cache(tmp_path):
    assert embedding_input("embeddinggemma:300m", "질문") == "task: search result | query: 질문"
    assert embedding_input("embeddinggemma:300m", "내용", "제목") == "title: 제목 | text: 내용"
    assert embedding_input("nomic-embed-text", "질문") == "search_query: 질문"
    assert SearchKnowledge(tmp_path, model="embeddinggemma:300m").cache_path != SearchKnowledge(tmp_path).cache_path


def test_hybrid_cannot_bypass_evidence_gate(tmp_path):
    (tmp_path / "note.md").write_text("# RAM\n\nRAM 16GB", encoding="utf-8")
    knowledge = SearchKnowledge(tmp_path, FakeEmbedder(), threshold=1.01)
    knowledge.reindex()
    assert knowledge.search("RAM", mode="bm25")
    assert not knowledge.search("RAM", mode="hybrid")


def test_calibration_balances_coverage_and_refusal():
    rows = [{"score": .8, "has_evidence": True}, {"score": .7, "has_evidence": True},
            {"score": .4, "has_evidence": False}, {"score": .3, "has_evidence": False}]
    result = choose_threshold(rows)
    assert .4 < result["threshold"] <= .7
    assert result["balanced_accuracy"] == 1
    with pytest.raises(ValueError):
        choose_threshold(rows[:2])
