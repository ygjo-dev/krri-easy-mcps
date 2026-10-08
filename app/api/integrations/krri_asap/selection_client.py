"""KRRI_ASAP Gateway 사용자별 MCP selection (내 MCP) boundary.

**Gateway contract (ASAP-Gateway src/features/mcpMarket, 2026-09-29 read-only 재확인)**

GET /api/me/mcp-selections           (권한 ANYONE)
PUT /api/me/mcp-selections           (권한 ANYONE, body strict {groupIds?, toolRefs?, serverIds?})
    응답 둘 다 정규화된 {groupIds, serverIds, toolRefs}

    groupIds   market tool-group id. 저장되고, 정규화 때 그 group 의 toolRefs 로 펼쳐진다
    toolRefs   실행 권한의 실제 범위. "<serverId>/<tool>" 또는 "<serverId>/*" (소문자).
               Executor 는 "<serverId>/*" 를 그 server 의 모든 tool 로 본다
    serverIds  toolRefs 에서 거꾸로 뽑은 값 (파생). 입력으로는 legacy — groupIds · toolRefs 가
               둘 다 비었을 때만 "<id>/*" 로 바뀐다

사용자 식별: 로그인 사용자는 JWT sub. 없으면 guest cookie ``asap_mcp_guest`` (UUID v4,
HttpOnly · SameSite=Lax · Path=/ · 1년). cookie 가 없거나 형식이 틀리면 Gateway 가 새 UUID 를
만들어 Set-Cookie 로 준다. user id 는 "guest:<uuid>".

**Portal 의 내 MCP = groupIds.** 등록 · 해제는 ASAP-web MCP market 과 같게 ``{groupIds}`` 만 PUT 한다.
그래서 두 화면이 같은 selection 을 같은 뜻으로 읽고 쓴다. 「등록됨」 판정도 Gateway market 의
isApplied 와 같다: groupIds 가 있으면 그 목록, 없으면(legacy toolRefs 만 있는 selection) toolRefs 가
group 의 정의 refs 를 모두 덮는 group. PUT 이 groupIds 만 실으므로 group 으로 안 펼쳐지는 explicit
toolRefs(예: 이전 Portal 이 넣은 ``<serverId>/*``)는 첫 쓰기 때 위 판정으로 groupIds 가 되고 사라진다.

Portal 은 브라우저의 ``asap_mcp_guest`` cookie 를 ASAP-web 과 같은 이름 · Path=/ 로 그대로 쓰고
(services/mcp_selection/selection_service.py), Gateway 를 부를 때 ``Cookie: asap_mcp_guest=<uuid>`` 로 옮겨 싣는다. 이 값은 JSON · 로그에 싣지 않는다.

GET /api/me/mcp-selections/events    (권한 ANYONE, text/event-stream)
    같은 주인의 selection 이 PUT 으로 저장될 때마다 ``event: selection_changed`` 를 보낸다. 25초마다 ``: ping``.
    신호만 온다 — selection 은 GET 으로 다시 읽는다. Portal 은 이 흐름을 브라우저로 그대로 넘길 뿐이다.
"""

import asyncio
import json
import re
import urllib.error
import urllib.request
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from http.cookies import SimpleCookie

import httpx

from .gateway_client import SOURCE_LIVE, SOURCE_MOCK, GatewayUnavailable

GATEWAY_GUEST_COOKIE = "asap_mcp_guest"
SELECTIONS_PATH = "/api/me/mcp-selections"
EVENTS_PATH = "/api/me/mcp-selections/events"
# Gateway 는 25초마다 heartbeat 를 보낸다. 이만큼 아무것도 안 오면 끊긴 것으로 보고 흐름을 끝낸다(브라우저가 다시 잇는다).
EVENTS_READ_TIMEOUT_SECONDS = 60.0

# Gateway guestSession.ts 의 GUEST_ID_PATTERN 과 같다.
GUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


def valid_guest_id(value: str | None) -> str | None:
    return value if value and GUEST_ID_PATTERN.match(value) else None


@dataclass(frozen=True)
class Selection:
    group_ids: tuple[str, ...]
    tool_refs: tuple[str, ...]


@dataclass(frozen=True)
class SelectionEvents:
    """열린 selection 신호 흐름 하나. chunks 를 다 읽거나 aclose() 로 닫는다."""

    chunks: AsyncIterator[bytes]
    aclose: Callable[[], Awaitable[None]]
    # Gateway 가 새로 발급한 guest id. 새로 안 줬으면 None.
    issued_guest_id: str | None


@dataclass(frozen=True)
class SelectionReply:
    selection: Selection
    # Gateway 가 새로 발급한 guest id. 새로 안 줬으면 None.
    issued_guest_id: str | None


def _selection(data) -> Selection:
    if not isinstance(data, dict):
        raise GatewayUnavailable(f"selection response is {type(data).__name__}, expected object")
    return Selection(
        group_ids=tuple(str(g) for g in data.get("groupIds") or []),
        tool_refs=tuple(str(r).lower() for r in data.get("toolRefs") or []),
    )


# ── logical MCP(group) 단위 내 MCP ↔ Gateway selection ──────────────────


def _refs_cover(selected_refs: tuple[str, ...], group_refs: list[str]) -> bool:
    """Gateway mcpMarket.service refsCoverGroup 과 같다."""
    selected = set(selected_refs)
    return bool(group_refs) and all(
        ref in selected or f"{ref.split('/', 1)[0]}/*" in selected for ref in group_refs
    )


def registered_mcp_ids(selection: Selection, mcps: list[dict]) -> list[str]:
    """내 MCP에 「등록됨」인 logical MCP id. Gateway market isApplied 와 같은 판정, catalog 순서."""
    if selection.group_ids:
        chosen = set(selection.group_ids)
        return [m["mcp_id"] for m in mcps if m["mcp_id"] in chosen]
    return [m["mcp_id"] for m in mcps if _refs_cover(selection.tool_refs, m["tool_refs"])]


# ── clients ───────────────────────────────────────────────────────────


Transport = Callable[[str, str, dict | None, str | None], tuple[object, list[str]]]


class RealSelectionClient:
    """Gateway GET/PUT /api/me/mcp-selections. guest cookie 만 실어 보낸다 (Authorization 없음)."""

    source = SOURCE_LIVE

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 15,
        transport: Transport | None = None,
        stream_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport or self._urllib_transport
        self._stream_transport = stream_transport

    async def open_events(self, guest_id: str | None) -> SelectionEvents:
        """Gateway selection 신호 흐름을 연다. 바이트를 해석하지 않고 그대로 넘긴다. 못 열면 GatewayUnavailable."""
        headers = {"Accept": "text/event-stream"}
        if valid_guest_id(guest_id):
            headers["Cookie"] = f"{GATEWAY_GUEST_COOKIE}={guest_id}"
        client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout, read=EVENTS_READ_TIMEOUT_SECONDS),
            transport=self._stream_transport,
        )
        try:
            response = await client.send(client.build_request("GET", EVENTS_PATH, headers=headers), stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise GatewayUnavailable(f"GET {EVENTS_PATH} failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            await response.aclose()
            await client.aclose()
            raise GatewayUnavailable(f"GET {EVENTS_PATH} failed: HTTP {response.status_code}")

        async def chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            except httpx.HTTPError:
                return  # heartbeat 가 끊겼거나 Gateway 가 닫았다. 흐름을 끝낸다.

        async def aclose() -> None:
            await response.aclose()
            await client.aclose()

        return SelectionEvents(chunks(), aclose, _issued_guest_id(response.headers.get_list("set-cookie")))

    def get(self, guest_id: str | None) -> SelectionReply:
        return self._call("GET", None, guest_id)

    def put_groups(self, guest_id: str | None, group_ids: list[str]) -> SelectionReply:
        """ASAP-web 과 같게 {groupIds} 만 보낸다. toolRefs 는 Gateway 가 group 에서 펼친다."""
        return self._call("PUT", {"groupIds": list(group_ids)}, guest_id)

    def _call(self, method: str, body: dict | None, guest_id: str | None) -> SelectionReply:
        cookie = f"{GATEWAY_GUEST_COOKIE}={guest_id}" if valid_guest_id(guest_id) else None
        try:
            data, set_cookies = self._transport(method, SELECTIONS_PATH, body, cookie)
        except GatewayUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GatewayUnavailable(f"{method} {SELECTIONS_PATH} failed: {type(exc).__name__}") from exc
        return SelectionReply(_selection(data), _issued_guest_id(set_cookies))

    def _urllib_transport(self, method, path, body, cookie):
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(self._base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.load(response), response.headers.get_all("Set-Cookie") or []
        except urllib.error.HTTPError as exc:
            # 본문은 읽지 않는다 (Gateway 오류 원문을 어디에도 싣지 않게).
            raise GatewayUnavailable(f"{method} {path} failed: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise GatewayUnavailable(f"{method} {path} failed: {type(exc).__name__}") from None


def _issued_guest_id(set_cookies: list[str]) -> str | None:
    for header in set_cookies:
        jar = SimpleCookie()
        try:
            jar.load(header)
        except Exception:  # noqa: BLE001 — 못 읽는 Set-Cookie 는 무시한다.
            continue
        if GATEWAY_GUEST_COOKIE in jar:
            return valid_guest_id(jar[GATEWAY_GUEST_COOKIE].value)
    return None


class MockSelectionClient:
    """process-local. Gateway 처럼 guest id 가 없으면 새로 발급한다. groupIds 만 저장한다 (중복 제거)."""

    source = SOURCE_MOCK

    def __init__(self):
        self.store: dict[str, Selection] = {}

    def get(self, guest_id: str | None) -> SelectionReply:
        guest, issued = self._guest(guest_id)
        return SelectionReply(self.store.get(guest, Selection((), ())), issued)

    def put_groups(self, guest_id: str | None, group_ids: list[str]) -> SelectionReply:
        guest, issued = self._guest(guest_id)
        self.store[guest] = Selection(tuple(dict.fromkeys(group_ids)), ())
        return SelectionReply(self.store[guest], issued)

    async def open_events(self, guest_id: str | None) -> SelectionEvents:
        """mock 은 다른 화면이 없으므로 신호를 보내지 않는다. 연결만 붙잡아 둔다(heartbeat)."""
        _, issued = self._guest(guest_id)

        async def chunks() -> AsyncIterator[bytes]:
            yield b": connected\n\n"
            while True:
                await asyncio.sleep(25)
                yield b": ping\n\n"

        async def aclose() -> None:
            return None

        return SelectionEvents(chunks(), aclose, issued)

    def _guest(self, guest_id):
        if valid_guest_id(guest_id):
            return guest_id, None
        new = str(uuid.uuid4())
        return new, new


def make_selection_client(mode: str, base_url: str = ""):
    if mode == SOURCE_MOCK:
        return MockSelectionClient()
    if mode == SOURCE_LIVE:
        if not base_url:
            raise ValueError("KEM_GATEWAY_MODE=live requires KEM_GATEWAY_BASE_URL")
        return RealSelectionClient(base_url)
    raise ValueError(f"unknown KEM_GATEWAY_MODE {mode!r} (mock | live)")
