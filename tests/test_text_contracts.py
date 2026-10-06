from core.grounding import verify_grounded_answer
from core.knowledge_base import SearchResult
from core.text_contracts import verify_text_contracts

ROLES = SearchResult("roles.md", "결론", "- 정식 REST API와 백엔드: **FastAPI**\n- 빠른 AI 기능 검증과 발표 시연: **Streamlit**\n- 웹 프레임워크 원리 학습과 최소 구현: **Flask**", 1)
STATES = SearchResult("states.md", "화면 상태", "- `✅ 표 수치 검증 통과`\n- `✅ 금액·날짜·단위 검증 통과`\n- `⚠️ 검증 실패`\n- `ℹ️ 출처 연결됨 · 문장 의미는 사람 검토 필요`", 1)
Q = "FastAPI, Flask, Streamlit은 각각 무슨 용도로 쓰나요?"


def test_swapped_roles_fail_even_when_all_keywords_exist():
    result = verify_grounded_answer(Q, "FastAPI는 REST API와 백엔드. Flask는 빠른 AI 기능 검증과 발표 시연. Streamlit은 원리 학습과 최소 구현.", [ROLES])
    assert result["passed"] is False
    assert len(result["issues"]) == 2


def test_added_incorrect_role_also_fails():
    assert verify_text_contracts(Q, "FastAPI는 REST API와 발표 시연에 쓰인다.", [ROLES])["passed"] is False


def test_correct_roles_do_not_claim_full_semantic_pass():
    result = verify_text_contracts(Q, "FastAPI는 REST API로, Flask는 최소 구현 비교로, Streamlit은 발표 시연으로 쓴다.", [ROLES])
    assert result["passed"] is None
    assert result["issues"] == []


def test_role_before_next_entity_is_not_attached_to_previous_entity():
    answer = "FastAPI는 정식 REST API와 백엔드 역할을 수행하며, 빠른 AI 기능 검증과 발표 시연에는 Streamlit을 사용하고, 웹 프레임워크 원리 학습과 최소 구현에는 Flask을 사용한다."
    assert verify_text_contracts(Q, answer, [ROLES])["issues"] == []
    answer = "FastAPI는 백엔드이며 빠른 AI 기능 검증과 발표 시연에는 Streamlit을 사용한다."
    assert verify_text_contracts(Q, answer, [ROLES])["issues"] == []


def test_unknown_paraphrase_and_negation_need_review_not_failure():
    assert verify_text_contracts(Q, "Flask는 교육용이고 Streamlit은 시연용이다.", [ROLES])["passed"] is None
    assert verify_text_contracts(Q, "Flask는 발표 시연이 아니라 최소 구현이다.", [ROLES])["passed"] is None


def test_missing_fourth_phrase_fails():
    answer = "표 수치 검증 통과, 금액·날짜·단위 검증 통과, 검증 실패"
    assert verify_grounded_answer("네 가지 상태 문구를 적어줘", answer, [STATES])["passed"] is False


def test_icons_and_spacing_are_not_mandatory():
    answer = STATES.text.replace("✅", "").replace("⚠️", "").replace("ℹ️", "")
    assert verify_text_contracts("4가지 상태 문구를 적어줘", answer, [STATES])["issues"] == []


def test_unrelated_or_count_mismatch_does_not_trigger():
    assert verify_text_contracts("검증을 설명해줘", "설명", [STATES]) is None
    assert verify_text_contracts("두 가지 상태 문구를 적어줘", "설명", [STATES]) is None


def test_numeric_failure_is_preserved():
    result = verify_grounded_answer(Q, "FastAPI는 RAM 999GB를 쓴다.", [ROLES])
    assert result["passed"] is False
    assert result["numeric_verification"]["passed"] is False
