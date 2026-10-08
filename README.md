# privAI — 검증형 로컬 RAG 실험실

2026-10-06: 로컬 의미 검색과 하이브리드 검색 실험을 추가했다. 화면에서 검색 방식을
선택할 수 있고 `python search_evaluation.py`로 24문항 비교를 실행한다.
후속 다국어 실험에서 EmbeddingGemma 하이브리드 Top-1 79.2%, 근거 없음 4문항 모두
거절을 기록했다. 검색 기본값은 BM25로 유지하며 의미·하이브리드 옵션에는
EmbeddingGemma와 별도 12문항으로 교정한 근거 하한을 적용한다.
자세한 결과와 실행법은 [검색 실험 기록](docs/SEARCH-EXPERIMENT.md)을 참고한다.
후속 [실패 분석·질문 조건 검증](docs/SEARCH-FAILURE-ANALYSIS.md)에서 기존 실패 5문항,
새 평가 질문 12개, 추가 확인 6개, 1.7B/4B 답변 비교 및 사람 검토 절차를 기록했다.
저장된 답변의 [AI 원문 대조 검토](docs/AI-ANSWER-REVIEW.md)도 추가했다. 사람 평가는 별도로 필요하다.
수정 후 [1.7B·4B·양자화7B 비교](docs/THREE-MODEL-COMPARISON.md)를 완료했다.
실제 생성4문항 웜 평균은17.052/29.252/35.738초였으며 기본 모델은1.7B를 유지한다.
후속 [근거 길이 실험](docs/CONTEXT-LENGTH-EXPERIMENT.md)에서는 시간을 줄였지만
1.7B의 역할 혼동·목록 누락이 확인돼 기본 축약 적용을 보류했다.

privAI는 외부 LLM API 없이 Windows PC에서 Ollama 경량 모델을 실행하고, 로컬 문서를 검색해 출처와 검증 상태를 함께 보여주는 개인용 AI 실험 프로젝트입니다.

현재 버전은 **v0.1.0 — 검증형 로컬 RAG MVP**입니다.

## 현재 구현된 기능

- Ollama의 1.7B·4B Instruct·양자화 7B Instruct 로컬 추론
- 실측 결과 기반 빠른·균형·정밀 모델 모드
- FastAPI REST API와 `privAI.html` 채팅 화면
- 공통 Wiki RAG를 사용하는 Flask·Streamlit 비교 데모
- NDJSON 기반 응답 표시
- Obsidian Markdown Wiki 자동 색인
- 저사양용 BM25 검색과 상대 점수 기반 검색 노이즈 제거
- Markdown·TXT·텍스트 PDF 로컬 업로드
- 업로드 문서의 Markdown 변환과 자동 재색인
- 답변 출처 파일·제목 표시
- Markdown 표의 속도·시간 열 구조 분석
- 날짜·금액·단위 수치의 근거 원문 대조
- 모델 속도·형식 준수 자동 벤치마크
- 13문항 RAG 검색·답변·출처·거절·응답시간 평가

## 목표 환경

| 항목 | 기준 환경 |
|---|---|
| OS | Windows 11 Pro |
| CPU | Intel Core i3-7100 3.90GHz |
| RAM | 16GB (초기 기준 8GB) |
| GPU | Intel HD Graphics 630 |
| Python | 3.12.10 |
| 추론 | Ollama CPU 중심 추론 |

이 프로젝트는 고성능 GPU가 없는 PC에서도 작동하는 것을 중요한 설계 조건으로 삼습니다.

## 빠른 시작

### 1. Ollama 모델 준비

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:1.7b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:4b-instruct
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen2.5:7b-instruct
```

### 2. Python 환경 준비

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. FastAPI 실행

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

- 채팅 화면: http://127.0.0.1:8000
- REST API 문서: http://127.0.0.1:8000/docs
- Ollama API: http://127.0.0.1:11434

서버는 기본적으로 자기 PC에서만 접근 가능한 `127.0.0.1`에 바인딩합니다.

## 첫 테스트

화면에서 `samples/sample-policy.txt`를 선택하고 `문서 추가`를 누른 뒤 질문합니다.

```text
샘플 청년 AI 개발 지원금은 얼마이고 신청 마감일은 언제야?
```

정상 결과에는 다음 정보가 표시됩니다.

- 월 10만원
- 2026년 9월 30일
- `Uploads/...md#문서 내용` 출처
- `금액·날짜·단위 검증 통과`

## 프레임워크 비교 실행

```powershell
# Flask — http://127.0.0.1:5000
python flask_app.py

# Streamlit — http://127.0.0.1:8501
streamlit run streamlit_app.py
```

세 앱은 같은 Wiki 검색·출처·검증 코어를 사용합니다. FastAPI는 제품 백엔드,
Streamlit은 빠른 실험 UI, Flask는 웹 프레임워크 비교군으로 사용합니다.

Flask와 Streamlit에서도 `Wiki 근거 사용`을 켜고 위의 지원금 질문을 입력하면
FastAPI와 동일한 로컬 문서를 근거로 답합니다. 서버를 실행하기 전에 Ollama가
실행 중인지 확인해야 합니다.

## 테스트와 벤치마크

```powershell
python -m pytest -q

# 두 모델에서 첫 문항만 빠르게 실행
python benchmark.py --max-cases 1

# 두 모델·5문항 전체 평가
python benchmark.py

# 1.7B·4B·양자화 7B 전체 비교
python benchmark.py --models qwen3:1.7b qwen3:4b-instruct qwen2.5:7b-instruct

# LLM 호출 없이 BM25 검색 정확도만 빠르게 평가
python rag_evaluation.py --retrieval-only

# 1.7B의 전체 RAG 답변 평가
python rag_evaluation.py --models qwen3:1.7b

# 실패 문항만 빠르게 재평가
python rag_evaluation.py --models qwen3:1.7b --case-ids verification_states upload_flow
```

현재 자동 테스트는 **275개**입니다. 벤치마크 결과는 로컬 `benchmark-results/`에 JSON·CSV·Markdown으로 생성되며 Git에는 포함되지 않습니다.

역할 표현·대상 수와 독립적인 메모리 보호와 수치 검사 상태 구분은 [공통 메모리 보호](docs/COMMON-MEMORY-GUARD.md)를 참고하세요.
역할의 표·일반 목록 대조와 메모리 도구명 열·KiB 처리는 [역할 충돌·메모리 표 형식 개선](docs/ROLE-CONFLICT-MEMORY-COLUMNS.md)을 참고하세요.
RSS·RAM 및 ‘역할 및 메모리’, ‘맡는 일’ 질문의 부분 답변 연결과 최신 회귀 결과는 [추가 경계 평가](docs/ROLE-MEMORY-FOLLOWUP-20261007.md)를 참고하세요.
최대·평균·최소 메모리의 요구·출처 구분과 일반 측정값 대체 금지는 [메모리 측정 조건 개선](docs/MEMORY-STATISTICS-20261007.md)을 참고하세요.
웹 서버·Ollama 서비스·모델 실행 프로세스를 분리할 실측 기준은 [메모리 측정 프로토콜](docs/MEMORY-MEASUREMENT-PROTOCOL.md)을 참고하세요. 실제 측정값은 아직 없습니다.
해당 기준의 [분리 수집 도구 사용법과 제한](docs/MEMORY-COLLECTOR.md): 기본 사전 확인은 생성하지 않으며, 실제 측정은 명시적인 실행 옵션이 필요합니다. 도구 구현·가상 데이터 검증까지 완료했고 실측은 아직입니다.

[업무·메모리 요구 개선](docs/ROLE-MEMORY-GUARDS.md): 일반 역할 목록을 제한적으로 읽고 대상별 메모리 측정 행을 추적한다. 전체 RAM이나 모델 파일 크기로 메모리 사용량을 대신하지 않는다.

[복합 질문 별도 첫 평가](docs/COMPOUND-HOLDOUT.md): Wiki 6문항과 통제 근거 6문항을 분리해 확인했다. 모델 없는 11문항은 항목 검사를 통과했고, 의역 질문 1개는 실제 생성 후 차단되어 답변 요구가 미충족이었다.

[항목별 추가 검색과 부분 답변](docs/REQUIREMENT-RETRIEVAL.md): 제한된 역할·속도·이유 질문에서 필요한 근거를 추가 검색하고, 확인한 원문과 미확인 항목을 분리한다.

[복합 질문 근거 확인](docs/COMPOUND-QUESTION-GUARDS.md): 도구 역할 비교의 요청 항목을 제한적으로 확인하고, 알려진 검증 실패 답변은 JSON·스트리밍 본문에서 안전한 안내로 바꾼다.

[출처 선택 개선](docs/CITATION-SELECTION.md): 모델은 답변과 근거 번호를 구조화해서 반환하고 서버가 정확한 출처로 연결한다. 문장 의미의 정확도와는 별개다.

[제한적 원문 추출](docs/SOURCE-TEXT-EXTRACTION.md): 명확한 역할·상태 문구 목록을 모델 호출 없이 원문에서 복사한다.

[역할 비교표 추출](docs/ROLE-COMPARISON-EXTRACTION.md): 범위가 명확한 역할·차이 질문은 검색된 비교표의 역할·API 문서 셀을 직접 복사한다. 일반적인 성능·기능 한계나 선택 이유는 이 경로로 답하지 않는다.

[역할·필수 문구 검증 보강](docs/TEXT-CONTRACT-VALIDATION.md): 기존 축약 실험 답변의 역할 교환과 문구 누락을 재검사했다. 제한 규칙이며 전체 문장 의미 검증은 아니다.

## 실험 결과 요약

13문항 BM25 최초 기준선은 Top-1 53.8%, Top-3 76.9%였으며 검색 개선 후
Top-1 100%, Top-3 100%를 기록했다. 검색 방식 변경은 이 고정 문항에서 정확도와
지연시간이 함께 개선될 때 채택한다.

1.7B 전체 RAG 평균 답변 점수는 최초 89.4점에서 최종 **99.4점**으로 개선됐고,
평균 응답시간은 20.293초다. 4B 전체 평가는 평균 답변 점수 97.4점, 평균 응답시간
48.627초였다. 답변 간결화·고유 표기 보존·출처 정규화 개선 후 실패 문항 2건은
모두 100점을 기록했다.

| 모델 | 평균 시간 | 평균 생성속도 | 현재 역할 |
|---|---:|---:|---|
| qwen3:1.7b | 7.959초 | 13.99 token/s | 현재 기본 데모·빠른 RAG |
| qwen3:4b-instruct | 16.034초 | 6.80 token/s | 균형 모드 후보 |
| qwen2.5:7b-instruct Q4_K_M | 28.539초 | 3.80 token/s | 정밀 모드 후보 |

16GB 환경의 5문항 자동점수는 각각 80.0, 83.3, 90.0이었습니다. 자동점수는
형식과 핵심어 점수이며 사실성 점수가 아닙니다. 7B는 16GB에서 안정적으로 실행됐지만
4B보다 느리고 사람 검토 사실성이 뚜렷하게 우수하지 않아 기본 모델로 채택하지 않았습니다.

주의: 현재 Ollama의 `qwen3:4b` 태그는 `qwen3:4b-thinking`과 같은 모델을
가리키므로 짧은 일반 답변 벤치마크에는 `qwen3:4b-instruct`를 사용한다.

초기 8GB 한계 시험에서는 7B 첫 문항이 117.257초였지만, 16GB 증설 후 전체
5문항을 평균 28.539초로 완료했습니다. 콜드 런은 43.984초, 웜 런은 19.415초로
모델 적재 상태가 전체 대기시간에 큰 영향을 줍니다.

## 프로젝트 구조

```text
local-llm-web-lab/
├─ app.py                       # FastAPI 주력 서버
├─ privAI.html                  # 로컬 채팅 UI
├─ flask_app.py                 # Flask 비교 구현
├─ streamlit_app.py             # Streamlit 비교 구현
├─ benchmark.py                 # 모델 평가 실행기
├─ evaluation.py                # 자동 평가 규칙
├─ evaluation_cases.json        # 공통 평가 문항
├─ core/
│  ├─ ollama_client.py          # Ollama REST 클라이언트
│  ├─ knowledge_base.py         # Markdown BM25 색인
│  ├─ grounding.py              # 표·주장 검증 하니스
│  ├─ rag_service.py            # 세 프레임워크 공통 RAG 흐름
│  ├─ document_ingest.py        # MD·TXT·PDF 변환
│  ├─ schemas.py                # API 입력 스키마
│  └─ config.py                 # 저사양 기본 설정
├─ docs/                        # GitHub용 공식 문서
├─ wiki/                        # Obsidian 연구일지
├─ samples/                     # 공개 가능한 가상 문서
├─ presentations/               # 세미나 발표자료
└─ tests/                       # 자동 테스트
```

## 문서 안내

| 문서 | 내용 |
|---|---|
| [프로젝트 개요](docs/PROJECT-OVERVIEW.md) | 목표, 범위, 현재 상태 |
| [프로젝트 상태](docs/PROJECT-STATUS.md) | 완료 기능, 기술 부채, 공개 준비 상태 |
| [아키텍처](docs/ARCHITECTURE.md) | 구성요소와 데이터 흐름 |
| [Windows 설치](docs/SETUP-WINDOWS.md) | Windows 설치·실행 절차 |
| [REST API](docs/API.md) | REST API 명세와 예제 |
| [실험 결과](docs/EXPERIMENT-RESULTS.md) | 모델·프레임워크 실험 결과 |
| [보안과 개인정보](docs/SECURITY-AND-PRIVACY.md) | 개인정보 보호와 공개 점검표 |
| [문제 해결](docs/TROUBLESHOOTING.md) | 자주 발생하는 오류 해결 |
| [기술 의사결정](docs/DECISIONS.md) | 주요 기술 선택과 이유 |
| [문서 유지 규칙](docs/DOCUMENTATION-MAINTENANCE.md) | 살아 있는 문서 갱신 규칙 |
| [로드맵](ROADMAP.md) | 다음 버전 계획 |
| [변경 이력](CHANGELOG.md) | 버전별 변경 이력 |

## 개인정보 보호

- 업로드 파일은 외부 LLM API로 보내지 않습니다.
- 변환된 문서는 `wiki/Uploads/`에 저장됩니다.
- `wiki/Uploads/*`, `.env`, 가상환경과 벤치마크 원본은 Git에서 제외됩니다.
- GitHub에는 `samples/`의 가상 데이터만 올리는 것을 원칙으로 합니다.
- 스캔 PDF OCR, 악성 PDF 격리와 다중 사용자 권한 제어는 아직 구현되지 않았습니다.

자세한 공개 전 점검사항은 `docs/SECURITY-AND-PRIVACY.md`를 확인하세요.

## 현재 한계

- BM25는 단어가 전혀 다른 동의어 검색에 약합니다.
- 일반 서술문의 의미적 사실성은 완전 자동 검증하지 못합니다.
- 스캔 이미지 PDF는 OCR 없이는 처리할 수 없습니다.
- CPU 환경에서는 1.7B 모델도 긴 답변이 느릴 수 있습니다.
- 인증·다중 사용자·외부 배포 기능은 범위 밖입니다.

## 라이선스

라이선스는 아직 선택하지 않았습니다. GitHub 공개 전에 사용·수정·배포 조건을 결정해 `LICENSE` 파일을 추가해야 합니다.
