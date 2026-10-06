import pytest
import json
import httpx
from core.ollama_client import OllamaClient
from core.knowledge_base import SearchResult, build_grounded_prompt
from core.rag_service import validate_source_citations, grounded_response

ROWS = [SearchResult("11-v0.1.0-Milestone.md", "1. 웹 프레임워크 실험", "웹 프레임워크 실험", 1),
        SearchResult("02-Framework-Comparison.md", "구현 비교", "FastAPI는 주력 REST API, Flask는 최소 비교군", .5)]


def test_selected_number_resolves_exact_version_heading_and_only_selected_source():
    answer, verification = validate_source_citations("역할 차이를 설명합니다. [출처: 근거 2]", ROWS, require_explicit=True)
    assert verification is None
    assert answer.endswith("[출처: 02-Framework-Comparison.md#구현 비교]")
    assert "Milestone" not in answer


@pytest.mark.parametrize("citation", ["[출처: 근거 0]", "[출처: 근거 3]", "[출처: 근거 -1]", "[출처: 근거 abc]"])
def test_unknown_ids_are_blocked_not_replaced_with_first_source(citation):
    answer, verification = validate_source_citations("설명 " + citation, ROWS, require_explicit=True)
    assert verification["passed"] is False
    assert verification["method"] == "invalid_source_id"
    assert "Milestone" not in answer


def test_valid_id_does_not_hide_invalid_filename_in_same_answer():
    answer, verification = validate_source_citations("설명 [출처: 근거 2] [출처: 11-v0.0.0-milestone.md#1. 웹 프레임워크 실험]", ROWS, require_explicit=True)
    assert verification["method"] == "invalid_source_citation"
    assert "차단" in answer


def test_missing_selection_is_not_automatically_attached_in_strict_mode():
    _, verification = validate_source_citations("FastAPI는 주력 REST API입니다.", ROWS, require_explicit=True)
    assert verification["method"] == "missing_source_citation"


def test_strict_mode_does_not_guess_section_of_known_filename():
    _, verification = validate_source_citations("설명 [출처: 02-Framework-Comparison.md#임의 제목]", ROWS, require_explicit=True)
    assert verification["method"] == "invalid_source_citation"


def test_abstention_without_selection_remains_valid_abstention():
    answer, verification = validate_source_citations("Wiki에서 근거를 찾지 못했습니다.", ROWS, require_explicit=True)
    assert verification["method"] == "model_abstained"


def test_scope_uses_only_actually_sent_results():
    class Client:
        def chat(self, prompt, model, system):
            assert "[출처: 근거 2]" not in prompt
            return {"answer": "설명 [출처: 근거 2]", "elapsed_seconds": 1}
    response = grounded_response("설명해줘", "test", None, ROWS, Client(), context_mode="primary")
    assert response["verification"]["method"] == "invalid_source_id"


def test_prompt_requests_ids_not_filename_regeneration():
    prompt = build_grounded_prompt("차이를 알려줘", ROWS)
    assert "출처 파일명이나 절 제목을 직접 쓰지 말고" in prompt
    assert "[출처: 근거 1]" in prompt
    assert "[출처: 11-v0.1.0-Milestone.md#" not in prompt


def test_valid_selection_does_not_mean_role_claim_is_correct():
    roles = SearchResult("roles.md", "결론", "- 정식 REST API와 백엔드: **FastAPI**\n- 빠른 AI 기능 검증과 발표 시연: **Streamlit**\n- 웹 프레임워크 원리 학습과 최소 구현: **Flask**", .1)
    class Client:
        def chat_with_sources(self, *args):
            return {"answer": json.dumps({"answer": "Flask는 빠른 AI 기능 검증과 발표 시연입니다.", "source_id": 1}), "elapsed_seconds": 1}
    response = grounded_response("FastAPI, Flask, Streamlit의 역할과 차이는?", "test", None, ROWS + [roles], Client())
    assert response["verification"]["passed"] is False
    assert response["verification"]["method"] == "source_text_contract_validation"


def test_real_client_sends_schema_and_service_resolves_selected_id():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["format"]["properties"]["source_id"]["enum"] == [0, 1, 2]
        return httpx.Response(200, json={"message": {"content": json.dumps({"answer": "FastAPI는 REST API, Flask는 최소 비교군입니다.", "source_id": 2})}})
    client = OllamaClient(transport=httpx.MockTransport(handler))
    response = grounded_response("역할과 차이를 알려줘", "test", None, ROWS, client)
    assert response["answer"].endswith("[출처: 02-Framework-Comparison.md#구현 비교]")
    assert len(response["sources"]) == 1
    assert response["verification"]["passed"] is None


@pytest.mark.parametrize("data", [
    {"answer": "설명", "source_id": True},
    {"answer": "설명", "source_id": 3},
    {"answer": "설명", "source_id": 0},
    {"answer": "설명"},
    {"answer": "설명", "source_id": 1, "extra": "임의"},
    {"answer": "설명 [출처: other.md#제목]", "source_id": 1},
    "깨진 JSON",
])
def test_structured_output_revalidated_on_server(data):
    class Client:
        def chat_with_sources(self, *args):
            return {"answer": json.dumps(data) if not isinstance(data, str) else data, "elapsed_seconds": 1}
    response = grounded_response("차이를 설명해줘", "test", None, ROWS, Client())
    assert response["verification"]["method"] == "invalid_structured_citation"
    assert response["sources"] == []
