# 검증 기록과 배포 경계

## 증거를 구분하는 원칙

1. **과거 현장 관찰**: 패키지 제작 전 수행한 TEST-001~011 기록.
   이 패키지의 코드가 존재하기 전 다른 프롬프트/수동 명령으로 얻은 결과다.
2. **이번 로컬 검증**: 표준 unittest의 모의 Slack/Orca/HTTP 응답, Skill 형식 검사,
   실제 설치된 Orca CLI의 version/help 검사다.
3. **설치 후 점검**: 실제 Keychain·Slack·Dot·관리자·Automation을 연결하는 별도 단계다.
   0.1.0 초기 제작에서는 실토큰 조회, Slack 게시, Automation 생성/활성화, Gate/Task 변경을 수행하지 않았다.

0.1.1 설치 중 Keychain 인증·Slack 읽기/전송, 기존 Orca Automation 백업과 수동 회차 실행,
별도의 Codex 관리자 수신 ACK를 확인했다. 작성 중인 입력이 있으면 전송을 막고, 화면의 ACK 줄바꿈을 처리한다.

0.1.2 점검에서 Dot은 기존 10분 작업을 v1으로 바꿨다고 보고했고, 실제 새 요청에 다섯 식별자와
`execute:false`를 포함해 답장했다. Slack 원본 API의 `text`가 header 줄바꿈을 공백으로 바꾸는 경우를
처리한 뒤, 동일 요청에 대한 관리자 수신 ACK와 Slack의 `RECEIVED_CONFIRMED` 보고를 확인했다.
순차 재실행은 `DUPLICATE_SKIPPED`였다. 이 실측은 한 건의 왕복과 순차 중복 확인을 증명하며,
동시 실행의 원자성·장애 복구·모든 예약 회차의 성공을 보장하지 않는다.
Gate 해결과 Task 취소는 실행하지 않았다. 당시 0.1.2의 모의 테스트 46개가 통과했다.

## GitHub Projects 현장 점검

0.2.1에서 별도 테스트 이슈 두 건을 접수했다. 첫 이슈의 읽기 전용 Worker 결과를 GitHub에
기록한 뒤 두 번째 이슈를 같은 세션에서 처리했다. 마지막 코멘트와 보드 상태 반영이 끝난 뒤
세션이 닫혔고, 재실행에서 중복 코멘트가 생기지 않았다. 이 검증은 접수·읽기 전용 작업·상태
동기화를 다룬다. 0.3.2 후보의 검증은 아래 로컬 점검과 회귀 테스트에 해당한다.

## 과거 현장 관찰 요약

| 항목 | 관찰 | 증명하지 않는 것 |
|---|---|---|
| TEST-002/003 | Dot 판단 전달, 관리자 수신 확인, 원본 Slack 스레드 보고 | 모든 관리자/버전에서 같은 출력 구조 |
| TEST-004 | 10분 예약 회차에서 scheduled/completed와 실제 왕복 보고 | 상시 서비스 가용성·정확히 한 번 전송 |
| 중복 순차 확인 | 기존 처리 흔적을 보고 반복 게시/전달 건너뜀 | 동시 처리·crash 뒤 원자적 중복 방지 |
| TEST-007 | 수동 gate-resolve 성공, Gate resolved, Task 정리 후 failed, Worker 0/Dispatch null 최종 확인 | 두 명령 사이 ready 상태·외부 실행 주체가 전혀 없었다는 증명 |
| TEST-008 | needs_info/execute:false, Gate pending·Task blocked 유지 | CLI/OS 수준 강제 실행 차단 |
| TEST-009 | human_required/execute:false 뒤 사람 승인 요청 알림 게시 | 실제 승인 접수와 자동 실행 |
| TEST-010 | 허용된 테스트 사람 user, type message, subtype null, 원본 API에서 bot_id 없음 확인 | 영구적인 운영 승인자 권한 관리·모든 자동화 계정 배제 |
| TEST-011 | 수동 task-update failed/result cancelled, Gate pending 유지 | Slack reject에 따른 자동 Task 취소·실행 중 Worker 종료 |

과거의 모든 TEST 번호를 독립적으로 성공했다고 묶지 않는다. 중단·보류된 Gate 실험이 있었다.
실제 사용자 ID, 프로젝트 이름, 핸들, 토큰, Slack permalink는 배포용 증거에 복사하지 않았다.

## 이번 구현의 새 경계

v1 원본 header, nonce, 전체 binding, 만료, 로컬 단계 영수증, 엄격한 boolean/메타데이터 검증은
새 코드다. 과거 통신 성공을 이 구현의 라이브 검증으로 대체하지 않는다.
권한 정책 YAML은 사람/에이전트용 예시이며 동적으로 로드되는 정책 엔진이 아니다.
구현은 config의 allowlist, 고정 high/critical 사람 검토, 모든 미검증 feature false를 사용한다.

## 재현

```bash
python3 -m unittest discover -s tests -v
python3 scripts/check_install.py --config config.yaml
```

모의 테스트는 자동 왕복, 순차 중복, ACK 지연, 승인 요청/사람 식별, 메타데이터 위장,
다른 thread/nonce/Run 응답, 잘못된 boolean, 만료, 고위험 승격, 일부 페이지/429,
전송 결과 불명확 시 중단, 호환성 거부, Keychain 비밀의 오류 출력 방지를 다룬다.
0.3.2에서는 초안 제거 후 첫 전송, 페이지 경계에 걸친 ACK, 진행하지 않는 ACK 커서,
GitHub Worker CLI 옵션이 부족할 때 외부 연결 전 중단을 회귀 테스트로 확인했다.
실제 macOS Keychain 대화형 저장·Dot 예약은 모의 테스트가 증명하지 않는다.
Slack/Keychain 기존 인증과 관리자 ACK 출력은 위 별도 현장 점검 범위에 한해서 확인했다.

릴리스 제작 환경의 검사 결과는 `release-checks.json`에 기록한다.
지원 버전 범위는 선언하지 않는다. 버전 숫자가 같아도 doctor의 capability 검사와 온라인 점검이 필요하다.
