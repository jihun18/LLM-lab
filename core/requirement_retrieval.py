"""Bounded follow-up retrieval and source-copy answers, never invented reasons."""
import re
from .query_requirements import role_requirements
from .table_comparison import _tables
from .role_lists import memory_rows, role_candidates, role_value_key
from .query_requirements import role_conflicts


def bounded_question(question, check):
    remainder = question
    for name in check["entities"]:
        remainder = re.sub(re.escape(name), "", remainder, flags=re.I)
    remainder = re.sub(r"[\s,?.!·/]+", "", remainder)
    grammar = ("설명해주세요", "설명해줘", "알려주세요", "알려줘", "알려주고", "사용하는지도", "사용하는지",
               "함께", "쓰는지", "쓰는", "사용", "생성속도", "처리속도", "속도", "이유", "왜",
               "역할", "용도", "차이", "비교", "각각", "둘", "두", "도", "의", "와", "과", "을", "를", "은", "는", "고", "주")
    grammar += ("무엇을담당하며", "무엇을담당", "담당하는일", "어떤일을", "하나요", "응답속도", "어때", "하며")
    grammar += ("업무", "메모리사용량", "메모리", "사용량")
    grammar += ("맡는작업", "맡는일", "가", "이", "및")
    # Match the metric aliases recognized by asks_memory, without treating
    # arbitrary extra instructions as supported source-copy requirements.
    grammar += ("RSS", "RAM", "원문", "근거로", "확인해줘")
    return bool(check["entities"]) and re.fullmatch("(?:" + "|".join(map(re.escape, grammar)) + ")*", remainder, re.I) is not None


def supplement_role_evidence(question, initial, knowledge, search_mode):
    check = role_requirements(question, initial, allow_missing_roles=True)
    if not check or not check["missing"] or not bounded_question(question, check):
        return initial, []
    # No hidden whole-index scan: at most four queries, three hits each, and
    # at most six new chunks. Use the user's selected retrieval mode.
    queries = []
    for name in check["entities"]:
        if f"{name}의 역할" in check["missing"]:
            queries.append(f"{name} 역할 용도")
        if f"{name}의 표 기반 생성속도" in check["missing"]:
            queries.append(f"{name} 생성속도 token/s")
        if f"{name}의 대상별 메모리 사용량" in check["missing"]:
            queries.append(f"{name} 메모리 사용량 RSS")
    if check["requires_reason"] and "요청한 도구를 함께 사용하는 이유" in check["missing"]:
        queries.append(" ".join(check["entities"]) + " 함께 사용하는 이유 목적 분담")
    if check.get("requires_response_speed"):
        queries.append(" ".join(check["entities"]) + " 전체 응답시간 동일 조건 비교")
    combined = list(initial)
    seen = {(r.source, r.heading, r.text) for r in combined}
    trace = []
    for query in queries[:4]:
        hits = (knowledge.search(query, 3) if search_mode == "bm25"
                else knowledge.search(query, 3, mode=search_mode))
        added = 0
        for result in hits:
            key = (result.source, result.heading, result.text)
            if key not in seen and len(combined) < len(initial) + 6:
                combined.append(result)
                seen.add(key)
                added += 1
        trace.append({"query": query, "added_chunks": added})
    return combined, trace


def requirement_source_answer(question, results):
    check = role_requirements(question, results)
    if not check or not bounded_question(question, check):
        return None
    # Preserve the ordinary simple-comparison path. This is for missing targets
    # and speed/reason additions, not every role query.
    if not (check["missing"] or check["requires_speed"] or check["requires_reason"] or check.get("requires_memory") or role_conflicts(question, results)):
        return None
    items, missing, used = [], [], []

    def copy_item(label, candidates, value_key=lambda value: value):
        values = {value_key(value) for value, _ in candidates}
        if len(values) != 1:
            missing.append(label + (" (원문 값 충돌)" if values else " (검색 근거 부족)"))
            return
        value, result = candidates[0]
        items.append(f"- {label}: {value}\n  [출처: {result.source}#{result.heading}]")
        if result not in used:
            used.append(result)

    for name in check["entities"]:
        roles, speeds, memories = [], [], []
        for result in results:
            memories.extend((value, result) for value in memory_rows(name, result))
            for headers, rows in _tables(result.text):
                if headers[0] == "항목":
                    columns = [i for i, header in enumerate(headers) if header.lower() == name.lower()]
                    for row in rows:
                        if row[0] == "역할":
                            roles.extend((row[column], result) for column in columns if row[column])
                elif check["requires_speed"]:
                    speed_columns = [i for i, header in enumerate(headers) if "생성속도" in header or "token/s" in header.lower()]
                    for row in rows:
                        if row[0].lower() == name.lower() and any(re.fullmatch(r"\d+(?:\.\d+)?\s*token/s", row[i], re.I) for i in speed_columns):
                            # Copy the entire row (including model/time columns),
                            # not a context-free number attributed to the framework.
                            speeds.append(("; ".join(f"{headers[i]} — {row[i]}" for i in range(1, len(headers))), result))
        # Check every supported format before choosing a displayed raw value.
        # Table values remain the display preference only after agreement.
        all_roles = role_candidates(name, results)
        ordered_roles = roles + [candidate for candidate in all_roles if candidate not in roles]
        copy_item(name + "의 역할", ordered_roles, role_value_key)
        if check["requires_speed"]:
            copy_item(name + "의 기록된 생성속도 행", speeds)
        if check.get("requires_memory"):
            copy_item(name + "의 대상별 메모리 사용량", memories)
    if check["requires_reason"]:
        reasons = []
        for result in results:
            for sentence in re.split(r"[\n.!?]+", result.text):
                if (all(re.search(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", sentence, re.I) for name in check["entities"])
                        and any(marker in sentence for marker in ("때문", "분담", "목적", "위해서", "하기 위해"))):
                    reasons.append((sentence.strip(), result))
        copy_item("함께 사용하는 이유의 원문", reasons)
    if not items:
        return None
    answer = "검색된 Wiki 원문에서 확인한 항목:\n" + "\n".join(items)
    if check["requires_speed"]:
        answer += "\n\n속도 행은 당시 모델 생성 실측 기록입니다. 프레임워크 자체의 처리 성능이나 동일 조건의 우열을 뜻하지 않습니다."
    if check.get("requires_response_speed"):
        answer += "\n응답속도 질문에 참고할 생성속도 기록만 제시했습니다. 전체 응답시간에는 모델 적재·입력 처리·답변 길이 등이 포함되어, token/s와 같은 지표가 아닙니다."
        missing.append("전체 응답속도의 동일 조건 비교 근거 (생성속도 기록만으로 판단 불가)")
    if check.get("requires_memory"):
        answer += "\n\n메모리 사용량은 요청한 도구의 측정 행만 확인합니다. PC의 전체 RAM 용량이나 모델 파일 크기를 도구별 메모리 사용량으로 대신하지 않습니다."
    if missing:
        answer += "\n\n확인하지 못한 항목:\n" + "\n".join("- " + item for item in missing)
        answer += "\n해당 근거 문서를 보완해주세요. 확인한 항목만 답했으며 질문 전체가 해결된 것은 아닙니다."
    return answer, used, {"passed": None if missing else True,
                         "method": "deterministic_requirement_copy",
                         "display_label": "일부 항목 원문 추출 · 미확인 항목 있음" if missing else "요청 항목 원문 추출 완료",
                         "missing_items": missing, "issues": missing,
                         "scope": "원문 복사만 확인하며 내용 의미와 원문 자체의 사실성은 보장하지 않습니다."}
