from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
import math
import re


TOKEN_PATTERN = re.compile(r"[가-힣]+|[a-z0-9]+", re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
ISO_DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
RAG_PRIORITY_PATTERN = re.compile(r"<!--\s*rag-priority:\s*([0-9.]+)\s*-->")
LOW_SIGNAL_QUERY_TOKENS = {
    "privai",
    "wiki",
    "알려줘",
    "설명해줘",
    "무엇이야",
    "뭐야",
    "어떤",
    "각각",
}
STANDALONE_KOREAN_PARTICLES = {
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "의",
    "에",
    "도",
    "만",
    "로",
}
KOREAN_SUFFIXES = (
    "으로부터",
    "에게서",
    "에서는",
    "으로는",
    "에서도",
    "에게",
    "에서",
    "으로",
    "로는",
    "에는",
    "와는",
    "과는",
    "한다면",
    "하면서",
    "하면",
    "하는",
    "하고",
    "해서",
    "돼",
    "해",
    "이나",
    "나",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "의",
    "에",
    "도",
    "만",
    "로",
)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in TOKEN_PATTERN.findall(text):
        token = raw_token.lower()
        if token in STANDALONE_KOREAN_PARTICLES:
            continue
        tokens.append(token)
        if re.fullmatch(r"[가-힣]+", token):
            for suffix in KOREAN_SUFFIXES:
                if token.endswith(suffix) and len(token) >= len(suffix) + 2:
                    normalized = token[: -len(suffix)]
                    if normalized not in tokens:
                        tokens.append(normalized)
                    break
    return tokens


@dataclass
class Chunk:
    source: str
    heading: str
    text: str
    tokens: list[str]
    latest_date: str | None = None
    priority: float = 1.0


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
        self.latest_date: str | None = None

    def _chunks_from_markdown(self, path: Path) -> list[Chunk]:
        text = path.read_text(encoding="utf-8-sig")
        if "<!-- rag-exclude -->" in text:
            return []
        priority_match = RAG_PRIORITY_PATTERN.search(text)
        priority = float(priority_match.group(1)) if priority_match else 1.0
        relative = path.relative_to(self.root).as_posix()
        chunks: list[Chunk] = []
        heading = path.stem
        document_title = path.stem
        buffer: list[str] = []
        inside_code_block = False

        def flush() -> None:
            content = "\n".join(buffer).strip()
            if not content:
                return
            searchable = f"{document_title}\n{heading}\n{content}"
            dates = ISO_DATE_PATTERN.findall(searchable)
            chunks.append(
                Chunk(
                    source=relative,
                    heading=heading,
                    text=content,
                    tokens=tokenize(searchable),
                    latest_date=max(dates) if dates else None,
                    priority=priority,
                )
            )

        for line in text.splitlines():
            if RAG_PRIORITY_PATTERN.fullmatch(line.strip()):
                continue
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
                if len(match.group(1)) == 1:
                    document_title = heading
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
        dates = [chunk.latest_date for chunk in self.chunks if chunk.latest_date]
        self.latest_date = max(dates) if dates else None
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
        raw_query_tokens = list(dict.fromkeys(tokenize(query)))
        query_tokens = [
            token for token in raw_query_tokens if token not in LOW_SIGNAL_QUERY_TOKENS
        ] or raw_query_tokens
        if not query_tokens or not self.chunks:
            return []

        total_chunks = len(self.chunks)
        k1, b = 1.5, 0.75
        scored: list[SearchResult] = []
        for chunk in self.chunks:
            counts = Counter(chunk.tokens)
            length = len(chunk.tokens)
            score = 0.0
            matched_tokens = 0
            for token in query_tokens:
                frequency = counts[token]
                if not frequency:
                    continue
                matched_tokens += 1
                document_frequency = self.document_frequency[token]
                inverse_document_frequency = math.log(
                    1 + (total_chunks - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + k1 * (
                    1 - b + b * length / max(self.average_length, 1)
                )
                score += inverse_document_frequency * frequency * (k1 + 1) / denominator
            if len(query_tokens) >= 4 and matched_tokens < 2:
                continue
            score *= chunk.priority
            if (
                any(marker in query for marker in ("현재", "최신", "지금"))
                and self.latest_date
                and chunk.latest_date == self.latest_date
            ):
                score *= 1.5
            if any(marker in query for marker in ("이유", "까닭", "왜")) and any(
                marker in chunk.heading for marker in ("이유", "원인", "배경")
            ):
                score *= 1.5
            heading_intents = (
                ("순서", "흐름"),
                ("화면", "화면"),
                ("표시", "상태"),
            )
            for query_marker, heading_marker in heading_intents:
                if query_marker in query and heading_marker in chunk.heading:
                    score *= 1.6
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
    allowed_sources = "\n".join(
        f"- [출처: 근거 {index}]" for index, result in enumerate(results, start=1)
    )
    return (
        "아래 근거에 있는 내용만 사용하여 질문에 한국어로 답하세요. "
        "근거에 답이 없으면 'Wiki에서 근거를 찾지 못했습니다.'라고 답하세요. "
        "근거를 사용해 답변했다면 근거 없음 문장을 추가하지 마세요. "
        "근거 1을 가장 우선해서 사용하고, 근거 1만으로 답할 수 있으면 다른 근거의 내용을 섞지 마세요. "
        "일반 질문은 최대 세 문장으로 답하고 질문과 직접 관계없는 배경 설명은 생략하세요. "
        "각각의 용도나 역할 질문에는 근거의 대상과 역할 연결을 그대로 유지하세요. "
        "복합 질문은 요청 항목마다 답하거나 근거 부족을 명시하세요. 역할 목록만으로 함께 쓰는 이유나 실제 연동 구조를 추측하지 마세요. "
        "특정 개수의 상태 문구를 요구하면 문장 수 제한보다 목록 완전성을 우선하고 원문 문구를 모두 복사하세요. "
        "질문이 절차나 순서를 요구하면 근거의 단계와 핵심 용어를 빠뜨리지 마세요. "
        "절차 답변은 번호 목록을 먼저 사용하고, 중복 처리처럼 근거에 명시된 핵심 조건은 목록 뒤에 한 문장으로 적으세요. "
        "수치 비교가 이유라면 비교 대상의 수치와 단위를 함께 적으세요. "
        "해시 이름, 모델명, 수치처럼 고유한 표기는 근거의 문자열을 그대로 복사하세요. "
        "추측하거나 새로운 사실을 만들지 말고 출처는 하나만 사용하세요. "
        "출처 파일명이나 절 제목을 직접 쓰지 말고, 실제 사용한 근거 번호를 선택하세요. "
        "마지막 줄에는 아래 허용 출처 중 실제로 사용한 항목을 정확히 표시하세요.\n"
        f"[허용 출처]\n{allowed_sources}\n\n"
        f"{context_text}\n\n[질문]\n{question}"
    )
