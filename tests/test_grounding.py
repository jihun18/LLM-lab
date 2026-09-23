from core.grounding import (
    deterministic_metric_answer,
    extract_table_facts,
    requested_unit,
    verify_grounded_answer,
    verify_metric_answer,
    verify_structured_claims,
)
from core.knowledge_base import SearchResult
from core.rag_service import validate_source_citations


RESULT = SearchResult(
    source="benchmark.md",
    heading="요약",
    score=10.0,
    text="""| 모델 | 평균 시간 | 평균 token/s | 자동점수 |
|---|---:|---:|---:|
| qwen3:0.6b | 2.814초 | 24.45 | 80.0 |
| qwen3:1.7b | 7.205초 | 10.28 | 80.0 |""",
)

FOUR_B_RESULT = SearchResult(
    source="4b.md",
    heading="4B 전체 평가",
    score=12.0,
    text="""| 모델 | 문항 | 평균 시간 | 평균 속도 | 평균 자동점수 |
|---|---:|---:|---:|---:|
| qwen3:4b-instruct | 5 | 16.038초 | 5.00 token/s | 83.3 |""",
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


def test_average_speed_header_and_requested_model_are_selected():
    question = "4B Instruct 전체 평가의 평균 생성속도는 몇 token/s야?"
    answer, verification = deterministic_metric_answer(question, [FOUR_B_RESULT, RESULT])
    assert "qwen3:4b-instruct가 5.00 token/s" in answer
    assert "24.45" not in answer
    assert verification["facts"][0]["source"] == "4b.md"


def test_compound_question_is_not_reduced_to_one_metric():
    question = "4B 평균 속도와 자동점수는 얼마고 7B 평가를 생략한 이유는?"
    assert deterministic_metric_answer(question, [FOUR_B_RESULT]) is None


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
    assert verification["display_label"] == "금액·날짜·단위 검증 통과"
    assert verification["claim_types"] == ["amount", "date"]
    assert verification["supported_claims"] == ["2026년 9월 30일", "월 10만원"]


def test_benchmark_metrics_use_numeric_verification_label():
    result = SearchResult(
        source="benchmark.md",
        heading="16GB 결과",
        text="7B 평균 응답시간은 28.539초이고 평균 생성속도는 3.80 token/s다.",
        score=5.0,
    )
    verification = verify_structured_claims(
        "7B 평균 응답시간은 28.539초이고 평균 생성속도는 3.80 token/s입니다.",
        [result],
    )
    assert verification["passed"] is True
    assert verification["display_label"] == "수치 근거 검증 통과"
    assert verification["claim_types"] == ["metric"]


def test_unsupported_amount_fails_verification():
    result = SearchResult("policy.md", "정책", "지원금은 월 10만원이다.", 5.0)
    verification = verify_structured_claims("지원금은 월 20만원입니다.", [result])
    assert verification["passed"] is False
    assert verification["unsupported_claims"] == ["월 20만원"]


def test_general_sentence_is_not_overstated_as_verified():
    verification = verify_structured_claims("FastAPI가 주력 백엔드입니다.", [RESULT])
    assert verification["passed"] is None
    assert verification["method"] == "source_attached_semantic_review_needed"


def test_placeholder_source_is_removed_from_abstention():
    answer, verification = validate_source_citations(
        "Wiki에서 근거를 찾지 못했습니다.\n[출처: 파일명#제목]",
        [RESULT],
    )
    assert answer == "Wiki에서 근거를 찾지 못했습니다."
    assert verification["method"] == "model_abstained"


def test_unretrieved_source_is_blocked():
    answer, verification = validate_source_citations(
        "답변입니다.\n[출처: other.md#다른 문서]",
        [RESULT],
    )
    assert "차단했습니다" in answer
    assert verification["method"] == "invalid_source_citation"


def test_missing_citation_gets_primary_retrieved_source():
    answer, verification = validate_source_citations("근거 기반 답변입니다.", [RESULT])
    assert answer.endswith("[출처: benchmark.md#요약]")
    assert verification is None


def test_retrieved_source_citation_is_allowed():
    answer = "답변입니다.\n출처: [출처: benchmark.md#요약]"
    checked, verification = validate_source_citations(answer, [RESULT])
    assert checked == "답변입니다.\n[출처: benchmark.md#요약]"
    assert verification is None
