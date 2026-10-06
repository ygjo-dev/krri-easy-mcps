"""내 MCP. 이미 KRRI 에 있는 logical MCP 를 사용자 selection 에 넣고 빼는 것 (신규 MCP server 등록이 아니다).

브라우저 contract 는 mcp_id 뿐이다. Gateway selection 에는 그 mcp_id 가 groupId 로 들어간다
(ASAP-web MCP market 과 같은 표현). groupIds · toolRefs 계산은 여기서 끝난다.
개발 중 MCP 는 등록 · 해제 대상이 아니다 (409, Gateway 를 부르지 않는다).
사용자 식별은 Gateway 의 guest cookie(``asap_mcp_guest``, GUEST_COOKIE) 그대로다. 그 값은 JSON 에 싣지 않는다.

**ASAP-web 과 같은 cookie 를 쓴다.** 이름 · Path=/ · HttpOnly · SameSite=Lax · 1년이 Gateway guestSession.ts 와 같다.
cookie 는 port 를 가리지 않으므로 같은 hostname 에 뜬 ASAP-web 이 받은 guest 를 여기서도 그대로 읽고,
여기서 발급된 guest 를 ASAP-web 도 그대로 읽는다. 그래서 두 화면이 같은 Gateway selection 행을 쓴다.

예전 Portal cookie(LEGACY_GUEST_COOKIE, Path=/api) 는 이행용으로만 읽는다. 유효한 canonical 이 없을 때만 그 UUID 를
그대로 canonical 로 올려(같은 Gateway 행) 적고, 성공 응답에서 legacy 는 지운다. 둘 다 있으면 canonical 이 이긴다.

**EASY 로그인(계정 내 MCP).** 로그인해도 Gateway 쪽은 그대로 이 guest selection 이다 (KRRI ASAP 연동 유지).
계정 내 MCP은 그 위의 영구 저장이다. Gateway 가 실제로 반영한 값만 계정에 적는다. 로그인 중이면 내 MCP을 읽기 전에 맞춘다:

    계정 내 MCP이 아직 없음        → 지금 guest selection 을 그대로 계정에 저장 (빈 것도 "초기화된 빈 내 MCP")
    이 세션이 이 guest 와 처음 맞춤 → 계정 내 MCP을 guest selection 에 PUT (다른 PC · 브라우저에서 복원)
    이미 맞춘 guest               → 마지막으로 맞춘 값을 기준으로 3-way merge.
                                    계정이 그대로면 Gateway 값(KRRI ASAP 쪽 변경 포함)을 계정에 저장하고,
                                    다른 기기가 계정을 바꿨으면 그 변경을 이 guest 에 PUT 한다.

등록 · 해제는 위로 맞춘 뒤 Gateway PUT 이 성공한 실제 결과만 계정에 저장한다. Gateway 가 실패하면 계정은 그대로다.
로그아웃은 EASY 세션만 지운다. guest cookie 와 Gateway selection 은 건드리지 않는다.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..accounts import Login, current_login, guest_key
from ..clients.selection import GATEWAY_GUEST_COOKIE, SelectionReply, registered_mcp_ids, valid_guest_id
from .catalog import NOT_FOUND_DETAIL, card, find_planned, ordered_mcps

router = APIRouter(prefix="/api/toolbox", tags=["toolbox"])

GUEST_COOKIE = GATEWAY_GUEST_COOKIE
GUEST_COOKIE_PATH = "/"
GUEST_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # Gateway asap_mcp_guest 와 같다.
LEGACY_GUEST_COOKIE = "kem_gateway_guest"
LEGACY_GUEST_COOKIE_PATH = "/api"

NOT_APPLIED_DETAIL = "Gateway 가 이 MCP 를 내 MCP에 반영하지 않았습니다."
IN_DEVELOPMENT_DETAIL = "개발 중인 MCP 는 내 MCP에 등록할 수 없습니다."


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


def _merged(base: tuple[str, ...], gateway: list[str], account: list[str]) -> list[str]:
    """마지막으로 맞춘 base 에서 Gateway 쪽 · 계정 쪽 변경을 합친다. 한쪽이라도 뺀 것은 빠지고, 더한 것은 들어간다."""
    before, now, saved = set(base), set(gateway), set(account)
    keep = {i for i in before if i in now and i in saved} | (now - before) | (saved - before)
    return [i for i in dict.fromkeys([*gateway, *account]) if i in keep]


def _current(request: Request, session: _Session, login: Login | None) -> list[str]:
    """지금 내 MCP (Gateway 가 반영한 실제 값). 로그인 중이면 계정 내 MCP과 맞춘 뒤의 값이다 (모듈 docstring)."""
    client = request.app.state.selection
    registered = _registered(request, session.take(client.get(session.guest_id)))
    if login is None:
        return registered
    saved = request.app.state.accounts.toolbox(login.user)
    guest = guest_key(session.guest_id)
    if saved is None:
        target = registered
    elif login.synced_guest != guest or login.synced_mcp_ids is None:
        target = saved
    else:
        target = _merged(login.synced_mcp_ids, registered, saved)
    if set(target) != set(registered):
        registered = _registered(request, session.take(client.put_groups(session.guest_id, target)))
    unchanged = saved == registered and login.synced_guest == guest and list(login.synced_mcp_ids or ()) == registered
    if not unchanged:
        _save(request, session, login, registered)
    return registered


def _save(request: Request, session: _Session, login: Login | None, registered: list[str]):
    if login is not None:
        request.app.state.accounts.save_toolbox(login, guest_key(session.guest_id), registered)


def sync_login(request: Request, response: Response, login: Login) -> None:
    """로그인 직후 한 번 계정 내 MCP과 이 브라우저의 guest selection 을 맞춘다 (routes/auth.py).

    Gateway 가 실패하면 GatewayUnavailable 이 그대로 올라간다 (cookie 는 건드리지 않는다).
    """
    session = _Session(request)
    _current(request, session, login)
    session.remember(response)


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
    """내 MCP이 다른 화면(KRRI-ASAP 등)에서 바뀌면 오는 신호 (text/event-stream).

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
    registered = _current(request, session, current_login(request))
    session.remember(response)
    return _body(request, registered)


@router.post("/{mcp_id}")
def add_to_toolbox(mcp_id: str, request: Request, response: Response):
    _require_available(request, mcp_id)
    client = request.app.state.selection
    session = _Session(request)
    login = current_login(request)
    registered = _current(request, session, login)
    if mcp_id not in registered:
        registered = _registered(request, session.take(client.put_groups(session.guest_id, [*registered, mcp_id])))
        _save(request, session, login, registered)
        if mcp_id not in registered:
            return _refused(session, 409, NOT_APPLIED_DETAIL)
    session.remember(response)
    return _body(request, registered)


@router.delete("/{mcp_id}")
def remove_from_toolbox(mcp_id: str, request: Request, response: Response):
    _require_available(request, mcp_id)
    client = request.app.state.selection
    session = _Session(request)
    login = current_login(request)
    registered = _current(request, session, login)
    if mcp_id in registered:
        rest = [i for i in registered if i != mcp_id]
        registered = _registered(request, session.take(client.put_groups(session.guest_id, rest)))
        _save(request, session, login, registered)
        if mcp_id in registered:
            return _refused(session, 409, NOT_APPLIED_DETAIL)
    session.remember(response)
    return _body(request, registered)
