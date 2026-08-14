# 변경 이력

이 프로젝트의 주요 변경사항을 버전별로 기록한다.

## [Unreleased]

### 예정

- BM25와 경량 의미 검색 비교
- 검색 품질 평가 문항
- 일반 서술형 주장 검증 개선
- 스캔 PDF 로컬 OCR 검토
- 에이전트 도구 실행과 감사 로그

## [0.1.0] — 2026-08-14

### 추가

- FastAPI 기반 privAI 로컬 채팅 화면
- Flask와 Streamlit 비교 데모
- Ollama qwen3:0.6b·1.7b 연동
- 일반 채팅, 요약과 모델 조회 REST API
- NDJSON 응답 표시
- Obsidian Markdown Wiki 색인
- BM25 검색과 상대 점수 노이즈 필터
- 코드 블록 색인 제외
- RAG 답변과 출처 표시
- Markdown 표 열·단위 분석
- 결정론적 표 수치 답변
- 날짜·금액·단위 원문 검증
- MD·TXT·텍스트 PDF 로컬 업로드
- 안전한 파일명, 5MB와 PDF 100페이지 제한
- SHA-256 기반 업로드 중복 방지
- 자동 벤치마크와 JSON·CSV·Markdown 보고서
- 24개 자동 테스트
- GitHub 공식 문서와 Obsidian Wiki 분리
- 업로드 문서 Git 제외 정책

### 확인된 한계

- BM25 동의어 검색 한계
- 일반 서술문의 완전한 의미 검증 미지원
- 스캔 PDF OCR 미지원
- 다중 사용자와 인증 미지원
- 악성 문서 샌드박스 미지원

