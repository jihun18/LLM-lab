"""Small source-only readers for explicit PDF rows and unpublished fields.

No document names, event dates, monetary values or answer keys live here.
These are partial copies, not a certification of all requested semantics.
"""
import re

from .grounding import extract_structured_claims, AMOUNT_CLAIM_PATTERN, DATE_CLAIM_PATTERN


def _compact(text):
    return re.sub(r"[\s·]", "", text)


def _blocks(text):
    return re.split(r"\n\s*\n|(?=^[ \t]*[❍□※])", text, flags=re.M)


def pdf_source_answer(question, results):
    if not results or not results[0].source.startswith("Uploads/") or not all(
        r.source == results[0].source and re.fullmatch(r"PDF \d+페이지", r.heading) for r in results
    ):
        return None
    items, used, missing = [], [], []

    def copy(label, value, source):
        items.append(f"- {label}: {value.strip()}\n  [출처: {source.source}#{source.heading}]")
        if source not in used:
            used.append(source)

    if any(word in question for word in ("상금", "포상", "금액")) and re.search(r"몇\s*팀|시상\s*수|수량", question):
        rows = {}
        for source in results:
            for line in source.text.splitlines():
                match = re.fullmatch(r"\s*([가-힣A-Za-z][가-힣A-Za-z0-9_-]{1,30})\s{2,}(.+)", line)
                if not match:
                    continue
                label, rest = match.groups()
                if not re.search(r"(?<![가-힣A-Za-z])" + re.escape(label) + r"(?=은|는|이|가|[·,\s]|$)", question):
                    continue
                claims = extract_structured_claims(rest)
                if any(AMOUNT_CLAIM_PATTERN.search(c) for c in claims) and any(re.search(r"(?:팀|명|점|개)$", c) for c in claims):
                    rows.setdefault(label, []).append((line.strip(), source))
        for label, candidates in rows.items():
            if len({_compact(value) for value, _ in candidates}) != 1:
                missing.append(label + "의 수량·금액 (원문 값 충돌)")
            else:
                value, source = candidates[0]
                copy(label + "의 기록된 행", value, source)
        if not items:
            return None
        if "지급" in question:
            paragraphs = [(p, source) for source in used for p in _blocks(source.text)
                          if "지급" in p and len(p) <= 1000]
            if len({_compact(value) for value, _ in paragraphs}) == 1:
                value, source = paragraphs[0]
                copy("지급 관련 원문", value, source)
            else:
                missing.append("지급 방식의 단일 명시 근거")
        missing.append("팀 수 등의 단위 환산 및 요청 전체의 의미 검증 (원문의 단위를 그대로 제시)")
    elif "장소" in question and "시간" in question:
        notices = [(p, source) for source in results for p in _blocks(source.text)
                   if "장소" in _compact(p) and "시간" in _compact(p)
                   and any(term in _compact(p) for term in ("추후공개", "추후공지", "미정")) and len(p) <= 1000]
        if len({_compact(value) for value, _ in notices}) != 1:
            return None
        value, source = notices[0]
        # Match a contiguous phrase from the question, not just '발표' which
        # may refer to both finalist announcements and the final presentation.
        phrases = re.findall(r"(?=([가-힣]{2,})\s+([가-힣]{2,}))", question)
        date_rows = [line.strip() for line in source.text.splitlines()
                     if DATE_CLAIM_PATTERN.search(line)
                     and any(a + b in _compact(line) for a, b in phrases)]
        for line in dict.fromkeys(date_rows):
            copy("관련 일정 원문", line, source)
        copy("장소·시간 공개 관련 원문", value, source)
        missing.append("정확한 행사 장소·시작 시간 (원문에서 추후 공개·공지 또는 미정으로 안내)")
        if not date_rows:
            missing.append("요청한 행사의 날짜 연결 (지원하는 행 형식에서 확인하지 못함)")
    else:
        return None
    answer = "검색된 Wiki 원문에서 확인한 항목:\n" + "\n".join(items)
    answer += "\n\n확인하지 못한 항목:\n" + "\n".join("- " + item for item in missing)
    answer += "\n확인한 항목만 답했으며 질문 전체가 해결된 것은 아닙니다."
    return answer, used, {"passed": None, "method": "deterministic_requirement_copy",
                         "display_label": "PDF 행·문단 일부 추출 · 미확인 항목 있음",
                         "missing_items": missing, "issues": missing,
                         "scope": "명시된 행과 문단만 복사. 단위 환산·문서 전체 완전성·원문 자체의 사실성은 확인하지 않습니다."}
