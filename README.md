# KRRI EASY MCPs

KRRI 가 제공하는 MCP 서버를 찾아보고, 상세 정보와 Tool 을 확인하고,
미리 준비된 질문으로 「AI로 사용해보기」를 해 보는 Portal 이다. UI + thin BFF 로만 이루어진다.

> **현재 상태.** MCP 목록 · Tool · 상태는 `KEM_GATEWAY_MODE=live` 에서 실제 KRRI_ASAP Gateway 를 읽는다
> (기본은 mock). AI로 사용해보기 실행 결과와 등록 미리보기는 아직 **mock** 이다.

## 구조

```text
krri-easy-mcps/
├── web/        React + TypeScript + Vite. 브라우저 UI
├── api/        FastAPI thin BFF
│   ├── app/
│   │   ├── main.py          앱 조립, /api/health
│   │   ├── settings.py      KEM_* 환경변수 (내부 주소는 여기만)
│   │   ├── metadata.py      config/*.yaml 읽기
│   │   ├── trace.py         agentic_ai 이벤트 → Portal 실행 결과
│   │   ├── routes/          catalog · demo · registration
│   │   └── clients/         gateway.py (mock | live) · agentic_ai.py (mock)
│   └── tests/
├── config/
│   ├── presentation.yaml    Portal 전용 표시 정보 (server_id 기준)
│   └── demo_questions.yaml  「AI로 사용해보기」 고정 질문
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

## 화면

| route | 내용 |
|---|---|
| `/` | MCP 탐색. 카드(이름 · 요약 · 카테고리 · 기관 · Tool 수 · 상태), 검색, 카테고리 필터 |
| `/mcps/:serverId` | MCP 상세. 설명 · 상태 · Tool 목록/parameter · AI로 사용해보기 |
| `/toolbox/register` | 도구함 › MCP 등록. Endpoint 입력 → 정보 불러오기 → Server/Capabilities/Tool 미리보기 |

자유 질문 입력과 Tool 직접 테스트 화면은 없다.

## Browser ↔ BFF API

| method | path | 설명 |
|---|---|---|
| GET | `/api/health` | 상태와 client mode |
| GET | `/api/mcps` | catalog 카드 |
| GET | `/api/mcps/{server_id}` | 상세 + Tool/parameter |
| GET | `/api/mcps/{server_id}/demo-questions` | 고정 질문 `{question_id, display_text}` 만 |
| POST | `/api/demo/questions/{question_id}/execute` | 고정 질문 실행 → trace + 최종 답변 |
| POST | `/api/registration/inspect` | `{endpoint}` → 등록 미리보기 (mock, endpoint 를 호출하지 않음) |

## 책임 경계

| | 맡는 것 |
|---|---|
| **KRRI EASY MCPs** | catalog · 검색 · 상세 · 표시 정보 · 도구함/등록 UI · AI로 사용해보기 UI. BFF 는 내부 client 호출과 응답 변환만 |
| **agentic_ai** | Resolve · Ontology · Recipe 선택 · workflow materialization · 실행 orchestration (source of truth) |
| **KRRI_ASAP** | Gateway · MCP registry · MCP 실행 |

- 의존 방향은 `KRRI EASY MCPs → existing agentic_ai API → agentic_ai pipeline → KRRI_ASAP` 하나다.
  **KRRI EASY MCPs 를 위해 agentic_ai 를 수정하지 않는다.** agentic_ai 코드를 import · 복사 · symlink 하지 않는다.
- 고정 질문을 눌러도 Resolve 를 우회하지 않는다. BFF 는 display_text 를 agentic_ai 기존
  `POST /chat/stream` 에 발화로 보낸다 (향후). `expected_recipe_id` · `expected_tools` 는 검증·설명용이다.
- 브라우저는 BFF(`/api`)만 부른다. Gateway · MCP endpoint · agentic_ai · credential 은 브라우저에 노출하지 않는다.
- technical MCP/tool 정보의 source of truth 는 **Gateway** 다 (`GET /api/tools` + 보조 `GET /api/mcp-market`).
  status 는 `online`(이번 refresh 에 tool 이 있음) · `offline`(single-server group 이 error/disabled 명시) ·
  `unknown`(그 밖) 셋뿐이다. mock 데이터는 UI 검증용 대표 subset 이고 production catalog 가 아니다.
  `config/presentation.yaml` 에는 사용자-facing 정보만 두고 endpoint · credential · schema 를 두지 않는다.

자세한 boundary 와 기존 `/chat/stream` 의 이벤트 모양, limitation 은
[docs/integration-boundary.md](docs/integration-boundary.md) 에 있다.

## 아직 안 된 것

- 실제 registration inspect (Gateway MCP server test 재사용), 등록 · 게시
- existing agentic_ai API (`POST /chat/stream`) 실제 연동
- 실제 MCP 실행
- production 인증 · 배포
