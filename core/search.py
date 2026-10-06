"""Local, lazy embedding search with a content-addressed disk cache."""
from hashlib import sha256
import json
import math
from pathlib import Path
from threading import RLock

from .knowledge_base import KnowledgeBase, SearchResult
from .ollama_client import OllamaClient, OllamaError

SEARCH_MODES = ("bm25", "semantic", "hybrid")


def normalized(vector):
    norm = math.sqrt(sum(float(x) ** 2 for x in vector))
    if not norm or not math.isfinite(norm):
        raise OllamaError("유효하지 않은 임베딩 벡터입니다.")
    return [float(x) / norm for x in vector]


class SearchKnowledge(KnowledgeBase):
    def __init__(self, root: Path, client=None, model="nomic-embed-text", threshold=0.65):
        super().__init__(root)
        self.embedding_client = client or OllamaClient()
        self.embedding_model = model
        self.threshold = threshold
        self.cache_path = self.root.parent / ".search-cache" / "embeddings.json"
        self.vectors = {}
        self.lock = RLock()
        try:
            self.vectors = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def reindex(self):
        with self.lock:
            return super().reindex()

    def status(self):
        return {**super().status(), "search_modes": list(SEARCH_MODES),
                "embedding_model": self.embedding_model, "semantic_threshold": self.threshold}

    def _key(self, text):
        return sha256((self.embedding_model + "\n" + text).encode()).hexdigest()

    def _semantic(self, query, top_k):
        texts = [f"search_document: {c.source}\n{c.heading}\n{c.text}" for c in self.chunks]
        missing = list(dict.fromkeys(t for t in texts if self._key(t) not in self.vectors))
        for offset in range(0, len(missing), 8):
            batch = missing[offset:offset + 8]
            vectors = self.embedding_client.embed(batch, self.embedding_model)
            self.vectors.update({self._key(t): normalized(v) for t, v in zip(batch, vectors)})
        if missing:
            self.cache_path.parent.mkdir(exist_ok=True)
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.vectors), encoding="utf-8")
            temporary.replace(self.cache_path)
        query_vector = normalized(self.embedding_client.embed(
            [f"search_query: {query}"], self.embedding_model)[0])
        scored = []
        for chunk, text in zip(self.chunks, texts):
            vector = self.vectors[self._key(text)]
            if len(vector) != len(query_vector):
                raise OllamaError("임베딩 차원이 달라 .search-cache를 재구축해야 합니다.")
            score = sum(a * b for a, b in zip(vector, query_vector))
            if score >= self.threshold:
                scored.append(SearchResult(chunk.source, chunk.heading, chunk.text, round(score, 6)))
        return sorted(scored, key=lambda r: r.score, reverse=True)[:top_k]

    def search(self, query, top_k=3, min_relative_score=0.3, mode="bm25"):
        if mode not in SEARCH_MODES:
            raise ValueError("검색 방식은 bm25, semantic, hybrid 중 하나여야 합니다.")
        with self.lock:
            if mode == "bm25":
                return super().search(query, top_k, min_relative_score)
            if not query.strip() or not self.chunks:
                return []
            top_k = max(1, min(top_k, 5))
            semantic = self._semantic(query, 5)
            if mode == "semantic":
                return semantic[:top_k]
            lexical = super().search(query, 5, min_relative_score)
            fused = {}
            for ranking in (lexical, semantic):
                for rank, result in enumerate(ranking, 1):
                    key = (result.source, result.heading)
                    previous = fused.get(key)
                    score = (previous.score if previous else 0) + 1 / (60 + rank)
                    fused[key] = SearchResult(result.source, result.heading, result.text, score)
            return sorted(fused.values(), key=lambda r: r.score, reverse=True)[:top_k]
