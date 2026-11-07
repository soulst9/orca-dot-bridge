# GitHub Projects 접수

기존 Projects 보드 하나를 설정에 고정한다. 브리지는 해당 저장소의 열린 이슈가 보드에 올라와 있고 시작 상태에 있을 때만 새로 접수한다. 보드에 이슈를 추가하는 일은 GitHub Projects의 기존 자동화가 맡는다. Slack 명령과 기존 관리자 설정은 별도 경로를 사용한다.

| 단계 | 조건과 동작 |
| --- | --- |
| 접수 | 개별 테스트는 `issue_allowlist`로 승인한다. 운영 후보는 배치 설정과 `orca-intake` 라벨이 필요하다. |
| 관리자 | Orca가 프로젝트별 Worktree와 Run을 처음 한 번 만든다. 접수할 일이 있을 때 관리자 세션을 열고, 열려 있으면 같은 세션을 쓴다. 닫힌 뒤에는 기록된 Worktree와 Run에 새 세션을 연결한다. |
| 수신 확인 | 관리자는 검증된 이슈 URL과 일회용 토큰만 받는다. 응답 토큰을 확인한 뒤 브리지가 이슈 코멘트와 보드 상태를 갱신한다. |
| Worker | 읽기 전용으로 승인된 테스트 이슈에만 전용 Run의 Task와 독립 Worktree를 자동 생성한다. Orca의 Task 결과를 이슈에 남긴다. |
| PR | 옵션이 켜져 있고 Worker가 성공한 경우 전용 Worktree의 원격 브랜치와 정확히 일치하는 PR을 이슈에 연결한다. 아래의 별도 게시 승인을 확인하면 Draft PR을 만들 수 있다. |

## 실행

[공개 GitHub 저장소의 설치 명령](https://github.com/soulst9/orca-dot-bridge#install-from-github)으로 플러그인을 설치한 뒤
Codex에서는 `setup-orca-bridge` 스킬을 선택하고, Claude Code에서는
`/orca-dot-bridge:setup-orca-bridge`를 실행한다. 설정 파일이 여러 개라면 사용할 프로젝트의
경로를 지정한다. 터미널에서 처음 설정할 때는 예제 설정을 복사한 다음 같은 선택을 한다.

```sh
cp -n github-intake.example.json github-intake.json
./bin/orca-dot-bridge github-intake-setup
```

- **1. 필요할 때 열기**는 새 설치의 기본값이다. 대기열이 비고 GitHub 반영이 끝나면 세션을 닫는다. 다음 접수에는 같은 Worktree와 Run에 새 세션을 연결한다.
- **2. 같은 세션 유지**는 대기열이 비어도 관리자 세션을 계속 열어 둔다.

설정이 이미 있으면 같은 명령으로 선택을 바꿀 수 있다. Enter는 현재 값을 유지한다.
`coordinator_auto_close`가 없는 이전 설정은 런타임과 설정 화면에서 모두 같은 세션 유지로 처리한다.
터미널 입력이 없는 설치에서는 `github-intake-setup --session-mode on-demand` 또는
`github-intake-setup --session-mode persistent`를 실행한다. 선택은 `coordinator_auto_close`에
저장되고 다음 접수 회차부터 적용된다.

설정 파일에 식별자와 보드의 Status 이름을 채운다. 프로젝트 ID는 `gh project view NUMBER --owner OWNER --format json`, Orca 저장소 ID는 `orca repo list --json`으로 확인한다. CLI와 Orca가 실행되는 동일한 Mac 계정에서 `gh auth status`로 로그인과 Projects 접근 권한을 확인한다. 다른 위치의 설정을 쓸 때는 하위 명령 앞에 `--config /absolute/path.json`을 넣는다.

```sh
./bin/orca-dot-bridge github-intake --doctor
./bin/orca-dot-bridge github-intake --issue 101
./bin/orca-dot-bridge github-intake --issue 101 --apply
./bin/orca-dot-bridge github-intake --issue 101 --issue 102 --apply --workers
```

`--apply`를 빼면 읽기 전용이다. `awaiting_coordinator_ack`나 `worker_running`이면 다음 실행이 동일한 요청을 이어받는다. 예제 설정은 `Todo` 상태의 이슈를 접수해 `In Progress`로 이동한다. 읽기 전용 Worker가 끝나면 결과 코멘트를 남긴다. 구현이나 앱 빌드가 끝난 것으로 표시하지 않는다.

브리지는 GitHub와 Orca 연결을 열기 전에 해당 실행 경로의 Orca CLI 옵션을 검사한다.
`--doctor`는 현재 설정에서 사용할 적용·종료·Worker 명령까지 확인한다.

예제의 이슈 번호는 자신의 테스트 이슈 번호로 바꾼다. 테스트 이슈를 여러 건 지정하려면 `--issue`를 반복하고 매 회차 같은 목록을 전달한다. `coordinator_auto_close`가 켜져 있으면 매 회차 GitHub 보드를 다시 읽어 접수 가능한 이슈가 남았는지 확인한다. 다음 접수 대상이 있으면 CLI는 `coordinator_session: queued`를 반환하고 기존 세션을 유지한다. 진행 중인 요청과 GitHub 반영이 모두 끝나면 해당 관리자 세션만 닫고 `coordinator_session: closed`를 반환한다. Worktree, Run, 처리 기록은 다음 요청에서도 사용한다. 새 세션의 대화 맥락은 별도로 시작한다.

운영 접수를 켤 때는 `batch_enabled`를 활성화하고 접수할 이슈에 설정된 라벨을 붙인다. 작업 스케줄러에서 설치된 CLI의 절대 경로로 `github-intake --apply`를 실행하면 한 회차에 최대 한 건을 처리한다. 작업 디렉터리를 설치 경로로 지정하거나 `--config`로 절대 경로를 전달한다. 스케줄러에도 동일한 GitHub 계정과 로컬 Orca 접근이 필요하다. 기본 설치에서는 운영 배치와 예약 실행이 꺼져 있다.

## 승인과 PR

`worker_mode: read_only`와 `worker_canaries`는 고정된 읽기 전용 확인만 허용한다. 이슈 본문과 코멘트는 에이전트에 전달하지 않는다. 현재 Orca 에이전트의 실행 권한은 Worktree 분리와 별개이므로 이 설정으로 제품 코드 구현을 위임할 수 없다.

`draft_pr_enabled`는 기본값이 `false`다. 활성화하면 성공한 Worker의 Worktree에서 검토자가 코드를 검토하고 해당 전용 브랜치를 직접 게시할 수 있다. 브리지가 새 Draft PR을 만드는 데에는 설정된 GitHub 계정이 이슈에 남긴 정확한 `orca-approve-draft-pr BRANCH COMMIT_SHA` 코멘트가 필요하다. 브리지는 현재 원격 SHA와 승인 내용을 대조하고 해당 브랜치의 기존 PR을 먼저 조회한다. 푸시, 병합, 배포, 데이터 삭제, Gate 해결은 브리지의 작업 경로에 없다. PR 링크와 Worker 결과는 이슈 코멘트로 동기화한다.

후속 개발 Worker는 동일한 Task/Dispatch 저장 구조를 사용한다. 이슈 본문의 정확한 리비전을 확인한 승인, 코드 쓰기 범위가 제한된 실행 환경, 운영 자격증명 분리가 선행 조건이다. 테스트 결과와 커밋 SHA를 기록한 뒤 별도 게시 승인을 통해 Draft PR로 이어가도록 한다.

## 재시작과 중복 방지

- 프로젝트별로 동일한 비공개 상태 파일을 사용한다. 잠금 파일과 원자적 저장으로 같은 Mac의 두 실행이 동시에 같은 작업을 생성하는 것을 막는다. 상태는 프로젝트, 저장소, 관리자 유형과 GitHub 계정에 묶인다.
- 외부 변경 전에 의도를 저장한다. 재실행은 Worktree, Orca Run/Task/Dispatch, 수신 토큰, 작성자와 고유 마커가 일치하는 GitHub 코멘트, Projects의 현재 값을 확인해 이어간다. 완료된 접수는 다시 코멘트를 남기거나 상태를 되돌리지 않는다.
- 관리자의 Orca 핸들이 달라졌다면 기록된 동일 pane을 먼저 찾는다. 조회 범위가 해당 실행 호스트를 포함하고 이전 pane이 사라졌음이 확인되면 전용 Worktree에 새 세션을 열고 기존 Run을 이어받는다. 이전 세션에서 읽기 전용 응답을 받지 못했다면 새 토큰으로 수신 확인만 다시 요청한다. 외부 작업의 결과를 확인할 수 없으면 중단하고 상태 파일을 보존한다. Orca 자체 재시작은 운영 Run에 영향을 줄 수 있어 검증 절차에 포함하지 않았다.
- Projects 상태를 갱신하기 직전에 이슈와 현재 상태를 재조회한다. GitHub API에는 상태 비교와 쓰기를 묶는 조건부 연산이 없어 그 순간 보드에서 동시에 발생한 변경까지 원자적으로 보호할 수는 없다.
- 상태에는 GitHub 이슈, 보드 항목, Orca 리소스 ID와 처리 영수증이 저장된다. 토큰과 이슈 본문을 저장하지 않는다. 수신 확인에 쓰는 난수는 로컬 상태에만 기록한다.

### 시작 결과를 잃은 관리자 세션 복구

`bridge_terminal_unavailable:restore_recorded_pane`이 나오면 해당 브리지의 예약 실행을
멈추고 상태 파일의 `coordinator.worktree`, `coordinator.handle`, `coordinator.pane`을 읽는다.
같은 Orca 호스트에서 `orca terminal list --worktree id:WORKTREE --json`으로 그 전용
Worktree만 검사한다. 이미 기록된 pane이 있으면 그 세션을 복구하고 다시 실행한다.

`launch`는 있는데 handle과 pane이 없다면 상태에는 시작 시도만 기록된 것이다. 전용
Worktree에서 이미 시작된 관리자가 하나 확인되면 다음 접수 회차가 해당 세션을 확인해 연결한다.
실행이 발생하지 않았고 나중에 실행될 요청도 없다는 사실을 확인한 경우에만 아래처럼 같은
전용 Worktree에서 설정의 관리자 종류로 터미널을 하나 시작한 뒤 접수를 재실행한다.

```sh
orca agent launch --agent AGENT --worktree id:WORKTREE --surface terminal --json
```

연결할 세션은 기존 터미널 목록에 없던 관리자 하나로 확인돼야 한다. 결과가 불명확하거나
후보가 여러 개면 Orca의 시작 기록을 대조한 뒤 재개한다. 같은 복구 방식은 시작 기록을
잃었지만 아직 배정하지 않은 전용 Worker Worktree에도 적용한다.
