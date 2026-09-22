"""도구함: Browser → BFF → Gateway /api/me/mcp-selections.

FakeSelectionGateway 는 Gateway mcpMarket.service 의 정규화를 필요한 만큼 흉내 낸다:
groupIds 는 아는 group 만, toolRefs = group 의 refs + 명시 refs 중 등록된 server 것만 (소문자 · 중복 제거),
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
    without_server,
)
from app.main import GATEWAY_UNAVAILABLE_DETAIL, create_app
from app.routes.toolbox import GUEST_COOKIE

BASE_URL = "http://gateway.internal.example:3000"

TOOLS = [
    {"name": "geo.geocode", "serverId": "asap-mcp-core", "inputSchema": {}},
    {"name": "road.getCctv", "serverId": "asap-mcp-core", "inputSchema": {}},
    {"name": "web.search", "serverId": "web-search", "inputSchema": {}},
]
MARKET = [
    {"id": "krri-road-cctv", "serverIds": ["asap-mcp-core"], "status": "ready"},
    {"id": "route-accessibility", "serverIds": ["otp-router", "r5-server"], "status": "error"},
    {"id": "web-research", "serverIds": ["web-search"], "status": "ready"},
]
GROUP_REFS = {
    "krri-road-cctv": ["asap-mcp-core/road.getcctv"],
    "route-accessibility": ["otp-router/*", "r5-server/*"],
    "web-research": ["web-search/web.search", "web-search/web.fetch"],
}
AVAILABLE = {"asap-mcp-core", "otp-router", "r5-server", "web-search"}


class FakeSelectionGateway:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.calls: list[tuple[str, str | None]] = []
        self.fail: Exception | None = None
        self.drop_server: str | None = None  # Gateway 가 이 server ref 를 조용히 버리는 경우

    def seed(self, group_ids, tool_refs) -> str:
        guest = str(uuid.uuid4())
        self.store[guest] = self._normalize(group_ids, tool_refs)
        return guest

    def _normalize(self, group_ids, tool_refs):
        groups = [g for g in dict.fromkeys(group_ids) if g in GROUP_REFS]
        refs = [r.lower() for g in groups for r in GROUP_REFS[g]] + [r.lower() for r in tool_refs]
        refs = [r for r in dict.fromkeys(refs) if r.split("/")[0] in AVAILABLE and r.split("/")[0] != self.drop_server]
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


def test_get_empty_toolbox_issues_portal_cookie(client, gw):
    r = client.get("/api/toolbox")
    assert r.status_code == 200
    assert r.json() == {"server_ids": [], "mcps": []}
    header = r.headers["set-cookie"]
    assert header.startswith(f"{GUEST_COOKIE}=")
    assert "HttpOnly" in header and "Path=/api" in header and "samesite=lax" in header.lower()
    assert GATEWAY_GUEST_COOKIE not in header


def test_add_get_remove_keeps_one_guest_identity(client, gw):
    client.get("/api/toolbox")
    guest = client.cookies.get(GUEST_COOKIE)
    body = client.post("/api/toolbox/asap-mcp-core").json()
    assert body["server_ids"] == ["asap-mcp-core"]
    assert body["mcps"][0]["display_name"] == "ASAP Core MCP"
    assert body["mcps"][0]["tool_count"] == 2
    assert client.get("/api/toolbox").json()["server_ids"] == ["asap-mcp-core"]
    assert gw.store[guest]["toolRefs"] == ["asap-mcp-core/*"]
    assert client.delete("/api/toolbox/asap-mcp-core").json()["server_ids"] == []
    assert gw.store[guest]["toolRefs"] == []
    # 첫 GET 뒤로는 모든 Gateway 호출이 같은 guest 로 갔다
    assert {g for _, g in gw.calls[1:]} == {guest}
    # 다른 브라우저(cookie 없음)는 다른 도구함
    assert TestClient(client.app).get("/api/toolbox").json()["server_ids"] == []


def test_first_add_without_cookie_uses_issued_guest_for_put(client, gw):
    r = client.post("/api/toolbox/web-search")
    assert r.json()["server_ids"] == ["web-search"]
    guest = client.cookies.get(GUEST_COOKIE)
    assert gw.calls == [("GET", None), ("PUT", guest)]


def test_unknown_server_404_without_gateway_write(client, gw):
    assert client.post("/api/toolbox/nope").status_code == 404
    assert client.delete("/api/toolbox/nope").status_code == 404
    assert gw.puts() == []


def test_duplicate_add_is_stable(client, gw):
    client.post("/api/toolbox/asap-mcp-core")
    r = client.post("/api/toolbox/asap-mcp-core")
    assert r.status_code == 200
    assert r.json()["server_ids"] == ["asap-mcp-core"]
    assert len(gw.puts()) == 1


def test_remove_not_selected_is_stable(client, gw):
    r = client.delete("/api/toolbox/web-search")
    assert r.status_code == 200
    assert r.json()["server_ids"] == []
    assert gw.puts() == []


def test_add_preserves_existing_groups_and_refs(app, gw):
    c = seeded_client(app, gw, ["krri-road-cctv", "web-research"], ["asap-mcp-core/geo.geocode"])
    guest = c.cookies.get(GUEST_COOKIE)
    before = dict(gw.store[guest])
    c.post("/api/toolbox/otp-router")
    after = gw.store[guest]
    assert after["groupIds"] == before["groupIds"]
    assert set(before["toolRefs"]) < set(after["toolRefs"])
    assert set(after["toolRefs"]) - set(before["toolRefs"]) == {"otp-router/*"}


def test_remove_drops_only_that_server(app, gw):
    c = seeded_client(app, gw, ["krri-road-cctv", "web-research"], ["asap-mcp-core/geo.geocode", "web-search/*"])
    guest = c.cookies.get(GUEST_COOKIE)
    assert c.get("/api/toolbox").json()["server_ids"] == ["web-search"]
    c.delete("/api/toolbox/web-search")
    after = gw.store[guest]
    assert after["groupIds"] == ["krri-road-cctv"]
    assert after["toolRefs"] == ["asap-mcp-core/road.getcctv", "asap-mcp-core/geo.geocode"]


def test_multi_server_group_is_not_pulled_in_by_add(client, gw):
    body = client.post("/api/toolbox/otp-router").json()
    assert body["server_ids"] == ["otp-router"]
    guest = client.cookies.get(GUEST_COOKIE)
    assert gw.store[guest]["groupIds"] == []
    assert "r5-server/*" not in gw.store[guest]["toolRefs"]


def test_removing_one_server_of_multi_server_group_keeps_the_other(app, gw):
    c = seeded_client(app, gw, ["route-accessibility"], [])
    assert c.get("/api/toolbox").json()["server_ids"] == ["otp-router", "r5-server"]
    body = c.delete("/api/toolbox/otp-router").json()
    assert body["server_ids"] == ["r5-server"]
    guest = c.cookies.get(GUEST_COOKIE)
    assert gw.store[guest] == {"groupIds": [], "serverIds": ["r5-server"], "toolRefs": ["r5-server/*"]}


def test_without_server_uses_group_mapping_case_insensitively():
    sel = Selection(("route-accessibility", "web-research"), ("otp-router/*", "r5-server/*", "web-search/web.search"))
    out = without_server(sel, "OTP-Router", {"route-accessibility": ["otp-router", "r5-server"], "web-research": ["web-search"]})
    assert out == Selection(("web-research",), ("r5-server/*", "web-search/web.search"))


def test_gateway_dropping_ref_is_409_not_success(client, gw):
    gw.drop_server = "otp-router"
    r = client.post("/api/toolbox/otp-router")
    assert r.status_code == 409
    assert r.json() == {"detail": "Gateway 가 이 MCP 를 도구함에 반영하지 않았습니다."}
    # 이번에 발급된 guest 는 실패 응답에도 실린다
    assert r.headers["set-cookie"].startswith(f"{GUEST_COOKIE}=")


@pytest.mark.parametrize("method,path", [("get", "/api/toolbox"), ("post", "/api/toolbox/asap-mcp-core"),
                                         ("delete", "/api/toolbox/asap-mcp-core")])
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
    assert client.post("/api/toolbox/asap-mcp-core").status_code == 502
    client.app.state.selection = RealSelectionClient(BASE_URL, transport=gw)
    assert client.get("/api/toolbox").json()["server_ids"] == []


def test_browser_json_has_no_identity_or_internal_values(app, gw):
    c = seeded_client(app, gw, ["route-accessibility", "web-research"], [])
    guest = c.cookies.get(GUEST_COOKIE)
    bodies = [c.get("/api/toolbox").json(), c.post("/api/toolbox/asap-mcp-core").json(),
              c.delete("/api/toolbox/otp-router").json()]
    text = json.dumps(bodies, ensure_ascii=False)
    for marker in (guest, "guest:", GATEWAY_GUEST_COOKIE, GUEST_COOKIE, "Set-Cookie", "Cookie", "Authorization",
                   BASE_URL, "192.168.", "Traceback", "groupIds", "toolRefs", "/*"):
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
    assert c.get("/api/toolbox").json()["server_ids"] == []
    assert c.post("/api/toolbox/r5-server").json()["server_ids"] == ["r5-server"]
    assert c.get("/api/toolbox").json()["mcps"][0]["display_name"] == "R5 접근성 분석"
    assert c.delete("/api/toolbox/r5-server").json()["server_ids"] == []
    assert c.post("/api/toolbox/nope").status_code == 404
