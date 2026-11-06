# 운영과 수동 점검

## 일상 운영

Dot과 Orca는 각각 10분 주기다. 판단 도착과 ACK가 다음 회차로 넘어갈 수 있다.
CLI는 대기 루프를 띄우지 않고 매번 종료한다. 기본 TTL 1시간 안에서 처리되지 않으면 새 요청을 만든다.
한 회차에서 진행시키는 요청은 최대 한 건이다. 기존 보고/판단 없음/사람 대기는 건너뛸 수 있다.
Automation을 중복 등록하지 않고 같은 config/상태 파일을 쓰는 회차를 겹쳐 실행하지 않는다.
한 스레드에는 Dot 결정 하나와 사람 결정 하나만 둔다.
많은 요청을 한 채널에서 처리하는 높은 처리량의 서비스는 이 릴리스의 검증 범위가 아니다.

## 출력 해석

| 결과 | 뜻 | 다음 조치 |
|---|---|---|
| NO_PENDING_REQUEST / NO_DOT_DECISION | 처리할 새 판단 없음 | 다음 회차 |
| HUMAN_APPROVAL_REQUESTED | 사람 검토 알림만 게시 | 사람 답장 대기 |
| WAITING_FOR_HUMAN | 허용된 사람 응답 없음 | 같은 원본 스레드에서 응답 |
| AWAITING_MANAGER_ACK_NO_RESEND | 전송 시도 기록 존재, 실제 ACK 미확인 | 재전송 없이 다음 회차에서 읽기 |
| RECEIVED_CONFIRMED | 관리자 ACK와 Slack 보고 완료 | 실행 승인 완료로 해석하지 않기 |
| DUPLICATE_SKIPPED | 해당 원본 스레드의 Bridge 보고 존재 | 중복 작업 없음 |
| VERIFICATION_FAILED | 신원/바인딩/시간/메시지 형식 등 불일치 | 해당 요청 보류, 원본 확인 |
| uncertain_effect | 외부 호출 결과가 불확실 | 예약 실행 중단, 수동 대조 |
| slack_rate_limited | Slack 429 또는 제한 응답 | Retry-After 확인, 자동 반복 금지 |

HTTP 200이라도 Slack ok:false는 실패다. 429·전송 오류·일부 페이지 조회·cursor 반복이면 성공으로 처리하지 않는다.
새 history는 시간 창 전체를 읽고, 각 스레드는 모든 cursor 페이지를 읽은 뒤 검증한다.
page budget을 넘기면 해당 읽기는 실패다. 이전 스레드에서 이미 완료된 부수효과는 되돌리지 않는다.

## 오류 시 멈추는 순서

1. 정확한 Automation ID로 `automations edit --id ... --disabled --json`을 실행한다.
2. 진행 중 회차가 끝났는지 runs에서 확인한다. 비활성화만으로 이미 실행 중인 프로세스가 종료된 것은 아니다.
3. 로컬 상태 파일을 접근 제한된 위치에 보관한다. 토큰은 포함되지 않지만 식별자와 영수증이 있다.
4. 해당 원본 Slack 스레드, manager terminal read와 runtime, Automation 기록을 읽기 전용으로 비교한다.
   전송 여부를 확인하기 위해 시험 삼아 같은 입력을 다시 보내지 않는다.
5. 외부 효과를 확정할 수 없으면 보류한다. 확정됐더라도 자동으로 상태를 다시 맞추는 기능은 없다.
   운영자가 근거를 남기고 해당 단계의 로컬 영수증을 수동 대조해야 한다. 전체 state를 삭제해 재시작하지 않는다.
6. 미해결 요청을 만료시킨 뒤 새 nonce/새 request_id로 다시 시작할 때도 기존 효과가 끝났는지 확인한다.

자동 reconciliation 명령이나 retry 플래그를 제공하지 않는다. `inflight`/`uncertain`을 무조건 done으로
바꾸면 중복 전송 또는 누락을 만들 수 있다. 장애 후 정확히 한 번 처리된다는 보장은 없다.

## 관리자 종료·Orca 재시작

terminal_handle_stale이면 이름이나 제목으로 새 핸들을 추측하지 않는다.
선택한 같은 실행 파일/호스트의 terminal list에서 전체 핸들을 다시 찾고 설치자가 실제 관리자를 확인한다.
원래 Run, provider, worktree 경로도 다시 확인한 뒤 config를 갱신한다.
이미 전송된 요청은 새 관리자로 자동 재전송하지 않는다. runtime이 바뀌면 기존 receipt의 확인을 멈춘다.
manager가 채팅 전용이면 별도로 터미널 기반 관리자를 준비하거나 후속 릴리스에서 구조화 mailbox 경로를 검증해야 한다.

## 최소권한의 한계

전송기는 고정 Slack 호스트·한 채널·네 API만 사용한다. 토큰은 Keychain에서 메모리로 읽고
Authorization header에만 쓴다. HTTP redirect를 거부하고, 오류에 원본 응답/헤더/토큰을 출력하지 않는다.
일회성 post/request는 사람의 명시적 CLI 호출이며 자동 중복 방지 대상이 아니다.

CLI가 허용하는 API와 scope를 줄인 것이 OS 수준 격리는 아니다.
같은 macOS 계정이나 넓은 권한을 가진 에이전트는 security/orca를 직접 실행할 수 있다.
Skill, prompt, config false, --from handle은 강한 권한 강제가 아니다.
자동 실행을 도입하려면 별도 자격 경계·승인자 관리·원자성·복구 검증이 필요하다. 이 릴리스에서 켤 수 없다.

## 버전별 호환성

실행 파일 선택은 ORCA_CLI_COMMAND → ORCA_DEV_REPO_ROOT의 orca-dev → macOS orca다.
지정 파일이 실패하면 다른 Orca 빌드로 자동 전환하지 않는다. Linux에서는 orca-ide를 선택하지만
Keychain 기반 실제 운영은 macOS만 지원한다.

doctor는 --version, 두 version-matched Skill, 관련 명령 --help의 실제 옵션 행을 검사한다.
`--id` 지원이 없는데 positional 인자로 임의 대체하거나 task cancel 명령을 추측하지 않는다.
필수 옵션이 없으면 automation-plan/tick을 거부한다. skills get을 모르는 구버전은 가용성 경고와 함께
도움말 검사만 가능하며, 최신 가이드가 필요하면 Orca를 업데이트한다.

도움말 검사는 호스트 상태·권한·JSON 응답 구조·상태 전이의 실제 동작을 증명하지 않는다.
업데이트 후 doctor와 온라인 읽기 점검을 다시 수행하고, 테스트 채널에서 한 회차만 확인한 뒤 예약을 재개한다.
