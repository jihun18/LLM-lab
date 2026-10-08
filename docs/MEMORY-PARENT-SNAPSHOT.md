# 범위 검사 중복 조회 개선

## 변경한 내용

- Windows 실제 수집에서는 매 범위 검사마다 새 부모 PID 표를 한 번 읽고, 웹 서버·runner·서비스 트리를 같은 표에서 구성한다. 이전의 세 번 `children(recursive=True)`와 서비스 콘솔 호스트의 추가 `ppid()` 조회를 대체한다.
- Windows 공개 [Toolhelp 스냅샷 API](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot)와 [PROCESSENTRY32W 구조](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w)를 사용한다. psutil 내부 함수나 전역 패치는 사용하지 않는다.
- 부모 표를 표본 간 캐시하지 않는다. 비 Windows 및 기존 가상 프로세스 주입에서는 기존 psutil 자식 조회 경로를 유지한다. 새 경로는 별도 가상 부모 표로도 검증한다.
- 성공 표본의 `membership_backend`는 새 경로에서 `single-parent-snapshot-v1`, 기존 경로에서 `psutil-children`이다. 사전 검사 표본에도 남아 기존 원자료와 구분할 수 있다.

## 유지·강화한 안전 검사

각 표본의 루트 PID·생성 시각, runner의 서비스 소속, 범위 중복, 알 수 없는 서비스 자식, 제외 콘솔 호스트의 실제 실행 경로·직속 부모·고정 PID/생성 시각 검사를 유지한다. 부모보다 먼저 생성된 자식이나 순환 관계는 무효다. 표 구성 후 관련 프로세스의 생성 시각을 재확인하고, RSS 읽기 전후에도 확인한다. 범위 확인 뒤 읽기 전 PID가 바뀌는 경우도 거부한다.

네이티브 스냅샷 생성·첫 조회·후속 조회·핸들 종료 오류, 접근 거부, 프로세스 종료를 실패로 처리한다. 후속 조회는 정상 목록 끝 오류 코드 18만 허용한다. 오류를 부분 표·0 RSS·기존 경로 자동 대체로 숨기지 않는다.

프로세스 목록과 RSS는 원자적 측정이 아니며, 목록 취득 직후 생성된 프로세스가 다음 표본에서 확인될 수 있다는 한계는 남는다. 따라서 순간 최대나 모든 순간의 완전한 트리를 보장하지 않는다.

## 검증과 다음 측정

새 경로 검증 25개를 추가했다. 매 검사 한 번 조회, 자식/부모 추가 조회 금지, 제외 호스트 규칙, 멤버 변경·PID 재사용·접근 거부·네이티브 오류 및 실제 Windows 현재 프로세스의 부모 PID를 검증한다. 기존 보호 테스트도 유지한다.

실제 7B 개선 후 OFF 5회를 완료하고 [전후 결과](MEMORY-PARENT-SNAPSHOT-RESULT-20261008.md)를 재검산했다. 평균 간격 194.65→122.63ms, 누락 목표 305→110회지만 5회 모두 지연 경고가 남는다. 모델 옵션·프롬프트·회차·100ms 목표·오류 처리·Wiki 쓰기 금지는 그대로다. 출력 길이·runner 재적재와 시스템 부하 차이가 있어 단일 전후 결과만으로 인과나 정확한 피크를 단정하지 않는다.

```powershell
.\.venv\Scripts\python.exe memory_launch.py --model qwen2.5:7b-instruct --prepare-model --run --confirm-interactively
```

웹 서버를 켜둔 상태에서 다른 요청을 멈추고 `MEASURE`를 입력한다. 이번 변경은 서버가 로드하지 않는 수집기 모듈에만 적용되어 서버 재시작은 필요 없다. 단계별 계측 ON은 선택적 추가 측정이며 기본 OFF 결과와 섞지 않는다.
