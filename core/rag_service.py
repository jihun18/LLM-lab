from __future__ import annotations

from collections.abc import Iterator
import re

from .grounding import deterministic_metric_answer, verify_grounded_answer
from .knowledge_base import KnowledgeBase, SearchResult, build_grounded_prompt
from .ollama_client import OllamaClient


SOURCE_CITATION_PATTERN = re.compile(r"\[출처:\s*([^\]#]+)#([^\]]+)\]")
NO_EVIDENCE_ANSWER = "Wiki에서 근거를 찾지 못했습니다."
BLOCKED_SOURCE_ANSWER = (
    "Wiki 근거와 연결되지 않은 답변을 차단했습니다. "
    "Wiki를 재색인하거나 질문을 더 구체적으로 입력해주세요."
)


def validate_source_citations(
    answer: str, results: list[SearchResult]
) -> tuple[str, dict | None]:
    answer = re.sub(r"(?m)^\s*출처\s*:\s*(?=\[출처:)", "", answer)
    citations = SOURCE_CITATION_PATTERN.findall(answer)
    if NO_EVIDENCE_ANSWER in answer:
        sanitized = SOURCE_CITATION_PATTERN.sub("", answer).strip()
        return sanitized, {
            "passed": False,
            "method": "model_abstained",
            "issues": ["검색 결과에서 질문의 답을 뒷받침하는 근거를 찾지 못했습니다."],
        }

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
            primary = results[0]
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
) -> dict:
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

    grounded_prompt = build_grounded_prompt(prompt, results)
    response = client.chat(grounded_prompt, model, system)
    answer, citation_verification = validate_source_citations(
        response["answer"], results
    )
    verification = citation_verification or verify_grounded_answer(
        prompt, answer, results
    )
    return {**response, "answer": answer, "verification": verification}


def rag_response(
    prompt: str,
    model: str,
    system: str | None,
    top_k: int,
    knowledge: KnowledgeBase,
    client: OllamaClient,
) -> dict:
    results = knowledge.search(prompt, top_k)
    sources = source_payload(results)
    if not results:
        return {
            "model": model,
            "answer": "Wiki에서 관련 근거를 찾지 못했습니다.",
            "sources": [],
            "elapsed_seconds": 0,
            "tokens_per_second": None,
            "eval_count": 0,
            "verification": {
                "passed": False,
                "method": "no_evidence",
                "issues": ["질문과 관련된 Wiki 근거가 없습니다."],
            },
        }

    response = grounded_response(prompt, model, system, results, client)
    return {**response, "sources": sources}


def rag_stream_events(
    prompt: str,
    model: str,
    system: str | None,
    top_k: int,
    knowledge: KnowledgeBase,
    client: OllamaClient,
) -> Iterator[dict]:
    response = rag_response(prompt, model, system, top_k, knowledge, client)
    yield {"sources": response["sources"]}
    yield {
        "done": False,
        "content": response["answer"],
        "verification": response.get("verification"),
    }
    yield {
        "done": True,
        "elapsed_seconds": response["elapsed_seconds"],
        "tokens_per_second": response["tokens_per_second"],
        "eval_count": response["eval_count"],
        "verification": response.get("verification"),
    }
