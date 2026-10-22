"""Per-request index snapshots: filter before ranking, never after top-k."""
from collections import Counter
from contextlib import nullcontext
from copy import copy
import re


class DocumentScopeError(ValueError):
    pass


def validate_document_scope(knowledge, source):
    if source is None:
        return
    if not isinstance(source, str) or len(source) > 240 or not re.fullmatch(r"Uploads/[^/\\:]+\.md", source) or any(
        part in source for part in ("..", "\x00", "\n", "\r")
    ):
        raise DocumentScopeError("대상 문서는 업로드 목록의 정확한 문서 경로로 선택해주세요.")
    with getattr(knowledge, "lock", nullcontext()):
        if not any(c.source == source for c in knowledge.chunks):
            raise DocumentScopeError("선택한 문서를 색인에서 찾지 못했습니다. 목록과 재색인 상태를 확인해주세요.")


def scoped_knowledge(knowledge, source):
    if source is None:
        return knowledge
    with getattr(knowledge, "lock", nullcontext()):
        validate_document_scope(knowledge, source)
        scoped = copy(knowledge)
        scoped.chunks = [c for c in knowledge.chunks if c.source == source]
        scoped.document_frequency = Counter()
        for chunk in scoped.chunks:
            scoped.document_frequency.update(set(chunk.tokens))
        scoped.average_length = sum(len(c.tokens) for c in scoped.chunks) / len(scoped.chunks)
        scoped.files_indexed = 1
        dates = [c.latest_date for c in scoped.chunks if c.latest_date]
        scoped.latest_date = max(dates) if dates else None
        # Semantic vectors/cache lock stay shared, but only scoped chunks are
        # embedded/ranked. Follow-up retrieval receives this same snapshot.
        return scoped
