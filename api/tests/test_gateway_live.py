"""RealGatewayClient: Gateway GET /api/tools + GET /api/mcp-market 를 가짜 fetch 로 주입해 검증.

fixture 모양은 2026-09-22 실제 Gateway 응답에서 필요한 칸만 줄여 옮겼다.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.clients.gateway import GatewayUnavailable, RealGatewayClient, make_gateway_client, normalize_gateway_catalog
from app.main import GATEWAY_UNAVAILABLE_DETAIL, create_app

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
    {"id": "krri-road-cctv", "name": "도로/CCTV 조회", "serverIds": ["asap-mcp-core"], "status": "ready",
     "headers": {"Authorization": "Bearer secret-token"}},
    {"id": "route-accessibility", "name": "경로/접근성 분석", "serverIds": ["otp-router", "r5-server"],
     "status": "error", "lastError": "connect EHOSTUNREACH 192.168.71.236:8001"},
    {"id": "web-research", "name": "웹 리서치", "serverIds": ["web-search"], "status": "ready"},
    # group 정의에 안 걸린 server 는 Gateway 가 id=server_id fallback group 을 만든다.
    {"id": "new-mcp", "name": "New MCP Server", "description": "새로 등록된 서버", "version": "registered",
     "serverIds": ["new-mcp"], "status": "error"},
    {"id": "off-mcp", "name": "off-mcp", "serverIds": ["off-mcp"], "status": "disabled"},
    {"id": "idle-mcp", "name": "idle-mcp", "serverIds": ["idle-mcp"], "status": "ready"},
]


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


def by_id(servers):
    return {s["server_id"]: s for s in servers}


def test_normalize_discovers_servers_from_tools_and_market():
    servers = by_id(normalize_gateway_catalog(TOOLS, MARKET))
    assert sorted(servers) == ["asap-mcp-core", "idle-mcp", "new-mcp", "off-mcp", "otp-router", "r5-server", "web-search"]
    assert [t["name"] for t in servers["asap-mcp-core"]["tools"]] == ["geo.geocode", "road.getCctv"]
    assert servers["asap-mcp-core"]["tools"][0]["input_schema"]["required"] == ["query"]
    assert servers["otp-router"]["tools"] == []


def test_status_is_conservative():
    servers = by_id(normalize_gateway_catalog(TOOLS, MARKET))
    # tools/list 가 방금 성공한 server
    assert servers["asap-mcp-core"]["status"] == "online"
    assert servers["web-search"]["status"] == "online"
    # multi-server group 의 error 를 개별 server 로 옮기지 않는다
    assert servers["otp-router"]["status"] == "unknown"
    assert servers["r5-server"]["status"] == "unknown"
    # single-server group 이 명시한 error / disabled
    assert servers["new-mcp"]["status"] == "offline"
    assert servers["off-mcp"]["status"] == "offline"
    # ready 라고 적혀 있어도 이번 결과에 tool 이 없으면 근거 부족
    assert servers["idle-mcp"]["status"] == "unknown"


def test_technical_name_only_from_server_fallback_group():
    servers = by_id(normalize_gateway_catalog(TOOLS, MARKET))
    assert servers["new-mcp"]["name"] == "New MCP Server"
    assert servers["new-mcp"]["description"] == "새로 등록된 서버"
    # group name(도로/CCTV 조회)은 server 이름이 아니다
    assert servers["asap-mcp-core"]["name"] == "asap-mcp-core"


def test_catalog_joins_presentation_and_falls_back(client):
    cards = by_id(client.get("/api/mcps").json())
    core = cards["asap-mcp-core"]
    assert core["display_name"] == "ASAP Core MCP"
    assert core["technical_name"] == "asap-mcp-core"
    assert core["category"] == "공간정보"
    assert core["tool_count"] == 2
    assert core["source"] == "live"
    new = cards["new-mcp"]
    assert new["display_name"] == "New MCP Server"
    assert new["summary"] == "새로 등록된 서버"
    assert new["category"] == "기타"
    assert new["organization"] == ""
    assert new["status"] == "offline"


def test_detail_parameters_from_live_schema(client):
    tools = {t["name"]: t for t in client.get("/api/mcps/web-search").json()["tools"]}
    params = {p["name"]: p for p in tools["web.search"]["parameters"]}
    assert params["query"]["type"] == "string"
    assert params["domains"]["type"] == "array<string>"
    assert params["cutoffs"]["type"] == "array<integer> | null"
    assert params["odd"]["type"] == "any"
    assert params["odd"]["description"] == "지원 안 하는 schema"
    assert "input_schema" not in tools["web.search"]


def test_unknown_server_404(client):
    assert client.get("/api/mcps/nope").status_code == 404


def test_cache_reuses_one_gateway_read(client, gateway, clock):
    client.get("/api/mcps")
    client.get("/api/mcps/asap-mcp-core")
    client.get("/api/mcps/web-search")
    assert gateway.calls == ["/api/tools", "/api/mcp-market"]
    clock.now += 61
    client.get("/api/mcps")
    assert gateway.calls == ["/api/tools", "/api/mcp-market"] * 2


def test_browser_response_hides_internal_values(client):
    body = json.dumps(
        [client.get("/api/mcps").json()] + [client.get(f"/api/mcps/{s}").json() for s in ("asap-mcp-core", "otp-router")],
        ensure_ascii=False,
    )
    for marker in (BASE_URL, "gateway.internal", "Authorization", "Bearer", "secret-token", "headers",
                   "EHOSTUNREACH", "192.168.", "lastError", "qualifiedName"):
        assert marker not in body


def test_gateway_failure_is_sanitized(client, gateway):
    gateway.fail = ConnectionError(f"boom {BASE_URL}/api/tools Traceback secret-token")
    for path in ("/api/mcps", "/api/mcps/asap-mcp-core"):
        r = client.get(path)
        assert r.status_code == 502
        assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}


def test_gateway_non_list_response_is_failure(gateway, clock):
    gateway.responses["/api/tools"] = {"error": "Internal Server Error"}
    c = RealGatewayClient(BASE_URL, fetch_json=gateway, clock=clock)
    with pytest.raises(GatewayUnavailable):
        c.list_servers()


def test_failure_is_not_cached(client, gateway):
    gateway.fail = ConnectionError("down")
    assert client.get("/api/mcps").status_code == 502
    gateway.fail = None
    assert client.get("/api/mcps").status_code == 200


def test_real_http_error_becomes_gateway_unavailable():
    # 127.0.0.1:9 (discard) 는 열려 있지 않다. 연결 거부가 GatewayUnavailable 로 모인다.
    with pytest.raises(GatewayUnavailable):
        RealGatewayClient("http://127.0.0.1:9", timeout_seconds=2).list_servers()


def test_factory_modes():
    assert make_gateway_client("mock").source == "mock"
    assert make_gateway_client("live", BASE_URL).source == "live"
    with pytest.raises(ValueError):
        make_gateway_client("live", "")
    with pytest.raises(ValueError):
        make_gateway_client("nope")
