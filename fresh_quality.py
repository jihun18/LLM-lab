"""Frozen internal first-run evaluation; never tunes production or Wiki."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import subprocess
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

from compound_holdout import OfflineClient, GenerationNeeded, FixtureKnowledge, score
from core.knowledge_base import KnowledgeBase, SearchResult
from core.ollama_client import OllamaClient
from core.rag_service import rag_response

ROOT = Path(__file__).resolve().parent
CASES = ROOT / 'fresh_quality_cases.json'


def hashes():
    paths = [CASES, Path(__file__), ROOT / 'compound_holdout.py', ROOT / 'app.py', ROOT / 'config.py']
    paths += sorted((ROOT / 'core').glob('*.py')) + sorted((ROOT / 'wiki').rglob('*.md'))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def automatic_checks(case, response):
    # Hints only: never turn substring success into semantic correctness.
    checks = score(case, response)['checks']
    checks['text_groups'] = all(any(text in response['answer'] for text in group)
                               for group in case['groups'])
    checks['not_blocked_when_answerable'] = (case['target'] == 'refusal' or
                                             response.get('answer_status') != 'blocked')
    return checks


def review_text(package, report):
    cases = {c['id']: c for c in package['cases']}
    lines = ['# 새 질문 답변 검토표', '',
             '자동 통과는 정답 판정이 아니다. 각 문항의 원문·답변·요구 누락·오류를 대조한다.',
             '최종 분류: 정답 / 부분 답변 / 올바른 거절 / 잘못된 답변. 미실행·오류는 별도 보류.',
             '정답: 모든 요구를 근거와 정확히 연결. 부분 답변: 확인한 내용만 답하고 미확인을 명시.',
             '올바른 거절: 답할 근거가 없어 추측하지 않음. 잘못된 답변: 오인용·수치 대체·역할 교환·근거 없는 주장이 있음.',
             '안전하게 전부 차단했더라도 답할 근거가 있으면 요구 미충족을 기록한다.',
             '분류와 별도로 요구 충족: 전체 / 일부 / 미충족. 근거 오류: 있음 / 없음.',
             '모든 문항을 검토하기 전 최종 정확도·완료율은 계산하지 않는다.', '']
    for row in report['results']:
        case = cases[row['id']]
        lines += [f"## {row['id']} — {row['scope']} / 기대 근거: {case['target']}", '',
                  case['question'], '', f"실행 상태: {row['status']} (최종 의미 판정 아님)", '',
                  *['- ' + text for text in case['criteria']], '',
                  '답변:', row.get('response', {}).get('answer', row.get('reason', '')), '',
                  '검토할 근거(JSON):', json.dumps(row.get('response', {}).get('sources', []), ensure_ascii=False), '',
                  '최종 분류: 미검토', '요구 충족: 미검토', '근거 오류: 미검토',
                  '검토자 / 검토 일시 / 근거 대조 메모:', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='필요한 문항만 실제 모델 호출 (최대 문항별 90초)')
    parser.add_argument('--case-ids', nargs='+')
    args = parser.parse_args()
    package = json.loads(CASES.read_text(encoding='utf-8'))
    cases = package['cases']
    if args.case_ids:
        unknown = set(args.case_ids) - {c['id'] for c in cases}
        if unknown: parser.error('알 수 없는 문항: ' + ', '.join(sorted(unknown)))
        cases = [c for c in cases if c['id'] in args.case_ids]
    before = hashes()
    kb = KnowledgeBase(ROOT / 'wiki')
    kb.reindex()
    client = OllamaClient(timeout=90) if args.live else OfflineClient()
    rows = []
    for case in cases:
        knowledge = kb if case['scope'] == 'wiki' else FixtureKnowledge([
            SearchResult(x['source'], x['heading'], x['text'], 1)
            for key in case['fixtures'] for x in package['fixtures'][key]])
        start = monotonic()
        row = {'id': case['id'], 'scope': case['scope'], 'target': case['target'],
               'question': case['question'], 'semantic_classification': 'unreviewed'}
        try:
            response = rag_response(case['question'], 'qwen3:1.7b',
                                    'Wiki 근거만 사용하고 간결하고 정확한 한국어로 답하세요.',
                                    3, knowledge, client)
            checks = automatic_checks(case, response)
            row.update(response=response, checks=checks,
                       status='automatic_pass' if all(checks.values()) else 'automatic_mismatch')
        except GenerationNeeded as exc:
            row.update(status='pending_generation', reason=str(exc))
        except Exception as exc:
            row.update(status='error', reason=f'{type(exc).__name__}: {exc}')
        row['wall_seconds'] = round(monotonic()-start, 3)
        rows.append(row)
        print(f"{case['id']}: {row['status']}", flush=True)
    after = hashes()
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    report = {'protocol': {'created_at': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
              'git_head': git.stdout.strip() if git.returncode == 0 else None,
              'mode': 'live_if_needed' if args.live else 'offline', 'model': 'qwen3:1.7b',
              'search_mode': 'bm25', 'top_k': 3, 'fingerprints_before': before,
              'fingerprints_after': after, 'unchanged_after_run': before == after,
              'limits': 'Internal, not independent external evaluation. Fixtures bypass retrieval. No semantic accuracy inferred from automatic checks.'},
              'summary': {scope: dict(Counter(r['status'] for r in rows if r['scope'] == scope))
                          for scope in ('wiki', 'fixture')}, 'results': rows}
    output = ROOT / 'benchmark-results' / ('fresh-quality-' + datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d-%H%M%S-%f'))
    output.parent.mkdir(exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    output.with_suffix('.review.md').write_text(review_text(package, report), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))
    print(f"결과: {output.with_suffix('.json')}; 변경 없음: {report['protocol']['unchanged_after_run']}")
    return 0 if report['protocol']['unchanged_after_run'] and not any(r['status'] == 'error' for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
