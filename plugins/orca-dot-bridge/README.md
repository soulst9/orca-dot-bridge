# orca-dot-bridge 0.3.0

Dot의 판단을 Slack 스레드로 받아 기존 Orca Claude/Codex 관리자에게 **분석 데이터로 전달**하고,
실제 수신 ACK를 확인한 뒤 Slack에 보고하는 배포용 패키지다.
Orca Automations가 필요할 때 Python CLI를 한 번 실행한다. 별도 상시 Node.js 서버·웹훅·포트·DB가 없다.

```text
Dot 예약 판단 ⇄ Slack 원본 스레드 ⇄ Orca Automation → 일회성 CLI → 기존 관리자
                         ↑                  ↓                   ↓
                  사람 결정 식별       macOS Keychain       실제 수신 ACK
                         └───────── Slack 원본 스레드 보고 ───────┘
```

초기 `enabled:false`이며 자동 Gate 해결·자동 취소·원자적 중복 방지·장애 자동 복구·강한 실행 권한 통제는
모두 false다. 미검증 기능을 true로 바꾸면 CLI가 거부한다. 실행 기능은 이 릴리스에 포함하지 않는다.

## 채팅에서 세션 설정

[공개 GitHub 저장소의 설치 명령](https://github.com/soulst9/orca-dot-bridge#install-from-github)으로 Codex 또는 Claude Code에
플러그인을 설치한다. Codex에서는 설치된 `setup-orca-bridge` 스킬을 선택하고, Claude Code에서는
`/orca-dot-bridge:setup-orca-bridge`를 실행한다. 새 설치의 기본값은 필요할 때 열기다. 이 스킬은
브리지 CLI로 로컬 설정을 저장한다. [GitHub 연결 및 터미널 설정 안내](docs/github-intake.md)를 참고한다.

## GitHub Projects 접수

`github-intake`는 기존 보드에서 이슈를 찾아 프로젝트 전용 Orca 관리자와 Run을 자동으로
생성하거나 재사용한다. 읽기 전용 수신 확인이 오면 이슈에 코멘트를 달고 보드 상태를 갱신한다.
승인된 테스트 이슈는 Orca가 별도 Task, Worktree, 읽기 전용 Worker를 생성한다.
GitHub 접수 설치 시 `github-intake-setup`에서 관리자 세션 방식을 고른다. 기본값은 대기열이
비고 GitHub 반영이 끝나면 세션을 닫는 방식이다. 같은 세션을 계속 열어 두는 옵션도 있다.
[GitHub Projects 설치 및 복구 절차](docs/github-intake.md)를 참고한다.

## 검증 범위

| 기능 | 패키지 제작 전 확인한 범위 | 이 패키지의 상태 |
|---|---|---|
| 자동 왕복 메시지 | TEST-002/003 왕복, TEST-004 10분 예약 회차 `scheduled/completed` | 실제 v1 응답·관리자 ACK·Slack 보고 확인. 새 환경은 설치 점검 필요 |
| 중복 건너뛰기 | 순차 재실행 확인 | 실제 v1 요청 재실행 `DUPLICATE_SKIPPED` 확인. 동시 원자성 없음 |
| 실행 보류 | TEST-008 `needs_info/execute:false`, Gate pending·Task blocked | 판단 데이터만 전달. 상태 변경 호출 없음 |
| 사람 승인 요청/응답 식별 | TEST-009 요청 게시, TEST-010 원본 메타데이터 확인 | 허용 사용자·thread·nonce·시간·boolean 검증. 실제 실행 승인 처리 없음 |
| 수동 Gate 해결 | TEST-007 `resolved` 최종 확인 | 별도 [수동 운영 가이드](docs/manual-gates.md) |
| 수동 Task 취소 | TEST-011 Task failed, Gate pending 유지 | 별도 수동 운영 가이드 |
| 자동 Gate 해결/취소 | 미검증 | 비활성·미구현 |
| 원자적 중복 방지·장애 복구·강한 권한 강제 | 미검증 | 비활성·보장하지 않음 |

이전 TEST-* 결과는 패키지 제작 전 현장 관찰이며, 새 v1 패키지의 설치 점검과 구분한다.
v1 규약의 nonce·만료·검증 절차는 모의 테스트와 별도의 실제 왕복 점검으로 확인했다.
이전 `ORCA_BRIDGE_TEST`/TEST-* 메시지를 자동 이관하거나 재처리하지 않는다.
자세한 근거와 제한은 [validation.md](docs/validation.md)에 있다.

기존 환경에 0.1.2를 설치해 Dot의 v1 판단, Codex의 실제 ACK, Slack 원본 스레드 보고까지 확인했다.
0.1.1에서 관리자 초안 보호와 화면 ACK 줄바꿈 처리를 보강했고, 0.1.2에서 Slack의 header 줄바꿈이
공백으로 바뀌는 경우를 처리했다. 새 설치는 아래 순서대로 대상 채널과 관리자 연결을 확인한다.

## 설치

필수: macOS, Python 3.9 이상(표준 라이브러리만), 실행 중인 Orca와 그 CLI,
Slack 앱/채널, Slack을 읽고 답할 수 있는 Dot 예약 실행, 기존 Claude 또는 Codex 관리자 터미널.
CLI 패키지는 별도 라이브러리를 설치하지 않고 압축 해제한 폴더에서 바로 실행한다.

```bash
chmod +x bin/orca-dot-bridge
cp config.example.yaml config.yaml
python3 -m unittest discover -s tests -v
```

`config.yaml`의 `${NAME}`들을 설치자 값으로 치환한다. 또는 같은 이름의 환경변수를 설정하면 CLI가 확장한다.
예약 실행 세션은 셸 환경을 그대로 상속하지 않을 수 있으므로, **로컬 config에 비밀이 아닌 식별자를 채우는 방식**을 권장한다.
예제는 JSON 표기의 YAML 1.2다. 의존성 없이 읽기 위해 JSON 문법을 유지한다. 일반 YAML 문법·주석은 지원하지 않는다.

- Slack: team/channel, Bridge bot의 user+bot ID, Dot user+bot ID, 사람 approver ID 목록.
  Dot이 bot_id 없는 연결이라면 dot_bot_id를 빈 문자열로 직접 설정한다.
- Keychain: account, writer_service, reader_service. 토큰 값은 config에 넣지 않는다.
- 관리자: provider를 `codex` 또는 `claude`로 설정하고 현재 Run ID, 전체 terminal handle, 절대 worktree 경로를 채운다.
  제목·이름·짧은 핸들로 추측하지 않는다. 채팅 전용 관리자는 현재 터미널 전송 경로의 대상이 아니다.
- state_file: 사용자 전용 상태 파일의 절대 경로. 프로젝트별로 채널/config/상태 파일/Automation을 분리한다.
- orca.executable: 보통 `auto`. 지정할 때는 실행 파일의 절대 경로 하나를 사용한다. 셸 명령 문자열은 지원하지 않는다.

현재 핸들과 Run은 선택한 Orca의 `terminal list --json`, `orchestration run-list --json`으로 찾고
설치자가 관리자의 실제 소속을 확인한다. Run이 없다면 설치된 orchestration Skill의 생성 절차를 따른다.
Skill은 `skills/dot-manager/SKILL.md`와 `skills/orca-coordinator/SKILL.md`를 각각 해당 에이전트에 등록/첨부한다.
Dot의 Skill 설치·스케줄을 자동 생성하는 API는 이 패키지에서 가정하지 않는다.

## Slack 최소권한과 Keychain

1. 전용 Slack 앱을 만들고 한 Bridge 채널에 초대한다. 전송 bot scope는 `chat:write`만 요청한다.
   [chat.postMessage 문서](https://docs.slack.dev/reference/methods/chat.postMessage/)를 기준으로 하며
   `chat:write.public`, `chat:write.customize`, 관리자·파일·검색 scope는 필요 없다.
2. 읽기 토큰에는 사용하는 대화 유형의 scope 하나만 추가한다. 공개 채널 `channels:history`,
   비공개 채널 `groups:history`, DM `im:history` 중 실제 유형에 맞춘다.
   [history](https://docs.slack.dev/reference/methods/conversations.history/)와
   [replies](https://docs.slack.dev/reference/methods/conversations.replies/)는 반드시 실제 설치 토큰으로 확인한다.
   토큰 유형/Slack 설치 정책에 따라 채널 thread 읽기가 거부되면 자동으로 scope를 넓히지 않는다.
   필요한 경우 **읽기 scope만 가진 별도 user token**을 reader_service에 등록해 재점검한다.
   공개 채널 user token의 접근 범위는 이 CLI의 한 채널 제한보다 넓을 수 있다.
   설치자는 Slack 앱의 실제 granted scopes도 확인한다. auth-test는 토큰 신원 검사이며 과도한 scope를 자동 제거하지 않는다.
3. writer와 reader는 같은 Keychain 서비스여도 된다. 읽기 권한을 분리하려면 별도 서비스로 지정한다.
   [auth.test](https://docs.slack.dev/reference/methods/auth.test/)에는 별도 scope가 필요 없다.

토큰은 아래 명령의 대화형 비밀번호 입력에만 넣는다. 토큰을 명령 인자·환경변수·파일·채팅에 넣지 않는다.
macOS Keychain Access에서 같은 account/service의 일반 비밀번호로 직접 등록해도 된다.

```bash
./bin/orca-dot-bridge --config config.yaml auth-store --role writer
./bin/orca-dot-bridge --config config.yaml auth-store --role reader
./bin/orca-dot-bridge --config config.yaml auth-test
python3 scripts/check_install.py --config config.yaml
```

같은 서비스를 쓸 때 reader 등록은 생략한다. `auth-store`는 `security ... -w`를 마지막 인자로 호출해
시스템 프롬프트로 입력받는다. `security -w TOKEN`이나 `-A` 전체 앱 접근 허용을 사용하지 않는다.
Keychain 접근 승인은 실제 Automation 계정에서도 확인한다. 같은 OS 계정의 다른 프로세스까지
토큰 접근을 강제로 차단하는 보안 경계는 이 패키지에 없다.

## 첫 연결 점검과 예약 실행

1. 테스트 채널/관리자에서 시작한다. `config.yaml`의 enabled만 true로 바꾼다.
2. 요청 질문을 로컬 텍스트 파일에 쓰고 아래를 한 번 실행한다. task/gate 변수는 **실제 해당 Run의 ID**다.
   기존 Task/Gate가 없다면 버전별 도움말에 따라 별도로 테스트용 기록을 만든다. 이 명령은 기록을 만들거나 해결하지 않는다.

```bash
./bin/orca-dot-bridge --config config.yaml request \
  --question-file question.txt --task-id "$ORCA_TASK_ID" --gate-id "$ORCA_GATE_ID" --risk low
```

3. 반환된 thread_ts를 아래 변수에 넣는다. `doctor --online`은 읽기 전용으로 인증·채널·스레드·관리자 연결을 검사한다.

```bash
python3 scripts/check_install.py --config config.yaml --online --thread-ts "$SLACK_THREAD_TS"
./bin/orca-dot-bridge --config config.yaml tick --dry-run
```

4. Dot에 [dot-prompt.template.txt](automations/dot-prompt.template.txt)의 변수를 채워 10분 주기로 등록한다.
   원본 스레드의 Dot JSON을 확인한다. `tick --dry-run`의 예상 결과는 `WOULD_FORWARD_ANALYSIS_ONLY`다.
5. `tick`을 한 번 실행한다. 관리자 ACK가 아직 없으면 다음 회차에서 확인하며 같은 입력을 재전송하지 않는다.
   `RECEIVED_CONFIRMED`와 Slack 보고를 확인한다. 다시 순차 실행해 `DUPLICATE_SKIPPED`를 확인한다.
6. 다음 명령은 **비활성 Automation 생성 명령을 출력만 한다**. 출력의 argv/shell_command를 확인하고 실행한다.

```bash
./bin/orca-dot-bridge --config config.yaml automation-plan
```

생성 결과에서 전체 Automation ID를 보관한 뒤 한 회차만 수동 실행하고 기록을 확인한다.
아래 `orca`는 doctor가 선택한 실행 파일과 같아야 한다.

```bash
orca automations run --id "$ORCA_AUTOMATION_ID" --json
orca automations runs --id "$ORCA_AUTOMATION_ID" --limit 3 --json
orca automations edit --id "$ORCA_AUTOMATION_ID" --enabled --json
```

10분 cron과 시간대는 Orca 화면에서 확인한다. Mac과 Orca가 켜져 있고 Keychain 접근이 가능해야 한다.
수동 회차가 끝난 뒤 예약 실행을 활성화한다. `trigger:scheduled`와 실제 왕복 보고를 별도로 확인한다.
수동 Run now는 precheck를 우회하므로 precheck를 잠금이나 권한 통제로 취급하지 않는다.

## 운영

```bash
./bin/orca-dot-bridge --config config.yaml tick
./bin/orca-dot-bridge --config config.yaml read --thread-ts "$SLACK_THREAD_TS"
./bin/orca-dot-bridge --config config.yaml post --text-file note.txt --thread-ts "$SLACK_THREAD_TS"
orca automations edit --id "$ORCA_AUTOMATION_ID" --disabled --json
```

`read`에는 메시지 본문과 식별자가 출력된다. 토큰이나 인증 헤더는 출력하지 않는다.
`post`는 같은 채널의 단순 전송 도구이며 중복 방지 영수증을 사용하지 않는다. 자동 보고는 `tick`을 사용한다.
전송 timeout 뒤에는 수동 post/request도 바로 반복하지 말고 원본 채널에서 결과를 확인한다.
운영 중 `uncertain`, 손상된 상태, stale handle, ACK 조회 누락이면 예약 실행을 끄고
[수동 점검 절차](docs/operations.md)를 따른다. 자동 재전송/재시작/복구는 제공하지 않는다.

Slack [rate limit](https://docs.slack.dev/apis/web-api/rate-limits/)은 앱 배포 유형에 따라 다르다.
429면 Retry-After를 보고하고 종료한다. 재시도·장시간 대기는 하지 않는다.
15개 페이지와 전체 cursor 조회를 사용하므로 다수 요청/긴 스레드는 읽기 한도에 걸릴 수 있다.
한도를 이유로 일부 메시지만 읽고 승인하거나 작업하지 않는다.

## 파일

- `skills/`: Dot Manager / Orca Coordinator
- `orca_dot_bridge/`, `bin/`: Keychain·Slack 인증/전송·판단 검증·단일 회차 처리
- `config.example.yaml`, `policies/`: 배포용 변수와 승인 정책 예시
- `automations/`, `orca_dot_bridge/automation_prompt.txt`: 예약 프롬프트
- `scripts/check_install.py`, `tests/`: 설치·호환성 점검과 모의 테스트
- `docs/`: 프로토콜, 운영, 수동 Gate 처리, 검증 기록

압축 배포물에는 실제 토큰·사용자 ID·Run/Task/Gate ID·터미널 핸들·프로젝트 경로를 넣지 않는다.
테스트 식별자는 생성된 가상 값이다. 로컬 config·상태·온라인 점검 로그는 재배포하지 않는다.
