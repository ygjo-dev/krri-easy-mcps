"""내 MCP 의 사용자 식별(Gateway guest cookie)과 EASY 계정 내 MCP 동기화 규칙.

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
import hashlib

from fastapi import Request, Response

from ...integrations.krri_asap.selection_client import GATEWAY_GUEST_COOKIE, SelectionReply, registered_mcp_ids, valid_guest_id
from ..auth.account_service import Login
from ..catalog.catalog_service import ordered_mcps

GUEST_COOKIE = GATEWAY_GUEST_COOKIE
GUEST_COOKIE_PATH = "/"
GUEST_COOKIE_MAX_AGE = 365 * 24 * 60 * 60  # Gateway asap_mcp_guest 와 같다.
LEGACY_GUEST_COOKIE = "kem_gateway_guest"
LEGACY_GUEST_COOKIE_PATH = "/api"


def guest_key(guest_id: str | None) -> str | None:
    """세션 동기화 기록에 적는 guest 표시. guest id 원문 대신 hash 를 둔다 (같은 guest 인지만 본다)."""
    return hashlib.sha256(guest_id.encode()).hexdigest() if guest_id else None


class GuestSession:
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


def registered_mcps(request: Request, selection) -> list[str]:
    """Gateway selection → 등록된 mcp_id (catalog 순서)."""
    state = request.app.state
    return registered_mcp_ids(selection, ordered_mcps(state.gateway.list_mcps(), state.presentation))


def merged(base: tuple[str, ...], gateway: list[str], account: list[str]) -> list[str]:
    """마지막으로 맞춘 base 에서 Gateway 쪽 · 계정 쪽 변경을 합친다. 한쪽이라도 뺀 것은 빠지고, 더한 것은 들어간다."""
    before, now, saved = set(base), set(gateway), set(account)
    keep = {i for i in before if i in now and i in saved} | (now - before) | (saved - before)
    return [i for i in dict.fromkeys([*gateway, *account]) if i in keep]


def current(request: Request, session: GuestSession, login: Login | None) -> list[str]:
    """지금 내 MCP (Gateway 가 반영한 실제 값). 로그인 중이면 계정 내 MCP과 맞춘 뒤의 값이다 (모듈 docstring)."""
    client = request.app.state.selection
    registered = registered_mcps(request, session.take(client.get(session.guest_id)))
    if login is None:
        return registered
    store = request.app.state.selections
    saved = store.toolbox(login.user)
    synced = store.session_sync(login)
    synced_guest, synced_ids = (synced.guest, synced.mcp_ids) if synced else (None, None)
    guest = guest_key(session.guest_id)
    if saved is None:
        target = registered
    elif synced_guest != guest or synced_ids is None:
        target = saved
    else:
        target = merged(synced_ids, registered, saved)
    if set(target) != set(registered):
        registered = registered_mcps(request, session.take(client.put_groups(session.guest_id, target)))
    unchanged = saved == registered and synced_guest == guest and list(synced_ids or ()) == registered
    if not unchanged:
        save(request, session, login, registered)
    return registered


def save(request: Request, session: GuestSession, login: Login | None, registered: list[str]):
    if login is not None:
        request.app.state.selections.save(login, guest_key(session.guest_id), registered)


def sync_login(request: Request, response: Response, login: Login) -> None:
    """로그인 직후 한 번 계정 내 MCP과 이 브라우저의 guest selection 을 맞춘다 (auth/auth_router.py).

    Gateway 가 실패하면 GatewayUnavailable 이 그대로 올라간다 (cookie 는 건드리지 않는다).
    """
    session = GuestSession(request)
    current(request, session, login)
    session.remember(response)
