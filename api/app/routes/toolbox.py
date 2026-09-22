"""도구함. 이미 KRRI 에 있는 MCP 를 사용자 selection 에 넣고 빼는 것 (신규 MCP server 등록이 아니다).

브라우저 contract 는 server_id 뿐이다. groupIds · toolRefs · wildcard 계산은 여기서 끝난다.
사용자 식별은 Gateway guest id 를 담은 Portal cookie(GUEST_COOKIE) 하나다. 그 값은 JSON 에 싣지 않는다.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ..clients.selection import (
    SelectionReply,
    has_server,
    registered_server_ids,
    valid_guest_id,
    with_server,
    without_server,
)
from .catalog import card

router = APIRouter(prefix="/api/toolbox", tags=["toolbox"])

GUEST_COOKIE = "kem_gateway_guest"
GUEST_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # Gateway asap_mcp_guest 와 같다.

NOT_APPLIED_DETAIL = "Gateway 가 이 MCP 를 도구함에 반영하지 않았습니다."


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


def _body(request: Request, selection) -> dict:
    state = request.app.state
    registered = registered_server_ids(selection)
    servers = [s for s in state.gateway.list_servers() if s["server_id"].lower() in registered]
    return {
        "server_ids": [s["server_id"] for s in servers],
        "mcps": [card(s, state.presentation, state.gateway.source) for s in servers],
    }


def _not_applied(session: _Session) -> JSONResponse:
    # HTTPException 으로 올리면 이번에 발급된 guest cookie 가 응답에서 빠진다.
    response = JSONResponse(status_code=409, content={"detail": NOT_APPLIED_DETAIL})
    session.remember(response)
    return response


def _require_server(request: Request, server_id: str):
    if request.app.state.gateway.get_server(server_id) is None:
        raise HTTPException(status_code=404, detail="MCP 를 찾을 수 없습니다.")


@router.get("")
def get_toolbox(request: Request, response: Response) -> dict:
    session = _Session(request)
    selection = session.take(request.app.state.selection.get(session.guest_id))
    session.remember(response)
    return _body(request, selection)


@router.post("/{server_id}")
def add_to_toolbox(server_id: str, request: Request, response: Response):
    _require_server(request, server_id)
    client = request.app.state.selection
    session = _Session(request)
    selection = session.take(client.get(session.guest_id))
    if server_id.lower() not in registered_server_ids(selection):
        selection = session.take(client.put(session.guest_id, with_server(selection, server_id)))
        if server_id.lower() not in registered_server_ids(selection):
            return _not_applied(session)
    session.remember(response)
    return _body(request, selection)


@router.delete("/{server_id}")
def remove_from_toolbox(server_id: str, request: Request, response: Response):
    _require_server(request, server_id)
    state = request.app.state
    session = _Session(request)
    selection = session.take(state.selection.get(session.guest_id))
    if has_server(selection, server_id):
        selection = session.take(
            state.selection.put(session.guest_id, without_server(selection, server_id, state.gateway.group_servers()))
        )
        if has_server(selection, server_id):
            return _not_applied(session)
    session.remember(response)
    return _body(request, selection)
