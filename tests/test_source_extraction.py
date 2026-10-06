import pytest
from pathlib import Path
from core.source_extraction import deterministic_text_answer
from core.knowledge_base import KnowledgeBase, SearchResult
from core.rag_service import grounded_response, rag_response, rag_stream_events
from model_comparison import classify_path

ROLES = SearchResult("roles.md", "결론", "- 정식 REST API와 백엔드: **FastAPI**\n- 빠른 AI 기능 검증과 발표 시연: **Streamlit**\n- 웹 프레임워크 원리 학습과 최소 구현: **Flask**", 1)
STATES = SearchResult("states.md", "화면 상태", "- `✅ 표 수치 검증 통과`\n- `✅ 금액·날짜·단위 검증 통과`\n- `⚠️ 검증 실패`\n- `ℹ️ 출처 연결됨 · 문장 의미는 사람 검토 필요`", 1)

class NoModel:
    def chat(self, *args, **kwargs):
        raise AssertionError("원문 추출은 모델을 호출하지 않아야 합니다.")


def test_role_copy_keeps_entities_attached_to_source_roles():
    response = grounded_response("FastAPI, Flask, Streamlit의 용도를 알려줘", "qwen3:1.7b", None, [ROLES], NoModel())
    assert "Flask: 웹 프레임워크 원리 학습과 최소 구현" in response["answer"]
    assert "Streamlit: 빠른 AI 기능 검증과 발표 시연" in response["answer"]
    assert response["model"] == "deterministic-text"
    assert response["tokens_per_second"] is None
    assert response["verification"]["passed"] is True
    assert classify_path([], response) == "deterministic_text"


def test_four_phrases_are_copied_and_only_used_source_is_shown():
    response = grounded_response("자동 검증 결과 화면에 나타나는 네 가지 상태 문구를 적어주세요.", "test", None, [STATES, ROLES], NoModel())
    assert len(response["verification"]["items"]) == 4
    assert "ℹ️ 출처 연결됨 · 문장 의미는 사람 검토 필요" in response["answer"]
    assert [s["source"] for s in response["sources"]] == ["states.md"]


@pytest.mark.parametrize("question", [
    "FastAPI와 Flask의 역할과 차이를 설명해줘",
    "FastAPI, Flask, Django의 용도는?",
    "FastAPI, Flask의 역할과 속도는?",
    "2026년 FastAPI와 Flask의 역할은?",
    "FastAPI와 Flask의 역할을 예시와 함께 알려줘",
    "FastAPI와 Flask의 역할과 사용 포트는?",
    "FastAPI와 Flask의 역할 중 Flask는 빼고 알려줘",
    "문서를 요약해줘",
    "화면의 상태 문구 두 가지를 알려줘",
    "네 가지 메뉴 문구를 알려줘",
])
def test_unsupported_questions_do_not_silently_receive_partial_answer(question):
    assert deterministic_text_answer(question, [ROLES, STATES]) is None


def test_conflicting_sources_and_empty_evidence_fall_back():
    conflicting = SearchResult("other.md", "결론", "- 발표 시연: **Flask**", 1)
    assert deterministic_text_answer("FastAPI와 Flask의 역할은?", [ROLES, conflicting]) is None
    assert deterministic_text_answer("FastAPI와 Flask의 역할은?", []) is None


def test_generation_comparison_can_explicitly_bypass_extraction():
    class Client:
        def chat(self, *args):
            return {"answer": "FastAPI는 REST API, Flask는 최소 구현입니다.", "elapsed_seconds": 1}
    response = grounded_response("FastAPI와 Flask의 역할은?", "test", None, [ROLES], Client(), allow_text_extraction=False)
    assert response.get("model") != "deterministic-text"


@pytest.mark.parametrize("question,kind", [
    ("FastAPI, Flask, Streamlit을 이 프로젝트에서는 각각 무슨 용도로 사용하나요?", "role_pairs"),
    ("PrivAI에서 FastAPI와 Streamlit의 역할을 알려줘", None),
    ("자동 검증 결과 화면에 나타나는 네 가지 상태 문구를 적어주세요.", "verbatim_list"),
    ("검증 화면의 상태 문구 4가지를 그대로 적어줘", "verbatim_list"),
])
def test_real_wiki_bm25_service_and_stream_without_llm(question, kind):
    knowledge = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    knowledge.reindex()
    if kind is None:
        # A related but non-contract primary section must not be bypassed just
        # because a lower-ranked section has a convenient list.
        assert deterministic_text_answer(question, knowledge.search(question, 3)) is None
        return
    response = rag_response(question, "qwen3:1.7b", None, 3, knowledge, NoModel())
    assert response["verification"]["kind"] == kind
    assert len(response["sources"]) == 1
    events = list(rag_stream_events(question, "qwen3:1.7b", None, 3, knowledge, NoModel()))
    assert any(event.get("verification", {}).get("method") == "deterministic_text_extraction" for event in events)
