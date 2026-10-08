"""account_service — EASY 계정 · 세션 저장 (accounts.db).

- 비밀번호는 scrypt + 계정마다 salt hash 로만, 세션 token 은 SHA-256 hash 로만 저장한다.
- role 은 USER | ADMIN 뿐이다. 초기 관리자(KEM_ADMIN_*)는 그 이름이 없을 때 한 번만 만든다 (있으면 비밀번호를 바꾸지 않는다).
- 세션은 수명이 지나면 죽고 행도 지운다.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api.integrations.krri_asap.selection_client import RealSelectionClient
from app.api.main import create_app, load_settings
from app.api.services.auth.account_service import ROLE_ADMIN, ROLE_USER, AccountStore, hash_password, verify_password
from app.api.services.auth.account_service import SESSION_COOKIE
from tests.app.api.integrations.krri_asap.gateway_selection_fake import BASE_URL
from tests.app.api.services.browser_session import ADMIN, browser, guest_of, login


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


def test_db_files_are_isolated_per_store(tmp_path):
    one = AccountStore(tmp_path / "one.db", session_seconds=60, admin_username="admin", admin_password="admin")
    two = AccountStore(tmp_path / "two.db", session_seconds=60, admin_username="admin", admin_password="admin")
    token = one.create_session(one.authenticate("admin", "admin"))
    assert one.login(token) is not None and two.login(token) is None


def test_deleting_one_session_keeps_the_users_other_sessions(tmp_path):
    """로그아웃은 그 브라우저의 세션만 끝낸다. 같은 계정의 다른 브라우저 세션은 살아 있다."""
    store = AccountStore(tmp_path / "a.db", session_seconds=60, admin_username="admin", admin_password="admin")
    admin = store.authenticate("admin", "admin")
    first, second = store.create_session(admin), store.create_session(admin)
    store.delete_session(first)
    assert store.login(first) is None
    assert store.login(second).user.username == "admin"
