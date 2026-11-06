# 수동 Gate 해결과 Task 취소

이 문서는 자동화에 넣지 않는다. 현장 테스트에서 성공한 수동 절차를 템플릿으로 보관한 것이다.
설치된 Orca의 도움말과 상태를 다시 확인한다. 아래 변수는 운영자가 해당 요청의 실제 값으로 채운다.
`orca`는 doctor가 선택한 실행 파일로 바꾼다. `--from`은 호출자 인증 수단이 아니다.

## 사전 확인

```bash
orca orchestration gate-list --task "$ORCA_TASK_ID" --from "$ORCA_COORDINATOR_HANDLE" --json
orca orchestration task-list --run "$ORCA_RUN_ID" --json
orca orchestration worker-list --run "$ORCA_RUN_ID" --json
orca orchestration dispatch-show --task "$ORCA_TASK_ID" --from "$ORCA_COORDINATOR_HANDLE" --json
```

같은 Run/Task/Gate인지, Gate pending·Task blocked인지 확인한다.
실행 중 Worker/Dispatch가 있으면 단순 task-update만으로 취소하지 않는다.
설치된 orchestration recovery-and-cleanup 문서를 읽어 별도 중지·회수 절차를 수행한다.
이 패키지는 그 상태를 자동 처리하지 않는다.

## 사람이 별도로 실행을 허가한 approve

해당 요청에 대한 최신 사람 권한, 실행 범위, 만료, 현재 상태와 다른 실행 주체를 별도로 확인한 뒤
운영자가 아래 한 명령을 직접 실행한다.

```bash
orca orchestration gate-resolve --id "$ORCA_GATE_ID" \
  --resolution approve --from "$ORCA_COORDINATOR_HANDLE" --json
```

Gate 해결은 Task를 ready로 전환할 수 있다. Gate 해결과 후속 정리는 하나의 트랜잭션이 아니다.
전용 터미널이나 Worker 0개만으로 다른 실행 주체가 없음을 보장할 수 없다.
해결 후 gate-list/task-list/worker-list/dispatch-show로 결과를 다시 확인한다.
TEST-007의 최종 resolved/failed/Worker 0/dispatch null 관찰은 모든 중간 상태의 안전성 증명이 아니다.

## reject와 수동 취소

**reject, needs_info, human_required를 gate-resolve에 전달하지 않는다.**
관찰한 Orca 구현에서는 resolution 문구가 거절이어도 Task가 ready로 바뀔 수 있었다.
reject는 Gate를 유지하고, 해당 Task의 취소를 별도로 검토한다.

사람의 해당 Task 취소 허가와 Worker/Dispatch 없음이 확인된 경우의 수동 명령:

```bash
orca orchestration task-update --id "$ORCA_TASK_ID" --status failed --result cancelled \
  --run "$ORCA_RUN_ID" --from "$ORCA_COORDINATOR_HANDLE" --json
```

확인할 최종 상태는 Task failed와 Gate pending이다. pending Gate를 오류라며 추가 해결하지 않는다.
Orca에는 이 경로의 cancelled status가 없으므로 failed + result cancelled로 기록한다.
이것은 프로세스 종료 명령이 아니며, 나중의 worker-start --retry-of가 Task를 재개할 수 있다.
테스트 간 과거 승인/거절 결정을 새 Task의 실행 허가로 재사용하지 않는다.

needs_info, human_required, execute:false는 Gate를 그대로 유지한다.
승인 입력이 식별됐다는 이유만으로 위 명령을 Automation에서 실행하지 않는다.
