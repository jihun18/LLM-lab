from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import math
import re


TOKEN_PATTERN = re.compile(r"[가-힣]+|[a-z0-9]+", re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


@dataclass
class Chunk:
    source: str
    heading: str
    text: str
    tokens: list[str]


@dataclass
class SearchResult:
    source: str
    heading: str
    text: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


class KnowledgeBase:
    """Small BM25 Markdown index designed for an 8GB CPU-only PC."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.chunks: list[Chunk] = []
        self.document_frequency: Counter[str] = Counter()
        self.average_length = 0.0
        self.files_indexed = 0

    def _chunks_from_markdown(self, path: Path) -> list[Chunk]:
        text = path.read_text(encoding="utf-8-sig")
        relative = path.relative_to(self.root).as_posix()
        chunks: list[Chunk] = []
        heading = path.stem
        buffer: list[str] = []
        inside_code_block = False

        def flush() -> None:
            content = "\n".join(buffer).strip()
            if not content:
                return
            searchable = f"{heading}\n{content}"
            chunks.append(
                Chunk(
                    source=relative,
                    heading=heading,
                    text=content,
                    tokens=tokenize(searchable),
                )
            )

        for line in text.splitlines():
            if line.strip().startswith("```"):
                inside_code_block = not inside_code_block
                continue
            if inside_code_block:
                continue
            match = HEADING_PATTERN.match(line)
            if match:
                flush()
                buffer = []
                heading = match.group(2).strip()
            else:
                buffer.append(line)
        flush()
        return chunks

    def reindex(self) -> dict:
        self.chunks = []
        paths = sorted(self.root.rglob("*.md")) if self.root.exists() else []
        for path in paths:
            if path.is_file():
                self.chunks.extend(self._chunks_from_markdown(path))

        self.document_frequency = Counter()
        for chunk in self.chunks:
            self.document_frequency.update(set(chunk.tokens))
        self.average_length = (
            sum(len(chunk.tokens) for chunk in self.chunks) / len(self.chunks)
            if self.chunks
            else 0.0
        )
        self.files_indexed = len(paths)
        return self.status()

    def status(self) -> dict:
        return {
            "root": str(self.root),
            "files_indexed": self.files_indexed,
            "chunks_indexed": len(self.chunks),
            "engine": "BM25 lexical search",
        }

    def search(
        self, query: str, top_k: int = 3, min_relative_score: float = 0.3
    ) -> list[SearchResult]:
        query_tokens = list(dict.fromkeys(tokenize(query)))
        if not query_tokens or not self.chunks:
            return []

        total_chunks = len(self.chunks)
        k1, b = 1.5, 0.75
        scored: list[SearchResult] = []
        for chunk in self.chunks:
            counts = Counter(chunk.tokens)
            length = len(chunk.tokens)
            score = 0.0
            for token in query_tokens:
                frequency = counts[token]
                if not frequency:
                    continue
                document_frequency = self.document_frequency[token]
                inverse_document_frequency = math.log(
                    1 + (total_chunks - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + k1 * (
                    1 - b + b * length / max(self.average_length, 1)
                )
                score += inverse_document_frequency * frequency * (k1 + 1) / denominator
            if score > 0:
                scored.append(
                    SearchResult(
                        source=chunk.source,
                        heading=chunk.heading,
                        text=chunk.text,
                        score=round(score, 4),
                    )
                )
        scored.sort(key=lambda item: item.score, reverse=True)
        if not scored:
            return []
        threshold = scored[0].score * max(0.0, min(min_relative_score, 1.0))
        relevant = [item for item in scored if item.score >= threshold]
        return relevant[: max(1, min(top_k, 5))]


def build_grounded_prompt(question: str, results: list[SearchResult]) -> str:
    contexts = []
    for index, result in enumerate(results, start=1):
        contexts.append(
            f"[근거 {index}: {result.source}#{result.heading}]\n{result.text}"
        )
    context_text = "\n\n".join(contexts)
    return (
        "아래 근거에 있는 내용만 사용하여 질문에 한국어로 답하세요. "
        "근거에 답이 없으면 'Wiki에서 근거를 찾지 못했습니다.'라고 답하세요. "
        "추측하거나 새로운 사실을 만들지 말고 마지막 줄에 사용한 근거를 "
        "[출처: 파일명#제목] 형식으로 표시하세요.\n\n"
        f"{context_text}\n\n[질문]\n{question}"
    )
