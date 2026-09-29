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

## BFF → agentic_ai (mock | live)

`api/app/clients/agentic_ai.py`. `KEM_AGENTIC_AI_MODE` 로 고른다.

- `mock` (기본): 고정 이벤트. tests · local 용.
- `live`: agentic_ai 의 기존 `POST /chat/stream` 을 부른다 (agentic_ai `app/api/main.py`, 2026-09-22 read-only 확인.
  KRRI_ASAP 도 이 창구를 부른다). `KEM_AGENTIC_AI_BASE_URL` 필수, timeout 기본 360초 (`KEM_AGENTIC_AI_TIMEOUT_SECONDS`).

브라우저는 `question_id` 만 보낸다. BFF 가 그 id 로 config 의 trusted `display_text` 를 찾아 발화로 보낸다.

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

agentic 이 더한 칸(`step_end.failed`, KRRI 가 돌았을 때의 `result.status`)과 모르는 event type 은 읽지 않고 둔다.
BFF 는 흐름을 `data: [DONE]` 까지 읽고, 다음은 모두 실패로 본다: 연결 실패 · timeout · 200 아닌 응답 ·
`text/event-stream` 아닌 응답 · JSON 이 아닌 data · [DONE] 전에 끝남 · result 이벤트 없음.
실패는 502 `{"detail": "AI 실행 서비스에 연결하지 못했습니다."}` 이고 원인 종류만 BFF 로그에 남는다 (URL · 본문 없음).

Portal 은 display_text 를 발화로 보낼 뿐이다. recipe_id 를 지정하거나 Resolve 를 건너뛰지 않는다.
fixed question 의 `expected_recipe_id` · `expected_tools` 는 실행 명령이 아니라,
해석/실행이 예상한 기능으로 갔는지 **검증·설명**하는 metadata 다.

### BFF 가 하는 변환 (`api/app/trace.py`)

- resolve step_end message → `resolve_status`, `matches_expected_recipe` (recipe_id 원문은 안 내보냄)
- tool step_end message → `steps[].tool`, `steps[].status`
- result → `answer`, `map_command_count` (commands 본문은 안 내보냄)

### Limitation

기존 `/chat/stream` 이벤트에는 **tool 단위 Request/Response 가 없다.** 그래서 PlayMCP 스타일
Request/Response 전체는 기존 API 만으로 줄 수 없다. live 에서 `steps[].request/response` 는 `null` 이고
화면은 Request/Response 를 그리지 않는다. mock 의 예시값도 화면에는 쓰지 않는다.
이 이유만으로 agentic_ai 를 수정하지 않는다.

또 step 이벤트는 agentic_ai 가 실행을 마친 뒤 한꺼번에 나간다 (step 시각이 실제 호출 시각이 아님).

## BFF → KRRI_ASAP Gateway (mock | live)

`api/app/clients/gateway.py`. `KEM_GATEWAY_MODE` 로 고른다.

- `mock` (기본): 고정 대표 subset. tests · local 용.
- `live`: 실제 Gateway 를 **GET 으로만** 읽는다. `KEM_GATEWAY_BASE_URL` 필수.
  live 가 실패하면 BFF 는 502 `{"detail": "Gateway 에서 MCP 정보를 가져오지 못했습니다."}` 를 낸다.
  **mock 으로 자동 전환하지 않는다.** 원인은 BFF 서버 로그에만 남는다.

### Portal MCP = Gateway logical MCP (market group)

사용자-facing 단위는 physical MCP server 가 아니라 **KRRI_ASAP Gateway `ASAP-Gateway/data/tool-groups.json` 의 group** 이다.
group id 가 Portal 의 `mcp_id` 이고, Catalog · 상세 URL · 도구함 · 고정 질문이 모두 이 id 로 묶인다. physical server 는 runtime
구현 세부라 브라우저 JSON 에 싣지 않는다 (BFF 안에서만 `server_ids` · `tool_refs` 를 둔다).

- 한 server 가 여러 MCP 로 나뉜다: `asap-mcp-core` (40 tool) → `krri-map-location` · `krri-railway-network` · `krri-admin-boundary` … 12개
- 여러 server 가 MCP 하나로 묶인다: `route-accessibility` → `otp-router/*` + `r5-server/*` (「R5 기반 등시선도 MCP」)
- Gateway 는 어느 group 에도 안 걸린 server 에 `id = server_id` fallback group 을 만든다. 그것도 MCP 하나로 보인다.

Portal 은 tool 이름 등을 보고 group 을 만들거나 고치지 않는다. 어느 Tool 이 어느 MCP 에 속하는지는 market item 의
`resolvedToolRefs`(Gateway 가 정의 toolRefs 를 지금 Tool 로 펼친 값)로만 판단한다. 사용자 노출 Tool 이 group 에 안 걸렸으면
Portal 에도 안 보이므로, 고칠 곳은 KRRI_ASAP `tool-groups.json` 이다.

### technical source (KRRI_ASAP/ASAP-Gateway, 2026-09-29 read-only 재확인)

| 정보 | source | 비고 |
|---|---|---|
| MCP 목록 · 이름 · 설명 · 소속 Tool | `GET /api/mcp-market` (ANYONE) | item 하나 = MCP 하나. `id` · `name` · `description` · `serverIds` · `toolRefs` · `resolvedToolRefs` · `status` · `enabled` 를 쓴다. 요청마다 guest cookie 발급 + guest selection DB SELECT. Gateway tool cache 가 비면 이 GET 도 refresh 를 일으킨다. `category`(추천/일반…)는 ASAP-web market tab 값이라 쓰지 않는다 |
| tool name · description · inputSchema | `GET /api/tools` (ANYONE) | authoritative. ASAP-orchestrator 도 쓰는 live discovery 경로. **write 는 아니지만 호출마다 `registry.refreshTools()`** — 모든 MCP 에 tools/list 를 보내고 Gateway 메모리의 tool cache · status 를 갱신한다 |

BFF 는 두 GET 의 결과를 `KEM_GATEWAY_CACHE_SECONDS`(기본 60) 동안 한 벌로 재사용한다.
그 안의 Catalog / Detail / 도구함 요청은 Gateway catalog 를 다시 부르지 않는다.

쓰지 않는 것: `/api/admin/mcp-servers[/:id]` (Keycloak ADMIN JWT 필요, 응답에 server `url` · `headers` 포함),
admin POST/PUT/DELETE, `/refresh`, `/test`. Portal BFF 에 ADMIN credential 을 두지 않는다.

### status

| 값 | 근거 |
|---|---|
| `online` | group 에 Tool 이 있고, group 의 모든 server 가 이번 `/api/tools` refresh 에 Tool 을 냈다 |
| `offline` | group 에 Tool 이 하나도 없고, Gateway 가 group status 를 `error` 또는 `disabled` 라고 명시한다 |
| `unknown` | 그 밖의 모든 경우. 일부 server 만 응답한 multi-server group, `ready` 인데 Tool 0개 등 |

### presentation join

`config/presentation.yaml` 은 `mcp_id` 로 붙는 표시 정보(display_name · summary · category · organization)와 Catalog 순서뿐이다.
display_name · summary 를 비우면 Gateway group 의 name · description 을 쓴다. entry 가 없는 group 도 숨기지 않는다:
뒤에 id 순으로 붙고 category = `기타`, organization = 빈 값. 분류는 Portal 것이다 (KRRI 계열 = `KRRI 정책현안 분석도구`,
route-accessibility = `교통 접근성 분석`).

### 개발 중 MCP (planned)

`config/planned_mcps.yaml` 은 **Gateway 에 server · group 이 아직 없는** MCP 의 Portal catalog metadata 다
(`api/app/metadata.py` `PlannedMcp`). Gateway 값처럼 꾸미지 않는다.

- 카드 · 상세는 `lifecycle: "development"`, `status: null`, `tool_count: null`, `source: "planned"`. 화면은 「개발 중」 배지만 보인다
  (「사용 불가」 · 「상태 모름」 · Tool 0개로 보이지 않는다).
- 도구함 `POST/DELETE /api/toolbox/{id}` 는 409 이고 Gateway 를 부르지 않는다. 대화 예시가 없고, 개발 중 MCP 에 질문을 붙이면 BFF 가 뜨지 않는다.
- 같은 id 의 group 이 Gateway 에 생기면 planned entry 는 무시된다(로그 경고). 공개되면 planned 에서 지우고 presentation 으로 옮긴다.

지금 entry: `gtfs-accessibility-aro` (GTFS 기반 접근성 분석 MCP · 아로), `gtfs-accessibility-university` (같은 이름 · 시립대),
`nodelink-accessibility-vwl` (노드링크 기반 접근성 분석 MCP · VWL). 분류는 셋 다 `교통 접근성 분석`.

### 고정 질문과 MCP

한 recipe 가 여러 MCP 의 Tool 을 쓸 수 있어서 (부산역 = 위치 + 행정구역, 수원역 CCTV = 위치 + CCTV) 질문은 세 값을 따로 둔다.

| 칸 | 뜻 |
|---|---|
| `mcp_id` | 이 질문을 대화 예시로 보여 줄 MCP 하나 (상세 화면) |
| `expected_mcp_ids` | 실행이 거칠 것으로 예상하는 MCP. `mcp_id` 를 포함한다 |
| `expected_tools` | 실행이 거칠 것으로 예상하는 physical Tool (`<server_id>/<tool>`, 순서대로). trace 검증용 |

실행 결과의 `steps[].mcp_name` 은 그 단계 Tool 을 가진 MCP 이름이다. 후보는 `expected_mcp_ids` 뿐이고 소속은 Gateway group Tool 로
판단한다. 하나로 정해지지 않거나 Gateway 를 못 읽으면 `null` 이고, 실행 결과 자체는 그대로 돌려준다.

## 도구함 (toolbox) — 기존 MCP 의 사용자 selection

**도구함 등록 = 이미 KRRI 에 있는 logical MCP 를 내 selection 에 넣는 것.** 신규 MCP server 를 시스템에 추가하는 것이 아니다.

`api/app/clients/selection.py` · `api/app/routes/toolbox.py`. Gateway 의 기존 selection API 만 쓴다.

| Gateway | 권한 | 내용 |
|---|---|---|
| `GET /api/me/mcp-selections` | ANYONE | `{groupIds, serverIds, toolRefs}` (정규화된 값) |
| `PUT /api/me/mcp-selections` | ANYONE | body strict `{groupIds?, toolRefs?, serverIds?}` → 정규화된 값을 저장하고 돌려줌 |

- `groupIds`: market tool-group. 저장되고, 정규화 때 그 group 의 정의 toolRefs 로 펼쳐진다. 없는 · disabled group 은 버려진다.
- `toolRefs`: 실행 권한의 실제 범위. `<serverId>/<tool>` 또는 `<serverId>/*`. Executor 는 `<serverId>/*` 를 server 전체로 본다.
- `serverIds`: toolRefs 에서 뽑은 파생 값. 입력으로는 legacy (groupIds · toolRefs 가 둘 다 비었을 때만 `<id>/*` 로 바뀜).

**Portal 의 canonical selection 은 `groupIds` 다.** ASAP-web MCP market (`ASAP-web/apps/asap/src/features/mcp/api.ts`
`updateMcpSelections`) 과 같은 표현을 쓰므로, 같은 사용자라면 두 화면이 같은 도구함을 같은 뜻으로 읽고 쓴다.

| 동작 | Gateway 에 보내는 것 |
|---|---|
| 등록 | `PUT {groupIds: 지금 등록된 MCP + 이 mcp_id}` |
| 해제 | `PUT {groupIds: 지금 등록된 MCP − 이 mcp_id}` |
| 등록됨 판정 | Gateway market `isApplied` 와 같다: `groupIds` 가 있으면 그 목록, 없으면 `toolRefs` 가 group 정의 refs 를 모두 덮는 group |

PUT 은 ASAP-web 처럼 `groupIds` 만 싣는다. 그래서 group 으로 안 펼쳐지는 explicit `toolRefs`(예: 이전 Portal 이 넣던
`<serverId>/*`)는 첫 쓰기 때 위 판정으로 groupIds 가 되고 사라진다. Gateway 가 PUT 을 반영하지 않으면(예: disabled group) 409.
개발 중 MCP 는 등록 · 해제 대상이 아니다 (409, Gateway 호출 없음).

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
(`adminBoundary.*` 는 Gateway `SYSTEM_MCP_TOOL_REFS` 기본값이라 selection 과 무관하게 proxy 실행 범위에 들어간다.)
**지금 8000 번의 agentic_ai 는 이 header 를 읽지 않는다.** agentic 은 KRRI `POST /workflow/execute` 를 부를 때
고정 `USER_CONTEXT` 로 `X-User-ID` · `X-User-MCP-Tools` 를 붙인다 (asap-mcp-core · r5-server · otp-router, web-search 없음).
그래서 도구함 selection 은 KRRI 쪽 selection 저장소와 orchestrator 계약에는 반영되지만, 현재 agentic_ai 실행 범위는 바꾸지 않는다.
또 Portal 의 guest(`kem_gateway_guest`) 와 ASAP-web 의 guest cookie 는 서로 다른 사용자다.

## Future backlog: 신규 MCP server onboarding

신규 endpoint 를 KRRI 시스템에 등록하는 것은 도구함과 다른 기능이며 지금 범위가 아니다. 후보 Gateway API 는
`POST /api/admin/mcp-servers/test` (ADMIN JWT, body `{id, type, url, name?, description?, headers?, timeoutMs?}` →
`{ok, server, toolCount, tools, error?}`) 와 `POST /api/admin/mcp-servers` 다. Portal 에 ADMIN credential 을 둘지 정한 뒤 다룬다.

## Browser → BFF

브라우저는 같은 origin 의 `/api/*` 만 부른다. 내부 URL · credential 은 BFF 환경변수에만 둔다.
