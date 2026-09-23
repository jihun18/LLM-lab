# privAI — 검증형 로컬 RAG 실험실

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

현재 자동 테스트는 **49개**입니다. 벤치마크 결과는 로컬 `benchmark-results/`에 JSON·CSV·Markdown으로 생성되며 Git에는 포함되지 않습니다.

## 실험 결과 요약

13문항 BM25 최초 기준선은 Top-1 53.8%, Top-3 76.9%였으며 1차 검색 개선 후
Top-1 92.3%, Top-3 100%를 기록했다. 검색 방식 변경은 이 고정 문항에서 정확도와
지연시간이 함께 개선될 때 채택한다.

1.7B 전체 RAG의 최초 평균 답변 점수는 89.4점이었으며, 낮은 3개 문항의 표적
수정 후 재시험 점수는 100.0점·91.7점·100.0점이었다.

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
