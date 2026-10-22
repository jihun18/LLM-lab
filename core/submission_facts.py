"""Copy bounded submission sections, including wrapped lists and stage scope.

This preserves provided instructions rather than guessing a list of document
names from a model summary. It does not prove whole-document completeness.
"""
import re

from .grounding import DATE_CLAIM_PATTERN


def compact(text):
    return re.sub(r"\s+", "", text)


def asks_submissions(question):
    q = compact(question).lower()
    if any(term in q for term in ("제출서류", "제출자료", "구비서류", "제출해야할서류")):
        return True
    # Explicit application/submission context plus a resource is required.
    # '이것만 하면 돼?' does not authorize guessing conversational context.
    if not any(term in q for term in ("접수", "제출", "신청")) or not any(
        term in q for term in ("pdf", "파일", "기획안", "제안서", "신청서", "서류", "자료")
    ):
        return False
    if any(term in q for term in ("말고", "묻는게아니", "질문이아니")):
        return False
    sufficiency = bool(re.search(r"만(?:내면|내도|제출하면|제출해도|보내면|보내도|올리면|올려도|으로)", q)) and any(
        term in q for term in ("끝", "충분", "완료", "돼", "되나", "될까", "되나요"))
    additional = any(term in q for term in (
        "다른자료", "추가자료", "추가서류", "다른파일", "동의절차", "동의도",
        "준비해야하는파일", "준비할서류"))
    return sufficiency or additional


def _heading(line):
    return bool(re.match(r"^\s*(?:#{1,6}\s+|\d+\s+)[가-힣A-Za-z]", line))


def _stage(line):
    match = re.match(r"^\s*(?:(?:#{1,6}|[❍□•*-])\s*)?(\d+)\s*차(?=[(（:：\s]|$)", line)
    return match.group(1) if match else None


def _sections(text):
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _heading(line) and any(
        term in compact(line) for term in ("신청방법", "접수방법", "제출안내", "제출서류", "제출자료", "구비서류"))]
    # Some PDFs omit a section heading but have an explicit submission label.
    if not starts:
        starts = [i for i, line in enumerate(lines) if re.match(
            r"^(?:[❍□•*-])?(?:제출서류|제출자료|구비서류)[:：]", compact(line))]
    sections = []
    for start in starts:
        end = start + 1
        while end < len(lines) and not (_heading(lines[end]) and not _stage(lines[end])):
            # Without a heading, stop at the next unrelated top-level bullet.
            if not _heading(lines[start]) and re.match(r"^\s*[❍□•]", lines[end]) and not _stage(lines[end]) and not any(
                term in compact(lines[end]) for term in ("제출", "구비서류", "동의")):
                break
            end += 1
        sections.append(lines[start:end])
    return sections


def submission_evidence(question, results):
    if not asks_submissions(question):
        return None
    requested = set(re.findall(r"(\d+)\s*차", question))
    candidates, missing = [], []
    for source in results:
        for lines in _sections(source.text):
            current_stage = None
            present = {_stage(line) for line in lines if _stage(line)}
            selected = []
            for line in lines:
                stage = _stage(line)
                if stage:
                    current_stage = stage
                if not requested or current_stage is None or current_stage in requested:
                    selected.append(line)
            # Shared material alone cannot certify a requested stage's list.
            if requested and not requested.issubset(present):
                missing.append("요청한 " + "·".join(n + "차" for n in sorted(requested - present)) + "의 명시적 제출 안내 범위")
            value = "\n".join(selected).strip()
            if value and any(term in compact(value) for term in ("제출", "구비서류")):
                candidates.append((value, source))
    items, seen = [], set()
    for value, source in candidates:
        key = (source.source, source.heading, compact(value))
        if key not in seen:
            items.append(("제출 안내 원문" + (" (" + "·".join(n + "차" for n in sorted(requested)) + ")" if requested else ""), value, source))
            seen.add(key)
    if not items:
        missing.append("요청한 제출 서류·자료 안내 (검색된 근거의 지원 형식에서 확인하지 못함)")
    if any(term in compact(question) for term in ("마감", "기한", "기간", "날짜", "일정", "시간", "언제", "몇시")):
        schedules = []
        for source in results:
            for line in source.text.splitlines():
                if not (any(term in compact(line) for term in ("접수", "신청", "제출")) and DATE_CLAIM_PATTERN.search(line)):
                    continue
                phase = set(re.findall(r"(\d+)\s*차", line))
                if requested and phase and not phase & requested:
                    continue
                schedules.append(("접수·제출 일정 원문", line.strip(), source))
        items.extend(schedules)
        if not schedules:
            missing.append("접수·제출 일정의 명시적 행 (검색 근거 부족 또는 지원 형식 미확인)")
    # Never turn a retrieved section into a universal completeness guarantee.
    missing.append("검색된 제출 안내 밖의 추가 서류·요청 항목 및 문서 전체 완전성 (별도 확인 필요)")
    return items, list(dict.fromkeys(missing))
