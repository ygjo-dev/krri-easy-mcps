"""/api/mcps — 전체 MCP 목록 · 상세 HTTP contract.

- 카드 모양은 {mcp_id, display_name, summary, category, organization, lifecycle, status, tool_count, source} 로 고정이다.
- 상세는 카드 + Gateway group 의 long_description · tags · connected_datasets · updated_at + Tool parameter 목록이다.
- 브라우저 JSON 에는 내부 endpoint · credential · physical server id · toolRefs · Data Library 실행 설정이 없다.
- Gateway 를 못 읽으면 502 (원인은 서버 로그에만), 모르는 id 는 404 다. Catalog · 상세 요청은 Gateway 읽기 한 벌을 같이 쓴다 (cache).
"""

import json

from tests.app.api.integrations.krri_asap.gateway_catalog_fake import BASE_URL
from app.api.main import GATEWAY_UNAVAILABLE_DETAIL


INTERNAL_MARKERS = ("http://", "https://", "host.docker.internal", "Authorization", "token", "password", "secret")

# physical server 는 구현 세부다. 브라우저 JSON 에 싣지 않는다.
PHYSICAL_MARKERS = ("asap-mcp-core", "otp-router", "r5-server", "web-search/", "server_id", "server_ids", "tool_refs",
                    "toolRefs", "serverIds")

PLANNED = ["gtfs-accessibility-aro", "gtfs-accessibility-university", "nodelink-accessibility-vwl"]


def by_id(cards):
    return {c["mcp_id"]: c for c in cards}


def test_catalog_lists_logical_mcps_then_planned(client):
    cards = client.get("/api/mcps").json()
    assert [c["mcp_id"] for c in cards] == [
        "krri-map-location", "krri-railway-network", "krri-admin-boundary", "krri-road-cctv", "krri-ev-chargers",
        "web-research", "route-accessibility", *PLANNED,
    ]
    cctv = by_id(cards)["krri-road-cctv"]
    assert cctv == {
        "mcp_id": "krri-road-cctv", "display_name": "도로/CCTV 조회",
        "summary": "지도 범위 내 도로 CCTV 조회 도구를 제공합니다.", "category": "KRRI 정책현안 분석도구",
        "organization": "KRRI ASAP", "lifecycle": "available", "status": "online", "tool_count": 1, "source": "mock",
    }


def test_card_keeps_its_shape(client):
    # 상세 칸은 목록 카드에 싣지 않는다
    for c in client.get("/api/mcps").json():
        assert set(c) == {"mcp_id", "display_name", "summary", "category", "organization", "lifecycle", "status",
                          "tool_count", "source"}


def test_detail_unknown_mcp_404(client):
    assert client.get("/api/mcps/nope").status_code == 404


def test_catalog_has_no_internal_endpoint_or_credential(client):
    body = json.dumps([client.get("/api/mcps").json()] + [
        client.get(f"/api/mcps/{c['mcp_id']}").json() for c in client.get("/api/mcps").json()
    ])
    for marker in INTERNAL_MARKERS + PHYSICAL_MARKERS:
        assert marker not in body


def test_detail_tools_have_parameters_not_raw_schema(client):
    detail = client.get("/api/mcps/krri-map-location").json()
    geocode = next(t for t in detail["tools"] if t["name"] == "geo.geocode")
    assert geocode["parameters"] == [
        {"name": "query", "type": "string", "required": True, "description": "", "default": None, "enum": None}
    ]
    assert "input_schema" not in geocode


def test_detail_carries_gateway_group_metadata(client):
    ev = client.get("/api/mcps/krri-ev-chargers").json()
    assert ev["long_description"].startswith("한국환경공단 전기자동차 충전소 정보")
    # Gateway 가 tags 에 붙이는 status 값(ready)은 빠진다
    assert ev["tags"] == ["전기차", "충전소", "교통", "지도"]
    assert ev["connected_datasets"] == [{
        "name": "전기차 충전소 현재 화면",
        "description": "현재 지도 화면과 줌에 맞춘 충전소 클러스터·사용 가능 상태",
        "geometry_kind": "point",
    }]
    assert ev["updated_at"] == "2026-09-29T01:18:49.165Z"
    # Tool 은 /api/tools 에서
    assert [t["name"] for t in ev["tools"]] == ["ev.searchStations"]


def test_detail_without_optional_metadata(client):
    web = client.get("/api/mcps/web-research").json()
    assert web["long_description"] == ""
    assert web["connected_datasets"] == []
    assert web["tags"] == ["검색", "웹", "출처"]  # status "error" tag 빠짐


def test_planned_detail_has_no_fake_gateway_metadata(client):
    for mcp_id in PLANNED:
        d = client.get(f"/api/mcps/{mcp_id}").json()
        assert (d["long_description"], d["tags"], d["connected_datasets"], d["updated_at"], d["tools"]) == (
            "", [], [], None, [])
        assert d["status"] is None and d["tool_count"] is None


def test_detail_has_no_dataset_execution_config(client):
    text = json.dumps(client.get("/api/mcps/krri-ev-chargers").json(), ensure_ascii=False)
    for marker in ("toolRef", "tool_ref", "ev.searchstations", "defaultStyle", "pointColor", "input", "mcp_ev_chargers",
                   "version", "rating", "downloads", "features", "contact", "추천"):
        assert marker not in text


# ── live Gateway (가짜 catalog) ──────────────────────────────────────


def test_live_detail_is_404_for_unknown_or_physical_server_id(live_client):
    assert live_client.get("/api/mcps/nope").status_code == 404
    # physical server id 는 MCP id 가 아니다
    assert live_client.get("/api/mcps/asap-mcp-core").status_code == 404


def test_catalog_and_detail_requests_share_one_cached_gateway_read(live_client, gateway, clock):
    live_client.get("/api/mcps")
    live_client.get("/api/mcps/krri-road-cctv")
    live_client.get("/api/mcps/web-research")
    live_client.get("/api/mcps/gtfs-accessibility-aro")
    assert gateway.calls == ["/api/tools", "/api/mcp-market"]
    clock.now += 61
    live_client.get("/api/mcps")
    assert gateway.calls == ["/api/tools", "/api/mcp-market"] * 2


def test_browser_response_hides_internal_values(live_client):
    body = json.dumps(
        [live_client.get("/api/mcps").json()] + [live_client.get(f"/api/mcps/{m}").json() for m in ("krri-road-cctv", "route-accessibility")],
        ensure_ascii=False,
    )
    for marker in (BASE_URL, "gateway.internal", "Authorization", "Bearer", "secret-token", "headers",
                   "EHOSTUNREACH", "192.168.", "lastError", "qualifiedName", "asap-mcp-core", "r5-server",
                   "otp-router", "serverIds", "toolRefs", "server_id", "tool_refs", "resolvedToolRefs", "추천"):
        assert marker not in body


def test_detail_rich_metadata_hides_internal_values(live_client):
    body = live_client.get("/api/mcps/krri-road-cctv").json()
    assert body["tags"] == ["도로", "CCTV"]
    assert body["connected_datasets"][0]["name"] == "CCTV 위치"
    assert body["organization"] == "KRRI ASAP"
    text = json.dumps(body, ensure_ascii=False)
    for marker in ("toolRef", "system/", "adminBoundary", "defaultStyle", "#ff0000", "limit", "mcp_cctv",
                   "rating", "downloads", "features", "version", "추천", "Bearer", "asap-mcp-core", "road.getcctv"):
        assert marker not in text


def test_gateway_failure_is_sanitized(live_client, gateway):
    gateway.fail = ConnectionError(f"boom {BASE_URL}/api/tools Traceback secret-token")
    for path in ("/api/mcps", "/api/mcps/krri-road-cctv", "/api/mcps/gtfs-accessibility-aro"):
        r = live_client.get(path)
        assert r.status_code == 502
        assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}
