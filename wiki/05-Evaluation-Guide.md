# 자동 평가 실행 가이드

## 빠른 점검

두 모델에서 첫 문항만 실행한다.

```powershell
python benchmark.py --max-cases 1
```

## 전체 평가

두 모델에서 5개 문항을 모두 실행한다.

```powershell
python benchmark.py
```

1.7B 모델 하나만 평가하려면 다음과 같이 실행한다.

```powershell
python benchmark.py --models qwen3:1.7b
```

결과는 `benchmark-results` 폴더에 JSON, CSV, Markdown 형식으로 저장된다. Excel에서는 UTF-8 CSV를 열고, Obsidian에서는 Markdown 보고서를 열어 사람 검토 점수를 입력한다.

자동점수는 정답률이 아니다. 다음 항목만 기계적으로 확인한다.

- 한국어 비율
- 요청한 문장 수
- 요청한 번호 목록 개수
- 필수 핵심어 포함 여부

문항에서 요구하지 않은 숨은 기준으로 채점하지 않는다. 필수 핵심어와 출력 형식은 평가 프롬프트에도 명시한다.
