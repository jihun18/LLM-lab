# 로컬 RAG 1단계

구현일: 2026-08-14

## 목적

경량 모델이 자체 기억만으로 답할 때 발생한 사실 오류를 줄이고, Obsidian Wiki의 근거를 함께 제시한다.

## 현재 구조

1. `wiki` 폴더의 Markdown 파일을 제목 단위로 분할한다.
2. 저사양 PC에 적합한 BM25 방식으로 질문과 관련된 문서 조각 3개를 찾는다.
3. 검색된 근거와 질문을 qwen3 모델에 함께 전달한다.
4. 답변 아래에 실제 검색된 파일명과 제목을 표시한다.

별도 벡터DB와 임베딩 모델을 사용하지 않으므로 RAM 사용량과 설치 복잡도가 작다. 의미가 다른 동의어 검색에는 한계가 있으므로 다음 단계에서 임베딩 검색과 비교한다.

## 사용법

FastAPI를 실행하고 privAI 화면에서 `Wiki 근거 사용`을 선택한다. Wiki 문서를 수정한 뒤에는 `Wiki 재색인` 버튼을 누른다.

테스트 질문:

```text
이 PC의 CPU와 RAM 사양을 알려줘.
```

```text
FastAPI와 Flask, Streamlit의 역할을 비교해줘.
```

```text
벤치마크에서 0.6B와 1.7B의 평균 속도는 얼마였어?
```

## API

- `GET /knowledge/status`
- `POST /knowledge/reindex`
- `POST /rag/chat`
- `POST /rag/chat/stream`

