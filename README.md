# KRRI EASY MCPs

KRRI 가 제공하는 MCP 서버를 찾아보고, 상세 정보와 Tool 을 확인하고,
미리 준비된 질문으로 「AI로 사용해보기」를 해 보는 Portal 이다. UI + thin BFF 로만 이루어진다.

> **현재 상태.** MCP 목록 · Tool · 상태와 도구함(사용자별 MCP selection)은 `KEM_GATEWAY_MODE=live` 에서
> 실제 KRRI_ASAP Gateway 를 쓴다 (기본은 mock). AI로 사용해보기는 `KEM_AGENTIC_AI_MODE=live` 에서 agentic_ai 의
> 기존 `POST /chat/stream` 을 부른다 (기본은 mock).
> EASY 자체 로그인(KRRI_ASAP 로그인과 별개)이 있고, 로그인하면 도구함이 계정에 저장된다. 비로그인 guest 도 그대로 쓸 수 있다.
> EASY ADMIN 은 「AI Skills」(사용자용 Skill library: 등록 · 탐색 · ChatGPT/Claude 용 ZIP 내려받기)를 쓸 수 있다.

## 구조

```text
krri-easy-mcps/
├── web/        React + TypeScript + Vite. 브라우저 UI
├── api/        FastAPI thin BFF
│   ├── app/
│   │   ├── main.py          앱 조립, /api/health
│   │   ├── settings.py      KEM_* 환경변수 (내부 주소는 여기만)
│   │   ├── accounts.py      EASY 자체 계정 · 세션 · 계정 도구함 (SQLite), require_admin
│   │   ├── skills.py        AI Skills package 검증 · 저장 · export
│   │   ├── metadata.py      config/*.yaml 읽기
│   │   ├── trace.py         agentic_ai 이벤트 → Portal 실행 결과
│   │   ├── routes/          auth · catalog · demo · toolbox · skills
│   │   └── clients/         gateway.py · selection.py · agentic_ai.py (각각 mock | live)
│   └── tests/
├── data/                    easy.db (EASY 계정 · Skill metadata DB) · skills/ (Skill package 파일). 실행 때 생김, gitignore
├── config/
│   ├── presentation.yaml    Portal 전용 표시 정보 (mcp_id = Gateway group id 기준)
│   ├── planned_mcps.yaml    개발 중 MCP (Gateway 에 아직 없음. 「개발 중」 카드만)
│   └── demo_questions.yaml  MCP 상세 「AI에게 이렇게 물어보세요」 질문 (실행 질문 · 예시, 출처 주석)
└── docs/
    └── integration-boundary.md
```

## 실행

요구: Python 3.12, Node 22.

Backend (BFF, 포트 8610)

```bash
cd api
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8610
.venv/bin/python -m pytest -q        # test
```

Frontend (Vite dev, 포트 5610. `/api` 는 BFF 로 proxy)

```bash
cd web
npm install
npm run dev          # http://127.0.0.1:5610
npm run build        # tsc + vite build
npm run lint         # oxlint
```

설정은 `.env.example` 참고. BFF 는 환경변수를 읽는다. 실제 Gateway 로 띄우려면:

```bash
KEM_GATEWAY_MODE=live KEM_GATEWAY_BASE_URL=http://127.0.0.1:3000 \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8610
```

live Gateway 가 실패하면 `/api/mcps*` 는 502 를 낸다. mock 으로 자동 전환하지 않는다.
Gateway `GET /api/tools` 는 호출마다 MCP tools/list refresh 를 일으키므로 BFF 가 60초(`KEM_GATEWAY_CACHE_SECONDS`) 재사용한다.

### EASY 로그인 (개발용 초기 계정 admin / admin)

BFF 가 처음 뜰 때 `data/easy.db` (SQLite, `KEM_DB_PATH`) 를 만들고 **개발 · 검증용 초기 관리자 계정
`admin` / `admin` (role ADMIN)** 을 넣는다. 설정 없이 바로 로그인된다. 운영에 쓸 비밀번호가 아니다.
`KEM_ADMIN_USERNAME` · `KEM_ADMIN_PASSWORD` 는 그 이름의 계정이 DB 에 없을 때 한 번만 쓰인다 (있으면 비밀번호를 바꾸지 않는다).
비밀번호는 scrypt + salt hash 로만 저장한다. 세션 수명은 `KEM_SESSION_HOURS` (기본 168시간).
DB 를 지우면 계정 · 세션 · 계정 도구함이 모두 초기화된다 (Gateway selection 은 그대로).

AI로 사용해보기를 실제 agentic_ai 로 실행하려면 `KEM_AGENTIC_AI_MODE=live` 와 `KEM_AGENTIC_AI_BASE_URL` 을 더한다
(예: 개발 장비 `http://127.0.0.1:8000`). 한 요청은 LLM 해석과 KRRI 실행을 포함하므로 기본 360초
(`KEM_AGENTIC_AI_TIMEOUT_SECONDS`) 를 기다린다. agentic_ai 를 못 부르거나 흐름이 깨지면
`/api/demo/questions/*/execute` 는 502 를 내고, mock 으로 자동 전환하지 않는다.

## 화면

| route | 내용 |
|---|---|
| `/` | MCP 탐색. 카드(이름 · 제공 · 요약 · Tool 수 · 상태 · 분류 · 도구함 등록), 검색, 분류 필터. 개발 중 MCP 는 「개발 중」 배지만 (Tool 수 · 등록 버튼 없음) |
| `/mcps/:mcpId` | MCP 상세. 왼쪽: 정보 · 도구함 등록/해제 · 상태/제공/Tools/분류 · 「Tool 목록」(접히는 행) / 「MCP 정보」 탭. 오른쪽: AI로 사용해보기 panel (좁은 화면에서는 아래로) |
| `/toolbox` | 도구함. 내가 등록한 기존 MCP 카드와 해제. 비었으면 MCP 탐색으로 안내 |
| `/skills` | AI Skills (EASY ADMIN 만, 메뉴도 ADMIN 에게만 보임). 설명 · 사용 순서 3단계 · 검색 · 태그 필터 · Skill 카드 · 새 Skill 등록(간단히 만들기 / ZIP 업로드) |
| `/skills/:skillId` | Skill 상세. 버전 · 작성자 · 태그 · 업데이트 · SKILL.md 미리보기/원문 · 포함 파일 · 사용 예시 · 「ChatGPT용 ZIP 다운로드」/「Claude용 ZIP 다운로드」(ZIP 내려받기 + 추가 안내) · 원본 패키지 · 새 버전 · 삭제 |

헤더 오른쪽은 EASY 계정이다. 비로그인이면 「로그인」(누르면 작은 로그인 창), 로그인하면 이름 · 「관리자」(ADMIN 일 때) · 「로그아웃」.
로그인 · 로그아웃은 페이지를 새로 읽지 않고 도구함만 다시 읽는다.

화면 구성은 Kakao PlayMCP 의 정보 구조(카드 · 상세 · 도구함 · AI 채팅 panel)를 따른다. Kakao 로고 · 이미지는 쓰지 않고,
MCP 아이콘은 모노그램이다. 모든 logical MCP 상세에 「AI에게 이렇게 물어보세요」 질문이 있다. AI로 사용해보기는 그중 실행 질문만 실행하고
(자유 입력 없음), agentic_ai 에 기능이 아직 없는 MCP 의 질문은 「예시」로만 보인다. live 에서는 tool 단위
Request/Response 를 보여 주지 않는다 (기존 `/chat/stream` 이벤트에 없다).

**MCP 하나 = logical MCP.** 화면의 단위는 physical MCP server 가 아니라 KRRI_ASAP Gateway `tool-groups.json` 의
market group 이고, group id 가 `mcp_id` 다. 한 server(ASAP Core)가 여러 MCP 로 나뉘고, 여러 server(OTP + R5)가
MCP 하나로 묶인다. 개발 중 MCP(`config/planned_mcps.yaml`)는 Gateway 에 없고 「개발 중」으로만 보인다
(도구함 등록 · AI 실행 불가, 사용 불가 · Tool 0개로 표시하지 않음).

Catalog 카드에도 「도구함에 등록」/「등록됨」이 있다. **도구함 등록은 이미 KRRI 에 있는 MCP 를 내 selection 에 넣는 것**이고,
신규 MCP server 를 시스템에 추가하는 기능(onboarding)은 future backlog 다.

자유 질문 입력과 Tool 직접 테스트 화면은 없다.

## Browser ↔ BFF API

| method | path | 설명 |
|---|---|---|
| GET | `/api/health` | 상태와 client mode |
| GET | `/api/auth/me` | EASY 로그인 상태 `{user: null}` 또는 `{user: {username, role}}` (role `USER` \| `ADMIN`) |
| POST | `/api/auth/login` | body `{username, password}` (JSON) → `{user}` + 세션 cookie. 틀리면 401 (없는 아이디와 같은 문구) |
| POST | `/api/auth/logout` | EASY 세션만 끝냄 → `{user: null}` |
| GET | `/api/skills` | Skill 카드 `{id, title, description, version, author, tags, compat{chatgpt, claude}, file_count, created_at, updated_at}` |
| GET | `/api/skills/{id}` | 상세: 카드 + `main_file` · `skill_md` · `files[{path, size}]` · `examples[{path, content}]` · `warnings` · `created_by` |
| POST | `/api/skills` | 간단히 만들기 (JSON `{id, title, description, version, author, tags, instructions, example}`) → 201. 같은 id 는 409 |
| POST | `/api/skills/upload` | ZIP 등록 (body = ZIP, `Content-Type: application/zip`, query `title · version · author · tags` 선택) → 201 |
| PUT | `/api/skills/{id}/package` | 같은 Skill 의 새 버전 ZIP (frontmatter name = id). 비운 표시 정보는 이전 값 |
| DELETE | `/api/skills/{id}` | 삭제 → 204 |
| GET | `/api/skills/{id}/download?target=chatgpt\|claude\|source` | ZIP 내려받기 |
| GET | `/api/mcps` | catalog 카드 `{mcp_id, display_name, summary, category, organization, lifecycle, status, tool_count, source}`. 개발 중은 `lifecycle: "development"`, `status` · `tool_count` 가 null |
| GET | `/api/mcps/{mcp_id}` | 상세: 카드 + Gateway group 의 `long_description` · `tags` · `connected_datasets[{name, description, geometry_kind}]` · `updated_at`(상태 확인 시각) + Tool/parameter. 개발 중은 빈 값 |
| GET | `/api/mcps/{mcp_id}/demo-questions` | 질문 `{question_id, display_text, runnable}` 만 |
| POST | `/api/demo/questions/{question_id}/execute` | 실행 질문 실행 → trace(단계마다 `mcp_name`) + 최종 답변. 예시 질문은 409 |
| GET | `/api/toolbox` | 내 도구함 `{mcp_ids, mcps: [catalog 카드]}` |
| POST | `/api/toolbox/{mcp_id}` | 도구함에 등록 (이미 있으면 그대로) → 도구함. 개발 중은 409 |
| DELETE | `/api/toolbox/{mcp_id}` | 도구함에서 해제 (없으면 그대로) → 도구함. 개발 중은 409 |
| GET | `/api/toolbox/events` | 도구함이 다른 화면(KRRI-ASAP 등)에서 바뀌면 오는 신호 (text/event-stream, `selection_changed`). 받으면 `GET /api/toolbox` 로 다시 읽는다 |

도구함은 Gateway `GET/PUT /api/me/mcp-selections` 를 쓴다. ASAP-web MCP market 과 같게 `{groupIds}` 만 PUT 하므로
Gateway selection 에는 등록한 `mcp_id` 가 groupId 로 들어간다. 사용자는 Gateway 의 guest cookie `asap_mcp_guest` (HttpOnly, Path=/) 로 구분한다. ASAP-web 과 같은 cookie 라 같은 hostname 이면 두 화면이 같은 selection 을 쓴다.

**EASY 계정 도구함.** EASY 로그인은 KRRI_ASAP 로그인(Keycloak/JWT)과 별개다. 로그인해도 Gateway 쪽은 그대로 이 브라우저의
guest selection 이라 KRRI ASAP 와의 자동 연동(같은 selection · SSE 신호)은 바뀌지 않는다. 계정은 그 selection 을 저장 · 복원한다.

| 상황 | 동작 |
|---|---|
| 비로그인 | 이전과 같다 (계정 DB 를 안 씀) |
| 처음 로그인하는 계정 | 지금 guest selection 을 계정 도구함으로 저장 (빈 것도 「초기화된 빈 도구함」) |
| 저장된 계정으로 로그인 (다른 PC · 브라우저 포함) | 계정 도구함을 이 브라우저의 guest selection 에 PUT → KRRI ASAP 도 같은 selection |
| 로그인 중 EASY 에서 등록 · 해제 | Gateway PUT 이 성공한 실제 결과만 계정에 저장. 실패하면 계정은 그대로 |
| 로그인 중 KRRI ASAP 에서 변경 | SSE 신호로 EASY 가 `GET /api/toolbox` 할 때 그 실제 selection 을 계정에 저장 |
| 로그아웃 | EASY 세션만 끝냄. `asap_mcp_guest` 와 Gateway selection 은 그대로, 다시 guest 동작 |

자세한 규칙은 [docs/integration-boundary.md](docs/integration-boundary.md) 「EASY 계정과 계정 도구함」.

`/api/skills*` 는 모두 서버에서 EASY ADMIN 인지 검사한다 (비로그인 401 · ADMIN 아님 403). 화면 메뉴 숨김은 안내일 뿐이다.

## AI Skills

실 내부에서 반복하는 AI 업무 방식을 **Skill package** 로 등록 · 탐색 · 내려받는 EASY 소유 library 다 (ADMIN 전용).
KRRI_ASAP orchestrator 의 내부 skill 과 무관하고 그것을 가져오지 않는다. MCP 기능과도 섞지 않는다.

- **형식**: [Agent Skills 규격](https://agentskills.io/specification). `<name>/SKILL.md` (YAML frontmatter `name` · `description` + Markdown 지시)
  와 references/ · assets/ · scripts/ 등. `name` 은 영문 소문자 · 숫자 · 하이픈 64자 이하이고 Skill id 이자 ZIP 폴더 이름이다.
  화면 이름(한글 가능) · 버전 · 작성자 · 태그는 EASY metadata 라 package 안에 넣지 않는다.
- **canonical 한 벌**: 올린 파일을 그대로 보관하고, ChatGPT · Claude 용 ZIP 은 export 때 packaging 만 맞춘다 (단일 top-level `<id>/` 폴더,
  main 파일 이름 `SKILL.md`). 두 서비스용 내용을 따로 고치지 않는다. 「원본 패키지」는 올린 main 파일 이름(SKILL.md / skill.md) 그대로다.
- **설치는 사용자가 한다**: 「ChatGPT용 ZIP 다운로드」/「Claude용 ZIP 다운로드」는 ZIP 을 내려받고 짧은 안내를 보여 줄 뿐이다. EASY 는 두 서비스 계정에
  설치하지 않고 설치됐다고 표시하지 않는다. 계정 · 요금제 · 워크스페이스에 따라 Skills 기능이 없을 수 있다.
- **보안**: 올린 package 는 보관 · 미리보기 · export 만 한다. 서버는 script 를 실행 · import 하지 않고 파일은 실행 권한 없이(0644) 저장한다.
  ZIP 은 `..` · 절대 경로 · 역슬래시 · symlink · 특수 파일 · 암호화 entry · 대소문자만 다른 중복 · SKILL.md 0개/2개 이상 ·
  두 개 이상의 top-level 폴더를 거부하고, 크기 상한(ZIP 20MB · 파일 200개 · 파일 10MB · 전체 50MB)을 실제로 읽은 바이트로 센다.
- **호환 표시**: 규격 검증을 통과하면 ChatGPT · Claude 둘 다 ✓. Claude 전용 제약(name 에 anthropic/claude, description 의 `< >`)에 걸리면
  Claude 는 「확인 필요」와 이유를 보인다.
- 저장: metadata 는 `data/easy.db` 의 `skills` 표, 파일은 `data/skills/<id>/source/` (`KEM_SKILLS_DIR`). repo 에 Skill 을 commit 하지 않는다.
  예시 Skill 은 repo 에 넣지 않았다. 화면의 「간단히 만들기」로 바로 하나를 만들 수 있다.

## 책임 경계

| | 맡는 것 |
|---|---|
| **KRRI EASY MCPs** | catalog · 검색 · 상세 · 표시 정보 · 도구함 UI · AI로 사용해보기 UI. BFF 는 내부 client 호출과 응답 변환만 |
| **agentic_ai** | Resolve · Ontology · Recipe 선택 · workflow materialization · 실행 orchestration (source of truth) |
| **KRRI_ASAP** | Gateway · MCP registry · MCP 실행 |

- 의존 방향은 `KRRI EASY MCPs → existing agentic_ai API → agentic_ai pipeline → KRRI_ASAP` 하나다.
  **KRRI EASY MCPs 를 위해 agentic_ai 를 수정하지 않는다.** agentic_ai 코드를 import · 복사 · symlink 하지 않는다.
- 고정 질문을 눌러도 Resolve 를 우회하지 않는다. BFF 는 display_text 를 agentic_ai 기존
  `POST /chat/stream` 에 발화로 보낸다 (향후). `expected_recipe_id` · `expected_mcp_ids` · `expected_tools` 는 검증·설명용이다.
- 브라우저는 BFF(`/api`)만 부른다. Gateway · MCP endpoint · agentic_ai · credential 은 브라우저에 노출하지 않는다.
- MCP 단위 · 소속 Tool 의 source of truth 는 **Gateway** 다 (`GET /api/mcp-market` 의 group + `GET /api/tools`).
  Portal 은 tool 이름으로 group 을 만들지 않는다. status 는 `online`(group 의 모든 server 가 이번 refresh 에 tool 을 냄) ·
  `offline`(tool 없음 + Gateway 가 error/disabled 명시) · `unknown`(그 밖) 셋뿐이다. mock 데이터는 UI 검증용 대표 subset 이다.
  `config/presentation.yaml` 에는 사용자-facing 정보(이름 · 요약 · 분류 · 제공)만 두고 endpoint · credential · schema · server id 를 두지 않는다.

자세한 boundary 와 기존 `/chat/stream` 의 이벤트 모양, limitation 은
[docs/integration-boundary.md](docs/integration-boundary.md) 에 있다.

## 아직 안 된 것

- 도구함 selection 을 agentic_ai 실행 범위에 반영 (지금 agentic_ai 는 고정 실행 범위를 쓴다)
- EASY 회원가입 · 사용자 관리 · 비밀번호 변경 화면 (지금은 DB 의 계정만. 구조는 USER/ADMIN 여러 계정을 지원)
- AI Skills: 승인 · 게시 workflow, 조직별 공개 범위, 버전 이력(지금은 최신 버전만 보관), ChatGPT · Claude 자동 설치
- 개인 ChatGPT · Claude 에서 KRRI EASY 를 직접 쓰는 Remote MCP 연결 (provider · 기관 network 결정 보류. prototype 은 local archive branch 에 보존)
- 로그인 시도 제한 · 감사 로그 등 production 인증 기능
- KRRI_ASAP 로그인(Keycloak) 연동은 하지 않는다 (EASY 계정은 의도적으로 별개)
- OTP · R5 는 Gateway 가 tools/list 를 못 받는 운영 문제로 「상태 모름」이다
- 신규 MCP server onboarding (future backlog)
- production 인증 · 배포
