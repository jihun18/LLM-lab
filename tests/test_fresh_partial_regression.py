"""Previously first-run cases are now development regressions, not holdout."""
import json
from pathlib import Path

import pytest

from compound_holdout import FixtureKnowledge
from core.knowledge_base import KnowledgeBase, SearchResult
from core.rag_service import rag_response, rag_stream_events, grounded_response, SOURCE_CITATION_PATTERN
from core.requirement_retrieval import requirement_source_answer, supplement_role_evidence

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = json.loads((ROOT / 'fresh_quality_cases.json').read_text(encoding='utf-8'))


class NoModel:
    def chat(self, *args): raise AssertionError('partial source copy must not generate')


def knowledge(case):
    if case['scope'] == 'wiki':
        kb = KnowledgeBase(ROOT / 'wiki')
        kb.reindex()
        return kb
    return FixtureKnowledge([SearchResult(x['source'], x['heading'], x['text'], 1)
                             for name in case['fixtures'] for x in PACKAGE['fixtures'][name]])


@pytest.mark.parametrize('case_id', ['q03', 'q04', 'q09', 'q10'])
@pytest.mark.parametrize('stream', [False, True])
def test_known_roles_preserved_but_unknown_requirements_stay_missing(case_id, stream):
    case = next(c for c in PACKAGE['cases'] if c['id'] == case_id)
    kb = knowledge(case)
    if stream:
        events = list(rag_stream_events(case['question'], 'test', None, 3, kb, NoModel()))
        body, sources, check = events[1]['content'], events[0]['sources'], events[-1]['verification']
        assert events[-1]['eval_count'] == 0
    else:
        response = rag_response(case['question'], 'test', None, 3, kb, NoModel())
        assert response['answer_status'] == 'partial'
        assert response['execution_path'] == 'deterministic_requirement_copy'
        assert response['eval_count'] == 0
        body, sources, check = response['answer'], response['sources'], response['verification']
    assert check['passed'] is None and check['missing_items']
    assert '질문 전체가 해결된 것은 아닙니다' in body
    expected = {'q03': ['Flask의 역할', 'Streamlit의 역할', '최소 메모리 사용량 (검색 근거 부족)'],
                'q04': ['FastAPI의 역할', 'Streamlit의 역할', 'Elysia의 역할 (검색 근거 부족)'],
                'q09': ['CedarApi의 역할', 'MapleView의 역할', '평균 메모리 사용량 (검색 근거 부족)'],
                'q10': ['CedarApi의 역할', 'MapleView의 역할', '이유의 원문 (검색 근거 부족)']}
    assert all(text in body for text in expected[case_id])
    assert not any(text in body for text in case.get('forbidden', []))
    cited = {(s.strip(), h.strip()) for s, h in SOURCE_CITATION_PATTERN.findall(body)}
    assert cited == {(x['source'], x['heading']) for x in sources}


ROLES = SearchResult('roles.md', '역할', '| 항목 | CedarApi | MapleView |\n|---|---|---|\n| 역할 | 문서 검색 API | 검토용 화면 |', 1)


@pytest.mark.parametrize('extra', ['CPU 사용률', '실행 포트', 'API 문서', '설계도', '실측값'])
def test_new_verbs_do_not_silently_drop_other_requirements(extra):
    assert requirement_source_answer(f'CedarApi와 MapleView의 역할과 {extra}을 정리해줘.', [ROLES]) is None


def test_conflict_is_not_overridden_by_new_partial_wording():
    other = SearchResult('other.md', '역할', '- CedarApi: 검색 화면', 1)
    copied = requirement_source_answer('CedarApi와 MapleView의 역할과 평균 메모리 사용량을 정리해줘.', [ROLES, other])
    answer, used, check = copied
    assert 'CedarApi의 역할 (원문 값 충돌)' in answer
    assert 'CedarApi의 역할: 문서 검색 API' not in answer
    assert 'MapleView의 역할: 검토용 화면' in answer
    assert all(x.source != 'other.md' for x in used)
    assert check['passed'] is None


def test_missing_year_is_still_rejected_before_copy():
    response = rag_response('2042년 CedarApi와 MapleView의 역할과 평균 메모리 사용량을 정리해줘.',
                            'test', None, 3, FixtureKnowledge([ROLES]), NoModel())
    assert response['verification']['method'] == 'no_evidence'
    assert response['sources'] == [] and '문서 검색 API' not in response['answer']


def test_disabled_extraction_keeps_frozen_context_memory_guard():
    response = grounded_response('CedarApi와 MapleView의 역할과 평균 메모리 사용량을 정리해줘.',
                                 'test', None, [ROLES], NoModel(), allow_text_extraction=False)
    assert response['verification']['method'] == 'memory_requirements_guard'
    assert '역할: 문서 검색 API' not in response['answer']


def test_new_wording_does_not_expand_followup_search_budget_or_change_mode():
    class Knowledge:
        def __init__(self): self.calls = []
        def search(self, query, top_k, **kwargs):
            self.calls.append((query, top_k, kwargs))
            return [ROLES]
    kb = Knowledge()
    _, trace = supplement_role_evidence('CedarApi와 MapleView의 역할과 평균 메모리 사용량을 정리해줘.',
                                       [ROLES], kb, 'hybrid')
    assert 0 < len(trace) <= 4
    assert all(n == 3 and kw == {'mode': 'hybrid'} for _, n, kw in kb.calls)
