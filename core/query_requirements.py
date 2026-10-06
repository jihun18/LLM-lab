"""Bounded evidence coverage for named tools in project-role questions.

Conservative eligibility checks, not general semantic entailment.
"""
import re
from .table_comparison import _tables
from .grounding import extract_table_facts
from .role_lists import plain_role_pairs, memory_rows


def asks_project_role(question):
    compact = re.sub(r"\s+", "", question)
    return any(word in compact for word in ("역할", "용도", "업무", "무엇을담당", "담당하는일", "어떤일을"))


def role_requirements(question, results, entities=None):
    if not asks_project_role(question):
        return None
    names = entities if entities is not None else list(dict.fromkeys(re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", question)))
    names = [name for name in names if name.lower() not in {"api", "rest", "ui", "token", "s"}]
    role_names = set()
    for result in results:
        role_names.update(name.lower() for name, _ in plain_role_pairs(result.text))
        for headers, rows in _tables(result.text):
            if headers and headers[0] == "항목" and any(row[0] == "역할" for row in rows):
                role_names.update(name.lower() for name in headers[1:])
        role_names.update(name.lower() for name in re.findall(
            r"(?m)^-\s+[^:\n]+:\s*\*\*([^*\n]+)\*\*\s*$", result.text))
    # Only activate for explicit multi-tool project comparisons. Other domains
    # (model modes, processes, Korean-only entities) keep existing checks.
    if entities is None and sum(name.lower() in role_names for name in names) < 2:
        return None
    missing = [f"{name}의 역할" for name in names if name.lower() not in role_names]
    requires_speed = "속도" in question or "token/s" in question.lower()
    requires_response_speed = "응답속도" in re.sub(r"\s+", "", question)
    requires_memory = "메모리" in question or "rss" in question.lower() or "ram 사용" in question.lower()
    if requires_memory:
        for name in names:
            if not any(memory_rows(name, result) for result in results):
                missing.append(f"{name}의 대상별 메모리 사용량")
    if requires_speed:
        facts = [fact for result in results for fact in extract_table_facts(result)]
        for name in names:
            if not any(fact.unit == "token/s" and fact.label.lower() == name.lower() for fact in facts):
                missing.append(f"{name}의 표 기반 생성속도")
    if requires_response_speed:
        missing.append("전체 응답속도의 동일 조건 비교 근거")
    requires_reason = "왜" in question or "이유" in question
    if requires_reason:
        # A roles table is not evidence that services are wired together.
        reason_found = any(
            all(re.search(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", sentence, re.I) for name in names)
            and any(marker in sentence for marker in ("때문", "분담", "목적", "위해서", "하기 위해"))
            for result in results for sentence in re.split(r"[\n.!?]+", result.text)
        )
        if not reason_found:
            missing.append("요청한 도구를 함께 사용하는 이유")
    return {"entities": names, "requires_speed": requires_speed,
            "requires_response_speed": requires_response_speed,
            "requires_memory": requires_memory,
            "requires_reason": requires_reason, "missing": missing,
            "scope": "명시적 역할 표·역할 목록, 대상별 속도 표, 제한된 이유 표현만 확인"}


def missing_answer_items(answer, requirements):
    """Completeness signals only; presence is not proof of correct meaning."""
    body = re.sub(r"\[출처:[^\]]+\]", "", answer)
    missing = [name + "의 설명" for name in requirements["entities"]
               if not re.search(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", body, re.I)]
    if requirements["requires_speed"] and "token/s" not in body.lower():
        missing.append("요청한 생성속도")
    if requirements.get("requires_memory") and "메모리" not in body and not re.search(r"\b(?:GB|MB|KB|GiB|MiB)\b", body, re.I):
        missing.append("요청한 대상별 메모리 설명")
    if requirements["requires_reason"] and not any(word in body for word in ("때문", "분담", "목적", "위해", "이유")):
        missing.append("함께 쓰는 이유 설명")
    return missing


def requirements_notice(check):
    return ("검색된 Wiki 근거로 질문의 모든 항목을 확인하지 못했습니다. "
            "확인되지 않은 항목: " + "; ".join(check["missing"]) +
            ". 해당 근거 문서를 추가하거나 질문을 항목별로 나눠주세요.")
