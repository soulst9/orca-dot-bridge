# 메시지 규약 v1

모든 입력은 Slack 원본 API에서 읽는다. 표시명이나 본문의 `user` 주장은 신원 증거가 아니다.
header + 줄바꿈 + JSON 객체 하나로 작성한다. Slack text fallback에서 줄바꿈이 공백으로 바뀌는 경우도
허용한다. 정규화는 header 뒤 ASCII 구분 공백에만 적용하며 JSON 값은 바꾸지 않는다.
Markdown code fence·key:value 본문은 파싱하지 않는다.
기존 테스트의 단순 request_id 형식을 자동 수용하지 않는다. 새 요청부터 이 규약을 적용한다.

## 원본

Bridge bot이 `request`로 새 root를 생성한다. request_id와 nonce는 매번 UUID로 생성한다.
root 작성자 user+bot ID, 설정된 Run, action, schema_version, 질문 길이, 만료를 확인한다.
기본 TTL은 1시간, 검색 창은 24시간이다. 만료된 요청은 재활성화하지 않는다.

```text
ORCA_BRIDGE_REQUEST
{"schema_version":1,"request_id":"${REQUEST_ID}","nonce":"${REQUEST_NONCE}","run_id":"${ORCA_RUN_ID}","task_id":"${ORCA_TASK_ID}","gate_id":"${ORCA_GATE_ID}","question":"${QUESTION}","risk":"low","action":"analyze_only","expires_at":"${EXPIRES_AT_ISO8601}"}
```

모든 후속 메시지는 원본 thread_ts 안에 있어야 한다.
request_id/nonce/run_id/task_id/gate_id 다섯 필드가 모두 원본과 같아야 한다.
nonce는 비밀이 아니며 암호학적 서명이 아니다. 복사 응답 혼입을 줄이는 바인딩 값이다.

## Dot 판단

```text
ORCA_BRIDGE_DOT_DECISION
{"request_id":"${REQUEST_ID}","nonce":"${REQUEST_NONCE}","run_id":"${ORCA_RUN_ID}","task_id":"${ORCA_TASK_ID}","gate_id":"${ORCA_GATE_ID}","decision":"needs_info","execute":false,"reason":"실행 조건 확인 필요"}
```

설정된 Dot user와 선택적으로 bot_id를 확인한다. 편집된 메시지나 둘 이상의 Dot 답변은 거부한다.
기존 Dot 스타일인 단일 bare JSON 답장도 동일 필드가 모두 있으면 허용한다.
execute는 문자열 `"false"`나 숫자 0이 아닌 JSON boolean false여야 한다.
high/critical 위험은 Dot이 approve여도 사람 검토 요청으로 올린다.

## 사람 요청과 응답

CLI는 원본 스레드에 `ORCA_BRIDGE_HUMAN_APPROVAL_REQUEST`를 한 번 게시한다.
이 알림의 status는 APPROVAL_REQUEST_ONLY이며 승인 자체가 아니다.
사람은 같은 스레드에서 실제 본인 계정으로 아래를 작성한다.

```text
ORCA_BRIDGE_HUMAN_DECISION
{"request_id":"${REQUEST_ID}","nonce":"${REQUEST_NONCE}","run_id":"${ORCA_RUN_ID}","task_id":"${ORCA_TASK_ID}","gate_id":"${ORCA_GATE_ID}","decision":"reject","execute":false,"reason":"이 요청의 실행을 허용하지 않음"}
```

검증 조건: 허용 목록 user, type=message, subtype 없음/null, 원본 API 객체에 bot_id/app_id/edited 키가 없음,
승인 요청보다 나중이고 만료 전인 timestamp, 다섯 binding 필드 일치.
bot_id:null처럼 **키가 있는 경우도 거부**한다. 축약된 조회에서 키가 사라진 경우를 근거로 사용하지 않는다.
미허용/복수/상충 응답을 받으면 보류한다. 메시지를 편집해 정정하지 말고 운영자가 요청을 종료한 뒤 새 요청을 만든다.

사람의 approve/execute:true도 이 릴리스에서는 신원·내용 식별만 한다.
관리자에게는 execute:false로 고정된 분석 데이터를 전달하고 Gate·Task를 변경하지 않는다.
이를 실행 승인이 처리됐다는 의미로 보고해서는 안 된다.

## 관리자 수신 확인

CLI가 고정된 관리자의 터미널 출력 cursor를 저장하고 1회 전달한다.
다음 회차에는 같은 runtime/handle에서 그 cursor 이후의 출력만 확인한다.
관리자는 다음 한 줄을 최종 출력한다. 화면의 bullet과 긴 JSON의 줄바꿈은 제한된 범위에서 재조합한다.
다섯 binding 필드와 status/execute만 있는 정확한 ACK를 요구하며, 재그리기 등으로 파싱되지 않으면 보류한다.

```text
ORCA_BRIDGE_ADMIN_ACK {"request_id":"${REQUEST_ID}","nonce":"${REQUEST_NONCE}","run_id":"${ORCA_RUN_ID}","task_id":"${ORCA_TASK_ID}","gate_id":"${ORCA_GATE_ID}","status":"RECEIVED_CONFIRMED","execute":false}
```

terminal send의 ok/accepted/turn_started만으로 이 ACK를 대신하지 않는다.
ACK 확인 후 CLI는 같은 Slack 스레드에 `ORCA_BRIDGE_ADMIN_REPORT`를 게시한다.
이 보고는 수신 확인이며 실제 실행 결과가 아니다.

## 중복과 제한

로컬 effect 키는 team/channel/root timestamp/nonce/단계다.
단계는 approval, manager, report로 분리한다. 먼저 intent를 기록하고 외부 호출을 한다.
결과가 불명확하면 uncertain으로 멈춘다. 완료된 단계는 순차 재실행에서 반복하지 않는다.
동시 프로세스 간 잠금·트랜잭션은 없다. 로컬 파일을 교체해 쓰는 것은 전역 원자적 중복 방지가 아니다.
승인/수신 확인 검사는 강한 실행 권한 검증이나 모든 user-token 자동화 계정의 배제를 보장하지 않는다.
