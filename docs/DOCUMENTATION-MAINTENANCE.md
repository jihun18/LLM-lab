# 살아 있는 문서 유지 규칙

## 목적

문서를 개발이 끝난 뒤 한 번 작성하는 결과물이 아니라 코드와 함께 변하는 프로젝트 구성요소로 관리한다.

## 문서 역할 분리

### GitHub 공식 문서

`README.md`, `docs/`, `CHANGELOG.md`, `ROADMAP.md`는 처음 보는 사용자가 읽는 정제된 문서다.

### Obsidian Wiki

`wiki/`는 실험 원문, 시행착오, 모델 답변과 작업 중 아이디어를 누적하는 연구일지다.

공식 문서에는 검증된 결론을 쓰고 Wiki에는 결론에 도달한 과정까지 남긴다.

## 기능 완료 정의

기능은 다음 항목이 모두 끝났을 때 완료로 본다.

- [ ] 구현
- [ ] 자동 테스트
- [ ] 실제 로컬 실행 확인
- [ ] 오류와 한계 기록
- [ ] 관련 Wiki 갱신
- [ ] GitHub 공식 문서 갱신
- [ ] `CHANGELOG.md` 갱신
- [ ] `ROADMAP.md` 상태 갱신
- [ ] 개인정보 공개 점검

## 업데이트 대상 표

| 변경 유형 | 필수 갱신 문서 |
|---|---|
| 새 기능 | README, CHANGELOG, 관련 docs, Wiki |
| API 변경 | docs/API, README, 테스트 |
| 아키텍처 변경 | docs/ARCHITECTURE, DECISIONS |
| 모델·성능 실험 | docs/EXPERIMENT-RESULTS, Wiki |
| 보안 변경 | SECURITY-AND-PRIVACY, CHANGELOG |
| 설치 변경 | SETUP-WINDOWS, TROUBLESHOOTING |
| 계획 변경 | ROADMAP, PROJECT-OVERVIEW |

## 버전 규칙

초기 단계에서는 Semantic Versioning 형태를 따른다.

- PATCH `0.1.1`: 버그 수정과 문서 개선
- MINOR `0.2.0`: 의미 검색처럼 호환되는 새 기능
- MAJOR `1.0.0`: 공모전 제출이 가능한 안정 데모

버전은 `VERSION`, `CHANGELOG.md`와 README에서 함께 갱신한다.

## 실험 기록 템플릿

```markdown
# 실험 제목

- 날짜:
- 하드웨어:
- 모델 태그:
- 설정:
- 질문·데이터:
- 결과:
- 실패 사례:
- 사람 검토:
- 결론:
- 다음 행동:
```

## 커밋 전 문서 점검

```powershell
pytest -q
git status --short
git diff --check
```

추가 확인:

- 업로드 문서가 Git에 포함되지 않았는가
- 숫자와 벤치마크 값이 최신인가
- 실행 명령이 새 환경에서 유효한가
- 구현되지 않은 기능을 완료된 것처럼 쓰지 않았는가
- 검증 범위를 과장하지 않았는가

## 릴리스 시점

각 마이너 버전 직전에 다음을 수행한다.

1. 새 환경 설치 재현
2. 전체 테스트
3. 데모 시나리오 실행
4. 성능 기준선 기록
5. 개인정보 점검
6. CHANGELOG 확정
7. 스크린샷 갱신
8. 버전 태그 준비

