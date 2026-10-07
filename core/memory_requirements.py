"""Conservative memory fallback independent of role phrasing/count."""
import re
from .role_lists import memory_rows


def asks_memory(question):
    return "메모리" in question or bool(re.search(r"(?<![a-z0-9_])(?:RSS|RAM)(?![a-z0-9_])", question, re.I))


def named_targets(question):
    ignored = {"api", "rest", "ui", "token", "s", "rss", "ram", "cpu", "gpu", "gb", "mb", "kb", "gib", "mib", "kib"}
    return list(dict.fromkeys(name for name in re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", question)
                             if name.lower() not in ignored))


def memory_fallback(question, results):
    """Never generate memory prose when bounded full-query extraction failed.

    Safe partial row copies do not certify arbitrary extra requirements.
    Unsupported targets/formats stay explicit instead of guessing.
    """
    if not asks_memory(question):
        return None
    names = named_targets(question)
    missing, items, used = [], [], []
    for name in names:
        candidates = [(row, result) for result in results for row in memory_rows(name, result)]
        values = {row for row, _ in candidates}
        if len(values) != 1:
            missing.append(name + "의 대상별 메모리 사용량" + (" (원문 값 충돌)" if values else " (검색 근거 부족)"))
        else:
            row, result = candidates[0]
            items.append(f"- {name}의 대상별 메모리 사용량: {row}\n  [출처: {result.source}#{result.heading}]")
            if result not in used:
                used.append(result)
    if not names:
        missing.append("요청 대상의 메모리 측정 근거 (대상 식별 형식 미지원)")
    answer = ("검색된 메모리 측정 행만 제시합니다:\n" + "\n".join(items) if items else "검색된 근거에서 요청 대상의 메모리 측정 행을 확인하지 못했습니다.")
    if missing:
        answer += "\n\n확인하지 못한 항목:\n" + "\n".join("- " + item for item in missing)
    answer += "\n\nPC의 전체 RAM 용량이나 모델 파일 크기로 대체하지 않습니다. 질문의 다른 요구는 확인하지 못했으며 질문 전체가 해결된 것은 아닙니다."
    return answer, used, {"passed": None if items else False,
                         "method": "memory_requirements_guard",
                         "display_label": "메모리 행 일부 확인 · 질문 전체는 미확인" if items else "메모리 요구 근거 부족 · 생성하지 않음",
                         "missing_items": missing, "issues": missing,
                         "scope": "지원하는 대상명·측정 표 형식의 행만 확인. 일반 의미 추론이나 다른 요구의 완전성 보장 없음."}
