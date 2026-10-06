import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import load_settings

TRUSTED_KEYS = ("recipe_id", "expected_recipe_id", "expected_tools", "expected_mcp_ids", "semantic_values", "context_preset")
INTERNAL_MARKERS = ("http://", "https://", "host.docker.internal", "Authorization", "token", "password", "secret")
# physical server 는 구현 세부다. 브라우저 JSON 에 싣지 않는다.
PHYSICAL_MARKERS = ("asap-mcp-core", "otp-router", "r5-server", "web-search/", "server_id", "server_ids", "tool_refs",
                    "toolRefs", "serverIds")
PLANNED = ["gtfs-accessibility-aro", "gtfs-accessibility-university", "nodelink-accessibility-vwl"]


@pytest.fixture
def client():
    return TestClient(create_app())


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "gateway": "mock", "agentic_ai": "mock"}


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


def test_web_search_card(client):
    web = by_id(client.get("/api/mcps").json())["web-research"]
    assert web["display_name"] == "Web Search MCP"
    assert web["category"] == "KRRI 정책현안 분석도구"


def test_every_krri_group_has_policy_category(client):
    for c in client.get("/api/mcps").json():
        if c["mcp_id"].startswith("krri-"):
            assert c["category"] == "KRRI 정책현안 분석도구", c


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


def test_detail_unknown_mcp_404(client):
    assert client.get("/api/mcps/nope").status_code == 404


def test_demo_questions_belong_to_one_logical_mcp_each(client):
    owners = {
        "krri-map-location": ["iksan-station-location", "cheongju-airport-location"],
        "krri-railway-network": ["cheonan-station-lines", "gyeongbu-line-section", "chungbuk-line-stations"],
        "krri-admin-boundary": ["nonsan-boundary", "busan-station-district"],
        "krri-road-cctv": ["suwon-station-cctv"],
        "web-research": ["web-rail-policy-news", "web-fetch-krri-home"],
    }
    for mcp_id, expected in owners.items():
        questions = client.get(f"/api/mcps/{mcp_id}/demo-questions").json()
        assert [q["question_id"] for q in questions] == expected
        for q in questions:
            assert set(q) == {"question_id", "display_text", "runnable"}
    # agentic_ai 에 recipe 가 없는 MCP 의 질문은 예시다
    assert {q["runnable"] for q in client.get("/api/mcps/web-research/demo-questions").json()} == {False}
    assert {q["runnable"] for q in client.get("/api/mcps/krri-road-cctv/demo-questions").json()} == {True}


def test_question_expectations_match_gateway_groups(client):
    """expected_mcp_ids 는 expected_tools 를 가진 group 과 같아야 한다 (실제 Gateway catalog snapshot 기준)."""
    snapshot = json.loads((Path(__file__).parent / "fixtures" / "gateway_catalog_20261002.json").read_text())
    for q in client.app.state.demo_questions.values():
        owners = {m["mcp_id"] for ref in q.expected_tools for m in snapshot["mcps"] if ref in m["tools"]}
        assert q.expected_tools and owners == set(q.expected_mcp_ids), q.question_id


def test_disabled_question_hidden_and_not_executable(tmp_path, monkeypatch):
    settings = load_settings()
    (tmp_path / "presentation.yaml").write_text((settings.config_dir / "presentation.yaml").read_text())
    (tmp_path / "demo_questions.yaml").write_text(
        "questions:\n"
        "  - {question_id: off, mcp_id: krri-map-location, display_text: x, enabled: false}\n"
    )
    (tmp_path / "planned_mcps.yaml").write_text((settings.config_dir / "planned_mcps.yaml").read_text())
    monkeypatch.setenv("KEM_CONFIG_DIR", str(tmp_path))
    c = TestClient(create_app())
    assert c.get("/api/mcps/krri-map-location/demo-questions").json() == []
    assert c.post("/api/demo/questions/off/execute").status_code == 404


def test_execute_mock_returns_trace_and_answer(client):
    r = client.post("/api/demo/questions/suwon-station-cctv/execute")
    assert r.status_code == 200
    body = r.json()
    assert body["resolve_status"] == "SELECT"
    assert body["matches_expected_recipe"] is True
    assert body["matches_expected_tools"] is True
    assert [(s["tool"], s["status"]) for s in body["steps"]] == [("geo.geocode", "success"), ("road.getCctv", "success")]
    assert body["steps"][0]["request"] == {"query": "수원역"}
    # 한 질문이 두 logical MCP 의 Tool 을 쓴다. 단계마다 그 Tool 의 MCP 이름.
    assert [s["mcp_name"] for s in body["steps"]] == ["지도/위치 검색", "도로/CCTV 조회"]
    assert "CCTV" in body["answer"]
    assert body["map_command_count"] == 1
    assert body["limitations"]


def test_every_enabled_question_resolves_as_expected(client):
    runnable = [q for q in client.app.state.demo_questions.values() if q.runnable]
    assert len(runnable) >= 14
    for q in runnable:
        body = client.post(f"/api/demo/questions/{q.question_id}/execute").json()
        assert body["matches_expected_recipe"] is True, q
        assert body["matches_expected_tools"] is True, q


def test_example_only_questions_are_not_executed(client):
    examples = [q for q in client.app.state.demo_questions.values() if not q.runnable]
    assert examples
    for q in examples:
        r = client.post(f"/api/demo/questions/{q.question_id}/execute")
        assert r.status_code == 409 and "예시" in r.json()["detail"], q.question_id


def test_execute_response_has_no_trusted_metadata_or_commands(client):
    body = client.post("/api/demo/questions/busan-station-district/execute").json()
    text = json.dumps(body, ensure_ascii=False)
    for key in TRUSTED_KEYS:
        assert f'"{key}"' not in text
    assert "recipe_034" not in text
    assert "commands" not in body


def test_execute_unknown_question_404(client):
    assert client.post("/api/demo/questions/nope/execute").status_code == 404


def test_step_labels_are_optional_when_gateway_is_down(client):
    from app.clients.gateway import GatewayUnavailable

    def down():
        raise GatewayUnavailable("down")

    client.app.state.gateway.list_mcps = down
    body = client.post("/api/demo/questions/busan-station-district/execute").json()
    assert body["matches_expected_tools"] is True
    assert [s["mcp_name"] for s in body["steps"]] == [None, None]


@pytest.mark.parametrize("yaml_text,error", [
    ("questions:\n  - {question_id: q, mcp_id: gtfs-accessibility-aro, display_text: x}\n", "in development"),
    ("questions:\n  - {question_id: q, mcp_id: krri-road-cctv, display_text: x, expected_mcp_ids: [krri-map-location]}\n",
     "not in expected_mcp_ids"),
])
def test_invalid_question_ownership_fails_startup(tmp_path, monkeypatch, yaml_text, error):
    settings = load_settings()
    for name in ("presentation.yaml", "planned_mcps.yaml"):
        (tmp_path / name).write_text((settings.config_dir / name).read_text())
    (tmp_path / "demo_questions.yaml").write_text(yaml_text)
    monkeypatch.setenv("KEM_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ValueError, match=error):
        create_app()


# ── 상세: Gateway group metadata ─────────────────────────────────────


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


def test_presentation_override_with_gateway_rich_metadata(client):
    route = client.get("/api/mcps/route-accessibility").json()
    # 이름 · 요약 · 제공은 EASY override
    assert route["display_name"] == "R5 기반 등시선도 MCP"
    assert route["organization"] == "R5 / OTP"
    assert route["summary"].startswith("출발지에서 정한 시간 안에")
    # 상세 본문 · tags 는 Gateway
    assert route["long_description"].startswith("교통 경로, 도달권, 접근성 분석에 필요한")
    assert route["tags"] == ["경로", "접근성", "도달권", "분석"]


def test_planned_detail_has_no_fake_gateway_metadata(client):
    for mcp_id in PLANNED:
        d = client.get(f"/api/mcps/{mcp_id}").json()
        assert (d["long_description"], d["tags"], d["connected_datasets"], d["updated_at"], d["tools"]) == (
            "", [], [], None, [])
        assert d["status"] is None and d["tool_count"] is None


def test_card_keeps_its_shape(client):
    # 상세 칸은 목록 카드에 싣지 않는다
    for c in client.get("/api/mcps").json():
        assert set(c) == {"mcp_id", "display_name", "summary", "category", "organization", "lifecycle", "status",
                          "tool_count", "source"}


def test_detail_has_no_dataset_execution_config(client):
    text = json.dumps(client.get("/api/mcps/krri-ev-chargers").json(), ensure_ascii=False)
    for marker in ("toolRef", "tool_ref", "ev.searchstations", "defaultStyle", "pointColor", "input", "mcp_ev_chargers",
                   "version", "rating", "downloads", "features", "contact", "추천"):
        assert marker not in text
