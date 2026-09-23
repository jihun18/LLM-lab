from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .knowledge_base import SearchResult


NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")
STRUCTURED_PATTERNS = [
    re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(
        r"(?:월|연|일|주)?\s*\d+(?:[.,]\d+)?\s*"
        r"(?:조원|억원|만원|천원|원|%|퍼센트|GB|MB|TB|GHz|MHz|token/s|초|분|시간|페이지|개)",
        re.IGNORECASE,
    ),
]
DATE_CLAIM_PATTERN = re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일")
AMOUNT_CLAIM_PATTERN = re.compile(r"(?:조원|억원|만원|천원|원)", re.IGNORECASE)


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
    if "시간" in normalized or "몇초" in normalized:
        return "seconds"
    return None


def metric_facts(question: str, results: list[SearchResult]) -> list[TableFact]:
    unit = requested_unit(question)
    if not unit:
        return []
    facts: list[TableFact] = []
    seen: set[tuple[str, str, float]] = set()
    for result in results:
        result_facts = extract_table_facts(result)
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
        if matching_facts:
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
    compound_markers = ("자동점수", "점수", "이유", "왜", "생략")
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
    metric_label = "평균 생성속도" if unit == "token/s" else "평균 시간"
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
        "display_label": "수치 근거 검증 통과",
        "requested_unit": unit,
        "facts": [fact.to_dict() for fact in facts],
        "issues": issues,
    }


def _normalized_claim(text: str) -> str:
    return re.sub(r"[\s,]", "", text).lower()


def extract_structured_claims(text: str) -> list[str]:
    claims: list[str] = []
    seen: set[str] = set()
    for pattern in STRUCTURED_PATTERNS:
        for match in pattern.finditer(text):
            claim = match.group().strip()
            normalized = _normalized_claim(claim)
            if normalized not in seen:
                claims.append(claim)
                seen.add(normalized)
    return claims


def structured_claim_types(claims: list[str]) -> list[str]:
    types: set[str] = set()
    for claim in claims:
        if DATE_CLAIM_PATTERN.fullmatch(claim):
            types.add("date")
        elif AMOUNT_CLAIM_PATTERN.search(claim):
            types.add("amount")
        else:
            types.add("metric")
    return sorted(types)


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

    evidence = _normalized_claim("\n".join(result.text for result in results))
    supported = [claim for claim in claims if _normalized_claim(claim) in evidence]
    unsupported = [claim for claim in claims if _normalized_claim(claim) not in evidence]
    claim_types = structured_claim_types(claims)
    issues = [f"근거 원문에서 확인되지 않은 값: {claim}" for claim in unsupported]
    return {
        "passed": not unsupported,
        "method": "structured_claim_verification",
        "display_label": (
            "수치 근거 검증 통과"
            if "metric" in claim_types
            else "금액·날짜·단위 검증 통과"
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
    if requested_unit(question):
        return verify_metric_answer(question, answer, results)
    return verify_structured_claims(answer, results)
