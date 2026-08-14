# Windows 설치와 실행

## 사전 준비

- Windows 11 권장
- Python 3.12
- Ollama
- 최소 RAM 8GB 권장
- 프로젝트 파일을 저장할 여유 공간 약 3GB 이상

## Python 설치 확인

```powershell
python --version
pip --version
```

예상 예시:

```text
Python 3.12.10
pip 25.0.1
```

명령을 찾지 못하면 새 PowerShell을 열거나 Python 설치 시 PATH 등록을 확인한다.

## Ollama 확인

PATH에 Ollama가 없다면 전체 경로를 사용한다.

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" --version
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list
```

서버 상태는 다음 명령으로 확인한다.

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

## 모델 설치

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:0.6b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:1.7b
```

크기를 쓰지 않고 `qwen3`만 입력하면 8GB 환경에 큰 기본 모델이 설치될 수 있으므로 태그를 명시한다.

## 가상환경과 의존성

프로젝트 폴더에서 실행한다.

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

활성화 후 프롬프트 앞에 `(.venv)`가 표시되는지 확인한다.

## FastAPI 실행

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

브라우저에서 다음 주소를 연다.

```text
http://127.0.0.1:8000
```

정상 화면:

- Ollama 연결됨
- 모델 목록 표시
- Wiki 문서·조각 수 표시
- 질문 입력과 전송 가능

서버 종료는 PowerShell에서 `Ctrl+C`다.

## 다른 프레임워크

한 번에 서버 하나만 실행하는 것을 권장한다.

```powershell
python flask_app.py
streamlit run streamlit_app.py
```

| 프레임워크 | 주소 |
|---|---|
| FastAPI | http://127.0.0.1:8000 |
| Flask | http://127.0.0.1:5000 |
| Streamlit | http://127.0.0.1:8501 |

## 환경변수

현재 PowerShell 세션에서 설정한다.

```powershell
$env:OLLAMA_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "qwen3:1.7b"
$env:OLLAMA_NUM_CTX = "2048"
$env:OLLAMA_NUM_PREDICT = "256"
$env:OLLAMA_TEMPERATURE = "0.3"
```

설정 후 서버를 다시 시작한다.

## 첫 기능 검증

1. `samples/sample-policy.txt`를 화면에서 선택한다.
2. `문서 추가`를 누른다.
3. 문서 수가 증가했는지 확인한다.
4. 지원금과 마감일을 질문한다.
5. 답변, 출처와 검증 상태를 확인한다.

## 테스트 실행

```powershell
pytest -q
```

v0.1.0의 기준 결과는 `24 passed`다.

