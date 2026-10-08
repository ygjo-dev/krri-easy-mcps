"""EASY 로그인 · 계정 내 MCP 테스트가 같이 쓰는 브라우저 흉내 (auth · mcp_selection).

browser() 는 Gateway guest cookie 를 가진 브라우저 하나다. Gateway 는 gateway_selection_fake.FakeSelectionGateway 다.
account_toolbox() 는 selections.db 에 저장된 계정 내 MCP 을 직접 읽는다 (없으면 None = 아직 초기화 안 됨).
"""

import json
import sqlite3

from fastapi.testclient import TestClient

from app.api.main import load_settings
from app.api.services.auth.account_service import SESSION_COOKIE
from app.api.services.mcp_selection.selection_service import GUEST_COOKIE


ADMIN = {"username": "admin", "password": "admin"}


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
