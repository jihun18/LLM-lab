from model_comparison import classify_path, summarize_rows


def test_generation_is_distinct_from_shared_service_paths():
    assert classify_path([{}], {"model": "qwen3:1.7b"}) == "llm_generation"
    assert classify_path([], {"model": "deterministic-table"}) == "deterministic_table"
    assert classify_path([], {"verification": {"method": "no_evidence"}}) == "no_evidence"


def test_non_generation_times_do_not_inflate_model_speed():
    rows = [{"generation_model": "test", "execution_path": "llm_generation", "elapsed_seconds": 30,
             "answer_score": 80, "tokens_per_second": 5},
            {"generation_model": "test", "execution_path": "no_evidence", "elapsed_seconds": 0,
             "answer_score": 100, "tokens_per_second": None}]
    result = summarize_rows(rows, "test")
    assert result["average_generation_seconds"] == 30
    assert result["average_generation_score"] == 80
    assert result["average_answer_score"] == 90
    assert result["average_tokens_per_second"] == 5
    assert result["non_generation_cases"] == 1
