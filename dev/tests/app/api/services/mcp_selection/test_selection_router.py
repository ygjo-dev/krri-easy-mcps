"""/api/toolbox — 내 MCP HTTP contract. 이미 KRRI 에 있는 logical MCP 를 내 Gateway selection 에 넣고 빼는 것이다.

- 브라우저 contract 는 mcp_id 뿐이다. 등록 · 해제는 Gateway 에 ``PUT {groupIds}`` (ASAP-web MCP market 과 같은 표현) 로 간다.
- 사용자 식별은 Gateway guest cookie ``asap_mcp_guest`` (ASAP-web 과 같은 이름 · Path=/ · HttpOnly · SameSite=Lax · 1년).
  예전 cookie ``kem_gateway_guest`` 는 같은 UUID 로 올리고 지운다. 형식이 틀린 cookie 는 Gateway 로 보내지 않는다.
- 개발 중 MCP 는 409, 모르는 id · physical server id 는 404 이고 둘 다 Gateway 를 부르지 않는다.
  Gateway 가 반영하지 않으면 409, Gateway 오류는 502 (성공으로 가정하지 않는다).
- GET /api/toolbox/events 는 Gateway selection 신호 흐름을 guest cookie 로 열어 바이트 그대로 넘긴다.
- 브라우저 JSON 에는 guest id · groupIds · toolRefs · 내부 주소가 없다.
"""

import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.integrations.krri_asap.gateway_client import GatewayUnavailable
from app.api.integrations.krri_asap.selection_client import EVENTS_PATH, GATEWAY_GUEST_COOKIE, RealSelectionClient
from app.api.main import GATEWAY_UNAVAILABLE_DETAIL, create_app
from app.api.services.mcp_selection.selection_router import IN_DEVELOPMENT_DETAIL, NOT_APPLIED_DETAIL
from app.api.services.mcp_selection.selection_service import GUEST_COOKIE, LEGACY_GUEST_COOKIE
from tests.app.api.integrations.krri_asap.gateway_selection_fake import BASE_URL, STREAM, FakeGatewayEvents


def seeded_client(app, gw, group_ids, tool_refs):
    c = TestClient(app)
    c.cookies.set(GUEST_COOKIE, gw.seed(group_ids, tool_refs))
    return c


# ── guest cookie (asap_mcp_guest) ───────────────────────────────────


def test_get_empty_toolbox_issues_canonical_gateway_cookie(live_client, gw):
    r = live_client.get("/api/toolbox")
    assert r.status_code == 200
    assert r.json() == {"mcp_ids": [], "mcps": []}
    [header] = r.headers.get_list("set-cookie")
    # ASAP-web 이 Gateway 에서 받는 것과 같은 cookie: 이름 · Path=/ · HttpOnly · SameSite=Lax · 1년
    assert GUEST_COOKIE == GATEWAY_GUEST_COOKIE == "asap_mcp_guest"
    issued = gw.calls[0]
    assert issued == ("GET", None)
    guest = live_client.cookies.get(GUEST_COOKIE)
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


def test_invalid_portal_cookie_is_not_forwarded(live_client, gw):
    live_client.cookies.set(GUEST_COOKIE, "not-a-uuid; asap_mcp_guest=evil")
    live_client.get("/api/toolbox")
    assert gw.calls[0] == ("GET", None)


# ── 등록 · 해제 → Gateway PUT {groupIds} ──────────────────────────────


def test_add_get_remove_writes_group_id(live_client, gw):
    live_client.get("/api/toolbox")
    guest = live_client.cookies.get(GUEST_COOKIE)
    body = live_client.post("/api/toolbox/krri-road-cctv").json()
    assert body["mcp_ids"] == ["krri-road-cctv"]
    assert body["mcps"][0]["display_name"] == "krri-road-cctv"
    assert body["mcps"][0]["category"] == "KRRI 정책현안 분석도구"
    assert body["mcps"][0]["tool_count"] == 1
    assert live_client.get("/api/toolbox").json()["mcp_ids"] == ["krri-road-cctv"]
    # Gateway selection 의 canonical 값은 groupId. toolRefs 는 Gateway 가 group 에서 펼친 것뿐
    assert gw.store[guest]["groupIds"] == ["krri-road-cctv"]
    assert gw.store[guest]["toolRefs"] == ["asap-mcp-core/road.getcctv"]
    assert live_client.delete("/api/toolbox/krri-road-cctv").json()["mcp_ids"] == []
    assert gw.store[guest] == {"groupIds": [], "serverIds": [], "toolRefs": []}
    # 첫 GET 뒤로는 모든 Gateway 호출이 같은 guest 로 갔다
    assert {g for _, g in gw.calls[1:]} == {guest}
    # 다른 브라우저(cookie 없음)는 다른 내 MCP
    assert TestClient(live_client.app).get("/api/toolbox").json()["mcp_ids"] == []


def test_put_body_is_group_ids_only_like_asap_web(live_client, gw):
    live_client.post("/api/toolbox/krri-map-location")
    live_client.post("/api/toolbox/web-research")
    live_client.delete("/api/toolbox/krri-map-location")
    assert gw.bodies == [
        {"groupIds": ["krri-map-location"]},
        {"groupIds": ["krri-map-location", "web-research"]},
        {"groupIds": ["web-research"]},
    ]


def test_same_server_groups_are_independent(live_client, gw):
    # 같은 physical server(asap-mcp-core) 의 두 logical MCP 는 따로 등록 · 해제된다
    live_client.post("/api/toolbox/krri-map-location")
    assert live_client.post("/api/toolbox/krri-road-cctv").json()["mcp_ids"] == ["krri-map-location", "krri-road-cctv"]
    assert live_client.delete("/api/toolbox/krri-map-location").json()["mcp_ids"] == ["krri-road-cctv"]


def test_first_add_without_cookie_uses_issued_guest_for_put(live_client, gw):
    r = live_client.post("/api/toolbox/web-research")
    assert r.json()["mcp_ids"] == ["web-research"]
    guest = live_client.cookies.get(GUEST_COOKIE)
    assert gw.calls == [("GET", None), ("PUT", guest)]


@pytest.mark.parametrize("mcp_id", ["nope", "asap-mcp-core", "otp-router", "web-search"])
def test_unknown_or_physical_id_404_without_gateway_write(live_client, gw, mcp_id):
    assert live_client.post(f"/api/toolbox/{mcp_id}").status_code == 404
    assert live_client.delete(f"/api/toolbox/{mcp_id}").status_code == 404
    assert gw.calls == []


@pytest.mark.parametrize("method", ["post", "delete"])
def test_development_mcp_is_refused_without_gateway_call(live_client, gw, method):
    r = getattr(live_client, method)("/api/toolbox/gtfs-accessibility-aro")
    assert r.status_code == 409
    assert r.json() == {"detail": IN_DEVELOPMENT_DETAIL}
    assert gw.calls == []


def test_duplicate_add_is_stable(live_client, gw):
    live_client.post("/api/toolbox/krri-road-cctv")
    r = live_client.post("/api/toolbox/krri-road-cctv")
    assert r.status_code == 200
    assert r.json()["mcp_ids"] == ["krri-road-cctv"]
    assert len(gw.puts()) == 1


def test_remove_not_selected_is_stable(live_client, gw):
    r = live_client.delete("/api/toolbox/web-research")
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


def test_multi_server_group_is_one_mcp(live_client, gw):
    body = live_client.post("/api/toolbox/route-accessibility").json()
    assert body["mcp_ids"] == ["route-accessibility"]
    assert len(body["mcps"]) == 1 and body["mcps"][0]["display_name"] == "R5 기반 등시선도 MCP"
    guest = live_client.cookies.get(GUEST_COOKIE)
    assert gw.store[guest]["toolRefs"] == ["otp-router/*", "r5-server/*"]
    live_client.delete("/api/toolbox/route-accessibility")
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


# ── 실패 · 브라우저 노출 ───────────────────────────────────────────


def test_gateway_dropping_group_is_409_not_success(live_client, gw):
    gw.drop_group = "web-research"
    r = live_client.post("/api/toolbox/web-research")
    assert r.status_code == 409
    assert r.json() == {"detail": NOT_APPLIED_DETAIL}
    # 이번에 발급된 guest 는 실패 응답에도 실린다
    assert r.headers["set-cookie"].startswith(f"{GUEST_COOKIE}=")


@pytest.mark.parametrize("method,path", [("get", "/api/toolbox"), ("post", "/api/toolbox/krri-road-cctv"),
                                         ("delete", "/api/toolbox/krri-road-cctv")])
def test_gateway_failure_is_sanitized(live_client, gw, method, path):
    gw.fail = GatewayUnavailable(f"PUT {BASE_URL} Traceback asap_mcp_guest=1234 192.168.71.236")
    r = getattr(live_client, method)(path)
    assert r.status_code == 502
    assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}


def test_put_failure_after_get_does_not_claim_success(live_client, gw):
    live_client.get("/api/toolbox")
    real_call = gw.__call__

    def fail_put(method, path, body, cookie):
        if method == "PUT":
            raise ConnectionError("down")
        return real_call(method, path, body, cookie)

    live_client.app.state.selection = RealSelectionClient(BASE_URL, transport=fail_put)
    assert live_client.post("/api/toolbox/krri-road-cctv").status_code == 502
    live_client.app.state.selection = RealSelectionClient(BASE_URL, transport=gw)
    assert live_client.get("/api/toolbox").json()["mcp_ids"] == []


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


def test_mock_mode_toolbox_roundtrip():
    c = TestClient(create_app())
    assert c.get("/api/toolbox").json()["mcp_ids"] == []
    assert c.post("/api/toolbox/route-accessibility").json()["mcp_ids"] == ["route-accessibility"]
    assert c.get("/api/toolbox").json()["mcps"][0]["display_name"] == "R5 기반 등시선도 MCP"
    assert c.delete("/api/toolbox/route-accessibility").json()["mcp_ids"] == []
    assert c.post("/api/toolbox/r5-server").status_code == 404
    assert c.post("/api/toolbox/nodelink-accessibility-vwl").status_code == 409


# ── 변경 신호 흐름 (GET /api/toolbox/events) ─────────────────────────


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


def test_events_do_not_forward_an_invalid_cookie():
    fake = FakeGatewayEvents()
    c = make_client(fake)
    c.cookies.set(GUEST_COOKIE, "not-a-uuid")
    c.get("/api/toolbox/events")
    assert "cookie" not in fake.requests[0].headers


@pytest.mark.parametrize("status", [401, 403, 500, 502])
def test_events_gateway_error_is_sanitized_502(status):
    fake = FakeGatewayEvents(status=status)
    r = make_client(fake).get("/api/toolbox/events")
    assert r.status_code == 502
    assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}
    assert fake.closed == 1


def test_events_unreachable_gateway_is_502():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    app = create_app()
    app.state.selection = RealSelectionClient(BASE_URL, stream_transport=httpx.MockTransport(boom))
    r = TestClient(app).get("/api/toolbox/events")
    assert r.status_code == 502
    assert r.json() == {"detail": GATEWAY_UNAVAILABLE_DETAIL}
