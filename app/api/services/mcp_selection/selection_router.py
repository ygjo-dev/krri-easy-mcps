"""내 MCP. 이미 KRRI 에 있는 logical MCP 를 사용자 selection 에 넣고 빼는 것 (신규 MCP server 등록이 아니다).

브라우저 contract 는 mcp_id 뿐이다. Gateway selection 에는 그 mcp_id 가 groupId 로 들어간다
(ASAP-web MCP market 과 같은 표현). groupIds · toolRefs 계산은 여기서 끝난다.
개발 중 MCP 는 등록 · 해제 대상이 아니다 (409, Gateway 를 부르지 않는다).
사용자 식별(guest cookie) · 계정 내 MCP 동기화 규칙은 selection_service.py.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..auth.account_service import current_login
from ..catalog.catalog_service import NOT_FOUND_DETAIL, card, find_planned
from .selection_service import GuestSession, current, registered_mcps, save

router = APIRouter(prefix="/api/toolbox", tags=["toolbox"])

NOT_APPLIED_DETAIL = "Gateway 가 이 MCP 를 내 MCP에 반영하지 않았습니다."
IN_DEVELOPMENT_DETAIL = "개발 중인 MCP 는 내 MCP에 등록할 수 없습니다."


def _body(request: Request, registered: list[str]) -> dict:
    state = request.app.state
    by_id = {m["mcp_id"]: m for m in state.gateway.list_mcps()}
    return {
        "mcp_ids": registered,
        "mcps": [card(by_id[i], state.presentation, state.gateway.source) for i in registered],
    }


def _refused(session: GuestSession, status_code: int, detail: str) -> JSONResponse:
    # HTTPException 으로 올리면 이번에 발급된 guest cookie 가 응답에서 빠진다.
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    session.remember(response)
    return response


def _require_available(request: Request, mcp_id: str):
    """Gateway logical MCP 만 통과. 개발 중이면 409, 없으면 404. selection 을 읽기 전에 막는다."""
    state = request.app.state
    if state.gateway.get_mcp(mcp_id) is not None:
        return
    if find_planned(state, mcp_id) is not None:
        raise HTTPException(status_code=409, detail=IN_DEVELOPMENT_DETAIL)
    raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)


@router.get("/events")
async def toolbox_events(request: Request):
    """내 MCP이 다른 화면(KRRI-ASAP 등)에서 바뀌면 오는 신호 (text/event-stream).

    Gateway 의 selection 신호 흐름을 이 guest 로 열어 바이트 그대로 넘긴다. 신호를 해석하거나 selection 을 싣지 않는다
    — 브라우저는 신호를 받으면 GET /api/toolbox 로 다시 읽는다. 브라우저가 끊으면 Gateway 쪽 흐름도 닫는다.
    Gateway 를 못 열면 502 (브라우저가 잠시 뒤 다시 잇는다).
    """
    session = GuestSession(request)
    events = await request.app.state.selection.open_events(session.guest_id)
    session.adopt(events.issued_guest_id)

    async def relay():
        try:
            async for chunk in events.chunks:
                yield chunk
        finally:
            await events.aclose()

    response = StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
    session.remember(response)
    return response


@router.get("")
def get_toolbox(request: Request, response: Response) -> dict:
    session = GuestSession(request)
    registered = current(request, session, current_login(request))
    session.remember(response)
    return _body(request, registered)


@router.post("/{mcp_id}")
def add_to_toolbox(mcp_id: str, request: Request, response: Response):
    _require_available(request, mcp_id)
    client = request.app.state.selection
    session = GuestSession(request)
    login = current_login(request)
    registered = current(request, session, login)
    if mcp_id not in registered:
        registered = registered_mcps(request, session.take(client.put_groups(session.guest_id, [*registered, mcp_id])))
        save(request, session, login, registered)
        if mcp_id not in registered:
            return _refused(session, 409, NOT_APPLIED_DETAIL)
    session.remember(response)
    return _body(request, registered)


@router.delete("/{mcp_id}")
def remove_from_toolbox(mcp_id: str, request: Request, response: Response):
    _require_available(request, mcp_id)
    client = request.app.state.selection
    session = GuestSession(request)
    login = current_login(request)
    registered = current(request, session, login)
    if mcp_id in registered:
        rest = [i for i in registered if i != mcp_id]
        registered = registered_mcps(request, session.take(client.put_groups(session.guest_id, rest)))
        save(request, session, login, registered)
        if mcp_id in registered:
            return _refused(session, 409, NOT_APPLIED_DETAIL)
    session.remember(response)
    return _body(request, registered)
