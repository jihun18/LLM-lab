"""Bounded project-table readers and explicit limits, not semantic verification.

Only recognized whole-query forms may copy cells. Unknown extra requests fall
through; inference questions never become a convenient numeric-table answer.
All evidence is obtained through the selected search mode with a fixed budget.
"""
import re

from .memory_requirements import named_targets
from .table_comparison import _tables
from .role_lists import role_candidates, role_value_key


def compact(text):
    return re.sub(r"[\s,?.!·/]+", "", text).lower()


def intent(question):
    q = compact(question)
    if "속도" in q and "usb" in q and any(x in q for x in ("적용", "비교", "옮긴", "이전")):
        return "storage_limit"
    if "속도" in q and any(x in q for x in ("결론", "단정", "성능이좋", "더빠르다고")):
        return "comparison_limit"
    names = named_targets(question)
    rest = question
    for name in names:
        rest = re.sub(re.escape(name), "", rest, flags=re.I)
    rest = compact(rest)
    grammar = ("이프로젝트에서", "이프로젝트를", "프로젝트에서", "지금까지", "기록된",
               "기록되어있어", "알려줘", "설명해줘", "설명하고", "어떤", "어떻게", "무엇이야",
               "역할", "실행포트", "화면구성", "화면", "구성", "api문서", "문서제공방식",
               "제공방식", "생성속도", "전체시간", "각각", "차이", "달라", "그리고",
               "둘이", "실제로", "통신하는방식", "연동방식", "사용하는", "모델", "기본모델",
               "확인된사실", "아직검증하지않은내용", "나눠서", "요약해줘",
               "은", "는", "이", "가", "의", "와", "과", "을", "를", "도", "야", "고")
    if re.fullmatch("(?:" + "|".join(map(re.escape, sorted(grammar, key=len, reverse=True))) + ")*", rest) is None:
        return None
    has_fields = any(x in q for x in ("실행포트", "화면", "api문서", "문서제공방식"))
    has_metrics = "생성속도" in q or "전체시간" in q
    has_link = "통신하는방식" in q or "연동방식" in q
    # Recognizing individual words does not mean every combination is handled.
    if (has_fields and has_metrics) or (has_link and has_metrics):
        return None
    if "요약" in q and "확인된" in q and "검증하지않은" in q and not names:
        return "overview"
    if "기본모델" in q and "모델" in q and not names and not (has_fields or has_metrics or has_link or "역할" in q):
        return "models"
    if not names:
        return None
    if "통신하는방식" in q or "연동방식" in q:
        return "connection"
    if "생성속도" in q and "전체시간" in q:
        return "measurements"
    if any(x in q for x in ("실행포트", "화면", "api문서", "문서제공방식")):
        return "fields"
    if "역할" in q:
        if "차이" in q or "비교" in q:
            return None  # Preserve the existing simple-comparison contract.
        return "roles"
    return None


def supplement_project_evidence(question, initial, knowledge, mode):
    kind = intent(question)
    names = named_targets(question)
    queries = {
        "roles": [" ".join(names) + " 역할 항목"],
        "fields": [" ".join(names) + " 실행 포트 화면 API 문서 항목"],
        "connection": [" ".join(names) + " 역할 항목", " ".join(names) + " 통신 연동 구조"],
        "measurements": [" ".join(names) + " 전체 시간 생성속도 프레임워크"],
        "comparison_limit": ["전체 시간 차이 프레임워크 최초 적재 답변 길이 캐시"],
        "storage_limit": ["USB 이전 저장장치 동일 조건 측정"],
        "models": ["모드 Ollama 모델", "현재 결정 빠른 모드 기본값"],
        "overview": ["역할 항목 프레임워크", "모드 Ollama 모델", "현재 결정 기본값"],
    }.get(kind, [])
    combined, trace = list(initial), []
    seen = {(r.source, r.heading, r.text) for r in combined}
    for query in queries[:4]:
        hits = knowledge.search(query, 3) if mode == "bm25" else knowledge.search(query, 3, mode=mode)
        added = 0
        for result in hits:
            key = (result.source, result.heading, result.text)
            if key not in seen and len(combined) < len(initial) + 6:
                combined.append(result)
                seen.add(key)
                added += 1
        trace.append({"query": query, "added_chunks": added})
    return combined, trace


def project_source_answer(question, results):
    kind = intent(question)
    if not kind:
        return None
    names = named_targets(question)
    items, missing, used = [], [], []

    def copy(label, candidates, key=lambda value: value):
        values = {key(value) for value, _ in candidates}
        if len(values) != 1:
            missing.append(label + (" (원문 값 충돌)" if values else " (검색 근거 부족)"))
            return
        value, source = candidates[0]
        items.append(f"- {label}: {value}\n  [출처: {source.source}#{source.heading}]")
        if source not in used:
            used.append(source)

    def cells(name, field):
        candidates = []
        for result in results:
            for headers, rows in _tables(result.text):
                if headers[0] != "항목":
                    continue
                for column, header in enumerate(headers[1:], 1):
                    if header.lower() == name.lower():
                        candidates.extend((row[column], result) for row in rows if row[0] == field and row[column])
        return candidates

    note = ""
    if kind in {"roles", "fields", "connection"}:
        q = compact(question)
        fields = ["역할"] if "역할" in q else []
        for term, field in (("실행포트", "실행 포트"), ("화면", "화면"), ("api문서", "API 문서"), ("문서제공방식", "API 문서")):
            if term in q and field not in fields:
                fields.append(field)
        for name in names:
            for field in fields:
                if field == "역할":
                    copy(name + "의 " + field, role_candidates(name, results), role_value_key)
                else:
                    copy(name + "의 " + field, cells(name, field))
        if kind == "connection":
            # Roles and generic HTTP knowledge do not prove a deployed link.
            missing.append("요청한 도구의 실제 통신·연동 구조 (명시적 구조 근거의 별도 검토 필요)")
            note = "역할 표만으로 도구끼리 HTTP 요청을 보내거나 연결되어 있다고 추정하지 않습니다."
    elif kind == "measurements":
        for name in names:
            if "역할" in question:
                copy(name + "의 역할", role_candidates(name, results), role_value_key)
            candidates = []
            for result in results:
                for headers, rows in _tables(result.text):
                    if not {"프레임워크", "모델", "전체 시간", "생성속도"}.issubset(headers):
                        continue
                    for row in rows:
                        if row[headers.index("프레임워크")].lower() == name.lower():
                            candidates.append(("; ".join(f"{h} — {row[headers.index(h)]}" for h in ("모델", "전체 시간", "생성속도")), result))
            copy(name + "의 기록된 측정 행", candidates)
        note = "개별 측정 행이며 평균으로 바꾸어 부르지 않습니다. 모델 생성속도와 전체 시간은 다른 지표이며 프레임워크 자체의 성능 우열을 뜻하지 않습니다."
    elif kind in {"comparison_limit", "storage_limit"}:
        if kind == "comparison_limit":
            candidates = [(line.strip(), r) for r in results for line in r.text.splitlines()
                          if "전체 시간 차이는 프레임워크만의 차이가 아니다" in line]
            copy("기록된 비교 한계", candidates)
            note = "생성속도 기록만으로 프레임워크 자체가 더 우수하다고 결론 내릴 수 없습니다."
        else:
            note = "기존 속도표는 USB 이전 후에도 같은 결과가 나온다는 근거가 아닙니다. 저장장치 변경 전후의 적재 조건과 측정 조건을 확인하기 전에는 그대로 적용할 수 있다고 답하지 않습니다."
        missing.append("요청 조건에서의 성능 우열·재현성 판단 근거 (단순 속도표로 대체 불가)")
    elif kind in {"models", "overview"}:
        tables = []
        for r in results:
            for headers, rows in _tables(r.text):
                if {"모드", "Ollama 모델"}.issubset(headers):
                    value = "; ".join(f"{row[headers.index('모드')]} — {row[headers.index('Ollama 모델')]}" for row in rows)
                    if value and all(row[headers.index('모드')] and row[headers.index('Ollama 모델')] for row in rows):
                        tables.append((value, r))
        copy("문서에 기록된 모델 모드", tables)
        defaults = [(paragraph.strip(), r) for r in results for paragraph in re.split(r"\n\s*\n", r.text)
                    if paragraph.strip().startswith("빠른 모드를 기본값으로 유지한다.")]
        copy("문서에 기록된 기본 모드 결정", defaults)
        note = "문서 기록이며 현재 Ollama에 설치된 전체 모델 목록이나 실행 중인 모델을 조회한 결과는 아닙니다."
        if kind == "overview":
            # Generic table-driven overview: do not invent completed validation.
            targets = list(dict.fromkeys(h for r in results for headers, rows in _tables(r.text)
                                         if headers[0] == "항목" and any(row[0] == "역할" for row in rows)
                                         for h in headers[1:]))
            for name in targets:
                copy(name + "의 역할", role_candidates(name, results), role_value_key)
            missing.append("프로젝트 전체의 최신 검증 완료·미완료 목록 (이 요약은 기록 일부이며 전체 검증 현황이 아님)")
    answer = "검색된 Wiki 원문에서 확인한 항목:\n" + "\n".join(items) if items else "요청한 판단을 뒷받침하는 명시적 근거를 확인하지 못했습니다."
    if note:
        answer += "\n\n" + note
    if missing:
        answer += "\n\n확인하지 못한 항목:\n" + "\n".join("- " + item for item in missing)
        answer += "\n확인한 항목만 답했으며 질문 전체가 해결된 것은 아닙니다."
    return answer, used, {"passed": None if missing else True,
                         "method": "deterministic_requirement_copy",
                         "display_label": "일부 항목 원문 추출 · 미확인 항목 있음" if missing else "요청 항목 원문 추출 완료",
                         "missing_items": missing, "issues": missing,
                         "scope": "명시적 표 셀·문장 복사만 확인. 의미 추론·최신 설치 상태·원문 자체의 사실성은 보장하지 않습니다."}
