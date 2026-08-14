from evaluation import korean_ratio, numbered_item_count, score_response, sentence_count


def test_text_metrics():
    assert korean_ratio("한국어 문장입니다.") == 1.0
    assert sentence_count("첫 문장입니다. 두 번째 문장입니다.") == 2
    assert sentence_count("1. 첫 문장입니다.\n2. 두 번째 문장입니다.") == 2
    assert numbered_item_count("1. 로컬 처리\n2. 암호화\n3. 접근 제어") == 3
    assert numbered_item_count("[1] 로컬 처리\n[2] 암호화\n[3] 접근 제어") == 3


def test_score_response_combines_checks():
    case = {
        "require_korean": True,
        "expected_sentence_count": 2,
        "expected_keywords": ["메모리", "로컬"],
    }
    answer = "메모리 요구량이 작습니다. 로컬 실행이 가능합니다."
    result = score_response(answer, case)
    assert result["auto_score"] == 100.0
    assert result["checks"]["sentence_count"]["passed"] is True
