"""도구함. 이미 KRRI 에 있는 logical MCP 를 사용자 selection 에 넣고 빼는 것 (신규 MCP server 등록이 아니다).

브라우저 contract 는 mcp_id 뿐이다. Gateway selection 에는 그 mcp_id 가 groupId 로 들어간다
(ASAP-web MCP market 과 같은 표현). groupIds · toolRefs 계산은 여기서 끝난다.
개발 중 MCP 는 등록 · 해제 대상이 아니다 (409, Gateway 를 부르지 않는다).
사용자 식별은 Gateway guest id 를 담은 Portal cookie(GUEST_COOKIE) 하나다. 그 값은 JSON 에 싣지 않는다.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ..clients.selection import SelectionReply, registered_mcp_ids, valid_guest_id
from .catalog import NOT_FOUND_DETAIL, card, find_planned, ordered_mcps

router = APIRouter(prefix="/api/toolbox", tags=["toolbox"])

GUEST_COOKIE = "kem_gateway_guest"
GUEST_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # Gateway asap_mcp_guest 와 같다.

NOT_APPLIED_DETAIL = "Gateway 가 이 MCP 를 도구함에 반영하지 않았습니다."
IN_DEVELOPMENT_DETAIL = "개발 중인 MCP 는 도구함에 등록할 수 없습니다."


class _Session:
    """요청 한 건 동안의 guest id. Gateway 가 새로 발급하면 이어지는 호출과 응답 cookie 에 쓴다."""

    def __init__(self, request: Request):
        self.guest_id = valid_guest_id(request.cookies.get(GUEST_COOKIE))
        self._issued = False
        self._secure = request.url.scheme == "https"

    def take(self, reply: SelectionReply):
        if reply.issued_guest_id and reply.issued_guest_id != self.guest_id:
            self.guest_id = reply.issued_guest_id
            self._issued = True
        return reply.selection

    def remember(self, response: Response):
        if self._issued:
            response.set_cookie(
                GUEST_COOKIE, self.guest_id, max_age=GUEST_COOKIE_MAX_AGE,
                path="/api", httponly=True, samesite="lax", secure=self._secure,
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
