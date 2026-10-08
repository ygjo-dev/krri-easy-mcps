"""내 MCP 변경 신호: Browser → BFF GET /api/toolbox/events → Gateway GET /api/me/mcp-selections/events.

BFF 는 흐름을 guest cookie 로 열어 바이트 그대로 넘긴다. selection 을 해석 · 복제하지 않는다.
Gateway 흐름은 httpx.MockTransport 로 흉내 낸다 (끝이 있는 흐름).
"""

import asyncio
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.integrations.krri_asap.gateway_client import GatewayUnavailable
from app.api.integrations.krri_asap.selection_client import EVENTS_PATH, GATEWAY_GUEST_COOKIE, MockSelectionClient, RealSelectionClient
from app.api.main import GATEWAY_UNAVAILABLE_DETAIL, create_app
from app.api.services.mcp_selection.selection_service import GUEST_COOKIE, LEGACY_GUEST_COOKIE

BASE_URL = "http://gateway.internal.example:3000"
STREAM = b": connected\n\nevent: selection_changed\ndata: {}\n\n: ping\n\n"


class FakeGatewayEvents:
    def __init__(self, status=200, body=STREAM, issue=None):
        self.status = status
        self.body = body
        self.issue = issue
        self.requests: list[httpx.Request] = []
        self.closed = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        headers = {"content-type": "text/event-stream"}
        if self.issue:
            headers["set-cookie"] = f"{GATEWAY_GUEST_COOKIE}={self.issue}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax"
        fake = self

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                for i in range(0, len(fake.body), 16):
                    yield fake.body[i:i + 16]

            async def aclose(self):
                fake.closed += 1

        return httpx.Response(self.status, headers=headers, stream=Body())


def make_client(fake: FakeGatewayEvents):
    app = create_app()
    app.state.selection = RealSelectionClient(BASE_URL, stream_transport=httpx.MockTransport(fake.handler))
    return TestClient(app)


def test_relays_gateway_stream_bytes_as_is_with_canonical_cookie():
    fake = FakeGatewayEvents()
    c = make_client(fake)
    guest = str(uuid.uuid4())
    c.cookies.set(GUEST_COOKIE, guest)
    r = c.get("/api/toolbox/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache, no-transform"
    assert r.content == STREAM
    [upstream] = fake.requests
    assert upstream.url.path == EVENTS_PATH
    assert upstream.headers["cookie"] == f"asap_mcp_guest={guest}"
    assert "authorization" not in upstream.headers
    assert r.headers.get_list("set-cookie") == []  # 이미 있는 guest 는 그대로
    assert fake.closed == 1  # 흐름이 끝나면 Gateway 쪽도 닫는다


def test_legacy_cookie_is_promoted_on_the_event_stream_too():
    fake = FakeGatewayEvents()
    c = make_client(fake)
    guest = str(uuid.uuid4())
    c.cookies.set(LEGACY_GUEST_COOKIE, guest)
    r = c.get("/api/toolbox/events")
    assert fake.requests[0].headers["cookie"] == f"asap_mcp_guest={guest}"
    cookies = r.headers.get_list("set-cookie")
    assert any(h.startswith(f"asap_mcp_guest={guest};") and "Path=/;" in h + ";" for h in cookies)
    assert any(h.startswith(f"{LEGACY_GUEST_COOKIE}=") and "Path=/api" in h for h in cookies)


def test_new_guest_issued_by_gateway_becomes_browser_cookie_not_body():
    issued = str(uuid.uuid4())
    fake = FakeGatewayEvents(issue=issued)
    c = make_client(fake)
    r = c.get("/api/toolbox/events")
    assert "cookie" not in fake.requests[0].headers
    [cookie] = r.headers.get_list("set-cookie")
    assert cookie.startswith(f"asap_mcp_guest={issued};") and "HttpOnly" in cookie
    assert issued.encode() not in r.content and b"guest:" not in r.content


def test_invalid_cookie_is_not_forwarded():
    fake = FakeGatewayEvents()
    c = make_client(fake)
    c.cookies.set(GUEST_COOKIE, "not-a-uuid")
    c.get("/api/toolbox/events")
    assert "cookie" not in fake.requests[0].headers


@pytest.mark.parametrize("status", [401, 403, 500, 502])
def test_gateway_error_is_sanitized_502(status):
    fake = FakeGatewayEvents(status=status)
    r = make_client(fake).get("/api/toolbox/events")
    assert r.status_code == 502
    assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}
    assert fake.closed == 1


def test_unreachable_gateway_is_502():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    app = create_app()
    app.state.selection = RealSelectionClient(BASE_URL, stream_transport=httpx.MockTransport(boom))
    r = TestClient(app).get("/api/toolbox/events")
    assert r.status_code == 502
    assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}


def test_open_events_raises_gateway_unavailable_on_error():
    client = RealSelectionClient(BASE_URL, stream_transport=httpx.MockTransport(FakeGatewayEvents(status=500).handler))
    with pytest.raises(GatewayUnavailable):
        asyncio.run(client.open_events(None))


def test_mock_mode_stream_opens_and_issues_guest():
    # mock 흐름은 끝이 없다(heartbeat 만). 첫 조각만 읽고 닫는다.
    async def first_chunk():
        events = await MockSelectionClient().open_events(None)
        try:
            return await anext(events.chunks), events.issued_guest_id
        finally:
            await events.chunks.aclose()
            await events.aclose()

    chunk, issued = asyncio.run(first_chunk())
    assert chunk.startswith(b": connected")
    assert issued is not None
