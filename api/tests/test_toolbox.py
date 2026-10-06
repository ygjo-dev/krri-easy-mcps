"""내 MCP: Browser → BFF → Gateway /api/me/mcp-selections. 단위는 logical MCP(= Gateway group).

FakeSelectionGateway 는 Gateway mcpMarket.service 의 정규화를 필요한 만큼 흉내 낸다:
groupIds 는 아는 group 만, toolRefs = group 의 정의 refs + 명시 refs 중 등록된 server 것만 (소문자 · 중복 제거),
cookie 가 없으면 guest UUID 를 새로 만들어 Set-Cookie 로 준다.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.clients.gateway import GatewayUnavailable, RealGatewayClient
from app.clients.selection import (
    GATEWAY_GUEST_COOKIE,
    RealSelectionClient,
    Selection,
    _issued_guest_id,
    registered_mcp_ids,
)
from app.main import GATEWAY_UNAVAILABLE_DETAIL, create_app
from app.routes.toolbox import GUEST_COOKIE, IN_DEVELOPMENT_DETAIL, LEGACY_GUEST_COOKIE, NOT_APPLIED_DETAIL

BASE_URL = "http://gateway.internal.example:3000"

TOOLS = [
    {"name": "geo.geocode", "serverId": "asap-mcp-core", "inputSchema": {}},
    {"name": "road.getCctv", "serverId": "asap-mcp-core", "inputSchema": {}},
    {"name": "otp_plan_trip", "serverId": "otp-router", "inputSchema": {}},
    {"name": "compute_isochrone", "serverId": "r5-server", "inputSchema": {}},
    {"name": "web.search", "serverId": "web-search", "inputSchema": {}},
]
GROUP_REFS = {
    "krri-map-location": ["asap-mcp-core/geo.geocode"],
    "krri-road-cctv": ["asap-mcp-core/road.getcctv"],
    "route-accessibility": ["otp-router/*", "r5-server/*"],
    "web-research": ["web-search/*"],
}
RESOLVED = {
    "krri-map-location": ["asap-mcp-core/geo.geocode"],
    "krri-road-cctv": ["asap-mcp-core/road.getcctv"],
    "route-accessibility": ["otp-router/otp_plan_trip", "r5-server/compute_isochrone"],
    "web-research": ["web-search/web.search"],
}
MARKET = [
    {"id": g, "name": g, "serverIds": sorted({r.split("/")[0] for r in refs}), "toolRefs": refs,
     "resolvedToolRefs": RESOLVED[g], "status": "ready"}
    for g, refs in GROUP_REFS.items()
]
AVAILABLE = {"asap-mcp-core", "otp-router", "r5-server", "web-search"}


class FakeSelectionGateway:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.calls: list[tuple[str, str | None]] = []
        self.bodies: list[dict] = []
        self.fail: Exception | None = None
        self.drop_group: str | None = None  # Gateway 가 이 group 을 조용히 버리는 경우 (예: disabled)

    def seed(self, group_ids, tool_refs) -> str:
        guest = str(uuid.uuid4())
        self.store[guest] = self._normalize(group_ids, tool_refs)
        return guest

    def _normalize(self, group_ids, tool_refs):
        groups = [g for g in dict.fromkeys(group_ids) if g in GROUP_REFS and g != self.drop_group]
        refs = [r.lower() for g in groups for r in GROUP_REFS[g]] + [r.lower() for r in tool_refs]
        refs = [r for r in dict.fromkeys(refs) if r.split("/")[0] in AVAILABLE]
        return {"groupIds": groups, "serverIds": sorted({r.split("/")[0] for r in refs}), "toolRefs": refs}

    def __call__(self, method, path, body, cookie):
        assert path == "/api/me/mcp-selections"
        guest = cookie.split("=", 1)[1] if cookie else None
        self.calls.append((method, guest))
        if self.fail:
            raise self.fail
        set_cookies = []
        if not guest:
            guest = str(uuid.uuid4())
            set_cookies = [f"{GATEWAY_GUEST_COOKIE}={guest}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax"]
        if method == "PUT":
            assert set(body) <= {"groupIds", "toolRefs", "serverIds"}
            self.bodies.append(body)
            self.store[guest] = self._normalize(body.get("groupIds", []), body.get("toolRefs", []))
        return self.store.get(guest, {"groupIds": [], "serverIds": [], "toolRefs": []}), set_cookies

    def puts(self):
        return [c for c in self.calls if c[0] == "PUT"]


@pytest.fixture
def gw():
    return FakeSelectionGateway()


@pytest.fixture
def app(gw):
    app = create_app()
    responses = {"/api/tools": TOOLS, "/api/mcp-market": MARKET}
    app.state.gateway = RealGatewayClient(BASE_URL, fetch_json=responses.__getitem__)
    app.state.selection = RealSelectionClient(BASE_URL, transport=gw)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def seeded_client(app, gw, group_ids, tool_refs):
    c = TestClient(app)
    c.cookies.set(GUEST_COOKIE, gw.seed(group_ids, tool_refs))
    return c


def test_get_empty_toolbox_issues_canonical_gateway_cookie(client, gw):
    r = client.get("/api/toolbox")
    assert r.status_code == 200
    assert r.json() == {"mcp_ids": [], "mcps": []}
    [header] = r.headers.get_list("set-cookie")
    # ASAP-web 이 Gateway 에서 받는 것과 같은 cookie: 이름 · Path=/ · HttpOnly · SameSite=Lax · 1년
    assert GUEST_COOKIE == GATEWAY_GUEST_COOKIE == "asap_mcp_guest"
    issued = gw.calls[0]
    assert issued == ("GET", None)
    guest = client.cookies.get(GUEST_COOKIE)
    assert header.startswith(f"asap_mcp_guest={guest};")
    assert "; Path=/;" in header + ";" and "Path=/api" not in header
    assert "HttpOnly" in header and "samesite=lax" in header.lower() and "Max-Age=31536000" in header
    assert "Secure" not in header


def test_canonical_cookie_is_secure_over_https(app, gw):
    r = TestClient(app, base_url="https://testserver").get("/api/toolbox")
    assert "Secure" in r.headers["set-cookie"]


def _cookie_headers(r, name):
    return [h for h in r.headers.get_list("set-cookie") if h.startswith(f"{name}=")]


def test_existing_canonical_cookie_is_used_as_is(app, gw):
    """ASAP-web 이 이미 받아 둔 guest 를 그대로 Gateway 에 싣는다. 새 guest · 새 cookie 없음."""
    guest = gw.seed(["krri-road-cctv"], [])
    c = TestClient(app)
    c.cookies.set("asap_mcp_guest", guest)
    r = c.get("/api/toolbox")
    assert r.json()["mcp_ids"] == ["krri-road-cctv"]
    assert gw.calls == [("GET", guest)]
    assert r.headers.get_list("set-cookie") == []


def test_legacy_portal_cookie_is_promoted_with_same_uuid(app, gw):
    """예전 Portal 사용자: 같은 UUID(= 같은 Gateway 행)를 canonical 로 올리고 legacy(Path=/api) 를 지운다."""
    guest = gw.seed(["krri-map-location"], [])
    c = TestClient(app)
    c.cookies.set(LEGACY_GUEST_COOKIE, guest)
    r = c.get("/api/toolbox")
    assert r.json()["mcp_ids"] == ["krri-map-location"]
    assert gw.calls == [("GET", guest)]
    [canonical] = _cookie_headers(r, "asap_mcp_guest")
    assert canonical.startswith(f"asap_mcp_guest={guest};") and "Path=/;" in canonical + ";" and "HttpOnly" in canonical
    [dropped] = _cookie_headers(r, LEGACY_GUEST_COOKIE)
    assert "Path=/api" in dropped and ("Max-Age=0" in dropped or "expires=" in dropped.lower())
    # 다음 요청부터는 canonical 만으로 같은 selection
    c2 = TestClient(app)
    c2.cookies.set("asap_mcp_guest", guest)
    assert c2.post("/api/toolbox/krri-road-cctv").json()["mcp_ids"] == ["krri-map-location", "krri-road-cctv"]
    assert gw.calls[-1] == ("PUT", guest)


def test_canonical_wins_over_legacy(app, gw):
    canonical = gw.seed(["krri-road-cctv"], [])
    legacy = gw.seed(["web-research"], [])
    c = TestClient(app)
    c.cookies.set("asap_mcp_guest", canonical)
    c.cookies.set(LEGACY_GUEST_COOKIE, legacy)
    r = c.get("/api/toolbox")
    assert r.json()["mcp_ids"] == ["krri-road-cctv"]
    assert gw.calls == [("GET", canonical)]
    assert _cookie_headers(r, "asap_mcp_guest") == []
    [dropped] = _cookie_headers(r, LEGACY_GUEST_COOKIE)
    assert "Path=/api" in dropped


@pytest.mark.parametrize("bad", ["not-a-uuid", "00000000-0000-1000-8000-000000000000", "guest:x; asap_mcp_guest=evil"])
def test_invalid_canonical_is_not_authoritative(app, gw, bad):
    c = TestClient(app)
    c.cookies.set("asap_mcp_guest", bad)
    r = c.get("/api/toolbox")
    assert gw.calls == [("GET", None)]
    [issued] = _cookie_headers(r, "asap_mcp_guest")
    assert bad not in issued


def test_invalid_canonical_falls_back_to_valid_legacy(app, gw):
    legacy = gw.seed(["krri-road-cctv"], [])
    c = TestClient(app)
    c.cookies.set("asap_mcp_guest", "not-a-uuid")
    c.cookies.set(LEGACY_GUEST_COOKIE, legacy)
    r = c.get("/api/toolbox")
    assert gw.calls == [("GET", legacy)]
    assert _cookie_headers(r, "asap_mcp_guest")[0].startswith(f"asap_mcp_guest={legacy};")


def test_invalid_legacy_is_not_promoted(app, gw):
    c = TestClient(app)
    c.cookies.set(LEGACY_GUEST_COOKIE, "nope")
    r = c.get("/api/toolbox")
    assert gw.calls == [("GET", None)]
    [issued] = _cookie_headers(r, "asap_mcp_guest")
    assert "nope" not in issued
    assert _cookie_headers(r, LEGACY_GUEST_COOKIE)  # 쓸모없는 legacy 도 지운다


def test_migration_responses_never_carry_the_uuid_in_json(app, gw):
    guest = gw.seed(["route-accessibility"], [])
    c = TestClient(app)
    c.cookies.set(LEGACY_GUEST_COOKIE, guest)
    bodies = [c.get("/api/toolbox").text, c.post("/api/toolbox/krri-road-cctv").text,
              c.delete("/api/toolbox/route-accessibility").text]
    for text in bodies:
        assert guest not in text and "asap_mcp_guest" not in text and LEGACY_GUEST_COOKIE not in text


def test_failed_gateway_call_keeps_legacy_cookie(app, gw):
    """이행은 성공 응답에서만 일어난다. Gateway 가 실패하면 cookie 를 건드리지 않는다."""
    guest = gw.seed([], [])
    gw.fail = GatewayUnavailable("down")
    c = TestClient(app)
    c.cookies.set(LEGACY_GUEST_COOKIE, guest)
    r = c.get("/api/toolbox")
    assert r.status_code == 502
    assert r.headers.get_list("set-cookie") == []


def test_add_get_remove_writes_group_id(client, gw):
    client.get("/api/toolbox")
    guest = client.cookies.get(GUEST_COOKIE)
    body = client.post("/api/toolbox/krri-road-cctv").json()
    assert body["mcp_ids"] == ["krri-road-cctv"]
    assert body["mcps"][0]["display_name"] == "krri-road-cctv"
    assert body["mcps"][0]["category"] == "KRRI 정책현안 분석도구"
    assert body["mcps"][0]["tool_count"] == 1
    assert client.get("/api/toolbox").json()["mcp_ids"] == ["krri-road-cctv"]
    # Gateway selection 의 canonical 값은 groupId. toolRefs 는 Gateway 가 group 에서 펼친 것뿐
    assert gw.store[guest]["groupIds"] == ["krri-road-cctv"]
    assert gw.store[guest]["toolRefs"] == ["asap-mcp-core/road.getcctv"]
    assert client.delete("/api/toolbox/krri-road-cctv").json()["mcp_ids"] == []
    assert gw.store[guest] == {"groupIds": [], "serverIds": [], "toolRefs": []}
    # 첫 GET 뒤로는 모든 Gateway 호출이 같은 guest 로 갔다
    assert {g for _, g in gw.calls[1:]} == {guest}
    # 다른 브라우저(cookie 없음)는 다른 내 MCP
    assert TestClient(client.app).get("/api/toolbox").json()["mcp_ids"] == []


def test_put_body_is_group_ids_only_like_asap_web(client, gw):
    client.post("/api/toolbox/krri-map-location")
    client.post("/api/toolbox/web-research")
    client.delete("/api/toolbox/krri-map-location")
    assert gw.bodies == [
        {"groupIds": ["krri-map-location"]},
        {"groupIds": ["krri-map-location", "web-research"]},
        {"groupIds": ["web-research"]},
    ]


def test_same_server_groups_are_independent(client, gw):
    # 같은 physical server(asap-mcp-core) 의 두 logical MCP 는 따로 등록 · 해제된다
    client.post("/api/toolbox/krri-map-location")
    assert client.post("/api/toolbox/krri-road-cctv").json()["mcp_ids"] == ["krri-map-location", "krri-road-cctv"]
    assert client.delete("/api/toolbox/krri-map-location").json()["mcp_ids"] == ["krri-road-cctv"]


def test_first_add_without_cookie_uses_issued_guest_for_put(client, gw):
    r = client.post("/api/toolbox/web-research")
    assert r.json()["mcp_ids"] == ["web-research"]
    guest = client.cookies.get(GUEST_COOKIE)
    assert gw.calls == [("GET", None), ("PUT", guest)]


@pytest.mark.parametrize("mcp_id", ["nope", "asap-mcp-core", "otp-router", "web-search"])
def test_unknown_or_physical_id_404_without_gateway_write(client, gw, mcp_id):
    assert client.post(f"/api/toolbox/{mcp_id}").status_code == 404
    assert client.delete(f"/api/toolbox/{mcp_id}").status_code == 404
    assert gw.calls == []


@pytest.mark.parametrize("method", ["post", "delete"])
def test_development_mcp_is_refused_without_gateway_call(client, gw, method):
    r = getattr(client, method)("/api/toolbox/gtfs-accessibility-aro")
    assert r.status_code == 409
    assert r.json() == {"detail": IN_DEVELOPMENT_DETAIL}
    assert gw.calls == []


def test_duplicate_add_is_stable(client, gw):
    client.post("/api/toolbox/krri-road-cctv")
    r = client.post("/api/toolbox/krri-road-cctv")
    assert r.status_code == 200
    assert r.json()["mcp_ids"] == ["krri-road-cctv"]
    assert len(gw.puts()) == 1


def test_remove_not_selected_is_stable(client, gw):
    r = client.delete("/api/toolbox/web-research")
    assert r.status_code == 200
    assert r.json()["mcp_ids"] == []
    assert gw.puts() == []


def test_add_keeps_other_groups(app, gw):
    c = seeded_client(app, gw, ["krri-road-cctv", "web-research"], [])
    guest = c.cookies.get(GUEST_COOKIE)
    body = c.post("/api/toolbox/route-accessibility").json()
    # 내 MCP은 Catalog 와 같은 순서 (presentation.yaml)
    assert body["mcp_ids"] == ["krri-road-cctv", "web-research", "route-accessibility"]
    assert gw.store[guest]["groupIds"] == ["krri-road-cctv", "web-research", "route-accessibility"]


def test_multi_server_group_is_one_mcp(client, gw):
    body = client.post("/api/toolbox/route-accessibility").json()
    assert body["mcp_ids"] == ["route-accessibility"]
    assert len(body["mcps"]) == 1 and body["mcps"][0]["display_name"] == "R5 기반 등시선도 MCP"
    guest = client.cookies.get(GUEST_COOKIE)
    assert gw.store[guest]["toolRefs"] == ["otp-router/*", "r5-server/*"]
    client.delete("/api/toolbox/route-accessibility")
    assert gw.store[guest]["toolRefs"] == []


def test_selection_saved_by_asap_web_is_read_as_is(app, gw):
    # ASAP-web MCP market 은 {groupIds} 만 PUT 한다. 같은 guest 면 Portal 도 같은 값으로 읽는다.
    c = seeded_client(app, gw, ["web-research", "krri-map-location"], [])
    assert c.get("/api/toolbox").json()["mcp_ids"] == ["krri-map-location", "web-research"]


def test_legacy_server_wildcard_is_read_like_gateway_is_applied(app, gw):
    # 이전 Portal 은 toolRefs 에 "<serverId>/*" 를 넣었다. groupIds 가 비면 refs 가 덮는 group 이 「등록됨」.
    c = seeded_client(app, gw, [], ["asap-mcp-core/*"])
    guest = c.cookies.get(GUEST_COOKIE)
    assert c.get("/api/toolbox").json()["mcp_ids"] == ["krri-map-location", "krri-road-cctv"]
    # 첫 쓰기에서 group id 로 옮겨진다
    c.post("/api/toolbox/web-research")
    assert gw.store[guest]["groupIds"] == ["krri-map-location", "krri-road-cctv", "web-research"]
    assert "asap-mcp-core/*" not in gw.store[guest]["toolRefs"]


def test_legacy_partial_refs_cover_only_whole_groups(app, gw):
    c = seeded_client(app, gw, [], ["asap-mcp-core/geo.geocode", "otp-router/*"])
    # route-accessibility 는 r5-server 가 빠져 덮이지 않는다
    assert c.get("/api/toolbox").json()["mcp_ids"] == ["krri-map-location"]


def test_registered_mcp_ids_rule():
    mcps = [{"mcp_id": g, "tool_refs": refs} for g, refs in GROUP_REFS.items()]
    assert registered_mcp_ids(Selection(("web-research", "gone"), ("asap-mcp-core/*",)), mcps) == ["web-research"]
    assert registered_mcp_ids(Selection((), ("otp-router/*", "r5-server/*")), mcps) == ["route-accessibility"]
    assert registered_mcp_ids(Selection((), ()), mcps) == []


def test_gateway_dropping_group_is_409_not_success(client, gw):
    gw.drop_group = "web-research"
    r = client.post("/api/toolbox/web-research")
    assert r.status_code == 409
    assert r.json() == {"detail": NOT_APPLIED_DETAIL}
    # 이번에 발급된 guest 는 실패 응답에도 실린다
    assert r.headers["set-cookie"].startswith(f"{GUEST_COOKIE}=")


@pytest.mark.parametrize("method,path", [("get", "/api/toolbox"), ("post", "/api/toolbox/krri-road-cctv"),
                                         ("delete", "/api/toolbox/krri-road-cctv")])
def test_gateway_failure_is_sanitized(client, gw, method, path):
    gw.fail = GatewayUnavailable(f"PUT {BASE_URL} Traceback asap_mcp_guest=1234 192.168.71.236")
    r = getattr(client, method)(path)
    assert r.status_code == 502
    assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}


def test_put_failure_after_get_does_not_claim_success(client, gw):
    client.get("/api/toolbox")
    real_call = gw.__call__

    def fail_put(method, path, body, cookie):
        if method == "PUT":
            raise ConnectionError("down")
        return real_call(method, path, body, cookie)

    client.app.state.selection = RealSelectionClient(BASE_URL, transport=fail_put)
    assert client.post("/api/toolbox/krri-road-cctv").status_code == 502
    client.app.state.selection = RealSelectionClient(BASE_URL, transport=gw)
    assert client.get("/api/toolbox").json()["mcp_ids"] == []


def test_browser_json_has_no_identity_or_internal_values(app, gw):
    c = seeded_client(app, gw, ["route-accessibility", "web-research"], [])
    guest = c.cookies.get(GUEST_COOKIE)
    bodies = [c.get("/api/toolbox").json(), c.post("/api/toolbox/krri-road-cctv").json(),
              c.delete("/api/toolbox/route-accessibility").json()]
    text = json.dumps(bodies, ensure_ascii=False)
    for marker in (guest, "guest:", GATEWAY_GUEST_COOKIE, GUEST_COOKIE, "Set-Cookie", "Cookie", "Authorization",
                   BASE_URL, "192.168.", "Traceback", "groupIds", "toolRefs", "/*", "asap-mcp-core", "otp-router",
                   "r5-server", "server_id"):
        assert marker not in text


def test_invalid_portal_cookie_is_not_forwarded(client, gw):
    client.cookies.set(GUEST_COOKIE, "not-a-uuid; asap_mcp_guest=evil")
    client.get("/api/toolbox")
    assert gw.calls[0] == ("GET", None)


def test_issued_guest_id_parsing():
    g = str(uuid.uuid4())
    assert _issued_guest_id([f"{GATEWAY_GUEST_COOKIE}={g}; Max-Age=1; Path=/; HttpOnly; SameSite=Lax"]) == g
    assert _issued_guest_id([f"{GATEWAY_GUEST_COOKIE}=nope; Path=/"]) is None
    assert _issued_guest_id(["other=1"]) is None


def test_real_http_error_becomes_gateway_unavailable():
    with pytest.raises(GatewayUnavailable):
        RealSelectionClient("http://127.0.0.1:9", timeout_seconds=2).get(None)


def test_mock_mode_toolbox_roundtrip():
    c = TestClient(create_app())
    assert c.get("/api/toolbox").json()["mcp_ids"] == []
    assert c.post("/api/toolbox/route-accessibility").json()["mcp_ids"] == ["route-accessibility"]
    assert c.get("/api/toolbox").json()["mcps"][0]["display_name"] == "R5 기반 등시선도 MCP"
    assert c.delete("/api/toolbox/route-accessibility").json()["mcp_ids"] == []
    assert c.post("/api/toolbox/r5-server").status_code == 404
    assert c.post("/api/toolbox/nodelink-accessibility-vwl").status_code == 409
