from __future__ import annotations

from collections.abc import Iterator
import re
import time

from .grounding import deterministic_metric_answer, verify_grounded_answer
from .knowledge_base import KnowledgeBase, SearchResult, build_grounded_prompt, tokenize
from .ollama_client import OllamaClient
from .source_extraction import deterministic_text_answer


SOURCE_CITATION_PATTERN = re.compile(r"\[출처:\s*([^\]#]+)#([^\]]+)\]")
NO_EVIDENCE_ANSWER = "Wiki에서 근거를 찾지 못했습니다."
BLOCKED_SOURCE_ANSWER = (
    "Wiki 근거와 연결되지 않은 답변을 차단했습니다. "
    "Wiki를 재색인하거나 질문을 더 구체적으로 입력해주세요."
)


def validate_source_citations(
    answer: str, results: list[SearchResult]
) -> tuple[str, dict | None]:
    answer = re.sub(r"(?m)^\s*(?:출처|근거)\s*:\s*(?=\[출처:)", "", answer)
    seen_citations: set[str] = set()

    def keep_first_citation(match: re.Match) -> str:
        normalized = match.group(0).lower()
        if normalized in seen_citations:
            return ""
        seen_citations.add(normalized)
        return match.group(0)

    answer = SOURCE_CITATION_PATTERN.sub(keep_first_citation, answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer).strip()
    if NO_EVIDENCE_ANSWER in answer:
        sanitized = SOURCE_CITATION_PATTERN.sub("", answer).strip()
        substantive = sanitized.replace(NO_EVIDENCE_ANSWER, "").strip()
        if len(tokenize(substantive)) >= 3:
            answer = substantive
        else:
            return sanitized, {
                "passed": False,
                "method": "model_abstained",
                "issues": ["검색 결과에서 질문의 답을 뒷받침하는 근거를 찾지 못했습니다."],
            }

    citations = SOURCE_CITATION_PATTERN.findall(answer)

    expected = {
        (result.source.strip().lower(), result.heading.strip().lower())
        for result in results
    }
    supplied = {
        (source.strip().lower(), heading.strip().lower())
        for source, heading in citations
    }
    if not supplied:
        if results:
            answer_tokens = set(tokenize(answer))
            primary = max(
                results,
                key=lambda result: len(
                    answer_tokens & set(tokenize(f"{result.heading}\n{result.text}"))
                ),
            )
            answer = (
                f"{answer.rstrip()}\n\n"
                f"[출처: {primary.source}#{primary.heading}]"
            )
            return answer, None
        return BLOCKED_SOURCE_ANSWER, {
            "passed": False,
            "method": "missing_source_citation",
            "issues": ["검색 결과와 모델 답변에 Wiki 출처가 없습니다."],
        }

    invalid = sorted(supplied - expected)
    if invalid:
        results_by_source = {
            result.source.strip().lower(): result for result in results
        }
        cited_retrieved_sources = [
            results_by_source[source]
            for source, _heading in invalid
            if source in results_by_source
        ]
        if len(cited_retrieved_sources) == len(invalid):
            primary = cited_retrieved_sources[0]
            answer = SOURCE_CITATION_PATTERN.sub("", answer).strip()
            answer = (
                f"{answer}\n\n[출처: {primary.source}#{primary.heading}]"
            )
            return answer, None
        invalid_text = ", ".join(f"{source}#{heading}" for source, heading in invalid)
        return BLOCKED_SOURCE_ANSWER, {
            "passed": False,
            "method": "invalid_source_citation",
            "issues": [f"검색된 Wiki 근거와 일치하지 않는 출처: {invalid_text}"],
        }
    return answer, None


def source_payload(results: list[SearchResult]) -> list[dict]:
    return [
        {
            "source": result.source,
            "heading": result.heading,
            "score": result.score,
            "excerpt": result.text[:240],
        }
        for result in results
    ]


def grounded_response(
    prompt: str,
    model: str,
    system: str | None,
    results: list[SearchResult],
    client: OllamaClient,
    context_mode: str = "full",
    allow_text_extraction: bool = True,
) -> dict:
    from .evidence_scope import unsupported_query_anchors
    missing = unsupported_query_anchors(prompt, results)
    if missing:
        return {"model": model, "answer": "Wiki에서 질문에 지정된 모델 또는 연도의 근거를 찾지 못했습니다.",
                "sources": [], "elapsed_seconds": 0, "tokens_per_second": None, "eval_count": 0,
                "verification": {"passed": False, "method": "no_evidence",
                                 "issues": ["질문 조건의 근거가 없습니다: " + ", ".join(missing)]}}
    started = time.perf_counter()
    text_extraction = deterministic_text_answer(prompt, results) if allow_text_extraction else None
    if text_extraction:
        answer, verification = text_extraction
        return {"model": "deterministic-text", "requested_model": model,
                "execution_path": "deterministic_text", "answer": answer,
                "elapsed_seconds": time.perf_counter() - started,
                "tokens_per_second": None, "eval_count": 0,
                "sources": source_payload(results[:1]), "verification": verification}
    deterministic = deterministic_metric_answer(prompt, results)
    if deterministic:
        answer, verification = deterministic
        return {
            "model": "deterministic-table",
            "answer": answer,
            "elapsed_seconds": 0,
            "tokens_per_second": None,
            "eval_count": 0,
            "verification": verification,
        }

    from .context_budget import select_context
    original_count = len(results)
    results = select_context(prompt, results, context_mode)
    grounded_prompt = build_grounded_prompt(prompt, results)
    response = client.chat(grounded_prompt, model, system)
    answer, citation_verification = validate_source_citations(
        response["answer"], results
    )
    verification = citation_verification or verify_grounded_answer(
        prompt, answer, results
    )
    return {**response, "answer": answer, "verification": verification,
            "sources": source_payload(results),
            "context": {"mode": context_mode, "retrieved_count": original_count,
                        "sent_count": len(results), "prompt_characters": len(grounded_prompt)}}


def rag_response(
    prompt: str,
    model: str,
    system: str | None,
    top_k: int,
    knowledge: KnowledgeBase,
    client: OllamaClient,
    search_mode: str = "bm25",
) -> dict:
    started = time.perf_counter()
    results = (knowledge.search(prompt, top_k) if search_mode == "bm25"
               else knowledge.search(prompt, top_k, mode=search_mode))
    search_seconds = time.perf_counter() - started
    sources = source_payload(results)
    if not results:
        return {
            "model": model,
            "search_mode": search_mode,
            "search_seconds": round(search_seconds, 3),
            "answer": "Wiki에서 관련 근거를 찾지 못했습니다.",
            "sources": [],
            "elapsed_seconds": round(search_seconds, 3),
            "tokens_per_second": None,
            "eval_count": 0,
            "verification": {
                "passed": False,
                "method": "no_evidence",
                "issues": ["질문과 관련된 Wiki 근거가 없습니다."],
            },
        }

    response = grounded_response(prompt, model, system, results, client)
    return {**response, "sources": response.get("sources", sources), "search_mode": search_mode,
            "search_seconds": round(search_seconds, 3),
            "elapsed_seconds": round(response["elapsed_seconds"] + search_seconds, 3)}


def rag_stream_events(
    prompt: str,
    model: str,
    system: str | None,
    top_k: int,
    knowledge: KnowledgeBase,
    client: OllamaClient,
    search_mode: str = "bm25",
) -> Iterator[dict]:
    response = rag_response(prompt, model, system, top_k, knowledge, client, search_mode)
    yield {"sources": response["sources"]}
    yield {
        "done": False,
        "content": response["answer"],
        "verification": response.get("verification"),
    }
    yield {
        "done": True,
        "search_mode": search_mode,
        "search_seconds": response["search_seconds"],
        "elapsed_seconds": response["elapsed_seconds"],
        "tokens_per_second": response["tokens_per_second"],
        "eval_count": response["eval_count"],
        "verification": response.get("verification"),
    }
