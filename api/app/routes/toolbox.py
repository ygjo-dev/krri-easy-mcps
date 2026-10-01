"""도구함. 이미 KRRI 에 있는 logical MCP 를 사용자 selection 에 넣고 빼는 것 (신규 MCP server 등록이 아니다).

브라우저 contract 는 mcp_id 뿐이다. Gateway selection 에는 그 mcp_id 가 groupId 로 들어간다
(ASAP-web MCP market 과 같은 표현). groupIds · toolRefs 계산은 여기서 끝난다.
개발 중 MCP 는 등록 · 해제 대상이 아니다 (409, Gateway 를 부르지 않는다).
사용자 식별은 Gateway 의 guest cookie(``asap_mcp_guest``, GUEST_COOKIE) 그대로다. 그 값은 JSON 에 싣지 않는다.

**ASAP-web 과 같은 cookie 를 쓴다.** 이름 · Path=/ · HttpOnly · SameSite=Lax · 1년이 Gateway guestSession.ts 와 같다.
cookie 는 port 를 가리지 않으므로 같은 hostname 에 뜬 ASAP-web 이 받은 guest 를 여기서도 그대로 읽고,
여기서 발급된 guest 를 ASAP-web 도 그대로 읽는다. 그래서 두 화면이 같은 Gateway selection 행을 쓴다.

예전 Portal cookie(LEGACY_GUEST_COOKIE, Path=/api) 는 이행용으로만 읽는다. 유효한 canonical 이 없을 때만 그 UUID 를
그대로 canonical 로 올려(같은 Gateway 행) 적고, 성공 응답에서 legacy 는 지운다. 둘 다 있으면 canonical 이 이긴다.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..clients.selection import GATEWAY_GUEST_COOKIE, SelectionReply, registered_mcp_ids, valid_guest_id
from .catalog import NOT_FOUND_DETAIL, card, find_planned, ordered_mcps

router = APIRouter(prefix="/api/toolbox", tags=["toolbox"])

GUEST_COOKIE = GATEWAY_GUEST_COOKIE
GUEST_COOKIE_PATH = "/"
GUEST_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # Gateway asap_mcp_guest 와 같다.
LEGACY_GUEST_COOKIE = "kem_gateway_guest"
LEGACY_GUEST_COOKIE_PATH = "/api"

NOT_APPLIED_DETAIL = "Gateway 가 이 MCP 를 도구함에 반영하지 않았습니다."
IN_DEVELOPMENT_DETAIL = "개발 중인 MCP 는 도구함에 등록할 수 없습니다."


class _Session:
    """요청 한 건 동안의 guest id. Gateway 가 새로 발급하면 이어지는 호출과 응답 cookie 에 쓴다.

    유효한 canonical > 유효한 legacy(canonical 로 올림) > 없음(Gateway 가 발급). 형식이 틀린 값은 믿지 않는다.
    """

    def __init__(self, request: Request):
        canonical = valid_guest_id(request.cookies.get(GUEST_COOKIE))
        legacy = valid_guest_id(request.cookies.get(LEGACY_GUEST_COOKIE))
        self.guest_id = canonical or legacy
        self._write = canonical is None and legacy is not None
        self._drop_legacy = LEGACY_GUEST_COOKIE in request.cookies
        self._secure = request.url.scheme == "https"

    def take(self, reply: SelectionReply):
        self.adopt(reply.issued_guest_id)
        return reply.selection

    def adopt(self, issued_guest_id: str | None):
        if issued_guest_id and issued_guest_id != self.guest_id:
            self.guest_id = issued_guest_id
            self._write = True

    def remember(self, response: Response):
        if self._write:
            response.set_cookie(
                GUEST_COOKIE, self.guest_id, max_age=GUEST_COOKIE_MAX_AGE,
                path=GUEST_COOKIE_PATH, httponly=True, samesite="lax", secure=self._secure,
            )
        if self._drop_legacy:
            response.delete_cookie(
                LEGACY_GUEST_COOKIE, path=LEGACY_GUEST_COOKIE_PATH,
                httponly=True, samesite="lax", secure=self._secure,
            )


def _body(request: Request, registered: list[str]) -> dict:
    state = request.app.state
    by_id = {m["mcp_id"]: m for m in state.gateway.list_mcps()}
    return {
        "mcp_ids": registered,
        "mcps": [card(by_id[i], state.presentation, state.gateway.source) for i in registered],
    }


def _registered(request: Request, selection) -> list[str]:
    state = request.app.state
    return registered_mcp_ids(selection, ordered_mcps(state.gateway.list_mcps(), state.presentation))


def _refused(session: _Session, status_code: int, detail: str) -> JSONResponse:
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
    """도구함이 다른 화면(KRRI-ASAP 등)에서 바뀌면 오는 신호 (text/event-stream).

    Gateway 의 selection 신호 흐름을 이 guest 로 열어 바이트 그대로 넘긴다. 신호를 해석하거나 selection 을 싣지 않는다
    — 브라우저는 신호를 받으면 GET /api/toolbox 로 다시 읽는다. 브라우저가 끊으면 Gateway 쪽 흐름도 닫는다.
    Gateway 를 못 열면 502 (브라우저가 잠시 뒤 다시 잇는다).
    """
    session = _Session(request)
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
    session = _Session(request)
    selection = session.take(request.app.state.selection.get(session.guest_id))
    session.remember(response)
    return _body(request, _registered(request, selection))


@router.post("/{mcp_id}")
def add_to_toolbox(mcp_id: str, request: Request, response: Response):
    _require_available(request, mcp_id)
    client = request.app.state.selection
    session = _Session(request)
    registered = _registered(request, session.take(client.get(session.guest_id)))
    if mcp_id not in registered:
        registered = _registered(request, session.take(client.put_groups(session.guest_id, [*registered, mcp_id])))
        if mcp_id not in registered:
            return _refused(session, 409, NOT_APPLIED_DETAIL)
    session.remember(response)
    return _body(request, registered)


@router.delete("/{mcp_id}")
def remove_from_toolbox(mcp_id: str, request: Request, response: Response):
    _require_available(request, mcp_id)
    client = request.app.state.selection
    session = _Session(request)
    registered = _registered(request, session.take(client.get(session.guest_id)))
    if mcp_id in registered:
        rest = [i for i in registered if i != mcp_id]
        registered = _registered(request, session.take(client.put_groups(session.guest_id, rest)))
        if mcp_id in registered:
            return _refused(session, 409, NOT_APPLIED_DETAIL)
    session.remember(response)
    return _body(request, registered)
