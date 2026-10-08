# 수집기 단계별 시간 계측

## 상태

[기존 원자료 진단](MEMORY-SAMPLING-DIAGNOSIS-20261008.md)에서 7B 최장 공백 대부분이 스냅샷 내부였음을 확인했다. 개별 단계와 실행/대기를 분리하기 위해 선택적 `--profile-timings`를 추가했다. 전체 자동 테스트 363개 및 PowerShell 문법 검사가 통과했다. 이후 같은 소스의 [실제 OFF/ON 실행](MEMORY-PROFILING-RESULT-20261008.md)을 각각 5회 완료했다.

기본값은 OFF다. 동일 소스에서 OFF/ON을 별도 실행해야 계측 자체의 영향을 볼 수 있다. 기존 7B 원자료와 새 ON 기록만으로 계측 부하를 정확히 분리했다고 주장하지 않는다. 기존 원자료는 보존한다.

## 실행

서버 창을 유지하고 다른 생성·업로드·재색인 작업을 중단한다. 다른 모델이 적재되어 있으면 자동 종료하지 않으며 설치된 7B만 준비한다. 다음을 순차 실행하고 각각 `MEASURE`로 확인한다. 첫 실행이 완료되기 전에 두 번째를 실행하지 않는다.

```powershell
.\.venv\Scripts\python.exe memory_launch.py --model qwen2.5:7b-instruct --prepare-model --run --confirm-interactively
.\.venv\Scripts\python.exe memory_launch.py --model qwen2.5:7b-instruct --prepare-model --run --confirm-interactively --profile-timings
```

PID 직접 지정 수집기에도 `--profile-timings`를 지원하며 PowerShell 래퍼 옵션은 `-ProfileTimings`다. 기준 JSON·100ms 목표·예열·5회 요청·안전 검사 빈도·PID/범위 보호·오류 중단·RSS 집계 방식은 유지한다. 수집기 전용 수정이므로 서버 재시작은 필요하지 않다.

## 기록

보고서 최상위 `profiling`은 enabled/version/CPU 지표/계측 영향 주의를 기록한다. 기본 OFF에서는 스레드 CPU 시계를 호출하거나 상세 자료를 만들지 않는다. OFF/ON 모두 기존 시각·RSS·목표 누락을 보존한다.

ON 표본의 `timing_profile`:

| 단계/필드 | 의미 |
|---|---|
| `version` | `collector-phase-v2` (이전 원자료는 v1) |
| `thread_cpu_seconds` | 스냅샷 내부 수집기 스레드 CPU 시간 |
| `phases[].membership` | 범위·자식·제외 호스트·중복 검사 전체 |
| `phases[].identity_before` | RSS 직전 생성 시각 읽기 |
| `phases[].rss_read` | 프로세스 memory_info 호출 |
| `phases[].identity_after` | 새 Process 객체 및 생성 시각 재확인 |

각 단계 항목은 phase/start/end/wall_seconds/thread_cpu_seconds/completed를 갖는다. 동일 phase는 구성원마다 반복된다. 단계 경과 합계와 전체 read_end-time의 차이는 계측 호출·자료 조립·그 밖의 처리 등을 포함하며 강제로 0으로 만들지 않는다.

v2는 별도 `membership_phases` 배열에 다음 내부 단계를 기록한다. 전체 `phases[].membership`과 내부 단계는 포함 관계이므로 **둘을 더하지 않는다**. 내부 단계끼리는 비중첩이며 합계와 membership의 차이는 타이머·기록 조립·그 밖의 처리 등을 포함한다.

| 내부 phase | 포함 작업 |
|---|---|
| `root_identity` | 루트 객체 생성 및 고정 생성 시각 확인 |
| `parent_snapshot` | 새 Windows 부모 표 취득: API 준비·열거·핸들 종료 포함 |
| `parent_index` | 부모→자식 인덱스 구성 및 루트 목록 존재 확인 |
| `tree_build` | 세 트리 탐색, 자식 객체/최초 생성 시각, 생성 순서·순환 검사 |
| `member_identity_recheck` | 관련 PID의 새 객체 생성 시각 재확인 |
| `runner_membership` | runner 트리의 서비스 소속 확인 |
| `console_host_verification` | 제외 호스트 경로·직속 부모·PID 및 제외 목록 확인 |
| `overlap_check` | 세 범위 및 제외 PID의 중복 확인 |
| `legacy_children` | 기존 psutil 경로의 세 자식 조회 (새 부모 표 경로에서는 없음) |

부모 표 경로에만 존재하는 단계는 기존 경로에서 생략한다. `tree_build`는 순수 리스트 계산만이 아니라 최초 프로세스 정보 읽기도 포함한다. 단계 이름만으로 특정 OS 호출 비용을 단정하지 않는다. 생성자/직접 사전 검사의 `members()` 호출에는 이 배열을 만들지 않고 ON 표본의 범위 검사에만 기록한다. 실패 표본에서도 실패한 내부 단계와 전체 membership의 completed=false를 모두 보존한다. 배열은 표본마다 새로 만든다.

실패한 단계도 completed=false로 기록하며 기존 오류·이미 읽은 값은 유지한다. 접근 거부·PID 변경 등 무효 구간을 CPU 또는 RSS 0으로 대체하지 않는다.

ON 구간의 `sampling_schedule.wait_calls`에는 tick/target_time/start/end/requested_seconds/wall_seconds/thread_cpu_seconds/completed_during_wait/excess_wait_seconds를 기록한다. 초과 대기는 실제 경과 시간에서 요청 대기를 뺀 양수 부분이다. 응답 완료로 대기가 끝났으면 excess_wait_seconds는 null이며 정상 wakeup 0으로 해석하지 않는다. 계측 기록과 다음 표본 조립 비용도 스케줄링에 영향을 줄 수 있다.

## 해석 한계

- CPU 시계는 `time.thread_time()`이다. 수집 스레드만 포함하며 HTTP 작업 스레드·웹 서버·Ollama CPU 사용률이 아니다.
- wall 시간이 길고 CPU 시간이 작으면 해당 스레드가 계속 CPU에서 실행된 것은 아니라는 단서다. OS 경쟁·IO·GIL 등 개별 대기 원인은 이것만으로 확정하지 않는다.
- 기록은 RSS나 누락 표본을 보정하는 데 쓰지 않는다. 타이머 자체 비용도 있어 ON과 OFF 결과가 같다고 가정하지 않는다.
- 두 실행의 모델·소스·옵션·생성 길이·표본 지연을 함께 확인한다. 한 쌍의 순차 실행으로 모든 외부 부하·실행 순서 효과를 제거한 실험은 아니다.
- 부모 표 중복 조회 제거는 별도 개선에서 완료했다. 이번 v2는 검사 캐싱·검사 빈도 감소·모델 교체를 하지 않으며 기본 OFF에서 상세 시간/CPU 기록을 만들지 않는다.

## 자동 검증

v2 테스트 12개를 추가해 전체 400개가 통과했다. 단계 구성/포함 경계/비중첩, 새 경로의 OFF CPU 호출 방지, 내부 8단계 실패와 전체 범위 검사 실패 보존, 표본별 기록 분리 및 wall/CPU 독립 기록을 확인한다. [개선 후 v1 ON 결과](MEMORY-PARENT-PROFILING-RESULT-20261008.md)에서는 스냅샷 경과의 90.33%가 membership이었다. 실제 v2 실행은 아직 하지 않았으므로 세부 단계 병목은 미확정이다. 위 상태 문단의 363개는 최초 v1 도입 시점의 기록이다.

OFF CPU 호출 방지, phase 구성, RSS/PID 보호 유지, 실패 phase 보존, wall/CPU 독립 기록, 늦은 wakeup·응답 완료 대기 종료, 경계 표본 유지, 옵션 전달을 8개 추가 테스트로 확인했다. 실제 ON에서는 스냅샷 경과의 98.85%가 membership이었다. 다만 세부 네이티브 조회 비용과 CPU 경쟁의 개별 원인은 아직 미확정이다.
