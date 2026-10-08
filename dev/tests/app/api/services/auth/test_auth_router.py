"""/api/auth — EASY 자체 로그인 HTTP contract. KRRI_ASAP 로그인(Keycloak/JWT)과 별개다.

- 응답은 ``{"user": null}`` 또는 ``{"user": {"username", "role"}}`` 뿐이다. password · hash · token · guest id 는 싣지 않는다.
- 로그인 실패는 없는 아이디 · 틀린 비밀번호 구분 없이 같은 401, 형식 오류는 입력값을 되돌리지 않는 400 이다. body 는 JSON 만 받는다.
- 세션 cookie ``kem_session`` (HttpOnly · SameSite=Lax · Path=/ · https 면 Secure) 은 Gateway guest cookie 와 따로다.
  로그아웃은 EASY 세션만 끝내고 guest cookie · Gateway selection 은 그대로 둔다.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.services.auth.account_service import SESSION_COOKIE
from app.api.services.auth.auth_router import LOGIN_FAILED_DETAIL, LOGIN_INVALID_DETAIL
from app.api.services.mcp_selection.selection_service import GUEST_COOKIE
from tests.app.api.services.browser_session import ADMIN, account_toolbox, browser, guest_of, login, session_cookie_header


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
