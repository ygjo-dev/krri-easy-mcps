"""selection_client — KRRI EASY 가 KRRI_ASAP Gateway 의 사용자별 MCP selection(내 MCP)을 읽고 쓰는 contract.

부르는 것 (권한 ANYONE, guest cookie 만)
    GET /api/me/mcp-selections          지금 selection {groupIds, serverIds, toolRefs}
    PUT /api/me/mcp-selections          body 는 {groupIds: [...]} 뿐 (ASAP-web MCP market 과 같은 표현)
    GET /api/me/mcp-selections/events   selection_changed 신호 흐름 (text/event-stream, 바이트 그대로 넘김)
부르지 않는 것
    /api/admin/mcp-servers* — 내 MCP 등록 · 해제는 이미 있는 MCP 를 내 selection 에 넣고 빼는 것이지,
    KRRI 의 MCP server registry 에 server 를 등록 · 삭제하는 것이 아니다.

- 사용자 식별은 ``Cookie: asap_mcp_guest=<UUID v4>`` 하나다. 형식이 틀린 id 는 보내지 않고, Authorization 은 없다.
  Gateway 가 새 guest 를 Set-Cookie 로 주면 그 id 를 호출한 쪽에 돌려준다.
- 「등록됨」 판정은 Gateway market isApplied 와 같다: groupIds 가 있으면 그것, 없으면 toolRefs 가 group 정의 refs 를 모두 덮는 group.
- Gateway 오류는 GatewayUnavailable 이고, Gateway 본문을 메시지에 옮기지 않는다.
"""

import asyncio
import json
import uuid

import httpx
import pytest

from app.api.integrations.krri_asap.gateway_client import GatewayUnavailable
from app.api.integrations.krri_asap.selection_client import (
    EVENTS_PATH,
    GATEWAY_GUEST_COOKIE,
    SELECTIONS_PATH,
    MockSelectionClient,
    RealSelectionClient,
    Selection,
    _issued_guest_id,
    registered_mcp_ids,
)
from tests.app.api.integrations.krri_asap.gateway_selection_fake import BASE_URL, GROUP_REFS, STREAM, FakeGatewayEvents


SELECTION = {"groupIds": ["krri-road-cctv"], "serverIds": ["asap-mcp-core"], "toolRefs": ["ASAP-MCP-CORE/road.getcctv"]}

# ── Gateway 에 보내는 요청 (실제 HTTP) ───────────────────────────────


def test_get_reads_selection_with_guest_cookie_and_no_credentials(recording_gateway):
    recording_gateway.reply("GET", SELECTIONS_PATH, json_body=SELECTION)
    guest = str(uuid.uuid4())
    reply = RealSelectionClient(recording_gateway.url).get(guest)
    assert reply.selection == Selection(("krri-road-cctv",), ("asap-mcp-core/road.getcctv",))  # toolRefs 는 소문자로
    assert reply.issued_guest_id is None
    [request] = recording_gateway.requests
    assert (request.method, request.path) == ("GET", SELECTIONS_PATH)
    assert request.headers["cookie"] == f"{GATEWAY_GUEST_COOKIE}={guest}"
    assert "authorization" not in request.headers


def test_put_groups_sends_only_group_ids(recording_gateway):
    """toolRefs · serverIds 는 보내지 않는다. Gateway 가 group 정의에서 펼친다."""
    recording_gateway.reply("PUT", SELECTIONS_PATH, json_body=SELECTION)
    guest = str(uuid.uuid4())
    RealSelectionClient(recording_gateway.url).put_groups(guest, ["krri-road-cctv", "web-research"])
    [request] = recording_gateway.requests
    assert (request.method, request.path) == ("PUT", SELECTIONS_PATH)
    assert json.loads(request.body) == {"groupIds": ["krri-road-cctv", "web-research"]}
    assert request.headers["content-type"] == "application/json"
    assert request.headers["cookie"] == f"{GATEWAY_GUEST_COOKIE}={guest}"


@pytest.mark.parametrize("bad", [None, "not-a-uuid", "00000000-0000-1000-8000-000000000000", "x; asap_mcp_guest=evil"])
def test_invalid_guest_id_is_never_forwarded(recording_gateway, bad):
    recording_gateway.reply("GET", SELECTIONS_PATH, json_body=SELECTION)
    RealSelectionClient(recording_gateway.url).get(bad)
    assert "cookie" not in recording_gateway.requests[0].headers


def test_guest_issued_by_gateway_is_returned_to_the_caller(recording_gateway):
    issued = str(uuid.uuid4())
    recording_gateway.reply("GET", SELECTIONS_PATH, json_body=SELECTION, headers={
        "Set-Cookie": f"{GATEWAY_GUEST_COOKIE}={issued}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax"})
    assert RealSelectionClient(recording_gateway.url).get(None).issued_guest_id == issued


def test_selection_events_open_with_guest_cookie_and_pass_bytes_through(recording_gateway):
    recording_gateway.reply("GET", EVENTS_PATH, body=STREAM, headers={"Content-Type": "text/event-stream"})
    guest = str(uuid.uuid4())

    async def read_all():
        events = await RealSelectionClient(recording_gateway.url).open_events(guest)
        try:
            return b"".join([chunk async for chunk in events.chunks])
        finally:
            await events.aclose()

    assert asyncio.run(read_all()) == STREAM  # selection_changed 신호를 해석하지 않고 그대로
    [request] = recording_gateway.requests
    assert (request.method, request.path) == ("GET", EVENTS_PATH)
    assert request.headers["cookie"] == f"{GATEWAY_GUEST_COOKIE}={guest}"
    assert request.headers["accept"] == "text/event-stream"


def test_gateway_error_status_raises_without_gateway_body(recording_gateway):
    recording_gateway.reply("PUT", SELECTIONS_PATH, status=500, json_body={"error": "Traceback secret-token 10.0.0.5"})
    with pytest.raises(GatewayUnavailable) as info:
        RealSelectionClient(recording_gateway.url).put_groups(str(uuid.uuid4()), ["krri-road-cctv"])
    assert "secret-token" not in str(info.value) and "Traceback" not in str(info.value)


def test_selection_changes_only_the_users_selection_never_the_mcp_server_registry(recording_gateway):
    """내 MCP 등록 · 해제 · 신호 구독에 쓰는 창구는 selection 두 개뿐이다 (GET · PUT). registry 는 건드리지 않는다."""
    recording_gateway.reply("GET", SELECTIONS_PATH, json_body=SELECTION)
    recording_gateway.reply("PUT", SELECTIONS_PATH, json_body=SELECTION)
    recording_gateway.reply("GET", EVENTS_PATH, body=STREAM, headers={"Content-Type": "text/event-stream"})
    client = RealSelectionClient(recording_gateway.url)
    guest = str(uuid.uuid4())
    client.get(guest)
    client.put_groups(guest, ["krri-road-cctv"])
    client.put_groups(guest, [])

    async def subscribe():
        events = await client.open_events(guest)
        await events.aclose()

    asyncio.run(subscribe())
    assert set(recording_gateway.calls()) == {("GET", SELECTIONS_PATH), ("PUT", SELECTIONS_PATH), ("GET", EVENTS_PATH)}
    assert not any("/admin" in path or "mcp-servers" in path for _, path in recording_gateway.calls())


def test_real_http_error_becomes_gateway_unavailable():
    with pytest.raises(GatewayUnavailable):
        RealSelectionClient("http://127.0.0.1:9", timeout_seconds=2).get(None)


def test_open_events_raises_gateway_unavailable_on_error():
    client = RealSelectionClient(BASE_URL, stream_transport=httpx.MockTransport(FakeGatewayEvents(status=500).handler))
    with pytest.raises(GatewayUnavailable):
        asyncio.run(client.open_events(None))


# ── 「등록됨」 판정 · guest cookie 읽기 ─────────────────────────────


def test_registered_mcp_ids_follow_gateway_is_applied():
    mcps = [{"mcp_id": g, "tool_refs": refs} for g, refs in GROUP_REFS.items()]
    assert registered_mcp_ids(Selection(("web-research", "gone"), ("asap-mcp-core/*",)), mcps) == ["web-research"]
    assert registered_mcp_ids(Selection((), ("otp-router/*", "r5-server/*")), mcps) == ["route-accessibility"]
    assert registered_mcp_ids(Selection((), ()), mcps) == []


def test_issued_guest_id_parsing():
    g = str(uuid.uuid4())
    assert _issued_guest_id([f"{GATEWAY_GUEST_COOKIE}={g}; Max-Age=1; Path=/; HttpOnly; SameSite=Lax"]) == g
    assert _issued_guest_id([f"{GATEWAY_GUEST_COOKIE}=nope; Path=/"]) is None
    assert _issued_guest_id(["other=1"]) is None


# ── mock (local · tests) ────────────────────────────────────────────


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
