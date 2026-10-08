"""selections.db — 계정 내 MCP 과 세션 동기화 기록. accounts.db 와 파일이 달라 FK 대신 세션 만료 시각으로 정리한다."""

import sqlite3

from app.api.services.auth.account_service import Login, User
from app.api.services.mcp_selection.selection_repository import SelectionStore


def test_save_keeps_account_toolbox_and_session_sync_together(tmp_path):
    store = SelectionStore(tmp_path / "selections.db", clock=lambda: 100.0)
    login = Login("t1", User(1, "admin", "ADMIN"), expires_at=200.0)
    assert store.toolbox(login.user) is None and store.session_sync(login) is None
    store.save(login, "guest-hash", ["a", "b"])
    assert store.toolbox(login.user) == ["a", "b"]
    sync = store.session_sync(login)
    assert sync.guest == "guest-hash" and sync.mcp_ids == ("a", "b")


def test_expired_session_syncs_are_removed_on_save(tmp_path):
    now = [100.0]
    store = SelectionStore(tmp_path / "selections.db", clock=lambda: now[0])
    user = User(1, "admin", "ADMIN")
    old = Login("old", user, expires_at=150.0)
    store.save(old, "g", ["a"])
    now[0] = 151.0
    store.save(Login("new", user, expires_at=300.0), "g", ["a"])
    with sqlite3.connect(tmp_path / "selections.db") as db:
        assert db.execute("SELECT token_hash FROM session_syncs").fetchall() == [("new",)]
    assert store.toolbox(user) == ["a"]
