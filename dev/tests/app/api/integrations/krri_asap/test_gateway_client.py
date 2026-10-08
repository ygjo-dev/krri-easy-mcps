"""gateway_client — KRRI EASY 가 KRRI_ASAP Gateway 에서 MCP catalog 를 읽는 contract.

읽는 것 (GET 만, credential 없음)
    GET /api/tools        Tool name · description · inputSchema · serverId 의 source
    GET /api/mcp-market   logical MCP(market group) 목록. group 하나 = EASY MCP 하나
쓰지 않는 것
    /api/admin/mcp-servers* (MCP server registry 조회 · 등록 · 수정 · 삭제 · refresh · test) — 부르지 않는다

- 어느 Tool 이 어느 MCP 에 속하는지는 Gateway 가 펼친 resolvedToolRefs 로만 정한다. EASY 가 tool 이름 · wildcard 로 group 을 다시 만들지 않는다.
- status 는 보수적이다: online(모든 server 가 Tool 을 냄) · offline(Tool 없음 + Gateway 가 error/disabled 명시) · unknown(그 밖).
- 내부 칸(serverIds · toolRefs)은 BFF 안 model 에만 두고, credential · lastError · Data Library 실행 설정은 읽지 않는다.
- GET /api/tools 는 Gateway 쪽 tools/list refresh 를 일으키므로 결과를 cache_seconds 동안 재사용한다. 실패는 cache 하지 않는다.
- live 가 실패하면 GatewayUnavailable 이다. mock catalog 로 자동 전환하지 않는다.
"""

import pytest

from app.api.integrations.krri_asap.gateway_client import (
    GatewayUnavailable,
    RealGatewayClient,
    make_gateway_client,
    normalize_gateway_catalog,
)
from tests.app.api.integrations.krri_asap.gateway_catalog_fake import BASE_URL, MARKET, TOOLS, Clock, FakeGateway


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def clock():
    return Clock()


def by_id(mcps):
    return {m["mcp_id"]: m for m in mcps}


# ── Gateway 에 보내는 요청 (실제 HTTP) ───────────────────────────────


def test_live_catalog_read_is_get_tools_then_get_mcp_market_only(recording_gateway):
    """catalog 를 읽을 때 부르는 것은 두 GET 뿐이다. admin MCP server registry 와 어떤 쓰기도 부르지 않는다."""
    recording_gateway.reply("GET", "/api/tools", json_body=TOOLS)
    recording_gateway.reply("GET", "/api/mcp-market", json_body=MARKET)
    client = RealGatewayClient(recording_gateway.url)
    assert [m["mcp_id"] for m in client.list_mcps()][:2] == ["krri-road-cctv", "krri-map-location"]
    client.get_mcp("krri-road-cctv")
    client.get_mcp("nope")
    assert recording_gateway.calls() == [("GET", "/api/tools"), ("GET", "/api/mcp-market")]
    assert not any(path.startswith("/api/admin") for _, path in recording_gateway.calls())


def test_live_catalog_read_carries_no_credentials(recording_gateway):
    """Gateway catalog 는 ANYONE 권한이다. Authorization · cookie 를 싣지 않는다 (BFF 에 ADMIN credential 이 없다)."""
    recording_gateway.reply("GET", "/api/tools", json_body=TOOLS)
    recording_gateway.reply("GET", "/api/mcp-market", json_body=MARKET)
    RealGatewayClient(recording_gateway.url).list_mcps()
    for request in recording_gateway.requests:
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert request.headers["accept"] == "application/json"


def test_live_gateway_error_raises_instead_of_falling_back_to_mock(recording_gateway):
    recording_gateway.reply("GET", "/api/tools", status=500, json_body={"error": "Internal Server Error"})
    live = make_gateway_client("live", recording_gateway.url, 0)
    assert live.source == "live"
    with pytest.raises(GatewayUnavailable):
        live.list_mcps()


def test_real_http_error_becomes_gateway_unavailable():
    # 127.0.0.1:9 (discard) 는 열려 있지 않다. 연결 거부가 GatewayUnavailable 로 모인다.
    with pytest.raises(GatewayUnavailable):
        RealGatewayClient("http://127.0.0.1:9", timeout_seconds=2).list_mcps()


def test_gateway_non_list_response_is_failure(gateway, clock):
    gateway.responses["/api/tools"] = {"error": "Internal Server Error"}
    c = RealGatewayClient(BASE_URL, fetch_json=gateway, clock=clock)
    with pytest.raises(GatewayUnavailable):
        c.list_mcps()


def test_factory_requires_base_url_for_live_and_rejects_unknown_mode():
    assert make_gateway_client("mock").source == "mock"
    assert make_gateway_client("live", BASE_URL).source == "live"
    with pytest.raises(ValueError):
        make_gateway_client("live", "")
    with pytest.raises(ValueError):
        make_gateway_client("nope")


# ── cache ────────────────────────────────────────────────────────────


def test_live_catalog_is_reused_for_cache_seconds(gateway, clock):
    client = RealGatewayClient(BASE_URL, cache_seconds=60, fetch_json=gateway, clock=clock)
    client.list_mcps()
    clock.now += 59
    client.get_mcp("krri-road-cctv")
    assert gateway.calls == ["/api/tools", "/api/mcp-market"]
    clock.now += 2
    client.list_mcps()
    assert gateway.calls == ["/api/tools", "/api/mcp-market"] * 2


def test_failure_is_not_cached(gateway, clock):
    client = RealGatewayClient(BASE_URL, fetch_json=gateway, clock=clock)
    gateway.fail = ConnectionError("down")
    with pytest.raises(GatewayUnavailable):
        client.list_mcps()
    gateway.fail = None
    assert client.list_mcps()


# ── Gateway 응답 → logical MCP model ─────────────────────────────────


def test_one_logical_mcp_per_gateway_market_group():
    mcps = by_id(normalize_gateway_catalog(TOOLS, MARKET))
    assert list(mcps) == ["krri-road-cctv", "krri-map-location", "route-accessibility", "web-research",
                          "new-mcp", "off-mcp", "idle-mcp"]
    # 한 server(asap-mcp-core) 의 Tool 이 group 마다 나뉜다
    assert [t["name"] for t in mcps["krri-road-cctv"]["tools"]] == ["road.getCctv"]
    assert [t["name"] for t in mcps["krri-map-location"]["tools"]] == ["geo.geocode"]
    assert mcps["krri-map-location"]["tools"][0]["input_schema"]["required"] == ["query"]
    # physical 값은 BFF 안에만
    route = mcps["route-accessibility"]
    assert route["server_ids"] == ["otp-router", "r5-server"]
    assert route["tool_refs"] == ["otp-router/*", "r5-server/*"]
    assert mcps["off-mcp"]["enabled"] is False and mcps["idle-mcp"]["enabled"] is True


def test_group_tools_come_only_from_resolved_refs():
    # Gateway 가 펼쳐 주지 않은 Tool 은 group 에 넣지 않는다 (Portal 이 toolRefs wildcard 를 다시 풀지 않는다).
    market = [{"id": "g", "serverIds": ["asap-mcp-core"], "toolRefs": ["asap-mcp-core/*"], "resolvedToolRefs": []}]
    assert normalize_gateway_catalog(TOOLS, market)[0]["tools"] == []


def test_status_is_conservative():
    mcps = by_id(normalize_gateway_catalog(TOOLS, MARKET))
    assert mcps["krri-road-cctv"]["status"] == "online"
    assert mcps["web-research"]["status"] == "online"
    # 일부 server 만 응답한 multi-server group 은 online 도 offline 도 아니다
    assert mcps["route-accessibility"]["status"] == "unknown"
    # Tool 이 없고 Gateway 가 error / disabled 라고 명시
    assert mcps["new-mcp"]["status"] == "offline"
    assert mcps["off-mcp"]["status"] == "offline"
    # ready 라고 적혀 있어도 이번 결과에 tool 이 없으면 근거 부족
    assert mcps["idle-mcp"]["status"] == "unknown"


def test_normalize_keeps_only_readable_group_metadata():
    cctv = by_id(normalize_gateway_catalog(TOOLS, MARKET))["krri-road-cctv"]
    assert cctv["long_description"] == "선택 위치나 현재 지도 범위 주변의 ITS CCTV 정보를 조회합니다."
    assert cctv["tags"] == ["도로", "CCTV"]  # 중복 · 빈 값 · 문자열 아닌 값 · status tag 제거
    assert cctv["author"] == "KRRI ASAP"
    assert cctv["updated_at"] == "2026-09-29T01:18:49.165Z"
    assert cctv["connected_datasets"] == [{"name": "CCTV 위치", "description": "현재 화면 CCTV", "geometry_kind": "point"}]
    # metadata 가 없는 group
    web = by_id(normalize_gateway_catalog(TOOLS, MARKET))["web-research"]
    assert (web["long_description"], web["tags"], web["author"], web["updated_at"], web["connected_datasets"]) == (
        "", [], "", None, [])
