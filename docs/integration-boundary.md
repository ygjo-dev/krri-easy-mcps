# Integration boundary

KRRI EASY MCPs 는 UI + thin BFF 다. 의존 방향은 한쪽뿐이다.

```text
KRRI EASY MCPs (web → BFF)
    ↓
existing agentic_ai API (POST /chat/stream)
    ↓
agentic_ai existing pipeline (Resolve → Accepted Recipe → workflow materialization → execution)
    ↓
KRRI_ASAP (Gateway / MCP servers)
```

**KRRI EASY MCPs 를 위해 agentic_ai 를 수정하지 않는다.** agentic_ai 는 이 Portal 의 존재를 알 필요가 없다.
Portal 전용 execution API · trace API · Resolve mode · recipe 직접 실행 경로를 전제하지 않는다.

## BFF → agentic_ai (지금 mock)

`api/app/clients/agentic_ai.py`. 향후 실제 client 는 agentic_ai 의 기존 `POST /chat/stream` 을 부른다
(agentic_ai `app/api/main.py`, 2026-09-22 read-only 확인. KRRI_ASAP 도 이 창구를 부른다).

요청

```json
{"text": "<고정 질문의 display_text>", "context": {}}
```

응답: `text/event-stream`. `data: <json>` 한 줄씩, 끝은 `data: [DONE]`.

| event | 모양 |
|---|---|
| 해석 시작 | `{"type":"step_start","node":"resolve","message":"발화를 해석하고 있습니다..."}` |
| 해석 끝 | `{"type":"step_end","node":"resolve","message":"<SELECT\|CLARIFY\|NO_MATCH> <recipe_id>"}` |
| tool 단계 | `{"type":"step_start","node":<node>,"message":"<tool> 호출 중입니다..."}` / `{"type":"step_end",...,"message":"<tool> 완료\|실패"}` |
| 마지막 | `{"type":"result","answer":<문자열>,"commands":[<지도 명령>]}` |

Portal 은 display_text 를 발화로 보낼 뿐이다. recipe_id 를 지정하거나 Resolve 를 건너뛰지 않는다.
fixed question 의 `expected_recipe_id` · `expected_tools` 는 실행 명령이 아니라,
해석/실행이 예상한 기능으로 갔는지 **검증·설명**하는 metadata 다.

### BFF 가 하는 변환 (`api/app/trace.py`)

- resolve step_end message → `resolve_status`, `matches_expected_recipe` (recipe_id 원문은 안 내보냄)
- tool step_end message → `steps[].tool`, `steps[].status`
- result → `answer`, `map_command_count` (commands 본문은 안 내보냄)

### Limitation

기존 `/chat/stream` 이벤트에는 **tool 단위 Request/Response 가 없다.** 그래서 PlayMCP 스타일
Request/Response 전체는 기존 API 만으로 줄 수 없다. 실제 연결 뒤 `steps[].request/response` 는 `null` 이고
UI 는 「제공되지 않음」으로 보인다. 지금 mock 은 UI 모양을 보이려고 예시값을 채운다.
이 이유만으로 agentic_ai 를 수정하지 않는다.

또 step 이벤트는 agentic_ai 가 실행을 마친 뒤 한꺼번에 나간다 (step 시각이 실제 호출 시각이 아님).

## BFF → KRRI_ASAP Gateway (지금 mock)

`api/app/clients/gateway.py`. technical 정보(status · tools · inputSchema)의 source of truth 는
향후 Gateway / live MCP `tools/list` 다. 지금의 `MOCK_SERVERS` 는 대표 subset 이다.
등록 미리보기(`inspect`)는 향후 Gateway 의 기존 MCP server test 기능으로 교체한다.
Portal 은 사용자가 입력한 endpoint 를 직접 부르지 않는다.

## Browser → BFF

브라우저는 같은 origin 의 `/api/*` 만 부른다. 내부 URL · credential 은 BFF 환경변수에만 둔다.
