# PrivAI 검색 방식 비교 — 2026-10-06

RAM 16GB, Intel Core i3-7100, CPU 환경에서 설치된 `nomic-embed-text`를 사용했다.
문서와 질문에는 각각 `search_document:`와 `search_query:`를 붙인다.
Ollama `/api/embed`를 호출하고 정규화한 벡터의 코사인 유사도를 계산한다.
하이브리드는 두 검색 목록을 Reciprocal Rank Fusion(k=60)으로 결합한다.
기본 검색은 BM25다. 의미 검색과 하이브리드는 실험 선택지다.

## 평가세트

기존 13문항을 그대로 두고 의미 변형·오타·조사·근접 문서·근거 없음 11문항을
별도 파일에 추가했다. 합계 24문항이다. 기존 13문항의 100%와 확장 세트 75%는
서로 다른 평가세트의 결과이므로 성능이 떨어졌다고 바로 해석하면 안 된다.
이 세트는 개발 중인 평가세트이며 아직 별도의 비공개 검증세트는 없다.

## 첫 검색 비교 결과

| 검색 | Top-1(24문항) | Top-3 적중 | 근거 없음 성공(4문항) | 평균 검색시간 |
|---|---:|---:|---:|---:|
| BM25 | 75.0% | 83.3% | 75.0% | 0.0019초 |
| 의미 검색 | 16.7% | 25.0% | 0% | 0.2225초 |
| 하이브리드 | 45.8% | 66.7% | 0% | 0.1716초 |

의미 검색 유사도 하한은 0.65로 고정했다. 임계값은 아직 한국어 자료에서 교정하지
않았으며 확률이나 사실성 점수가 아니다. 이 결과에 맞춰 테스트별 예외를 넣지 않았다.
임베딩의 한국어 성능과 근거 없음 판별은 후속 실험의 주요 과제다.

첫 임베딩 준비에는 37.315초가 걸렸다. 하이브리드 실행은 앞서 만든 캐시를 사용했다.
측정한 Python 프로세스 RSS 표본 최대값은 BM25 32.18MB, 의미 검색 49.60MB,
하이브리드 50.03MB였다. 이 값은 Ollama 모델 메모리를 포함하지 않고 실제 순간
최대 메모리도 아니다. 따라서 전체 시스템 메모리 사용량으로 발표하면 안 된다.

원본 결과: `benchmark-results/rag-retrieval-search-20261006-092841.json`.
검색 측정과 답변 생성 측정을 분리한다. 이 표는 검색 평가이며 답변 정확도는 아니다.

## 대표 문항 답변 평가

기본 생성 모델 1.7B로 파일 한도, 다음 검색 실험, 근거 없는 날씨 질문 3개를
실행했다. 전체 24문항 답변 평가가 아니며 모델 적재·출력 길이에 따라 시간이 달라진다.

| 검색 | 평균 자동 답변 점수 | 평균 전체 응답시간 | 시간 기준 통과 |
|---|---:|---:|---:|
| BM25 | 100점 | 13.293초 | 100% |
| 의미 검색 | 50점 | 23.034초 | 66.7% |
| 하이브리드 | 62.5점 | 14.617초 | 66.7% |

원본: `benchmark-results/rag-evaluation-search-20261006-093244.json`.
자동 점수는 핵심어·수치·출처·검증 상태의 점수이며 사실성 전체를 보장하지 않는다.

## 실행

```powershell
python search_evaluation.py
python search_evaluation.py --modes bm25 semantic hybrid --case-ids ko_ram ko_scan unknown_policy
python search_evaluation.py --answers --case-ids upload_limits semantic_variant no_evidence_weather
```

`--answers`는 동일한 검색 결과를 사용해 기본 모델 `qwen3:1.7b`로 답변도 평가한다.
`--model`로 생성 모델을 바꿀 수 있다. 전체 응답시간에는 검색시간을 포함한다.
추가 문항은 우선 검색용으로 작성했으므로 답변 비교에는 핵심어·수치가 정의된 기존
문항을 먼저 사용한다. JSON·CSV·Markdown 보고서는 `benchmark-results`에 저장한다.

FastAPI와 Flask 화면의 검색 방식에서 BM25, 의미 검색, 하이브리드를 선택한다.
Streamlit도 사이드바에서 선택한다. REST 요청은 `search_mode`에
`bm25`, `semantic`, `hybrid` 중 하나를 전달한다.

최초 의미 검색에서 임베딩을 준비하며 `.search-cache`에 로컬 저장한다.
문서를 변경하거나 업로드 후 재색인하면 달라진 문서만 새로 임베딩한다.
모델이 없거나 Ollama가 응답하지 않으면 오류를 표시한다.
유사도 하한은 실험 도구의 `--threshold`로 바꿀 수 있다.

## 다음 결정

BM25를 기본값으로 유지한다. 현재 임베딩을 추가했다고 검색 품질이 좋아진 것은 아니다.
한국어 또는 다국어 임베딩 후보를 같은 고정 세트로 비교하고, 별도 검증 질문에서
유사도 하한과 근거 없음 판별을 정한 뒤 기본값 변경 여부를 결정한다.

참고: [Ollama embed API](https://docs.ollama.com/api/embed),
[Nomic 모델 설명](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5).

## 후속: 다국어 임베딩과 근거 없음 교정 (2026-10-06)

EmbeddingGemma 300M을 로컬 Ollama에 추가했다. Google 공식 검색용 query/document
입력 형식을 적용하며 Nomic의 접두어와 구분한다. 캐시는 모델별 파일로 분리한다.
[공식 입력 형식](https://huggingface.co/google/embeddinggemma-300m#prompt-instructions).

고정 평가 24문항을 변경하지 않고 `search_calibration_cases.json`의 별도 12문항
(근거 있음 6, 없음 6)에서 최고 유사도로 답변 가능성을 교정했다. 후보 점수 사이의
중간값을 비교해 근거 있는 질문 수용률과 없는 질문 거절률의 평균을 최대화한다.
동점이면 거절률, 하한 순으로 선택한다. 이는 작은 개발용 교정 세트이며 독립적인
최종 시험 세트가 아니다. 질문 주제가 겹치므로 일반화 성능을 보장하지 않는다.

| 모델 | 선택 하한 | 교정 수용률 | 교정 거절률 |
|---|---:|---:|---:|
| Nomic | 0.754383 | 83.3% | 100% |
| Gemma | 0.4395475 | 100% | 100% |

하한은 모델별 코사인 점수 기준이지 사실성 확률이 아니다. 하이브리드도 의미 검색
후보가 하나도 하한을 통과하지 못하면 BM25 결과만으로 우회하지 않고 거절한다.
후보가 있으면 기존 RRF를 적용한다. 모든 결과 문장이 질문의 답이라는 보장은 없다.

| 검색·모델 | Top-1 24문항 | Top-3 적중 | 근거 없음 4문항 | 평균 검색시간 |
|---|---:|---:|---:|---:|
| BM25 | 75.0% | 83.3% | 75.0% | 0.0013초 |
| Nomic 의미·교정 | 25.0% | 33.3% | 75.0% | 0.1492초 |
| Nomic 하이브리드·교정 | 54.2% | 54.2% | 75.0% | 0.1533초 |
| Gemma 의미·교정 | 62.5% | 83.3% | 100% | 0.1435초 |
| Gemma 하이브리드·교정 | 79.2% | 83.3% | 100% | 0.1406초 |

원본 `rag-retrieval-search-20261006-094606.json`(Gemma),
`rag-retrieval-search-20261006-094648.json`(Nomic)은 로컬 benchmark-results에 있다.
Gemma 하이브리드는 근거 있는 20문항 Top-1 75%로 BM25와 동일했다. 전체 개선은
근거 없는 질문 1개를 더 거절한 효과다. 단독 의미 검색이 BM25보다 낫다는 뜻은 아니다.
첫 비교 대비 모델·하한·게이트가 함께 바뀌어 각 개선의 개별 효과를 분리한 실험도 아니다.

대표 3문항(파일 한도·후속 검색 계획·날씨)의 하이브리드 답변 자동 점수는 평균100,
전체 평균11.753초였다. `rag-evaluation-search-20261006-094728.json`.
전체 답변 평가나 사람 검토 결과가 아니며 생성 편차가 있다.

세 앱의 의미·하이브리드 옵션은 Gemma를 사용하지만 기본 검색은 BM25다.
Ollama 모델이 없는 다른 PC는 `ollama pull embeddinggemma:300m`이 필요하다.
설정 변경 후 서버 재시작이 필요하다.

```powershell
python search_calibration.py --embedding-model embeddinggemma:300m
python search_calibration.py --embedding-model nomic-embed-text
python search_evaluation.py --embedding-model embeddinggemma:300m --threshold 0.4395475
python search_evaluation.py --embedding-model nomic-embed-text --threshold 0.754383
$env:OLLAMA_EMBED_MODEL="nomic-embed-text"
$env:SEMANTIC_THRESHOLD="0.754383"
```

교정 스크립트는 보고서만 만들고 앱 설정을 자동 변경하지 않는다. Wiki가 바뀌면 하한을
다시 교정해야 한다. 다음은 남은 동의어·검증 상태 검색 실패 분석, 독립 질문 확장,
전체 답변의 사람 평가다. 기존 24문항은 개발 회귀 평가로 유지한다.
