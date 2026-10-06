import json
from compound_holdout import ROOT, score, OfflineClient, GenerationNeeded
import pytest

def test_holdout_has_unique_cases_and_separate_scopes():
    package = json.loads((ROOT / "compound_holdout_cases.json").read_text(encoding="utf-8"))
    cases = package["cases"]
    assert len(cases) == len({case["id"] for case in cases}) == 12
    assert sum(case["scope"] == "wiki" for case in cases) == 6
    assert sum(case["scope"] == "fixture" for case in cases) == 6
    for case in cases:
        assert case["required"]
        for name in case.get("fixtures", []):
            assert name in package["fixtures"]

def test_wrong_heading_fails_even_when_filename_matches():
    response = {"answer": "必要 [출처: a.md#틀린 절]", "sources": [{"source": "a.md", "heading": "정답 절"}]}
    assert score({"required": ["必要"], "sources": ["a.md#정답 절"]}, response)["status"] == "fail"

def test_missing_requirement_and_forbidden_value_each_fail():
    assert score({"required": ["확인하지 못한 항목"]}, {"answer": "답변", "sources": []})["status"] == "fail"
    assert score({"forbidden": ["9 token/s"]}, {"answer": "9 token/s", "sources": []})["status"] == "fail"

def test_offline_does_not_fake_generated_answer():
    with pytest.raises(GenerationNeeded):
        OfflineClient().chat("test", "model", None)

def test_automatic_pass_keeps_semantic_review_separate():
    row = score({"required": ["역할"], "semantic_review_required": True}, {"answer": "역할", "sources": []})
    assert row["status"] == "pass" and row["semantic_review_required"] is True
