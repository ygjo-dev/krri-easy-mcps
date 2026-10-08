"""EASY 자체 로그인 + 계정 내 MCP. KRRI_ASAP 로그인과 별개이고, Gateway 쪽은 계속 guest selection 이다.

Gateway 는 test_toolbox 의 FakeSelectionGateway 로 흉내 낸다. 「KRRI ASAP 에서 바꿈」은 같은 guest 의 Gateway 행을
직접 바꾸는 것으로 모사한다 (ASAP-web 은 같은 cookie 로 같은 행에 {groupIds} 를 PUT 한다).
DB 는 테스트마다 임시 파일이다 (conftest.py).
"""

import json
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.services.auth.account_service import ROLE_ADMIN, ROLE_USER, SESSION_COOKIE, AccountStore, hash_password, verify_password
from app.api.integrations.krri_asap.gateway_client import GatewayUnavailable, RealGatewayClient
from app.api.integrations.krri_asap.selection_client import RealSelectionClient
from app.api.main import create_app
from app.api.services.auth.auth_router import LOGIN_FAILED_DETAIL, LOGIN_INVALID_DETAIL
from app.api.services.mcp_selection.selection_router import NOT_APPLIED_DETAIL
from app.api.services.mcp_selection.selection_service import GUEST_COOKIE
from app.api.services.mcp_selection.selection_service import merged as _merged
from app.api.main import load_settings
from tests.api.mcp_selection.test_toolbox import BASE_URL, MARKET, TOOLS, FakeSelectionGateway

ADMIN = {"username": "admin", "password": "admin"}


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


def browser(app, gw, group_ids=()):
    """guest cookie 를 가진 브라우저 하나. group_ids 는 이 guest 의 Gateway selection (KRRI ASAP 와 공유)."""
    c = TestClient(app)
    c.cookies.set(GUEST_COOKIE, gw.seed(list(group_ids), []))
    return c


def guest_of(c) -> str:
    return c.cookies.get(GUEST_COOKIE)


def login(c, creds=ADMIN):
    r = c.post("/api/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return r


def account_toolbox(app, username="admin"):
    settings = load_settings()
    with sqlite3.connect(settings.accounts_db) as db:
        [(user_id,)] = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchall()
    with sqlite3.connect(settings.selections_db) as db:
        row = db.execute("SELECT mcp_ids FROM account_toolboxes WHERE user_id = ?", (user_id,)).fetchone()
    return json.loads(row[0]) if row else None


def session_cookie_header(r) -> str:
    [header] = [h for h in r.headers.get_list("set-cookie") if h.startswith(f"{SESSION_COOKIE}=")]
    return header


# ── 로그인 · 세션 ─────────────────────────────────────────


def test_me_is_anonymous_by_default(app):
    assert TestClient(app).get("/api/auth/me").json() == {"user": None}


def test_admin_admin_login_and_me(app, gw):
    c = browser(app, gw)
    r = login(c)
    assert r.json() == {"user": {"username": "admin", "role": "ADMIN"}}
    assert c.get("/api/auth/me").json() == {"user": {"username": "admin", "role": "ADMIN"}}


@pytest.mark.parametrize("creds", [{"username": "admin", "password": "wrong"},
                                   {"username": "nobody", "password": "admin"},
                                   {"username": "Admin", "password": "admin"}])
def test_bad_credentials_are_one_generic_401(app, gw, creds):
    c = browser(app, gw)
    r = c.post("/api/auth/login", json=creds)
    assert r.status_code == 401
    # 없는 사용자 · 틀린 비밀번호를 구분하지 않는다
    assert r.json() == {"detail": LOGIN_FAILED_DETAIL}
    assert r.headers.get_list("set-cookie") == []
    assert c.get("/api/auth/me").json() == {"user": None}
    assert gw.calls == []  # 실패한 로그인은 Gateway 를 부르지 않는다


@pytest.mark.parametrize("body", [None, "not json", [], {"username": "admin"}, {"password": "s3cr3t-pw"},
                                  {"username": 1, "password": "s3cr3t-pw"}, {"username": "", "password": ""}])
def test_malformed_login_is_400_without_echo(app, body):
    c = TestClient(app)
    if isinstance(body, str):
        r = c.post("/api/auth/login", content=body, headers={"content-type": "application/json"})
    else:
        r = c.post("/api/auth/login", json=body)
    assert r.status_code == 400
    assert r.json() == {"detail": LOGIN_INVALID_DETAIL}
    assert "s3cr3t-pw" not in r.text  # FastAPI 422 처럼 입력값을 되돌려 보내지 않는다


def test_login_accepts_json_only(app, gw):
    """다른 사이트의 form(enctype=text/plain) 이 JSON 모양 body 를 보내도 로그인되지 않는다 (login CSRF)."""
    c = browser(app, gw)
    r = c.post("/api/auth/login", content=json.dumps(ADMIN), headers={"content-type": "text/plain"})
    assert r.status_code == 400 and r.json() == {"detail": LOGIN_INVALID_DETAIL}
    assert SESSION_COOKIE not in c.cookies
    r = c.post("/api/auth/login", content=json.dumps(ADMIN), headers={"content-type": "application/json; charset=utf-8"})
    assert r.status_code == 200


def test_reading_unchanged_toolbox_does_not_write_db(app, gw):
    c = browser(app, gw, ["krri-road-cctv"])
    login(c)
    with sqlite3.connect(load_settings().selections_db) as db:
        before = db.execute("SELECT updated_at FROM account_toolboxes").fetchone()
    c.get("/api/toolbox")
    c.get("/api/toolbox")
    with sqlite3.connect(load_settings().selections_db) as db:
        assert db.execute("SELECT updated_at FROM account_toolboxes").fetchone() == before


def test_overlong_credentials_fail_without_hashing(app):
    r = TestClient(app).post("/api/auth/login", json={"username": "admin", "password": "x" * 10_000})
    assert r.status_code == 401
    assert r.json() == {"detail": LOGIN_FAILED_DETAIL}


def test_logout_returns_to_guest_and_keeps_gateway_guest(app, gw):
    c = browser(app, gw, ["krri-road-cctv"])
    guest = guest_of(c)
    login(c)
    r = c.post("/api/auth/logout")
    assert r.json() == {"user": None}
    assert c.get("/api/auth/me").json() == {"user": None}
    # EASY 세션 cookie 만 지운다. asap_mcp_guest 는 그대로 (KRRI ASAP 연동 유지)
    [cleared] = r.headers.get_list("set-cookie")
    assert cleared.startswith(f"{SESSION_COOKIE}=") and ("Max-Age=0" in cleared or "expires=" in cleared.lower())
    assert guest_of(c) == guest
    assert gw.store[guest]["groupIds"] == ["krri-road-cctv"]
    # 로그아웃 뒤는 기존 guest 동작
    assert c.post("/api/toolbox/web-research").json()["mcp_ids"] == ["krri-road-cctv", "web-research"]
    assert account_toolbox(app) == ["krri-road-cctv"]  # 로그아웃 뒤 변경은 계정에 안 들어간다


def test_old_session_token_is_dead_after_logout(app, gw):
    c = browser(app, gw)
    login(c)
    token = c.cookies.get(SESSION_COOKIE)
    c.post("/api/auth/logout")
    replay = TestClient(app)
    replay.cookies.set(SESSION_COOKIE, token)
    assert replay.get("/api/auth/me").json() == {"user": None}


def test_relogin_replaces_previous_session(app, gw):
    c = browser(app, gw)
    login(c)
    first = c.cookies.get(SESSION_COOKIE)
    login(c)
    assert c.cookies.get(SESSION_COOKIE) != first
    old = TestClient(app)
    old.cookies.set(SESSION_COOKIE, first)
    assert old.get("/api/auth/me").json() == {"user": None}


def test_session_cookie_attributes(app, gw):
    header = session_cookie_header(login(browser(app, gw)))
    assert "HttpOnly" in header and "samesite=lax" in header.lower()
    assert "Path=/;" in header + ";" and f"Max-Age={168 * 3600}" in header
    assert "Secure" not in header
    https = TestClient(app, base_url="https://testserver")
    https.cookies.set(GUEST_COOKIE, gw.seed([], []))
    assert "Secure" in session_cookie_header(login(https))


def test_session_cookie_is_separate_from_gateway_guest_cookie(app, gw):
    c = browser(app, gw)
    guest = guest_of(c)
    r = login(c)
    assert SESSION_COOKIE != GUEST_COOKIE
    token = c.cookies.get(SESSION_COOKIE)
    assert token and token != guest
    # 이미 guest 가 있으면 로그인이 guest cookie 를 다시 쓰지 않는다
    assert [h for h in r.headers.get_list("set-cookie") if h.startswith(f"{GUEST_COOKIE}=")] == []
    # Gateway 로는 guest cookie 만 간다 (EASY 세션 token 을 싣지 않는다)
    assert {g for _, g in gw.calls} == {guest}


def test_login_without_guest_cookie_gets_gateway_guest(app, gw):
    c = TestClient(app)
    r = login(c)
    guest = guest_of(c)
    assert guest and any(h.startswith(f"{GUEST_COOKIE}={guest};") for h in r.headers.get_list("set-cookie"))
    assert account_toolbox(app) == []
    assert c.get("/api/toolbox").json()["mcp_ids"] == []
    assert {g for _, g in gw.calls[1:]} == {guest}


def test_auth_responses_never_carry_secrets(app, gw):
    c = browser(app, gw, ["web-research"])
    texts = [login(c).text]
    token = c.cookies.get(SESSION_COOKIE)
    texts += [c.get("/api/auth/me").text, c.get("/api/toolbox").text, c.post("/api/toolbox/krri-road-cctv").text,
              c.post("/api/auth/logout").text,
              c.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).text]
    for text in texts:
        for marker in ("password", "scrypt", "hash", "token", SESSION_COOKIE, guest_of(c), token, "\"id\""):
            assert marker not in text, (marker, text)


def test_password_is_hashed_in_db(app):
    with sqlite3.connect(load_settings().accounts_db) as db:
        [(stored, role)] = db.execute("SELECT password_hash, role FROM users WHERE username = 'admin'").fetchall()
    assert stored != "admin" and stored.startswith("scrypt$") and "admin" not in stored
    assert role == ROLE_ADMIN
    assert verify_password("admin", stored) and not verify_password("wrong", stored)
    # 같은 비밀번호도 salt 가 달라 hash 가 다르다
    assert hash_password("admin") != hash_password("admin")


def test_session_token_is_stored_only_as_hash(app, gw):
    c = browser(app, gw)
    login(c)
    token = c.cookies.get(SESSION_COOKIE)
    dump = ""
    for path in (load_settings().accounts_db, load_settings().selections_db):
        with sqlite3.connect(path) as db:
            dump += "\n".join(db.iterdump())
    assert token not in dump and guest_of(c) not in dump


# ── role · DB ───────────────────────────────────────────


def test_role_model_user_and_admin(tmp_path):
    store = AccountStore(tmp_path / "a.db", session_seconds=60, admin_username="admin", admin_password="admin")
    assert store.authenticate("admin", "admin").role == ROLE_ADMIN
    alice = store.create_user("alice", "pw")
    assert alice.role == ROLE_USER
    assert store.authenticate("alice", "pw").public() == {"username": "alice", "role": "USER"}
    with pytest.raises(ValueError):
        store.create_user("bob", "pw", role="ROOT")
    with pytest.raises(sqlite3.IntegrityError):
        store.create_user("alice", "other")


def test_seed_does_not_overwrite_existing_admin(tmp_path):
    path = tmp_path / "a.db"
    AccountStore(path, session_seconds=60, admin_username="admin", admin_password="admin")
    store = AccountStore(path, session_seconds=60, admin_username="admin", admin_password="changed")
    assert store.authenticate("admin", "admin") is not None
    assert store.authenticate("admin", "changed") is None


def test_admin_credentials_come_from_settings(monkeypatch, gw):
    monkeypatch.setenv("KEM_ADMIN_USERNAME", "root")
    monkeypatch.setenv("KEM_ADMIN_PASSWORD", "pw-from-env")
    app = create_app()
    app.state.selection = RealSelectionClient(BASE_URL, transport=gw)
    c = TestClient(app)
    assert c.post("/api/auth/login", json=ADMIN).status_code == 401
    assert c.post("/api/auth/login", json={"username": "root", "password": "pw-from-env"}).json()["user"] == {
        "username": "root", "role": "ADMIN"}


def test_session_expires(tmp_path):
    now = [1000.0]
    store = AccountStore(tmp_path / "a.db", session_seconds=60, admin_username="admin", admin_password="admin",
                         clock=lambda: now[0])
    token = store.create_session(store.authenticate("admin", "admin"))
    now[0] += 59
    assert store.login(token).user.username == "admin"
    now[0] += 2
    assert store.login(token) is None
    with sqlite3.connect(tmp_path / "a.db") as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone() == (0,)


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


def test_db_files_are_isolated_per_store(tmp_path):
    one = AccountStore(tmp_path / "one.db", session_seconds=60, admin_username="admin", admin_password="admin")
    two = AccountStore(tmp_path / "two.db", session_seconds=60, admin_username="admin", admin_password="admin")
    token = one.create_session(one.authenticate("admin", "admin"))
    assert one.login(token) is not None and two.login(token) is None


# ── 비로그인: 기존 guest 동작 그대로 ─────────────────────────


def test_guest_toolbox_never_touches_account_db(app, gw):
    c = browser(app, gw)
    c.post("/api/toolbox/krri-road-cctv")
    c.delete("/api/toolbox/krri-road-cctv")
    c.get("/api/toolbox")
    with sqlite3.connect(load_settings().selections_db) as db:
        assert db.execute("SELECT COUNT(*) FROM account_toolboxes").fetchone() == (0,)
    with sqlite3.connect(load_settings().accounts_db) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone() == (0,)


# ── 계정 내 MCP ↔ Gateway guest selection ─────────────────


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


def test_merge_rule():
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
