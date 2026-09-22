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

## BFF → KRRI_ASAP Gateway (mock | live)

`api/app/clients/gateway.py`. `KEM_GATEWAY_MODE` 로 고른다.

- `mock` (기본): 고정 대표 subset. tests · local 용.
- `live`: 실제 Gateway 를 **GET 으로만** 읽는다. `KEM_GATEWAY_BASE_URL` 필수.
  live 가 실패하면 BFF 는 502 `{"detail": "Gateway 에서 MCP 정보를 가져오지 못했습니다."}` 를 낸다.
  **mock 으로 자동 전환하지 않는다.** 원인은 BFF 서버 로그에만 남는다.

### technical source (KRRI_ASAP/ASAP-Gateway, 2026-09-22 read-only 확인)

| 정보 | source | 비고 |
|---|---|---|
| tool name · description · inputSchema | `GET /api/tools` (ANYONE) | authoritative. ASAP-orchestrator 도 쓰는 live discovery 경로. **write 는 아니지만 호출마다 `registry.refreshTools()`** — 모든 MCP 에 tools/list 를 보내고 Gateway 메모리의 tool cache · status 를 갱신한다 |
| server id | `/api/tools` 의 `serverId` ∪ `/api/mcp-market` 의 `serverIds` | presentation.yaml 은 server source 가 아니다 |
| status 보조 | `GET /api/mcp-market` (ANYONE) | **tool-group(market) catalog 이지 server catalog 가 아니다.** 요청마다 guest cookie 발급 + guest selection DB SELECT. Gateway tool cache 가 비면 이 GET 도 refresh 를 일으킨다 |

BFF 는 두 GET 의 결과를 `KEM_GATEWAY_CACHE_SECONDS`(기본 60) 동안 한 벌로 재사용한다.
그 안의 Catalog / Detail 요청은 Gateway 를 다시 부르지 않는다.

쓰지 않는 것: `/api/admin/mcp-servers[/:id]` (Keycloak ADMIN JWT 필요, 응답에 server `url` · `headers` 포함),
admin POST/PUT/DELETE, `/refresh`, `/test`. Portal BFF 에 ADMIN credential 을 두지 않는다.
Gateway 에 safe read-only server catalog 가 생기면 `gateway.py` 안에서만 source 를 바꾼다.

### status

| 값 | 근거 |
|---|---|
| `online` | 이번 `/api/tools` refresh 결과에 그 server 의 tool 이 실제로 있다 (tools/list 가 방금 성공) |
| `offline` | 그 server **하나만** 담은 mcp-market group 이 `error` 또는 `disabled` 라고 명시한다 |
| `unknown` | 그 밖의 모든 경우. registry 에 있다는 것 ≠ online. multi-server group (예: `route-accessibility → [otp-router, r5-server]`) 의 status 는 개별 server 로 옮기지 않는다 |

### presentation join

`config/presentation.yaml` 은 server_id 로 붙는 표시 정보(display_name · summary · category · organization)뿐이다.
entry 가 없는 server 도 숨기지 않는다: display_name = technical name(없으면 server_id), summary = technical
description(없으면 빈 값), category = `기타`, organization = 빈 값.
technical name 은 Gateway 가 group 정의에 안 걸린 server 에 만드는 fallback group(id = server_id)의 name 만 쓴다.

## 도구함 (toolbox) — 기존 MCP 의 사용자 selection

**도구함 등록 = 이미 KRRI 에 있는 MCP 를 내 selection 에 넣는 것.** 신규 MCP server 를 시스템에 추가하는 것이 아니다.

`api/app/clients/selection.py` · `api/app/routes/toolbox.py`. Gateway 의 기존 selection API 만 쓴다.

| Gateway | 권한 | 내용 |
|---|---|---|
| `GET /api/me/mcp-selections` | ANYONE | `{groupIds, serverIds, toolRefs}` (정규화된 값) |
| `PUT /api/me/mcp-selections` | ANYONE | body strict `{groupIds?, toolRefs?, serverIds?}` → 정규화된 값을 저장하고 돌려줌 |

- `groupIds`: market tool-group. 저장되고, 정규화 때 그 group 의 toolRefs 로 펼쳐진다.
- `toolRefs`: 실행 권한의 실제 범위. `<serverId>/<tool>` 또는 `<serverId>/*`. Executor 는 `<serverId>/*` 를 server 전체로 본다.
- `serverIds`: toolRefs 에서 뽑은 파생 값. 입력으로는 legacy (groupIds · toolRefs 가 둘 다 비었을 때만 `<id>/*` 로 바뀜).

Portal 의 규칙:

| 동작 | Gateway 에 보내는 것 |
|---|---|
| 등록 | 지금 selection 그대로 + `toolRefs` 에 `<serverId>/*` 하나 |
| 해제 | 그 server 의 ref 전부 제거 + 그 server 를 담은 group id 만 제거. 다른 group · ref 는 그대로 |
| 등록됨 판정 | 정규화된 `toolRefs` 에 `<serverId>/*` 가 있다 |

multi-server group (`route-accessibility → otp-router, r5-server`): 등록은 group 을 건드리지 않으므로 다른 server 를 끌어오지 않는다.
해제 때 그 group 을 남기면 Gateway 가 빠진 server 를 다시 펼치므로 group id 는 빼지만, 이미 펼쳐져 저장된 다른 server 의
ref (`r5-server/*`) 는 남아 범위가 유지된다. 한 server 의 일부 tool 만 고른 상태는 「등록됨」이 아니며, 해제하면 그 일부도 빠진다.

주의: ASAP-web 의 MCP market 화면은 `{groupIds}` 만 PUT 한다. 같은 사용자가 거기서 저장하면 Portal 이 넣은 `<serverId>/*` 는 사라진다.

### 사용자 식별

로그인 사용자는 Gateway 가 JWT `sub` 로, 그 밖은 guest cookie `asap_mcp_guest` (UUID v4, HttpOnly, SameSite=Lax, Path=/, 1년) 로 찾는다.
Portal BFF 는 Gateway guest id 를 자기 cookie `kem_gateway_guest` (HttpOnly, SameSite=Lax, Path=/api, 1년) 에 담고,
Gateway 를 부를 때만 `Cookie: asap_mcp_guest=<id>` 로 보낸다. 처음 온 브라우저는 Gateway 가 발급한 Set-Cookie 에서 id 를 읽어 담는다.
id 값은 JSON · 로그에 싣지 않는다. Authorization 은 보내지 않는다 (로그인 연동은 아직 없음).

### 실패

Gateway 실패는 502 `{"detail": "Gateway 에서 MCP 정보를 가져오지 못했습니다."}`, Gateway 가 PUT 을 반영하지 않으면 409.
mock 으로 넘어가지 않고, 성공으로 가정하지 않는다. mock mode 는 process-local selection 이다.

### 채팅에 적용되는 경로 (read-only 확인)

Gateway proxy (`/api/orchestrator/*`, `/api/mcp/*`) 는 요청자의 selection 을 `X-User-MCP-Servers` · `X-User-MCP-Tools` ·
`X-User-MCP-Groups` header 로 붙여 downstream 에 넘긴다. ASAP-orchestrator 는 이 header 로 실행 범위를 정하고,
Gateway `POST /api/tools/execute` 는 명시 `user_context` 가 없으면 요청자의 selection 으로 `selected_mcp_tool_refs` 를 검사한다.
**지금 8000 번의 agentic_ai 는 이 header 를 읽지 않고 고정 `USER_CONTEXT` 를 `user_context` 로 보낸다.** 그래서 도구함 selection 은
KRRI 쪽 selection 저장소와 orchestrator 계약에는 반영되지만, 현재 agentic_ai 채팅의 tool 범위는 바꾸지 않는다.
또 Portal 의 guest(`kem_gateway_guest`) 와 ASAP-web 의 guest cookie 는 서로 다른 사용자다.

## Future backlog: 신규 MCP server onboarding

신규 endpoint 를 KRRI 시스템에 등록하는 것은 도구함과 다른 기능이며 지금 범위가 아니다. 후보 Gateway API 는
`POST /api/admin/mcp-servers/test` (ADMIN JWT, body `{id, type, url, name?, description?, headers?, timeoutMs?}` →
`{ok, server, toolCount, tools, error?}`) 와 `POST /api/admin/mcp-servers` 다. Portal 에 ADMIN credential 을 둘지 정한 뒤 다룬다.

## Browser → BFF

브라우저는 같은 origin 의 `/api/*` 만 부른다. 내부 URL · credential 은 BFF 환경변수에만 둔다.
