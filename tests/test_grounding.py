from core.grounding import (
    deterministic_metric_answer,
    extract_table_facts,
    requested_unit,
    verify_grounded_answer,
    verify_metric_answer,
    verify_structured_claims,
)
from core.knowledge_base import SearchResult


RESULT = SearchResult(
    source="benchmark.md",
    heading="요약",
    score=10.0,
    text="""| 모델 | 평균 시간 | 평균 token/s | 자동점수 |
|---|---:|---:|---:|
| qwen3:0.6b | 2.814초 | 24.45 | 80.0 |
| qwen3:1.7b | 7.205초 | 10.28 | 80.0 |""",
)


def test_extracts_labeled_table_facts():
    facts = extract_table_facts(RESULT)
    assert [(fact.unit, fact.value) for fact in facts] == [
        ("seconds", 2.814),
        ("token/s", 24.45),
        ("seconds", 7.205),
        ("token/s", 10.28),
    ]


def test_speed_question_uses_token_column_not_seconds():
    question = "0.6B와 1.7B 평균 속도는 얼마야?"
    generated = deterministic_metric_answer(question, [RESULT])
    assert generated is not None
    answer, verification = generated
    assert "24.45 token/s" in answer
    assert "10.28 token/s" in answer
    assert "2.814초" not in answer
    assert verification["passed"] is True
    assert verify_metric_answer(question, answer, [RESULT])["passed"] is True


def test_time_question_uses_seconds_column():
    question = "두 모델의 평균 시간은 얼마야?"
    answer, _ = deterministic_metric_answer(question, [RESULT])
    assert "2.814 초" in answer
    assert "7.205 초" in answer
    assert "24.45" not in answer
    assert requested_unit(question) == "seconds"


def test_amount_and_date_claims_are_checked_against_source():
    result = SearchResult(
        source="policy.md",
        heading="지원 정책",
        score=9.0,
        text="청년 지원금은 월 10만원이며 신청 마감일은 2026년 9월 30일이다.",
    )
    answer = "지원금은 월 10만원이고 마감일은 2026년 9월 30일입니다."
    verification = verify_grounded_answer("지원금과 마감일은?", answer, [result])
    assert verification["passed"] is True
    assert verification["supported_claims"] == ["2026년 9월 30일", "월 10만원"]


def test_unsupported_amount_fails_verification():
    result = SearchResult("policy.md", "정책", "지원금은 월 10만원이다.", 5.0)
    verification = verify_structured_claims("지원금은 월 20만원입니다.", [result])
    assert verification["passed"] is False
    assert verification["unsupported_claims"] == ["월 20만원"]


def test_general_sentence_is_not_overstated_as_verified():
    verification = verify_structured_claims("FastAPI가 주력 백엔드입니다.", [RESULT])
    assert verification["passed"] is None
    assert verification["method"] == "source_attached_semantic_review_needed"
