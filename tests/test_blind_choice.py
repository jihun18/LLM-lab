from collections import Counter
import json

import pytest
import blind_choice as choice


def cases():
    return json.loads(choice.CASES.read_text(encoding='utf-8'))['cases']


def test_frozen_cases_balanced_and_new():
    own = cases()
    assert len(own) == len({x['id'] for x in own}) == 12
    assert Counter(x['category'] for x in own) == {'wiki': 4, 'summary': 4, 'practical': 4}
    assert sum(c['important'] for c in own) == 6
    prior = set()
    for path in choice.ROOT.glob('*cases.json'):
        if path == choice.CASES: continue
        data = json.loads(path.read_text(encoding='utf-8'))
        for c in data.get('cases', []) if isinstance(data, dict) else data:
            if 'question' in c: prior.add(c['question'])
    assert not {c['question'] for c in own} & prior


def test_sources_frozen_and_identical_prompt_hash_is_available():
    for c in cases():
        frozen = choice.freeze_case(c)
        assert len(frozen['prompt_sha256']) == 64
        assert frozen['prompt_sha256'] == choice.digest(frozen['prompt'].encode())
        assert frozen['evidence'] if c['category'] == 'wiki' else not frozen['evidence']


def test_source_traversal_rejected():
    with pytest.raises(ValueError):
        choice.freeze_case({'question': 'x', 'sources': [{'file': '../app.py', 'sections': ['x']}]})


def test_mapping_balanced_per_case_and_not_fixed_identity():
    mapping = choice.make_mapping(cases())
    assert Counter(v['A'] for v in mapping.values()) == {choice.MODELS[0]: 6, choice.MODELS[1]: 6}
    assert all(set(v.values()) == set(choice.MODELS) for v in mapping.values())


def test_public_sheet_does_not_expose_identity_or_timing():
    c = choice.freeze_case(cases()[0]); mapping = {c['id']: {'A': choice.MODELS[0], 'B': choice.MODELS[1]}}
    rows = [{'case_id': c['id'], 'model': m, 'answer': '간단한 답변', 'valid': True,
             'wall_seconds': 987.123} for m in choice.MODELS]
    text = choice.blind_sheet([c], rows, mapping)
    assert not any(m in text for m in choice.MODELS)
    assert '987.123' not in text and '선호: 미검토' in text
    assert '### 답변 A' in text and '### 답변 B' in text


def payload(**kwargs):
    return {'model': choice.MODELS[0], 'message': {'content': '답변'}, 'done': True,
            'eval_count': 10, 'prompt_eval_count': 100, 'done_reason': 'stop', **kwargs}


def test_only_actual_completed_generation_is_valid():
    assert choice.evaluate_payload(payload(), choice.MODELS[0])[1] == []
    assert 'incomplete' in choice.evaluate_payload(payload(eval_count=0), choice.MODELS[0])[1]


def test_wrong_model_not_silently_accepted():
    assert 'model_mismatch' in choice.evaluate_payload(payload(), choice.MODELS[1])[1]


def test_truncation_and_context_budget_are_explicit():
    assert 'not_natural_stop' in choice.evaluate_payload(payload(done_reason='length'), choice.MODELS[0])[1]
    assert 'context_budget' in choice.evaluate_payload(payload(prompt_eval_count=2000), choice.MODELS[0])[1]


def test_self_identification_marks_blinding_issue():
    _, reasons = choice.evaluate_payload(payload(message={'content': choice.MODELS[0]}), choice.MODELS[0])
    assert 'identity_disclosed' in reasons


def test_missing_response_keeps_review_pending():
    c = choice.freeze_case(cases()[0])
    mapping = {c['id']: {'A': choice.MODELS[0], 'B': choice.MODELS[1]}}
    sheet = choice.blind_sheet([c], [], mapping)
    assert '아직 실행하지 않음' in sheet and '선호: 미검토' in sheet
