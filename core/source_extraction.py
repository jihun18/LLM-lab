"""Narrow, source-faithful answers; never synthesize explanations or comparisons."""
import re

from .text_contracts import normalized


def deterministic_text_answer(question, results):
    if not results:
        return None
    # A copied list cannot answer causal, comparative, procedural or numerical
    # follow-up requests. Keep those on the existing generation path.
    if any(word in question for word in ("왜", "이유", "비교", "차이", "추천", "장점", "단점", "절차", "속도", "시간", "마감", "금액", "제외", "빼고", "만 골라", "예시", "평가", "요약", "포트", "방법", "설치", "설정", "코드", "보안", "한계", "성능", "조건", "메모리", "지원금", "얼마", "그리고")):
        return None
    primary = results[0]
    pairs = re.findall(r"(?m)^-\s+([^:\n]+):\s*\*\*([^*\n]+)\*\*\s*$", primary.text)
    roles_requested = any(word in question for word in ("역할", "용도", "무슨 용"))
    selected = [(role, entity) for role, entity in pairs if re.search(r"(?<![a-z0-9_])" + re.escape(entity) + r"(?![a-z0-9_])", question, re.I)]
    if roles_requested and len(selected) >= 2:
        if re.search(r"\d", question):
            return None
        # Unknown named tools must not be silently dropped from the request.
        allowed = {entity.lower() for _, entity in selected} | {"wiki", "privai"}
        names = {name.lower() for name in re.findall(r"[a-zA-Z][a-zA-Z0-9_.:-]*", question)}
        if names - allowed or len({entity.lower() for _, entity in selected}) != len(selected):
            return None
        # Conflicting explicit mappings in other retrieved chunks require review.
        for result in results[1:]:
            other = re.findall(r"(?m)^-\s+([^:\n]+):\s*\*\*([^*\n]+)\*\*\s*$", result.text)
            for role, entity in other:
                if any(entity.lower() == name.lower() and normalized(role) != normalized(expected)
                       for expected, name in selected):
                    return None
        items = [f"{entity}: {role}" for role, entity in selected]
        kind = "role_pairs"
    else:
        if re.search(r"\d{4}|[a-zA-Z][a-zA-Z0-9_.:-]*", question):
            return None
        match = re.search(r"(\d+)\s*(?:개|가지)", question)
        count = int(match.group(1)) if match else next((n for word, n in (("네 가지", 4), ("세 가지", 3), ("두 가지", 2)) if word in question), None)
        items = re.findall(r"(?m)^-\s+`([^`\n]+)`\s*$", primary.text)
        # Require the source section name to occur in the question, not merely
        # an arbitrary quoted list with the same item count.
        if not (count and "문구" in question and "상태" in question
                and "상태" in primary.heading
                and all(normalized(word) in normalized(question) for word in primary.heading.split())
                and len(items) == count):
            return None
        for result in results[1:]:
            other = re.findall(r"(?m)^-\s+`([^`\n]+)`\s*$", result.text)
            if result.heading == primary.heading and other and other != items:
                return None
        kind = "verbatim_list"
    answer = "Wiki 원문 기준:\n" + "\n".join(f"- {item}" for item in items)
    answer += f"\n\n[출처: {primary.source}#{primary.heading}]"
    return answer, {"passed": True, "method": "deterministic_text_extraction",
                    "display_label": "역할·문구 원문 추출 완료", "kind": kind,
                    "items": items, "issues": [],
                    "scope": "원문 복사 여부만 보장하며 문서 자체의 사실성은 보장하지 않습니다."}
