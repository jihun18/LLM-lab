# 문제 해결

## `python`을 찾을 수 없음

증상:

```text
python 용어가 인식되지 않습니다
```

해결:

1. Python 3.12 설치 여부를 확인한다.
2. 새 PowerShell을 연다.
3. 설치할 때 PATH 등록을 확인한다.
4. `python --version`을 다시 실행한다.

## PowerShell 가상환경 활성화 차단

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

`Process` 범위는 현재 PowerShell을 닫으면 사라진다.

## Ollama 명령을 찾을 수 없음

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list
```

Ollama API가 응답하는지 확인한다.

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

## 모델 목록이 비어 있음

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:0.6b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:1.7b
```

## 8000번 포트 사용 중

증상:

```text
[WinError 10048] 각 소켓 주소는 하나만 사용할 수 있습니다
```

기존 서버 PowerShell에서 `Ctrl+C`를 누른 뒤 다시 실행한다. 서버 창을 찾을 수 없다면 포트를 사용 중인 프로세스를 확인하고 사용자가 직접 종료 여부를 판단한다.

## 화면에 새 기능이 보이지 않음

1. 서버를 `Ctrl+C`로 종료한다.
2. FastAPI를 다시 실행한다.
3. 브라우저에서 `Ctrl+F5`로 새로고침한다.

## Ollama 연결 실패

- Ollama 앱이 실행 중인지 확인
- `11434` 포트 확인
- `OLLAMA_URL` 환경변수 확인
- 방화벽이나 보안 소프트웨어 확인

## 응답이 매우 느림

- 먼저 `qwen3:0.6b`로 기능 확인
- 브라우저 탭과 메모리 사용 프로그램 정리
- 컨텍스트를 2,048로 유지
- 한 번에 서버 하나만 실행
- 최초 모델 적재 후 두 번째 요청과 비교
- 답변 최대 길이를 줄임

## 답변에 thinking이 표시됨

현재 클라이언트는 `think: false`를 보낸다. 이전 코드가 실행 중일 수 있으므로 서버를 재시작한다. Ollama와 모델 버전이 해당 옵션을 지원하는지도 확인한다.

## PDF 처리 오류

### `pypdf` 없음

```powershell
pip install -r requirements.txt
```

### 텍스트를 찾지 못함

PDF가 스캔 이미지일 가능성이 높다. v0.1.0에는 OCR이 없으므로 텍스트가 포함된 PDF나 TXT·Markdown을 사용한다.

### 암호화 PDF

비밀번호 보호 PDF는 지원하지 않는다. 신뢰할 수 있는 환경에서 사용자가 암호화를 제거한 복사본을 준비해야 한다.

## 업로드 문서가 검색되지 않음

1. 문서 추가 완료 메시지를 확인한다.
2. `wiki/Uploads`에 변환 Markdown이 있는지 확인한다.
3. `Wiki 재색인`을 누른다.
4. 질문에 문서의 구체적인 핵심어를 포함한다.

## 관계없는 출처가 표시됨

현재 검색은 BM25이며 단어가 겹치면 관계없는 문서가 후보가 될 수 있다. 1위 점수의 30% 미만 결과는 제거하지만 완전하지 않다. 구체적인 질문을 사용하고 향후 의미 검색 결과와 비교한다.

## 검증 통과인데 문장이 이상함

검증 배지의 범위를 확인한다.

- 표 수치 검증: 표의 값과 단위만 확인
- 금액·날짜·단위 검증: 해당 문자열만 확인
- 일반 문장 의미: 사람 검토 필요

부분 검증 통과는 답변 전체의 정확성을 보장하지 않는다.

## 테스트 실패

```powershell
pytest -q
```

실패한 테스트 이름과 전체 오류를 확인한다. 의존성 설치 후에도 실패하면 Python 버전, 작업 폴더와 실행 중인 서버 상태를 함께 기록해 이슈에 첨부한다.

