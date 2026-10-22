from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from .evidence_scope import unsupported_query_anchors, MODEL_TAG

from .knowledge_base import SearchResult
from .text_contracts import verify_text_contracts


NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")
STRUCTURED_PATTERNS = [
    re.compile(r"(?<!\d)(?:19|20)\d{2}\s*(?:년|[./-])\s*\d{1,2}\s*(?:월|[./-])\s*\d{1,2}\s*(?:일|\.)?"),
    re.compile(r"(?<!\d)\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(
        r"(?<![\d.,])(?:월|연|일|주)?\s*\d+(?:,\d{3})*(?:\.\d+)?\s*"
        r"(?:(?:조|억|만|천)\s*원|원|%|퍼센트|GB|MB|TB|GHz|MHz|token/s|초|분|시간|시|페이지|개\s*팀|팀|명|인|세|점|회|부|개)",
        re.IGNORECASE,
    ),
]
DATE_CLAIM_PATTERN = STRUCTURED_PATTERNS[0]
PARTIAL_DATE_PATTERN = STRUCTURED_PATTERNS[1]
AMOUNT_CLAIM_PATTERN = re.compile(r"(?:조\s*원|억\s*원|만\s*원|천\s*원|원)", re.IGNORECASE)


@dataclass(frozen=True)
class TableFact:
    label: str
    metric: str
    value: float
    display_value: str
    unit: str
    source: str
    heading: str

    def to_dict(self) -> dict:
        return asdict(self)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def metric_unit(header: str) -> str | None:
    normalized = header.lower().replace(" ", "")
    if "token/s" in normalized or "토큰/초" in normalized or "속도" in normalized:
        return "token/s"
    if "시간" in normalized or "초" in normalized:
        return "seconds"
    return None


def extract_table_facts(result: SearchResult) -> list[TableFact]:
    lines = result.text.splitlines()
    facts: list[TableFact] = []
    index = 0
    while index + 1 < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        headers = _cells(lines[index])
        separator = _cells(lines[index + 1])
        if len(separator) != len(headers) or not all(
            TABLE_SEPARATOR.match(cell.replace(" ", "")) for cell in separator
        ):
            index += 1
            continue

        index += 2
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            values = _cells(lines[index])
            if len(values) == len(headers) and values:
                label = values[0]
                for column in range(1, len(headers)):
                    unit = metric_unit(headers[column])
                    number = NUMBER_PATTERN.search(values[column])
                    if unit and number:
                        facts.append(
                            TableFact(
                                label=label,
                                metric=headers[column],
                                value=float(number.group()),
                                display_value=number.group(),
                                unit=unit,
                                source=result.source,
                                heading=result.heading,
                            )
                        )
            index += 1
    return facts


def requested_unit(question: str) -> str | None:
    normalized = question.lower().replace(" ", "")
    if "token/s" in normalized or "토큰/초" in normalized or "속도" in normalized:
        return "token/s"
    calendar = any(word in normalized for word in ("날짜", "일정", "마감", "시작시간", "행사", "시각"))
    duration = any(word in normalized for word in ("응답시간", "처리시간", "소요시간", "평균시간", "몇초", "걸리"))
    if duration or ("시간" in normalized and not calendar):
        return "seconds"
    return None


def metric_facts(question: str, results: list[SearchResult]) -> list[TableFact]:
    unit = requested_unit(question)
    if not unit:
        return []
    if unsupported_query_anchors(question, results):
        return []
    model_tags = {tag.lower() for tag in MODEL_TAG.findall(question)}
    facts: list[TableFact] = []
    seen: set[tuple[str, str, float]] = set()
    for result in results:
        result_facts = extract_table_facts(result)
        if model_tags:
            result_facts = [fact for fact in result_facts
                            if model_tags & {tag.lower() for tag in MODEL_TAG.findall(fact.label)}]
            if not result_facts:
                continue
        question_tokens = set(re.findall(r"[a-z0-9.]+", question.lower())) - {
            "token",
            "s",
        }
        matching_facts = [
            fact
            for fact in result_facts
            if question_tokens
            & set(re.findall(r"[a-z0-9.]+", fact.label.lower()))
        ]
        if matching_facts and not model_tags:
            result_facts = matching_facts

        for fact in result_facts:
            key = (fact.label.lower(), fact.unit, fact.value)
            if fact.unit == unit and key not in seen:
                facts.append(fact)
                seen.add(key)
        if facts:
            break
    return facts


def deterministic_metric_answer(
    question: str, results: list[SearchResult]
) -> tuple[str, dict] | None:
    normalized = question.lower().replace(" ", "")
    compound_markers = ("자동점수", "점수", "이유", "왜", "생략", "역할", "용도",
                        "usb", "적용", "결론", "단정", "성능", "연동", "통신", "전체시간")
    asks_speed = any(marker in normalized for marker in ("token/s", "토큰/초", "속도"))
    asks_time = any(marker in normalized for marker in ("평균시간", "몇초"))
    if any(marker in normalized for marker in compound_markers) or (
        asks_speed and asks_time
    ):
        return None

    facts = metric_facts(question, results)
    if not facts:
        return None

    unit = facts[0].unit
    unit_label = "token/s" if unit == "token/s" else "초"
    is_average = all("평균" in fact.metric for fact in facts)
    metric_label = ("평균 " if is_average else "기록된 ") + ("생성속도" if unit == "token/s" else "시간")
    values = [f"{fact.label}가 {fact.display_value} {unit_label}" for fact in facts]
    if len(values) == 1:
        value_text = values[0]
    else:
        value_text = ", ".join(values[:-1]) + f"이고, {values[-1]}"
    source = facts[0]
    answer = (
        f"Wiki 표 기준 {metric_label}는 {value_text}입니다.\n\n"
        f"[출처: {source.source}#{source.heading}]"
    )
    verification = {
        "passed": True,
        "method": "deterministic_table_extraction",
        "display_label": "표 수치 검증 통과",
        "requested_unit": unit,
        "facts": [fact.to_dict() for fact in facts],
        "issues": [],
    }
    return answer, verification


def verify_metric_answer(
    question: str, answer: str, results: list[SearchResult]
) -> dict:
    unit = requested_unit(question)
    if not unit:
        return {
            "passed": True,
            "method": "no_metric_requested",
            "requested_unit": None,
            "facts": [],
            "issues": [],
        }

    facts = metric_facts(question, results)
    issues: list[str] = []
    if not facts:
        issues.append("근거 표에서 질문 단위에 대응하는 열을 찾지 못했습니다.")
    expected_label = "token/s" if unit == "token/s" else "초"
    if expected_label.lower() not in answer.lower():
        issues.append(f"답변에 요청 단위 {expected_label}가 없습니다.")
    for fact in facts:
        if fact.display_value not in answer:
            issues.append(
                f"근거의 {fact.label} {fact.metric} 값 {fact.display_value}가 답변에 없습니다."
            )
    if unit == "token/s" and re.search(r"\d+(?:\.\d+)?\s*초", answer):
        issues.append("속도 질문에 시간 단위인 초를 사용했습니다.")
    return {
        "passed": not issues,
        "method": "metric_unit_validation",
        "display_label": "수치 근거 검증 통과" if not issues else "수치 근거 검증 실패",
        "requested_unit": unit,
        "facts": [fact.to_dict() for fact in facts],
        "issues": issues,
    }


def _normalized_claim(text: str) -> str:
    text = text.strip()
    if DATE_CLAIM_PATTERN.fullmatch(text):
        year, month, day = map(int, re.findall(r"\d+", text))
        return f"{year:04}-{month:02}-{day:02}"
    if PARTIAL_DATE_PATTERN.fullmatch(text):
        month, day = map(int, re.findall(r"\d+", text))
        return f"--{month:02}-{day:02}"
    return re.sub(r"[\s,]", "", text).lower().replace("개팀", "팀")


def extract_structured_claims(text: str) -> list[str]:
    # Citation identity is checked separately. A page number in a filename or
    # source heading is provenance, not a factual claim made by the answer.
    text = re.sub(r"\[출처:[^\]]*\]", "", text)
    claims: list[str] = []
    seen: set[str] = set()
    spans = []
    for pattern in STRUCTURED_PATTERNS:
        for match in pattern.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end in spans):
                continue
            spans.append(match.span())
            claim = match.group().strip()
            normalized = _normalized_claim(claim)
            if normalized not in seen:
                claims.append(claim)
                seen.add(normalized)
    return claims


def structured_claim_types(claims: list[str]) -> list[str]:
    types: set[str] = set()
    for claim in claims:
        if DATE_CLAIM_PATTERN.fullmatch(claim) or PARTIAL_DATE_PATTERN.fullmatch(claim):
            types.add("date")
        elif AMOUNT_CLAIM_PATTERN.search(claim):
            types.add("amount")
        else:
            types.add("metric")
    return sorted(types)


def row_claim_issues(answer: str, results: list[SearchResult]) -> list[str]:
    """Check only explicit named rows with both a count and money amount.

    A number existing elsewhere in the page does not prove a row association.
    This is not a general Korean entailment checker; unknown layouts stay out.
    """
    from .table_comparison import _tables
    candidates = {}
    for result in results:
        rows = [(row[0], " ".join(row[1:])) for _, table in _tables(result.text) for row in table]
        for line in result.text.splitlines():
            match = re.fullmatch(r"\s*([가-힣A-Za-z][가-힣A-Za-z0-9_-]{1,30})\s{2,}(.+)", line)
            if match:
                rows.append(match.groups())
        for label, rest in rows:
            claims = extract_structured_claims(rest)
            amounts = [c for c in claims if AMOUNT_CLAIM_PATTERN.search(c)]
            counts = [c for c in claims if re.search(r"(?:팀|명|인|점|회|개)$", c)]
            if amounts and counts and not re.search(r"\d|[|\n]", label):
                candidates.setdefault(label.strip(), []).append({_normalized_claim(c) for c in claims})
    if not candidates:
        return []
    labels = "|".join(re.escape(label) for label in sorted(candidates, key=len, reverse=True))
    pattern = re.compile(r"(?<![가-힣A-Za-z0-9_])(?:" + labels + r")(?=은|는|이|가|의|[:：\s,]|\d|$)")
    issues = []
    for clause in re.split(r"[\n;。]", re.sub(r"\[출처:[^\]]*\]", "", answer)):
        matches = list(pattern.finditer(clause))
        for i, match in enumerate(matches):
            label = match.group()
            segment = clause[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(clause)]
            for claim in extract_structured_claims(segment):
                if any(_normalized_claim(claim) not in row for row in candidates[label]):
                    issues.append(f"대상별 행 연결 불일치: {label} — {claim}")
    return issues


def verify_structured_claims(answer: str, results: list[SearchResult]) -> dict:
    claims = extract_structured_claims(answer)
    if not claims:
        return {
            "passed": None,
            "method": "source_attached_semantic_review_needed",
            "display_label": "출처 연결됨 · 문장 의미는 사람 검토 필요",
            "claims": [],
            "supported_claims": [],
            "unsupported_claims": [],
            "issues": ["자동 대조할 금액·날짜·단위 수치가 없습니다."],
        }

    evidence_text = "\n".join(result.text for result in results)
    evidence = {_normalized_claim(claim) for claim in extract_structured_claims(evidence_text)}
    # One explicit date range may omit the year on its second endpoint.
    # Inherit it only across a same-line range, never from a document title.
    for match in re.finditer(
        r"((?:19|20)\d{2})\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?(?:\([^\n)]*\))?\s*[~～]\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?", evidence_text
    ):
        year, month, day = map(int, match.groups())
        evidence.add(f"{year:04}-{month:02}-{day:02}")
    evidence.update("--" + key[5:] for key in list(evidence) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key))
    supported = [claim for claim in claims if _normalized_claim(claim) in evidence]
    unsupported = [claim for claim in claims if _normalized_claim(claim) not in evidence]
    claim_types = structured_claim_types(claims)
    issues = [f"근거 원문에서 확인되지 않은 값: {claim}" for claim in unsupported]
    issues.extend(row_claim_issues(answer, results))
    return {
        "passed": not issues,
        "method": "structured_claim_verification",
        "display_label": (
            "수치 근거 검증 실패" if issues else
            "수치 근거 검증 통과" if "metric" in claim_types else "금액·날짜·단위 검증 통과"
        ),
        "claims": claims,
        "claim_types": claim_types,
        "supported_claims": supported,
        "unsupported_claims": unsupported,
        "issues": issues,
    }


def verify_grounded_answer(
    question: str, answer: str, results: list[SearchResult]
) -> dict:
    numeric = (verify_metric_answer(question, answer, results) if requested_unit(question)
               else verify_structured_claims(answer, results))
    contract = verify_text_contracts(question, answer, results)
    if contract is None:
        return numeric
    contract["numeric_verification"] = numeric
    if numeric["passed"] is False:
        contract["passed"] = False
        contract["display_label"] = "검증 실패"
        contract["issues"].extend(numeric["issues"])
    return contract
