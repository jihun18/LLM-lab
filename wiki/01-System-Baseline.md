# 시스템 기준선

- OS: Windows 11 Pro
- CPU: Intel Core i3-7100 3.90GHz
- RAM: 16GB (2026-09-23 증설, 초기 기준 8GB)
- GPU: Intel HD Graphics 630
- Python: 3.12.10
- Ollama 모델: qwen3:1.7b, qwen3:4b-instruct, qwen2.5:7b-instruct Q4_K_M
- 기본 컨텍스트: 2,048 tokens
- 기본 최대 출력: 256 tokens

이 PC는 CPU 추론 환경으로 분류한다. 1.7B는 기본 데모, 4B Instruct는 균형 모드
후보, 양자화 7B Instruct는 정밀 모드 후보로 사용한다. 7B는 실행 가능하지만
응답성이 낮아 기본 모델로 사용하지 않는다.
