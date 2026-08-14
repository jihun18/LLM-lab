# REST API

기본 주소: `http://127.0.0.1:8000`

실행 중인 서버의 대화형 문서는 `/docs`, OpenAPI JSON은 `/openapi.json`에서 확인한다.

## 엔드포인트 요약

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | FastAPI와 Ollama 연결 상태 |
| GET | `/models` | 설치된 Ollama 모델 목록 |
| POST | `/chat` | 일반 비스트리밍 채팅 |
| POST | `/chat/stream` | 일반 NDJSON 채팅 |
| POST | `/summarize` | 한국어 요약 |
| GET | `/knowledge/status` | Wiki 색인 상태 |
| POST | `/knowledge/reindex` | Wiki 재색인 |
| POST | `/rag/chat` | 근거 기반 비스트리밍 채팅 |
| POST | `/rag/chat/stream` | 근거·검증 포함 NDJSON 채팅 |
| GET | `/documents` | 변환된 업로드 문서 목록 |
| POST | `/documents/upload` | MD·TXT·PDF 원문 업로드 |

## 상태 확인

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

응답 예시:

```json
{
  "status": "ok",
  "ollama_url": "http://127.0.0.1:11434",
  "latency_ms": 12.4,
  "framework": "FastAPI"
}
```

## 일반 채팅

```json
POST /chat
{
  "prompt": "경량 LLM의 장점을 두 문장으로 설명해줘.",
  "model": "qwen3:1.7b",
  "system": "간결하고 정확한 한국어로 답하세요."
}
```

응답에는 `answer`, `elapsed_seconds`, `tokens_per_second`, `eval_count`가 포함된다.

## RAG 채팅

```json
POST /rag/chat
{
  "prompt": "지원금과 신청 마감일은 언제야?",
  "model": "qwen3:1.7b",
  "system": "근거만 사용해 답하세요.",
  "top_k": 3
}
```

주요 응답 필드:

```json
{
  "answer": "근거 기반 답변",
  "sources": [
    {
      "source": "Uploads/example.md",
      "heading": "문서 내용",
      "score": 12.3,
      "excerpt": "검색된 문서 일부"
    }
  ],
  "verification": {
    "passed": true,
    "method": "structured_claim_verification",
    "supported_claims": ["월 10만원", "2026년 9월 30일"],
    "unsupported_claims": []
  }
}
```

`verification.passed`는 세 값 중 하나다.

- `true`: 현재 검증 규칙 범위에서 근거와 일치
- `false`: 근거에서 찾지 못한 구조화 값이 존재
- `null`: 자동 대조 대상이 없어 사람 의미 검토 필요

## 스트리밍 형식

`/chat/stream`, `/rag/chat/stream`은 한 줄에 JSON 객체 하나인 `application/x-ndjson`을 반환한다.

```json
{"sources": []}
{"done": false, "content": "답변 조각"}
{"done": true, "elapsed_seconds": 8.3, "tokens_per_second": 9.1}
```

RAG는 검증 후 최종 답변을 표시하기 위해 내부적으로 전체 답변을 만든 뒤 검증 정보를 함께 보낼 수 있다.

## Wiki 상태와 재색인

```powershell
Invoke-RestMethod http://127.0.0.1:8000/knowledge/status
Invoke-RestMethod -Method Post http://127.0.0.1:8000/knowledge/reindex
```

상태 필드:

- `root`
- `files_indexed`
- `chunks_indexed`
- `engine`

## 문서 업로드

업로드는 multipart가 아니라 원문 바이트 요청을 사용한다.

- 본문: 파일의 원본 바이트
- `Content-Type`: `application/octet-stream`
- `X-Filename`: URL 인코딩된 파일명
- 최대 크기: 5MB

브라우저 예시:

```javascript
await fetch('/documents/upload', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/octet-stream',
    'X-Filename': encodeURIComponent(file.name)
  },
  body: file
})
```

성공하면 변환 문서 정보와 갱신된 Wiki 상태를 반환한다.

## 오류 코드

| 코드 | 의미 |
|---:|---|
| 400 | 잘못된 파일, 인코딩, PDF 또는 요청 내용 |
| 413 | 5MB 초과 업로드 |
| 422 | Pydantic 입력 검증 실패 |
| 502 | Ollama 생성 요청 실패 |
| 503 | Ollama 상태·모델 조회 실패 |

