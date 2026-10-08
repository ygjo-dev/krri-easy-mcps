"""RealGatewayClient: Gateway GET /api/tools + GET /api/mcp-market 를 가짜 fetch 로 주입해 검증.

fixture 모양은 2026-09-29 실제 Gateway 응답에서 필요한 칸만 줄여 옮겼다.
Portal MCP 하나 = market group 하나. 소속 Tool 은 group 의 resolvedToolRefs 로만 찾는다.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.integrations.krri_asap.gateway_client import GatewayUnavailable, RealGatewayClient, make_gateway_client, normalize_gateway_catalog
from app.api.main import GATEWAY_UNAVAILABLE_DETAIL, create_app

BASE_URL = "http://gateway.internal.example:3000"

TOOLS = [
    {
        "name": "geo.geocode",
        "description": "장소명으로 좌표와 bbox를 반환",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "serverId": "asap-mcp-core",
        "qualifiedName": "asap-mcp-core/geo.geocode",
    },
    {
        "name": "road.getCctv",
        "description": "좌표 범위(bbox) 내의 CCTV 목록을 반환",
        "inputSchema": {"type": "object", "properties": {"minLon": {"type": "number"}}},
        "serverId": "asap-mcp-core",
    },
    {
        "name": "web.search",
        "description": "인터넷에서 최신 공개 정보를 검색합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색어"},
                "domains": {"type": "array", "items": {"type": "string"}},
                "cutoffs": {"anyOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "null"}], "default": None},
                "odd": {"$ref": "#/defs/x", "description": "지원 안 하는 schema"},
            },
        },
        "serverId": "web-search",
    },
    # 이름 없는 항목 · serverId 없는 항목은 버린다.
    {"description": "no name", "serverId": "asap-mcp-core"},
    {"name": "orphan"},
]

MARKET = [
    {"id": "krri-road-cctv", "name": "도로/CCTV 조회", "description": "지도 범위 내 도로 CCTV 조회 도구를 제공합니다.",
     "serverIds": ["asap-mcp-core"], "toolRefs": ["asap-mcp-core/road.getcctv"],
     "resolvedToolRefs": ["asap-mcp-core/road.getcctv"], "status": "ready", "enabled": True, "category": "추천",
     "headers": {"Authorization": "Bearer secret-token"},
     # MCP 상세 metadata (실제 market 모양)
     "longDescription": "선택 위치나 현재 지도 범위 주변의 ITS CCTV 정보를 조회합니다.",
     "tags": ["도로", "CCTV", "도로", " ", 3, "ready"], "author": "KRRI ASAP", "version": "group",
     "updatedAt": "2026-09-29T01:18:49.165Z", "rating": 5, "downloads": 0,
     "features": ["road.getCctv: 현재 지도 bbox 안의 ITS 도로 CCTV 위치를 조회합니다."],
     "layerDatasets": [
         {"id": "mcp_cctv", "name": "CCTV 위치", "description": "현재 화면 CCTV", "geometryKind": "point",
          "toolRef": "asap-mcp-core/road.getcctv", "input": {"limit": 500}, "defaultStyle": {"pointColor": "#ff0000"},
          "geometryJoin": {"toolRef": "system/adminBoundary.searchBoundaries"}},
         {"id": "no-name", "toolRef": "asap-mcp-core/road.getcctv"},
         "not-a-dict",
     ]},
    {"id": "krri-map-location", "name": "지도/위치 검색", "serverIds": ["asap-mcp-core"],
     "toolRefs": ["asap-mcp-core/geo.geocode"], "resolvedToolRefs": ["asap-mcp-core/geo.geocode"], "status": "ready"},
    # multi-server group. otp-router 는 이번 refresh 에 Tool 을 안 냈다.
    {"id": "route-accessibility", "name": "경로/접근성 분석", "serverIds": ["otp-router", "r5-server"],
     "toolRefs": ["otp-router/*", "r5-server/*"], "resolvedToolRefs": ["r5-server/compute_isochrone"],
     "status": "error", "lastError": "connect EHOSTUNREACH 192.168.71.236:8001"},
    {"id": "web-research", "name": "웹 리서치", "serverIds": ["web-search"], "toolRefs": ["web-search/*"],
     "resolvedToolRefs": ["web-search/web.search"], "status": "ready"},
    # group 정의에 안 걸린 server 는 Gateway 가 id=server_id fallback group 을 만든다. 그것도 MCP 하나다.
    {"id": "new-mcp", "name": "New MCP Server", "description": "새로 등록된 서버", "version": "registered",
     "serverIds": ["new-mcp"], "toolRefs": ["new-mcp/*"], "resolvedToolRefs": [], "status": "error"},
    {"id": "off-mcp", "name": "off-mcp", "serverIds": ["off-mcp"], "toolRefs": ["off-mcp/*"], "resolvedToolRefs": [],
     "status": "disabled", "enabled": False},
    {"id": "idle-mcp", "name": "idle-mcp", "serverIds": ["idle-mcp"], "toolRefs": ["idle-mcp/*"], "resolvedToolRefs": [],
     "status": "ready"},
    # id 없는 항목 · 중복 id 는 버린다.
    {"name": "no id"},
    {"id": "krri-map-location", "name": "dup"},
]

TOOLS.append({"name": "compute_isochrone", "description": "등시선", "inputSchema": {}, "serverId": "r5-server"})


class FakeGateway:
    def __init__(self, tools=TOOLS, market=MARKET):
        self.responses = {"/api/tools": tools, "/api/mcp-market": market}
        self.calls: list[str] = []
        self.fail: Exception | None = None

    def __call__(self, path):
        self.calls.append(path)
        if self.fail:
            raise self.fail
        return self.responses[path]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client(gateway, clock):
    app = create_app()
    app.state.gateway = RealGatewayClient(BASE_URL, cache_seconds=60, fetch_json=gateway, clock=clock)
    return TestClient(app)


def by_id(mcps):
    return {m["mcp_id"]: m for m in mcps}


def test_normalize_one_mcp_per_market_group():
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


def test_catalog_joins_presentation_and_falls_back(client):
    cards = client.get("/api/mcps").json()
    ids = [c["mcp_id"] for c in cards]
    # presentation 순서, 그다음 모르는 group 은 id 순, 그다음 개발 중
    assert ids[:4] == ["krri-map-location", "krri-road-cctv", "web-research", "route-accessibility"]
    assert ids[4:7] == ["idle-mcp", "new-mcp", "off-mcp"]
    live = by_id(cards)
    cctv = live["krri-road-cctv"]
    assert cctv["display_name"] == "도로/CCTV 조회"
    assert cctv["category"] == "KRRI 정책현안 분석도구"  # Gateway category(추천)가 아니다
    assert cctv["tool_count"] == 1
    assert cctv["source"] == "live"
    new = live["new-mcp"]
    assert new["display_name"] == "New MCP Server"
    assert new["summary"] == "새로 등록된 서버"
    assert new["category"] == "기타"
    assert new["organization"] == ""
    assert new["status"] == "offline"
    assert live["gtfs-accessibility-aro"]["lifecycle"] == "development"


def test_detail_parameters_from_live_schema(client):
    tools = {t["name"]: t for t in client.get("/api/mcps/web-research").json()["tools"]}
    params = {p["name"]: p for p in tools["web.search"]["parameters"]}
    assert params["query"]["type"] == "string"
    assert params["domains"]["type"] == "array<string>"
    assert params["cutoffs"]["type"] == "array<integer> | null"
    assert params["odd"]["type"] == "any"
    assert params["odd"]["description"] == "지원 안 하는 schema"
    assert "input_schema" not in tools["web.search"]


def test_unknown_mcp_404(client):
    assert client.get("/api/mcps/nope").status_code == 404
    # physical server id 는 MCP id 가 아니다
    assert client.get("/api/mcps/asap-mcp-core").status_code == 404


def test_cache_reuses_one_gateway_read(client, gateway, clock):
    client.get("/api/mcps")
    client.get("/api/mcps/krri-road-cctv")
    client.get("/api/mcps/web-research")
    client.get("/api/mcps/gtfs-accessibility-aro")
    assert gateway.calls == ["/api/tools", "/api/mcp-market"]
    clock.now += 61
    client.get("/api/mcps")
    assert gateway.calls == ["/api/tools", "/api/mcp-market"] * 2


def test_browser_response_hides_internal_values(client):
    body = json.dumps(
        [client.get("/api/mcps").json()] + [client.get(f"/api/mcps/{m}").json() for m in ("krri-road-cctv", "route-accessibility")],
        ensure_ascii=False,
    )
    for marker in (BASE_URL, "gateway.internal", "Authorization", "Bearer", "secret-token", "headers",
                   "EHOSTUNREACH", "192.168.", "lastError", "qualifiedName", "asap-mcp-core", "r5-server",
                   "otp-router", "serverIds", "toolRefs", "server_id", "tool_refs", "resolvedToolRefs", "추천"):
        assert marker not in body


def test_gateway_failure_is_sanitized(client, gateway):
    gateway.fail = ConnectionError(f"boom {BASE_URL}/api/tools Traceback secret-token")
    for path in ("/api/mcps", "/api/mcps/krri-road-cctv", "/api/mcps/gtfs-accessibility-aro"):
        r = client.get(path)
        assert r.status_code == 502
        assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}


def test_gateway_non_list_response_is_failure(gateway, clock):
    gateway.responses["/api/tools"] = {"error": "Internal Server Error"}
    c = RealGatewayClient(BASE_URL, fetch_json=gateway, clock=clock)
    with pytest.raises(GatewayUnavailable):
        c.list_mcps()


def test_failure_is_not_cached(client, gateway):
    gateway.fail = ConnectionError("down")
    assert client.get("/api/mcps").status_code == 502
    gateway.fail = None
    assert client.get("/api/mcps").status_code == 200


def test_real_http_error_becomes_gateway_unavailable():
    # 127.0.0.1:9 (discard) 는 열려 있지 않다. 연결 거부가 GatewayUnavailable 로 모인다.
    with pytest.raises(GatewayUnavailable):
        RealGatewayClient("http://127.0.0.1:9", timeout_seconds=2).list_mcps()


def test_factory_modes():
    assert make_gateway_client("mock").source == "mock"
    assert make_gateway_client("live", BASE_URL).source == "live"
    with pytest.raises(ValueError):
        make_gateway_client("live", "")
    with pytest.raises(ValueError):
        make_gateway_client("nope")


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


def test_detail_rich_metadata_hides_internal_values(client):
    body = client.get("/api/mcps/krri-road-cctv").json()
    assert body["tags"] == ["도로", "CCTV"]
    assert body["connected_datasets"][0]["name"] == "CCTV 위치"
    assert body["organization"] == "KRRI ASAP"
    text = json.dumps(body, ensure_ascii=False)
    for marker in ("toolRef", "system/", "adminBoundary", "defaultStyle", "#ff0000", "limit", "mcp_cctv",
                   "rating", "downloads", "features", "version", "추천", "Bearer", "asap-mcp-core", "road.getcctv"):
        assert marker not in text


def test_organization_falls_back_to_gateway_author(gateway, clock):
    market = [{"id": "other-group", "name": "Other", "serverIds": ["asap-mcp-core"], "toolRefs": ["asap-mcp-core/geo.geocode"],
               "resolvedToolRefs": ["asap-mcp-core/geo.geocode"], "status": "ready", "author": "외부 기관"}]
    app = create_app()
    app.state.gateway = RealGatewayClient(BASE_URL, fetch_json=FakeGateway(TOOLS, market), clock=clock)
    card = next(c for c in TestClient(app).get("/api/mcps").json() if c["mcp_id"] == "other-group")
    assert card["organization"] == "외부 기관"
