import json
from collections import Counter

import fresh_quality as quality


def package():
    return json.loads(quality.CASES.read_text(encoding='utf-8'))


def test_question_set_is_new_against_all_existing_case_files():
    cases = package()['cases']
    questions = [c['question'].strip().casefold() for c in cases]
    assert len(set(questions)) == len(questions) == 12
    prior = set()
    for path in quality.ROOT.glob('*cases.json'):
        if path == quality.CASES: continue
        data = json.loads(path.read_text(encoding='utf-8'))
        for c in data.get('cases', []) if isinstance(data, dict) else data:
            if 'question' in c: prior.add(c['question'].strip().casefold())
    assert not set(questions) & prior


def test_scopes_and_targets_are_balanced_and_fixtures_valid():
    p = package()
    assert Counter(c['scope'] for c in p['cases']) == {'wiki': 6, 'fixture': 6}
    assert Counter(c['target'] for c in p['cases']) == {'full': 4, 'partial': 4, 'refusal': 4}
    assert len({c['id'] for c in p['cases']}) == 12
    for c in p['cases']:
        assert c['groups'] and c['criteria']
        assert all(g and all(isinstance(x, str) and x for x in g) for g in c['groups'])
        assert all(key in p['fixtures'] for key in c.get('fixtures', []))


def response(answer='first', status='source_copied'):
    return {'answer': answer, 'answer_status': status, 'sources': []}


def test_text_group_alternatives_are_supported_without_semantic_score():
    case = {'target': 'full', 'groups': [['first', 'second']]}
    checks = quality.automatic_checks(case, response('second'))
    assert all(checks.values())
    assert not quality.automatic_checks(case, response('other'))['text_groups']
    assert 'semantic_classification' not in checks


def test_forbidden_claim_is_flagged():
    case = {'target': 'partial', 'groups': [['known']], 'forbidden': ['made up']}
    assert not quality.automatic_checks(case, response('known but made up'))['forbidden_text_absent']


def test_blocked_answerable_request_does_not_count_as_fulfillment():
    case = {'target': 'full', 'groups': [['first']]}
    assert not quality.automatic_checks(case, response(status='blocked'))['not_blocked_when_answerable']
    case['target'] = 'refusal'
    assert quality.automatic_checks(case, response(status='blocked'))['not_blocked_when_answerable']


def test_review_is_unreviewed_even_for_automatic_pass():
    p = package(); c = p['cases'][0]
    report = {'results': [{'id': c['id'], 'scope': c['scope'], 'status': 'automatic_pass',
                           'response': response()}]}
    text = quality.review_text(p, report)
    assert '최종 분류: 미검토' in text and '정확도' in text
    assert all(x in text for x in ('정답', '부분 답변', '올바른 거절', '잘못된 답변'))


def test_pending_generation_remains_visible_in_review():
    p = package(); c = p['cases'][0]
    text = quality.review_text(p, {'results': [{'id': c['id'], 'scope': c['scope'],
                               'status': 'pending_generation', 'reason': '실제 생성 필요'}]})
    assert 'pending_generation' in text and '실제 생성 필요' in text


def test_fingerprints_cover_cases_runner_production_wiki_and_shared_scorer():
    fingerprints = quality.hashes()
    assert {'fresh_quality.py', 'fresh_quality_cases.json', 'compound_holdout.py', 'app.py'} <= fingerprints.keys()
    assert any(k.startswith('core/') for k in fingerprints)
    assert any(k.startswith('wiki/') for k in fingerprints)
    assert all(len(v) == 64 for v in fingerprints.values())
