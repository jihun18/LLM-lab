from __future__ import annotations

from collections.abc import Iterator
import re
import json
import time

from .grounding import deterministic_metric_answer, verify_grounded_answer
from .knowledge_base import KnowledgeBase, SearchResult, build_grounded_prompt, tokenize
from .ollama_client import OllamaClient
from .source_extraction import deterministic_text_answer
from .text_contracts import verify_text_contracts
from .table_comparison import deterministic_role_comparison


SOURCE_CITATION_PATTERN = re.compile(r"\[출처:\s*([^\]#]+)#([^\]]+)\]")
SOURCE_ID_PATTERN = re.compile(r"\[출처:\s*근거\s*(\d+)\s*\]")
SOURCE_ID_TOKEN = re.compile(r"\[출처:\s*근거[^\]]*\]")
NO_EVIDENCE_ANSWER = "Wiki에서 근거를 찾지 못했습니다."
BLOCKED_SOURCE_ANSWER = (
    "Wiki 근거와 연결되지 않은 답변을 차단했습니다. "
    "Wiki를 재색인하거나 질문을 더 구체적으로 입력해주세요."
)


def validate_source_citations(
    answer: str, results: list[SearchResult], require_explicit: bool = False,
) -> tuple[str, dict | None]:
    id_tokens = SOURCE_ID_TOKEN.findall(answer)
    for token in id_tokens:
        match = SOURCE_ID_PATTERN.fullmatch(token)
        if not match or not 1 <= int(match.group(1)) <= len(results):
            return BLOCKED_SOURCE_ANSWER, {
                "passed": False, "method": "invalid_source_id",
                "issues": ["모델이 선택한 근거 번호가 제공된 범위에 없습니다."],
            }
    def resolve_id(match: re.Match) -> str:
        result = results[int(match.group(1)) - 1]
        return f"[출처: {result.source}#{result.heading}]"
    answer = SOURCE_ID_PATTERN.sub(resolve_id, answer)
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
        if results and not require_explicit:
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
            "issues": ["모델 답변에 명시적으로 선택한 Wiki 출처가 없습니다."],
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
        if not require_explicit and len(cited_retrieved_sources) == len(invalid):
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


def memory_guard_response(prompt, model, results):
    from .memory_requirements import memory_fallback
    guarded = memory_fallback(prompt, results)
    if guarded is None:
        return None
    answer, used, verification = guarded
    return {"model": "deterministic-memory-guard", "requested_model": model,
            "execution_path": "memory_requirements_guard", "answer": answer,
            "answer_status": "partial" if used else "blocked",
            "sources": source_payload(used), "elapsed_seconds": 0,
            "tokens_per_second": None, "eval_count": 0, "verification": verification}


def role_conflict_response(prompt, model, results):
    from .query_requirements import role_conflicts
    conflicts = role_conflicts(prompt, results)
    if not conflicts:
        return None
    labels = [name + "의 역할 (원문 값 충돌)" for name in conflicts]
    return {"model": "deterministic-role-guard", "requested_model": model,
            "execution_path": "role_conflict_guard", "answer_status": "blocked",
            "answer": "검색된 표와 목록의 역할 표현이 달라 임의 선택하지 않았습니다.\n" + "\n".join("- " + label for label in labels) + "\n원문 표현의 의미 차이는 별도 검토가 필요하며 질문의 다른 요구도 확인하지 못했습니다.",
            "sources": [], "elapsed_seconds": 0, "eval_count": 0, "tokens_per_second": None,
            "verification": {"passed": False, "method": "role_conflict_guard",
                             "display_label": "역할 원문 값 충돌 · 임의 선택 안 함", "issues": labels}}


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
    conflict_guard = role_conflict_response(prompt, model, results)
    if conflict_guard:
        return conflict_guard
    # Applies even to frozen-context calls with extraction disabled, unknown
    # role paraphrases, one target, and unsupported target naming formats.
    guarded = memory_guard_response(prompt, model, results)
    if guarded:
        return guarded
    from .query_requirements import role_requirements, requirements_notice, missing_answer_items
    requirements = role_requirements(prompt, results)
    if requirements and requirements["missing"]:
        return {"model": model, "execution_path": "requirements_abstention",
                "answer": requirements_notice(requirements), "sources": source_payload(results),
                "elapsed_seconds": 0, "tokens_per_second": None, "eval_count": 0,
                "verification": {"passed": False, "method": "missing_query_requirements",
                                 "requirements": requirements,
                                 "issues": ["부족한 요구 근거: " + item for item in requirements["missing"]]}}
    comparison = deterministic_role_comparison(prompt, results) if allow_text_extraction else None
    if comparison:
        answer, verification = comparison
        selected = results[verification["source_index"]]
        return {"model": "deterministic-comparison", "requested_model": model,
                "execution_path": "deterministic_role_comparison", "answer": answer,
                "elapsed_seconds": time.perf_counter() - started,
                "tokens_per_second": None, "eval_count": 0,
                "sources": source_payload([selected]), "verification": verification}
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
    structured = callable(getattr(client, "chat_with_sources", None))
    response = (client.chat_with_sources(grounded_prompt, model, system, len(results))
                if structured else client.chat(grounded_prompt, model, system))
    selected_results = results
    if structured:
        try:
            data = json.loads(response["answer"])
            if not isinstance(data, dict) or set(data) != {"answer", "source_id"}:
                raise ValueError("fields")
            if not isinstance(data["answer"], str) or not data["answer"].strip():
                raise ValueError("answer")
            if "[출처:" in data["answer"]:
                raise ValueError("citation_in_body")
            source_id = data["source_id"]
            if type(source_id) is not int or not 0 <= source_id <= len(results):
                raise ValueError("source_id")
            if source_id == 0 and data["answer"].strip() != NO_EVIDENCE_ANSWER:
                raise ValueError("unselected")
            response = {**response, "answer": data["answer"] + (f"\n[출처: 근거 {source_id}]" if source_id else "")}
            selected_results = [results[source_id - 1]] if source_id else []
        except (ValueError, TypeError, KeyError):
            return {**response, "answer": BLOCKED_SOURCE_ANSWER, "sources": [],
                    "verification": {"passed": False, "method": "invalid_structured_citation",
                                     "issues": ["답변 형식 또는 명시적 근거 번호가 올바르지 않습니다."]}}
    answer, citation_verification = validate_source_citations(
        response["answer"], results, require_explicit=True
    )
    if not structured and citation_verification is None:
        cited = {(source.strip().lower(), heading.strip().lower())
                 for source, heading in SOURCE_CITATION_PATTERN.findall(answer)}
        selected_results = [result for result in results
                            if (result.source.lower(), result.heading.lower()) in cited]
    verification = citation_verification or verify_grounded_answer(
        prompt, answer, selected_results
    )
    # Selection proves citation identity, not the answer's meaning. Explicit
    # role contradictions elsewhere in PROVIDED evidence must still be flagged.
    contract = verify_text_contracts(prompt, answer, results)
    if citation_verification is None and contract and contract["passed"] is False:
        contract["selected_source_verification"] = verification
        verification = contract
    selected_requirements = (role_requirements(prompt, selected_results, requirements["entities"])
                             if requirements else None)
    if (citation_verification is None and selected_requirements and selected_requirements["missing"]
            and verification.get("passed") is not False):
        verification = {"passed": False, "method": "selected_source_requirements_missing",
                        "requirements": selected_requirements, "previous_verification": verification,
                        "issues": ["선택 출처의 요구 근거 부족: " + item for item in selected_requirements["missing"]]}
    omissions = missing_answer_items(answer, requirements) if requirements else []
    if citation_verification is None and omissions and verification.get("passed") is not False:
        verification = {"passed": False, "method": "answer_requirements_missing",
                        "previous_verification": verification,
                        "issues": ["답변 요구 누락: " + item for item in omissions]}
    # Never stream an answer already known to fail verification. Do not include
    # the rejected body in normal API responses or browser events.
    blocked = verification.get("passed") is False
    if blocked and citation_verification is None:
        answer = "답변이 Wiki 근거 검증을 통과하지 못해 표시하지 않았습니다. 질문을 항목별로 나누거나 근거 문서를 보완해주세요."
    if not blocked and verification.get("passed") is True and verification.get("method") in {"structured_claim_verification", "metric_unit_validation"}:
        verification = {"passed": True, "method": "numeric_subset_semantic_review_needed",
                        "display_label": "수치 근거만 확인 · 질문 전체 의미는 사람 검토 필요",
                        "numeric_verification": verification, "issues": [],
                        "scope": "단위 수치의 근거 일치만 확인. 질문 전체 완전성·서술 의미는 미검증."}
    return {**response, "answer": answer, "verification": verification,
            "answer_status": "blocked" if blocked else "review_required" if verification.get("passed") is None or verification.get("method") == "numeric_subset_semantic_review_needed" else "verified",
            "sources": source_payload(selected_results),
            "context": {"mode": context_mode, "retrieved_count": original_count,
                        "citation_format": "structured_json" if structured else "inline",
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
    from .requirement_retrieval import supplement_role_evidence, requirement_source_answer
    from .evidence_scope import unsupported_query_anchors
    trace = []
    # Frozen-context/model comparison calls grounded_response directly, so
    # follow-up retrieval cannot silently alter their controlled evidence.
    if results and not unsupported_query_anchors(prompt, results):
        results, trace = supplement_role_evidence(prompt, results, knowledge, search_mode)
        copied = requirement_source_answer(prompt, results)
        if copied:
            answer, used, verification = copied
            elapsed = round(time.perf_counter() - started, 3)
            return {"model": "deterministic-requirements", "requested_model": model,
                    "execution_path": "deterministic_requirement_copy", "answer": answer,
                    "answer_status": "partial" if verification["missing_items"] else "source_copied",
                    "sources": source_payload(used), "verification": verification,
                    "search_mode": search_mode, "retrieval_followups": trace,
                    "search_seconds": elapsed, "elapsed_seconds": elapsed,
                    "eval_count": 0, "tokens_per_second": None}
    # Fallback precedes no-evidence and generic deterministic/model paths.
    # Don't let an unsupported requested model/year bypass its anchor guard.
    if not unsupported_query_anchors(prompt, results):
        conflict_guard = role_conflict_response(prompt, model, results)
        if conflict_guard:
            return {**conflict_guard, "search_mode": search_mode, "retrieval_followups": trace,
                    "search_seconds": round(time.perf_counter() - started, 3),
                    "elapsed_seconds": round(time.perf_counter() - started, 3)}
        guarded = memory_guard_response(prompt, model, results)
        if guarded:
            return {**guarded, "search_mode": search_mode, "retrieval_followups": trace,
                    "search_seconds": round(time.perf_counter() - started, 3),
                    "elapsed_seconds": round(time.perf_counter() - started, 3)}
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
            "retrieval_followups": trace,
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
