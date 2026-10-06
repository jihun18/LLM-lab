from pathlib import Path
import pytest
from core.knowledge_base import KnowledgeBase, SearchResult
from core.query_requirements import role_requirements
from core.requirement_retrieval import requirement_source_answer
from core.rag_service import rag_response

ROLE = SearchResult("roles.md", "역할", "- TaskApi: 문서 API\n- LabUi: 실험 화면", 1)

def test_plain_role_list_recognized_but_numeric_note_is_not():
    assert role_requirements("TaskApi와 LabUi의 업무와 메모리 사용량", [ROLE])
    amounts = SearchResult("notes.md", "메모", "- TaskApi: 12 GB\n- LabUi: 이름만 기록", 1)
    assert role_requirements("TaskApi와 LabUi의 업무와 메모리 사용량", [amounts]) is None

def test_missing_memory_is_not_replaced_by_system_ram_or_model_size():
    notes = SearchResult("notes.md", "메모리", "PC RAM 16 GB. 모델 파일 크기 4.7 GB.", 1)
    answer, used, check = requirement_source_answer("TaskApi와 LabUi의 업무와 메모리 사용량도 알려줘", [ROLE, notes])
    assert "문서 API" in answer and "실험 화면" in answer
    assert "16 GB" not in answer and "4.7 GB" not in answer
    assert len(check["missing_items"]) == 2
    assert used == [ROLE]

def test_measured_memory_rows_keep_conditions():
    measured = SearchResult("memory.md", "동일 환경 실측", "| 도구 | 모델 | 메모리 사용량 |\n|---|---|---|\n| TaskApi | demo:2b | 150 MB |\n| LabUi | demo:2b | 210 MB |", 1)
    answer, _, check = requirement_source_answer("TaskApi와 LabUi의 업무와 메모리 사용량도 알려줘", [ROLE, measured])
    assert "150 MB" in answer and "210 MB" in answer and "demo:2b" in answer
    assert not check["missing_items"]

def test_conflicting_memory_rows_are_not_arbitrarily_chosen():
    table = "| 도구 | RSS |\n|---|---|\n| TaskApi | 150 MB |\n| LabUi | 210 MB |"
    a = SearchResult("a.md", "실측", table, 1)
    b = SearchResult("b.md", "실측", table.replace("150 MB", "300 MB"), 1)
    answer, _, check = requirement_source_answer("TaskApi와 LabUi의 업무와 메모리 사용량", [ROLE, a, b])
    assert "150 MB" not in answer and "300 MB" not in answer
    assert "TaskApi의 대상별 메모리 사용량 (원문 값 충돌)" in check["missing_items"]

def test_conflicting_plain_roles_are_not_arbitrarily_chosen():
    other = SearchResult("other.md", "다른 역할", "- TaskApi: 실험 화면\n- LabUi: 실험 화면", 1)
    answer, _, check = requirement_source_answer("TaskApi와 LabUi의 업무와 메모리 사용량", [ROLE, other])
    assert "TaskApi의 역할 (원문 값 충돌)" in check["missing_items"]

@pytest.mark.parametrize("question,expected", [
    ("Flask와 Streamlit의 업무와 응답 속도는 어때?", "전체 응답속도의 동일 조건 비교 근거"),
    ("Flask와 Streamlit은 어떤 일을 하며 메모리 사용량도 알려줘.", "Flask의 대상별 메모리 사용량 (검색 근거 부족)"),
])
def test_live_failures_become_partial_regressions_without_generation(question, expected):
    class NoModel:
        def chat(self, *args):
            raise AssertionError("no generation expected")
    kb = KnowledgeBase(Path(__file__).resolve().parents[1] / "wiki")
    kb.reindex()
    response = rag_response(question, "test", None, 3, kb, NoModel())
    assert response["execution_path"] == "deterministic_requirement_copy"
    assert response["answer_status"] == "partial"
    assert expected in response["answer"]
    assert response["verification"]["passed"] is None
