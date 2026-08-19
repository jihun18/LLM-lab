from __future__ import annotations

from collections.abc import Iterator

from .grounding import deterministic_metric_answer, verify_grounded_answer
from .knowledge_base import KnowledgeBase, SearchResult, build_grounded_prompt
from .ollama_client import OllamaClient


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
    verification = verify_grounded_answer(prompt, response["answer"], results)
    return {**response, "verification": verification}


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
