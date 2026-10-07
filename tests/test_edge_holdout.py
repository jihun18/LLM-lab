import json
import hashlib
from compound_holdout import ROOT


def test_new_boundary_cases_do_not_repeat_previous_questions():
    package = json.loads((ROOT / "edge_holdout_cases.json").read_text(encoding="utf-8"))
    prior = json.loads((ROOT / "compound_holdout_cases.json").read_text(encoding="utf-8"))
    questions = [c["question"] for c in package["cases"]]
    assert len(questions) == len(set(questions)) == 12
    assert not set(questions) & {c["question"] for c in prior["cases"]}


def test_boundary_cases_keep_retrieval_and_fixture_scopes_separate():
    package = json.loads((ROOT / "edge_holdout_cases.json").read_text(encoding="utf-8"))
    assert sum(c["scope"] == "wiki" for c in package["cases"]) == 6
    assert sum(c["scope"] == "fixture" for c in package["cases"]) == 6
    for c in package["cases"]:
        assert c["required"]
        assert all(name in package["fixtures"] for name in c.get("fixtures", []))


def test_boundary_definition_has_sha256_fingerprint():
    digest = hashlib.sha256((ROOT / "edge_holdout_cases.json").read_bytes()).hexdigest()
    assert len(digest) == 64
