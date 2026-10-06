import pytest
from core.search import SearchKnowledge


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
