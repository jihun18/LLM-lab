"""One bounded local comparison. Blind sheet and reveal key stay separate."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parent
CASES = ROOT / 'blind_choice_cases.json'
MODELS = ('qwen3:4b-instruct', 'qwen2.5:7b-instruct')
OPTIONS = {'num_ctx': 2048, 'num_predict': 256, 'temperature': 0.3, 'seed': 42}
SYSTEM = '간결하고 정확한 한국어로 지시를 따르세요. 제공된 자료가 있으면 그 범위를 지키고 모르는 사실은 만들지 마세요. 자신이나 후보의 모델명은 언급하지 마세요.'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def freeze_case(case):
    evidence = []
    for spec in case.get('sources', []):
        path = (ROOT / 'wiki' / spec['file']).resolve()
        if not path.is_relative_to((ROOT / 'wiki').resolve()): raise ValueError('invalid source path')
        text = path.read_text(encoding='utf-8')
        for section in spec['sections']:
            marker = '## ' + section + '\n'
            if marker not in text: raise ValueError('missing section: ' + section)
            body = text.split(marker, 1)[1].split('\n## ', 1)[0].strip()
            evidence.append({'source': spec['file'], 'heading': section, 'text': body})
    context = '\n\n'.join(f"[근거 {i}] {x['source']}#{x['heading']}\n{x['text']}"
                           for i, x in enumerate(evidence, 1)) or case['text']
    prompt = case['question'] + '\n\n[제공 자료]\n' + context
    if evidence: prompt += '\n\n자료에서 확인한 내용의 출처를 [근거 번호]로 표시하세요.'
    return {**case, 'evidence': evidence, 'prompt': prompt, 'prompt_sha256': digest(prompt.encode())}


def make_mapping(cases):
    indices = list(range(len(cases)))
    secrets.SystemRandom().shuffle(indices)
    a_first = set(indices[:len(cases)//2])
    return {case['id']: {'A': MODELS[0] if i in a_first else MODELS[1],
                         'B': MODELS[1] if i in a_first else MODELS[0]}
            for i, case in enumerate(cases)}


def blind_sheet(cases, rows, mapping):
    lookup = {(r['case_id'], r['model']): r for r in rows}
    lines = ['# A/B 답변 품질 검토표', '',
             '모델명·응답시간·용량은 공개 파일에만 있다. 품질 판정 전 공개 파일을 열지 않는다.',
             '각 문항에서 정확성/요구 충족/명료성을 각각 0(문제 큼), 1(일부), 2(충족)로 평가한다.',
             '중대 오류: 근거 없는 핵심 주장, 숫자/조건/대상 교환, 금지된 파괴적 조치 등.',
             '선호: A / B / 동점 / 보류. 작은 문체 차이보다 정확성과 요구 충족을 우선한다.',
             '잘린 답변·실패 응답은 따로 표시하고 정상 완료 쌍과 섞지 않는다. 사람 판정 전 추천하지 않는다.', '']
    for case in cases:
        lines += [f"## {case['id']} — {case['category']} / {'중요' if case['important'] else '일반'}", '',
                  case['prompt'], '', '검토 기준:', *['- ' + x for x in case['criteria']], '']
        for label in ('A', 'B'):
            row = lookup.get((case['id'], mapping[case['id']][label]))
            lines += [f'### 답변 {label}', '', row.get('answer', '응답 실패') if row else '아직 실행하지 않음', '']
            if row and not row['valid']: lines += ['주의: 완료/출력 한도/문맥/응답 검증을 충족하지 못한 답변', '']
        lines += ['A: 정확성 __/2 · 요구 충족 __/2 · 명료성 __/2 · 중대 오류 있음/없음',
                  'B: 정확성 __/2 · 요구 충족 __/2 · 명료성 __/2 · 중대 오류 있음/없음',
                  '선호: 미검토', '근거 대조 메모:', '']
    return '\n'.join(lines)


def evaluate_payload(data, model):
    answer = data.get('message', {}).get('content', '')
    reasons = []
    if data.get('model') != model: reasons.append('model_mismatch')
    if data.get('done') is not True or not answer.strip() or data.get('eval_count', 0) <= 0: reasons.append('incomplete')
    if data.get('done_reason') != 'stop': reasons.append('not_natural_stop')
    if data.get('prompt_eval_count', 0) > OPTIONS['num_ctx']-OPTIONS['num_predict']: reasons.append('context_budget')
    if any(name in answer for name in MODELS): reasons.append('identity_disclosed')
    return answer, reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='설치된 두 모델로만 24개 답변 생성')
    parser.add_argument('--output', help='존재하지 않는 결과 폴더 (기존 결과 덮어쓰기 금지)')
    args = parser.parse_args()
    package = json.loads(CASES.read_text(encoding='utf-8'))
    cases = [freeze_case(c) for c in package['cases']]
    if not args.run:
        print(f'계획 검증: {len(cases)}문항, 24개 생성. 모델 호출 없음. --run으로 실행.')
        return 0
    target = Path(args.output) if args.output else ROOT / 'benchmark-results' / ('blind-choice-' + datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d-%H%M%S-%f'))
    target.mkdir(parents=True, exist_ok=False)
    mapping, rows = make_mapping(cases), []
    files = [CASES, Path(__file__)] + sorted((ROOT / 'core').glob('*.py')) + sorted((ROOT / 'wiki').rglob('*.md'))
    def fingerprints(): return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in files}
    before = fingerprints()
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report = {'status': 'running', 'protocol': {'date': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
              'git_head': head, 'options': OPTIONS, 'system': SYSTEM, 'think': False,
              'fingerprints_before': before, 'decision': package['decision'],
              'limits': 'Internal personal selection, not general ranking. Direct model generation; production extraction/guards bypassed. Sequential model blocks; loading/order/cache/USB conditions not fully controlled.'},
              'mapping': mapping, 'frozen_cases': cases, 'results': rows, 'human_review': 'pending'}
    def save():
        report['protocol']['unchanged_after_run'] = before == fingerprints()
        (target / 'reveal-private.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (target / 'blind-review.md').write_text(blind_sheet(cases, rows, mapping), encoding='utf-8')
    save()
    with httpx.Client(base_url='http://127.0.0.1:11434', timeout=httpx.Timeout(180, connect=5)) as client:
        try:
            r = client.get('/api/tags'); r.raise_for_status()
            installed = {m['name']: m for m in r.json()['models']}
            if not all(m in installed for m in MODELS): raise RuntimeError('required installed model missing; no download attempted')
            report['installed'] = {}
            for model in MODELS:
                r = client.post('/api/show', json={'model': model}); r.raise_for_status()
                show = r.json()
                report['installed'][model] = {**installed[model], 'details': show.get('details'),
                    'from': [x for x in show.get('modelfile', '').splitlines() if x.startswith('FROM ')]}
            report['ollama_version'] = client.get('/api/version').json()
            report['resident_before'] = client.get('/api/ps').json()
            save()
            for model in MODELS:
                for case in cases:
                    started = time.perf_counter()
                    row = {'case_id': case['id'], 'model': model, 'prompt_sha256': case['prompt_sha256']}
                    try:
                        r = client.post('/api/chat', json={'model': model, 'messages': [
                            {'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': case['prompt']}],
                            'stream': False, 'think': False, 'options': OPTIONS})
                        r.raise_for_status(); data = r.json()
                        answer, reasons = evaluate_payload(data, model)
                        row.update(answer=answer, valid=not reasons, issues=reasons,
                                   timings={k: data.get(k) for k in ('load_duration', 'prompt_eval_duration', 'eval_duration', 'total_duration', 'prompt_eval_count', 'eval_count', 'done_reason')})
                    except Exception as exc:
                        row.update(answer='', valid=False, issues=['request_failed'], error=f'{type(exc).__name__}: {exc}')
                    row['wall_seconds'] = time.perf_counter()-started
                    rows.append(row)
                    save()
                    print(f'응답 {len(rows)}/24 저장', flush=True)
                    if 'request_failed' in row['issues']: raise RuntimeError('request failed; checkpoint saved; no automatic retries')
            report['status'] = 'completed' if all(r['valid'] for r in rows) and before == fingerprints() else 'completed_with_issues'
        except Exception as exc:
            report['status'] = 'blocked_or_incomplete'; report['error'] = str(exc)
        finally:
            save()
    print('검토표: ' + str(target / 'blind-review.md'))
    print('상태: ' + report['status'] + '; 사람 품질 판정은 미완료. 공개 파일은 검토 후 열기.')
    return 0 if report['status'] in ('completed', 'completed_with_issues') else 1


if __name__ == '__main__':
    raise SystemExit(main())
