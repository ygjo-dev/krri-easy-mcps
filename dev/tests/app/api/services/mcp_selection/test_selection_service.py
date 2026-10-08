"""selection_service — EASY 계정 내 MCP ↔ Gateway guest selection 동기화 규칙 (API 로 관찰).

계정 내 MCP 은 guest selection 을 대체하지 않고 그 위에 얹는 영구 저장이다 (KRRI ASAP 와의 같은-guest 연동은 그대로).
Gateway 가 실제로 반영한 값만 계정에 저장한다.

    비로그인                         계정 DB 를 읽거나 쓰지 않는다
    계정 내 MCP 이 아직 없음(첫 로그인) 지금 guest selection 을 계정에 저장 (빈 것도 「초기화된 빈 내 MCP」)
    이 세션이 이 guest 와 처음 맞춤    계정 내 MCP 을 guest selection 에 PUT (다른 PC · 브라우저에서 복원)
    이미 맞춘 guest                  마지막으로 맞춘 값 기준 3-way merge (KRRI ASAP 쪽 변경 · 다른 기기 변경 모두 반영)
    Gateway 실패                     계정은 그대로. 로그인 때 실패해도 로그인은 되고 다음 요청에서 맞춘다
"""

import sqlite3
import uuid

from fastapi.testclient import TestClient

from app.api.integrations.krri_asap.gateway_client import GatewayUnavailable
from app.api.integrations.krri_asap.selection_client import RealSelectionClient
from app.api.main import create_app, load_settings
from app.api.services.mcp_selection.selection_router import NOT_APPLIED_DETAIL
from app.api.services.mcp_selection.selection_service import GUEST_COOKIE
from app.api.services.mcp_selection.selection_service import merged as _merged
from tests.app.api.integrations.krri_asap.gateway_selection_fake import BASE_URL
from tests.app.api.services.browser_session import ADMIN, account_toolbox, browser, guest_of, login


def test_guest_toolbox_never_touches_account_db(app, gw):
    c = browser(app, gw)
    c.post("/api/toolbox/krri-road-cctv")
    c.delete("/api/toolbox/krri-road-cctv")
    c.get("/api/toolbox")
    with sqlite3.connect(load_settings().selections_db) as db:
        assert db.execute("SELECT COUNT(*) FROM account_toolboxes").fetchone() == (0,)
    with sqlite3.connect(load_settings().accounts_db) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone() == (0,)


def test_first_login_adopts_current_guest_toolbox(app, gw):
    """B. guest 로 이미 등록해 둔 MCP 가 첫 로그인 때 사라지지 않고 계정에 저장된다."""
    c = browser(app, gw, ["krri-road-cctv", "web-research"])
    guest = guest_of(c)
    assert account_toolbox(app) is None  # 아직 초기화 안 됨
    login(c)
    assert account_toolbox(app) == ["krri-road-cctv", "web-research"]
    assert c.get("/api/toolbox").json()["mcp_ids"] == ["krri-road-cctv", "web-research"]
    assert gw.store[guest]["groupIds"] == ["krri-road-cctv", "web-research"]
    assert gw.puts() == []  # 가져오기만 했다 (Gateway 쓰기 없음)


def test_empty_guest_initializes_an_empty_account_toolbox(app, gw):
    """B. 빈 guest 도 「초기화된 빈 내 MCP」이 된다. 그래서 다른 브라우저에서 로그인하면 빈 내 MCP이 복원된다."""
    login(browser(app, gw))
    assert account_toolbox(app) == []
    other = browser(app, gw, ["web-research"])
    login(other)
    assert other.get("/api/toolbox").json()["mcp_ids"] == []
    assert gw.store[guest_of(other)]["groupIds"] == []
    assert account_toolbox(app) == []


def test_login_on_another_browser_restores_account_toolbox(app, gw):
    """C. 다른 PC · 브라우저(다른 guest)에서 같은 계정으로 로그인하면 계정 내 MCP을 그 guest selection 에 PUT 한다."""
    pc1 = browser(app, gw, ["krri-road-cctv"])
    login(pc1)
    pc1.post("/api/toolbox/route-accessibility")
    pc2 = browser(app, gw, ["web-research"])
    guest2 = guest_of(pc2)
    login(pc2)
    # 같은 guest 행을 쓰는 KRRI ASAP 도 이제 같은 selection 이다
    assert gw.store[guest2]["groupIds"] == ["krri-road-cctv", "route-accessibility"]
    assert gw.bodies[-1] == {"groupIds": ["krri-road-cctv", "route-accessibility"]}
    assert pc2.get("/api/toolbox").json()["mcp_ids"] == ["krri-road-cctv", "route-accessibility"]
    assert account_toolbox(app) == ["krri-road-cctv", "route-accessibility"]


def test_restore_is_one_put_and_then_stable(app, gw):
    login(browser(app, gw, ["krri-road-cctv"]))
    pc2 = browser(app, gw)
    login(pc2)
    puts = len(gw.puts())
    for _ in range(3):
        pc2.get("/api/toolbox")
    assert len(gw.puts()) == puts


def test_reading_unchanged_toolbox_does_not_write_db(app, gw):
    c = browser(app, gw, ["krri-road-cctv"])
    login(c)
    with sqlite3.connect(load_settings().selections_db) as db:
        before = db.execute("SELECT updated_at FROM account_toolboxes").fetchone()
    c.get("/api/toolbox")
    c.get("/api/toolbox")
    with sqlite3.connect(load_settings().selections_db) as db:
        assert db.execute("SELECT updated_at FROM account_toolboxes").fetchone() == before


def test_add_and_remove_while_logged_in_are_saved_to_account(app, gw):
    """D. Gateway 가 반영한 실제 결과를 계정에 저장한다."""
    c = browser(app, gw)
    guest = guest_of(c)
    login(c)
    assert c.post("/api/toolbox/krri-map-location").json()["mcp_ids"] == ["krri-map-location"]
    assert c.post("/api/toolbox/web-research").json()["mcp_ids"] == ["krri-map-location", "web-research"]
    assert account_toolbox(app) == ["krri-map-location", "web-research"]
    assert c.delete("/api/toolbox/krri-map-location").json()["mcp_ids"] == ["web-research"]
    assert account_toolbox(app) == ["web-research"]
    assert gw.store[guest]["groupIds"] == ["web-research"]
    # PUT body 는 기존과 같은 {groupIds} 뿐
    assert all(set(b) == {"groupIds"} for b in gw.bodies)


def test_gateway_write_failure_does_not_touch_account(app, gw):
    """D. Gateway PUT 이 실패하면 계정 내 MCP은 그대로다."""
    c = browser(app, gw, ["krri-road-cctv"])
    login(c)
    real = gw.__call__

    def fail_put(method, path, body, cookie):
        if method == "PUT":
            raise ConnectionError("down")
        return real(method, path, body, cookie)

    app.state.selection = RealSelectionClient(BASE_URL, transport=fail_put)
    assert c.post("/api/toolbox/web-research").status_code == 502
    assert c.delete("/api/toolbox/krri-road-cctv").status_code == 502
    assert account_toolbox(app) == ["krri-road-cctv"]


def test_gateway_unavailable_does_not_touch_account(app, gw):
    c = browser(app, gw, ["krri-road-cctv"])
    login(c)
    gw.fail = GatewayUnavailable("down")
    assert c.get("/api/toolbox").status_code == 502
    assert c.post("/api/toolbox/web-research").status_code == 502
    assert account_toolbox(app) == ["krri-road-cctv"]


def test_gateway_refusing_a_group_saves_only_the_real_result(app, gw):
    """D. Gateway 가 반영하지 않은 MCP 는 계정에 들어가지 않는다 (409)."""
    c = browser(app, gw, ["krri-road-cctv"])
    login(c)
    gw.drop_group = "web-research"
    r = c.post("/api/toolbox/web-research")
    assert r.status_code == 409 and r.json() == {"detail": NOT_APPLIED_DETAIL}
    assert account_toolbox(app) == ["krri-road-cctv"]


def test_change_made_in_krri_asap_is_saved_when_easy_reads(app, gw):
    """E. KRRI ASAP 가 같은 guest selection 을 바꾸고(→ SSE 신호) EASY 가 다시 읽으면 계정에도 반영된다."""
    c = browser(app, gw, ["krri-road-cctv"])
    guest = guest_of(c)
    login(c)
    gw.store[guest] = gw._normalize(["krri-road-cctv", "route-accessibility"], [])  # ASAP-web 의 PUT
    puts = len(gw.puts())
    assert c.get("/api/toolbox").json()["mcp_ids"] == ["krri-road-cctv", "route-accessibility"]
    assert account_toolbox(app) == ["krri-road-cctv", "route-accessibility"]
    gw.store[guest] = gw._normalize([], [])  # KRRI ASAP 에서 전부 해제
    assert c.get("/api/toolbox").json()["mcp_ids"] == []
    assert account_toolbox(app) == []
    assert len(gw.puts()) == puts  # 읽어서 저장만 한다. Gateway 를 되돌리지 않는다


def test_krri_change_then_relogin_elsewhere_restores_latest(app, gw):
    pc1 = browser(app, gw, ["krri-road-cctv"])
    login(pc1)
    gw.store[guest_of(pc1)] = gw._normalize(["web-research"], [])
    pc1.get("/api/toolbox")
    pc1.post("/api/auth/logout")
    pc2 = browser(app, gw)
    login(pc2)
    assert pc2.get("/api/toolbox").json()["mcp_ids"] == ["web-research"]


def test_change_from_another_device_reaches_this_browser(app, gw):
    """두 기기가 동시에 로그인. 다른 기기가 계정을 바꿨으면 이 guest 에 반영한다 (Gateway 값으로 덮어쓰지 않는다)."""
    pc1 = browser(app, gw, ["krri-road-cctv"])
    login(pc1)
    pc2 = browser(app, gw)
    login(pc2)
    pc2.post("/api/toolbox/web-research")
    assert pc1.get("/api/toolbox").json()["mcp_ids"] == ["krri-road-cctv", "web-research"]
    assert gw.store[guest_of(pc1)]["groupIds"] == ["krri-road-cctv", "web-research"]
    # 양쪽에서 동시에 바뀐 것은 합친다: pc1 쪽(KRRI ASAP)이 cctv 해제, pc2 쪽이 지도 등록
    gw.store[guest_of(pc1)] = gw._normalize(["web-research"], [])
    pc2.post("/api/toolbox/krri-map-location")
    assert pc1.get("/api/toolbox").json()["mcp_ids"] == ["krri-map-location", "web-research"]
    assert account_toolbox(app) == ["krri-map-location", "web-research"]


def test_new_guest_in_same_session_is_restored_not_mirrored(app, gw):
    """로그인 중 guest cookie 가 바뀌어도(쿠키 삭제 등) 빈 새 guest 로 계정 내 MCP을 덮어쓰지 않는다."""
    c = browser(app, gw, ["krri-road-cctv"])
    login(c)
    new_guest = gw.seed([], [])
    c.cookies.set(GUEST_COOKIE, new_guest)
    assert c.get("/api/toolbox").json()["mcp_ids"] == ["krri-road-cctv"]
    assert gw.store[new_guest]["groupIds"] == ["krri-road-cctv"]


def test_login_sync_failure_still_logs_in_and_syncs_later(app, gw):
    """로그인 때 Gateway 가 안 되면 로그인만 하고, 다음 내 MCP 요청에서 맞춘다 (새 guest 값으로 계정을 덮지 않는다)."""
    login(browser(app, gw, ["krri-road-cctv"]))
    pc2 = browser(app, gw, ["web-research"])
    gw.fail = GatewayUnavailable("down")
    assert login(pc2).json() == {"user": {"username": "admin", "role": "ADMIN"}}
    assert account_toolbox(app) == ["krri-road-cctv"]
    gw.fail = None
    assert pc2.get("/api/toolbox").json()["mcp_ids"] == ["krri-road-cctv"]
    assert account_toolbox(app) == ["krri-road-cctv"]


def test_expired_session_falls_back_to_guest(app, gw):
    c = browser(app, gw, ["krri-road-cctv"])
    login(c)
    with sqlite3.connect(load_settings().accounts_db) as db:
        db.execute("UPDATE sessions SET expires_at = 0")
    assert c.get("/api/auth/me").json() == {"user": None}
    c.post("/api/toolbox/web-research")
    assert account_toolbox(app) == ["krri-road-cctv"]


def test_sessions_and_toolboxes_are_per_user(app, gw):
    app.state.accounts.create_user("alice", "alice-pw")
    a = browser(app, gw, ["krri-road-cctv"])
    b = browser(app, gw, ["web-research"])
    login(a)
    login(b, {"username": "alice", "password": "alice-pw"})
    assert a.get("/api/auth/me").json()["user"]["username"] == "admin"
    assert b.get("/api/auth/me").json()["user"] == {"username": "alice", "role": "USER"}
    a.post("/api/toolbox/route-accessibility")
    assert account_toolbox(app, "admin") == ["krri-road-cctv", "route-accessibility"]
    assert account_toolbox(app, "alice") == ["web-research"]
    assert b.get("/api/toolbox").json()["mcp_ids"] == ["web-research"]


def test_three_way_merge_keeps_additions_and_removals_from_both_sides():
    assert _merged(("a", "b"), ["a", "b", "c"], ["a", "b"]) == ["a", "b", "c"]  # Gateway 만 더함
    assert _merged(("a", "b"), ["a"], ["a", "b"]) == ["a"]  # Gateway 만 뺌
    assert _merged(("a",), ["a"], ["a", "d"]) == ["a", "d"]  # 계정만 더함
    assert _merged(("a", "b"), ["b", "c"], ["a", "b", "d"]) == ["b", "c", "d"]  # 둘 다


def test_mock_mode_login_and_account_toolbox():
    c = TestClient(create_app())
    c.get("/api/toolbox")
    c.post("/api/toolbox/route-accessibility")
    assert c.post("/api/auth/login", json=ADMIN).json()["user"]["role"] == "ADMIN"
    assert c.get("/api/toolbox").json()["mcp_ids"] == ["route-accessibility"]
    other = TestClient(c.app)
    other.cookies.set(GUEST_COOKIE, str(uuid.uuid4()))
    other.post("/api/auth/login", json=ADMIN)
    assert other.get("/api/toolbox").json()["mcp_ids"] == ["route-accessibility"]
