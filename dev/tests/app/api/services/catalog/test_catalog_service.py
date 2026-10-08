"""catalog_service — logical MCP catalog 규칙 (API 로 관찰).

- 사용자-facing 단위는 Gateway logical MCP(market group)다. 한 MCP 가 여러 server 를 묶을 수 있고, physical server 는 MCP 가 아니다.
- presentation.yaml 은 이름 · 요약 · 분류 · 제공만 덮는다. entry 가 없는 group 도 숨기지 않는다 (Gateway 값 + 분류 「기타」, 뒤에 id 순).
- 개발 중 MCP(planned_mcps.yaml)는 Gateway 에 없는 「development」 카드다 (status · tool_count null). 같은 id 의 group 이 생기면 Gateway 쪽을 쓴다.
- Tool parameter 는 inputSchema 에서 읽은 type 한 줄로 보여 준다 (raw schema 는 내보내지 않는다).
"""

from fastapi.testclient import TestClient

from app.api.integrations.krri_asap.gateway_client import RealGatewayClient
from app.api.main import create_app
from tests.app.api.integrations.krri_asap.gateway_catalog_fake import BASE_URL, TOOLS, FakeGateway


PLANNED = ["gtfs-accessibility-aro", "gtfs-accessibility-university", "nodelink-accessibility-vwl"]


def by_id(cards):
    return {c["mcp_id"]: c for c in cards}


def test_route_accessibility_is_one_r5_card_over_two_servers(client):
    cards = by_id(client.get("/api/mcps").json())
    route = cards["route-accessibility"]
    assert route["display_name"] == "R5 기반 등시선도 MCP"
    assert route["category"] == "교통 접근성 분석"
    assert route["organization"] == "R5 / OTP"
    assert "KRRI" not in route["organization"]
    tools = [t["name"] for t in client.get("/api/mcps/route-accessibility").json()["tools"]]
    assert tools == ["otp_plan_trip", "compute_isochrone"]
    # physical server 는 card 가 아니다
    for server_id in ("otp-router", "r5-server", "web-search", "asap-mcp-core"):
        assert server_id not in cards
        assert client.get(f"/api/mcps/{server_id}").status_code == 404


def test_planned_mcps_are_development_not_offline(client):
    cards = by_id(client.get("/api/mcps").json())
    gtfs = [cards[i] for i in PLANNED[:2]]
    assert {c["display_name"] for c in gtfs} == {"GTFS 기반 접근성 분석 MCP"}
    assert [c["organization"] for c in gtfs] == ["아로", "시립대"]
    node = cards["nodelink-accessibility-vwl"]
    assert (node["display_name"], node["organization"], node["category"]) == (
        "노드링크 기반 접근성 분석 MCP", "VWL", "교통 접근성 분석")
    for mcp_id in PLANNED:
        c = cards[mcp_id]
        assert c["lifecycle"] == "development"
        assert c["status"] is None and c["tool_count"] is None
        assert c["source"] == "planned"
        detail = client.get(f"/api/mcps/{mcp_id}").json()
        assert detail["lifecycle"] == "development" and detail["tools"] == []
        assert client.get(f"/api/mcps/{mcp_id}/demo-questions").json() == []


def test_planned_id_taken_by_gateway_group_uses_gateway(client):
    app = client.app
    live = app.state.gateway.list_mcps()
    app.state.gateway.list_mcps = lambda: [*live, {**live[0], "mcp_id": "gtfs-accessibility-aro", "name": "GTFS 공개"}]
    app.state.gateway.get_mcp = lambda i: next((m for m in app.state.gateway.list_mcps() if m["mcp_id"] == i), None)
    cards = [c for c in client.get("/api/mcps").json() if c["mcp_id"] == "gtfs-accessibility-aro"]
    assert len(cards) == 1 and cards[0]["lifecycle"] == "available"


def test_presentation_override_with_gateway_rich_metadata(client):
    route = client.get("/api/mcps/route-accessibility").json()
    # 이름 · 요약 · 제공은 EASY override
    assert route["display_name"] == "R5 기반 등시선도 MCP"
    assert route["organization"] == "R5 / OTP"
    assert route["summary"].startswith("출발지에서 정한 시간 안에")
    # 상세 본문 · tags 는 Gateway
    assert route["long_description"].startswith("교통 경로, 도달권, 접근성 분석에 필요한")
    assert route["tags"] == ["경로", "접근성", "도달권", "분석"]


# ── live Gateway (가짜 catalog) ──────────────────────────────────────


def test_catalog_joins_presentation_and_falls_back(live_client):
    cards = live_client.get("/api/mcps").json()
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


def test_detail_parameters_from_live_schema(live_client):
    tools = {t["name"]: t for t in live_client.get("/api/mcps/web-research").json()["tools"]}
    params = {p["name"]: p for p in tools["web.search"]["parameters"]}
    assert params["query"]["type"] == "string"
    assert params["domains"]["type"] == "array<string>"
    assert params["cutoffs"]["type"] == "array<integer> | null"
    assert params["odd"]["type"] == "any"
    assert params["odd"]["description"] == "지원 안 하는 schema"
    assert "input_schema" not in tools["web.search"]


def test_organization_falls_back_to_gateway_author(gateway, clock):
    market = [{"id": "other-group", "name": "Other", "serverIds": ["asap-mcp-core"], "toolRefs": ["asap-mcp-core/geo.geocode"],
               "resolvedToolRefs": ["asap-mcp-core/geo.geocode"], "status": "ready", "author": "외부 기관"}]
    app = create_app()
    app.state.gateway = RealGatewayClient(BASE_URL, fetch_json=FakeGateway(TOOLS, market), clock=clock)
    card = next(c for c in TestClient(app).get("/api/mcps").json() if c["mcp_id"] == "other-group")
    assert card["organization"] == "외부 기관"
