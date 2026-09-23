from core.knowledge_base import SearchResult
from rag_evaluation import score_answer, score_retrieval, select_cases


CASE = {
    "expected_source": "answer.md",
    "expected_heading": "정답",
    "expected_keywords": ["BM25"],
    "expected_values": ["16GB"],
    "max_seconds": 10,
}
RESULT = SearchResult("answer.md", "정답", "BM25와 16GB", 5.0)


def test_retrieval_score_checks_top1_and_source_hit():
    score = score_retrieval([RESULT], CASE)
    assert score["top1_correct"] is True
    assert score["source_hit"] is True
    assert score["retrieval_score"] == 100.0


def test_retrieval_score_accepts_a_documented_alternative_source():
    case = {
        **CASE,
        "acceptable_sources": [{"source": "summary.md", "heading": "요약"}],
    }
    alternative = SearchResult("summary.md", "요약", "BM25와 16GB", 6.0)
    assert score_retrieval([alternative], case)["top1_correct"] is True


def test_answer_score_checks_content_source_and_latency():
    response = {
        "answer": "BM25는 16GB 환경에서 동작합니다.\n[출처: answer.md#정답]",
        "sources": [{"source": "answer.md", "heading": "정답"}],
        "verification": {"passed": True},
        "elapsed_seconds": 3.0,
    }
    score = score_answer(response, CASE)
    assert score["answer_score"] == 100.0
    assert score["citation_correct"] is True
    assert score["latency_passed"] is True


def test_no_evidence_case_rewards_abstention():
    case = {"expect_no_evidence": True, "max_seconds": 5}
    response = {
        "answer": "Wiki에서 관련 근거를 찾지 못했습니다.",
        "sources": [],
        "verification": {"method": "no_evidence", "passed": False},
        "elapsed_seconds": 0,
    }
    assert score_retrieval([], case)["retrieval_score"] == 100.0
    assert score_answer(response, case)["answer_score"] == 100.0


def test_select_cases_runs_only_requested_failures():
    cases = [{"id": "one"}, {"id": "two"}, {"id": "three"}]
    assert select_cases(cases, ["three", "one"], None) == [
        {"id": "one"},
        {"id": "three"},
    ]
