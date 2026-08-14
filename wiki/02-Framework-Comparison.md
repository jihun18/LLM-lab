# 웹 프레임워크 비교

실험일: 2026-08-14  
환경: Windows 11 Pro, Intel Core i3-7100, RAM 8GB, Intel HD Graphics 630  
모델: qwen3:1.7b, 컨텍스트 2,048, 최대 출력 256

## 구현 비교

| 항목 | FastAPI | Flask | Streamlit |
|---|---|---|---|
| 역할 | 주력 REST API | 최소 비교군 | 빠른 데모 UI |
| 실행 포트 | 8000 | 5000 | 8501 |
| API 문서 | 자동 `/docs` | 별도 필요 | 해당 없음 |
| 스트리밍 | NDJSON | NDJSON | 채팅 컴포넌트 |
| 화면 | privAI.html | privAI.html | Streamlit 기본 UI |

## 사용자 실측 결과

동일한 질문: `경량 LLM의 장점을 한국어로 두 문장만 설명해줘.`

| 프레임워크 | 모델 | 전체 시간 | 생성속도 |
|---|---|---:|---:|
| FastAPI | qwen3:1.7b | 13.975초 | 11.75 token/s |
| Flask | qwen3:1.7b | 5.003초 | 12.61 token/s |
| Streamlit | qwen3:1.7b | 4.953초 | 11.24 token/s |

전체 시간 차이는 프레임워크만의 차이가 아니다. 모델의 최초 적재 여부, 답변 길이와 운영체제 캐시가 함께 영향을 준다. 세 환경의 실제 생성속도는 약 11~12 token/s로 비슷했다.

## 결론

- 정식 REST API와 백엔드: **FastAPI**
- 빠른 AI 기능 검증과 발표 시연: **Streamlit**
- 웹 프레임워크 원리 학습과 최소 구현: **Flask**
- 공모전 제품은 FastAPI와 privAI.html을 기본으로 하고 Streamlit은 실험 도구로 유지한다.

