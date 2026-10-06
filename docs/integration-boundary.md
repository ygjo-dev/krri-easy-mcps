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

### MCP 상세 metadata 의 source

MCP 자체 정보는 Gateway group(`/api/mcp-market`), Tool 정보는 `/api/tools` 다. EASY config 에는 표시 override 만 둔다.
KRRI_ASAP 「KRRI MCPs」 상세(`ASAP-web .../features/mcp/components/McpDetail.tsx`)와 같은 market item 을 읽는다.

| 칸 | source | Portal 상세 |
|---|---|---|
| display_name · summary | presentation.yaml override → 없으면 Gateway `name` · `description` | 머리 |
| organization | presentation.yaml → 없으면 Gateway `author` | 머리 · MCP 정보 |
| `long_description` | Gateway `longDescription` 만 | 「개요」. 요약과 같거나 없으면 숨김 |
| `tags` | Gateway `tags` 만. Gateway 가 붙이는 status 값(ready · error …)은 뺀다 | 요약 아래 chip |
| `connected_datasets` | Gateway `layerDatasets` 의 `name` · `description` · `geometryKind` 만 | 「연결 데이터」 (있을 때만). 지도 적용 · Data Library 동작은 없다 |
| `updated_at` | Gateway `updatedAt` = group server 의 마지막 상태 확인 시각 | MCP 정보 「상태 확인」 |
| Tool name · description · parameter | `/api/tools` | Tool 목록 |

쓰지 않는 것:
- `features`: 지금 모든 항목이 `"<tool>: 설명"` 이라 Tool 목록과 겹친다. MCP 수준 기능 설명이 생기면 다시 본다.
- `version`: 늘 `"group"`. `rating` · `downloads`: 고정값. `category`: ASAP-web market tab.
- `lastError`: 내부 주소가 들어 있다. layerDatasets 의 `toolRef` · `input` · `defaultStyle` 등: Data Library 실행 설정.
- `contact`: Gateway 는 group `contact` 칸을 지원하지만 지금 어느 group 에도 없다. KRRI MCPs 에 보이는 담당자는
  ASAP-web `fetchMcpMarket()` 이 asap-mcp-core group 에 붙이는 frontend 하드코딩이다. Portal 에 복사하지 않는다.
  두 화면에 같이 보이려면 `tool-groups.json` group `contact` 로 옮겨야 한다 (KRRI_ASAP 결정 필요).

개발 중 MCP 상세는 이 칸들이 비어 있다 (`""` · `[]` · `null`). 가짜 값을 채우지 않는다.

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
Portal BFF 도 같은 cookie `asap_mcp_guest` (HttpOnly, SameSite=Lax, Path=/, 1년, https 면 Secure) 를 쓰고,
Gateway 를 부를 때 `Cookie: asap_mcp_guest=<id>` 로 옮겨 싣는다. 처음 온 브라우저는 Gateway 가 발급한 Set-Cookie 에서 id 를 읽어
같은 이름으로 담는다. cookie 는 port 를 가리지 않으므로 **같은 hostname** 의 ASAP-web 과 Portal 은 같은 guest · 같은 selection 이다
(localhost · 127.0.0.1 · LAN IP 는 서로 다른 host 다). 다른 subdomain · domain 배치에서는 공유되지 않는다.

예전 Portal cookie `kem_gateway_guest` (Path=/api) 는 이행용으로만 읽는다. 유효한 `asap_mcp_guest` 가 없을 때만 그 UUID 를 그대로
`asap_mcp_guest` 로 올리고(같은 Gateway 행), 응답에서 legacy cookie 를 지운다. 둘 다 있으면 `asap_mcp_guest` 가 이긴다.
형식(UUID v4)이 틀린 값은 어느 쪽이든 믿지 않는다.
id 값은 JSON · 로그에 싣지 않는다. Authorization 은 보내지 않는다. EASY 자체 로그인(아래)이 있어도 Gateway 에는
계속 guest cookie 만 간다 — EASY 계정 · 세션 token 을 Gateway 에 싣지 않는다.

### 다른 화면의 변경 신호

Gateway 는 같은 주인(guest cookie 또는 JWT sub)의 selection 이 PUT 으로 저장될 때마다
`GET /api/me/mcp-selections/events` (text/event-stream) 로 `event: selection_changed` 를 보낸다 (25초마다 `: ping`).
신호에는 selection 이 없다. Portal BFF 는 `GET /api/toolbox/events` 에서 이 흐름을 guest cookie 로 열어 바이트 그대로
브라우저로 넘기고, 브라우저는 신호를 받으면 `GET /api/toolbox` 로 다시 읽는다. 브라우저가 Gateway 를 직접 부르지 않는다.
끊기면 브라우저가 1s → 2s → 5s(상한)로 다시 잇고, 다시 이어지면 한 번 다시 읽는다. 반복 조회(polling)는 없다.
Gateway 한 process 안의 메모리 구독이라 Gateway 를 여러 개 띄우면 공유 broker 가 필요하다.

### EASY 계정과 계정 도구함

**EASY 로그인은 KRRI_ASAP 로그인(Keycloak/JWT)과 별개다.** EASY BFF 가 자기 사용자 · 세션을 가진다
(`api/app/accounts.py`, `api/app/routes/auth.py`). KRRI_ASAP 계정 · token 을 쓰지 않고, KRRI_ASAP 에 EASY 계정을 알리지 않는다.
계정 도구함은 위 guest selection 을 **대체하지 않고 그 위에 얹는 영구 저장**이다. 그래서 로그인해도 KRRI ASAP 와의 연동
(같은 hostname 의 같은 `asap_mcp_guest` → 같은 Gateway selection, 아래 변경 신호)은 그대로다. 별도 「KRRI 연결」 절차는 없다.

저장소: SQLite (`KEM_DB_PATH`, 기본 `data/easy.db`, gitignore). Python stdlib `sqlite3` 와 parameter binding 만 쓴다.

| 표 | 내용 |
|---|---|
| `users` | `username` · `password_hash` (`hashlib.scrypt`, 계정마다 salt) · `role` (`USER` \| `ADMIN`) |
| `account_toolboxes` | 계정 도구함 `mcp_ids` (JSON). **행이 없으면 아직 초기화 안 됨**, `[]` 이면 일부러 비운 도구함 |
| `sessions` | `token_hash` (SHA-256) · user · 만료 시각 · 이 세션이 마지막으로 맞춘 guest(SHA-256)와 도구함 |

- 초기 계정 `admin` / `admin` (ADMIN) 은 **개발 · 검증용**이다. 그 이름이 DB 에 없을 때만 만든다 (`KEM_ADMIN_*`).
- 세션 cookie `kem_session`: opaque random token(`secrets.token_urlsafe(32)`), HttpOnly · SameSite=Lax · Path=/ · https 면 Secure ·
  Max-Age = `KEM_SESSION_HOURS`. DB 에는 token 원문 대신 hash 만 둔다. 만료 세션은 읽을 때 · 로그인할 때 지운다.
  `asap_mcp_guest` 와 다른 cookie 이고, 로그인 · 로그아웃이 guest cookie 를 바꾸거나 지우지 않는다.
- 로그인 실패는 없는 아이디 · 틀린 비밀번호 모두 같은 401 문구이고, 없는 아이디도 같은 hash 비용을 쓴다.
  로그인 body 는 JSON 만 받고(다른 사이트 form POST 로 로그인시키기 방지), 형식 오류도 입력값을 되돌려 보내지 않는다.
- 응답에는 `{user: {username, role}}` 만 싣는다. password · hash · token · guest id 는 JSON · 로그에 없다.

**동기화 규칙** (`api/app/routes/toolbox.py` `_current`). 로그인 중이면 도구함을 읽거나 바꾸기 전에 계정과 맞춘다.
Gateway 가 실제로 반영한 값(PUT 응답 · GET 결과)만 계정에 저장한다.

| 상황 | 동작 |
|---|---|
| 비로그인 | 이전과 같다. 계정 DB 를 읽거나 쓰지 않는다 |
| 계정 도구함이 아직 없음 (첫 로그인) | 지금 guest selection 을 그대로 계정에 저장 (빈 selection 도 「초기화된 빈 도구함」) |
| 이 세션이 이 guest 와 처음 맞춤 (저장된 계정으로 로그인 · 다른 PC/브라우저 · 로그인 중 guest cookie 가 바뀜) | 계정 도구함을 `PUT {groupIds}` 로 guest selection 에 적용 (복원) |
| 이미 맞춘 guest | 마지막으로 맞춘 값을 기준으로 3-way merge. 계정이 그대로면 Gateway 값(KRRI ASAP 쪽 변경 포함)을 계정에 저장하고, 다른 기기가 계정을 바꿨으면 그 변경을 이 guest 에 PUT 한다 |
| 로그인 중 EASY 등록 · 해제 | 위로 맞춘 뒤 Gateway PUT. 성공한 실제 결과만 계정에 저장. Gateway 오류(502)면 계정은 그대로, Gateway 가 반영 안 함(409)이면 반영된 실제 값만 저장 |
| 로그아웃 | EASY 세션만 지운다. guest cookie · Gateway selection 은 그대로 (이 브라우저는 마지막 도구함을 guest 로 계속 쓴다) |

로그인 API 는 응답 전에 한 번 맞춘다. 그때 Gateway 가 실패해도 로그인은 성공하고, 세션이 「아직 안 맞춤」으로 남아
다음 도구함 요청에서 다시 맞춘다 (새 guest 의 값으로 저장된 계정을 덮지 않는다).
KRRI ASAP 쪽 변경은 EASY 가 다시 읽을 때(신호 · focus) 계정에 들어간다. EASY 를 열지 않은 동안의 KRRI 쪽 변경은
다음에 EASY 가 읽을 때 저장된다. 「관리자」(ADMIN) 역할은 UI 에 보이기만 하고 지금 권한 차이는 없다.

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
guest cookie 는 ASAP-web 과 같다 (위 「사용자 식별」).

## KRRI AI Skills (EASY 소유, ADMIN 전용)

AI Skills 는 MCP · Gateway · agentic_ai 와 연결되지 않는 EASY 자체 기능이다 (`api/app/skills.py`, `api/app/routes/skills.py`).
KRRI_ASAP orchestrator 의 내부 skill 을 읽거나 노출하지 않는다. 의존 방향 그림에도 들어가지 않는다.

- 권한: router 전체에 `require_admin` (EASY 세션의 role). 비로그인 401 · ADMIN 아님 403. KRRI_ASAP Keycloak role 은 보지 않는다.
- 외부 서비스: ChatGPT · Claude 를 부르지 않는다. 공식 설치 API 를 흉내 내지 않고 업로드할 ZIP 만 만든다.
  package 형식 근거 (2026-10 확인): Claude 「Create custom skills」 — ZIP 은 `<skill-name>/SKILL.md` 를 top level 로, name 은 소문자 · 숫자 · 하이픈
  64자, folder 이름 = name, description 1024자. OpenAI skills — 단일 top-level folder, SKILL.md 이름 매칭은 대소문자 무시, zip 50MB · 500 파일.
  두 서비스 모두 [Agent Skills 규격](https://agentskills.io/specification)을 따른다. export 결과는 공식 `skills-ref validate` 를 통과한다 (live smoke).
- 올린 package 는 실행하지 않는다 (README 「AI Skills」의 ZIP 검증 규칙).

## Future backlog: 신규 MCP server onboarding

신규 endpoint 를 KRRI 시스템에 등록하는 것은 도구함과 다른 기능이며 지금 범위가 아니다. 후보 Gateway API 는
`POST /api/admin/mcp-servers/test` (ADMIN JWT, body `{id, type, url, name?, description?, headers?, timeoutMs?}` →
`{ok, server, toolCount, tools, error?}`) 와 `POST /api/admin/mcp-servers` 다. Portal 에 ADMIN credential 을 둘지 정한 뒤 다룬다.

## Browser → BFF

브라우저는 같은 origin 의 `/api/*` 만 부른다. 내부 URL · credential 은 BFF 환경변수에만 둔다.
Skill ZIP 은 multipart 가 아니라 요청 body 그대로 보낸다 (`Content-Type: application/zip`, 새 dependency 없음).
