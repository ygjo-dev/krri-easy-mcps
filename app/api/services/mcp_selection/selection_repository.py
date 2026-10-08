"""계정 내 MCP 저장소 (SQLite selections.db, stdlib 만). 동기화 규칙은 selection_service.py.

표 (selections.db)
    account_toolboxes 계정 내 MCP(mcp_id JSON 목록). **행이 없으면 아직 초기화 안 됨**, "[]" 이면 일부러 비운 내 MCP
    session_syncs     로그인 세션(token_hash)이 마지막으로 맞춘 guest(SHA-256) 와 내 MCP. 세션 만료 시각까지만 뜻이 있다

user_id · token_hash 는 accounts.db 의 users · sessions 값이다. DB 파일이 달라 FK 는 없다.
세션이 끝나면(만료 · 로그아웃) 그 token_hash 는 다시 오지 않으므로, 만료가 지난 session_syncs 행은 쓸 때 지운다.
guest id 원문 · 세션 token 원문은 두지 않는다.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..auth.account_service import Login, User
from ..runtime_db import open_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS account_toolboxes (
    user_id    INTEGER PRIMARY KEY,
    mcp_ids    TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS session_syncs (
    token_hash     TEXT PRIMARY KEY,
    synced_guest   TEXT,
    synced_mcp_ids TEXT NOT NULL,
    expires_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS session_syncs_expires_at ON session_syncs(expires_at);
"""


@dataclass(frozen=True)
class SessionSync:
    """이 세션이 마지막으로 계정과 맞춘 guest(hash) · 내 MCP."""

    guest: str | None
    mcp_ids: tuple[str, ...]


class SelectionStore:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self._path = Path(path)
        self._clock = clock
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open_db(self._path) as db:
            db.executescript(_SCHEMA)

    def toolbox(self, user: User) -> list[str] | None:
        """계정 내 MCP. None = 아직 한 번도 초기화 안 됨 ([] 은 일부러 비운 내 MCP)."""
        with open_db(self._path) as db:
            row = db.execute("SELECT mcp_ids FROM account_toolboxes WHERE user_id = ?", (user.id,)).fetchone()
        return json.loads(row[0]) if row else None

    def session_sync(self, login: Login) -> SessionSync | None:
        """이 세션이 맞춘 기록. 아직 한 번도 안 맞췄으면 None."""
        with open_db(self._path) as db:
            row = db.execute(
                "SELECT synced_guest, synced_mcp_ids FROM session_syncs WHERE token_hash = ?", (login.token_hash,)
            ).fetchone()
        return SessionSync(row[0], tuple(json.loads(row[1]))) if row else None

    def save(self, login: Login, guest: str | None, mcp_ids: list[str]) -> None:
        """Gateway 가 실제로 반영한 내 MCP 을 계정에 저장하고, 이 세션이 그 guest 와 맞췄다고 적는다 (한 transaction)."""
        value = json.dumps(list(mcp_ids))
        now = self._clock()
        with open_db(self._path) as db:
            db.execute("DELETE FROM session_syncs WHERE expires_at <= ?", (now,))
            db.execute(
                "INSERT INTO account_toolboxes (user_id, mcp_ids, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET mcp_ids = excluded.mcp_ids, updated_at = excluded.updated_at",
                (login.user.id, value, now),
            )
            db.execute(
                "INSERT INTO session_syncs (token_hash, synced_guest, synced_mcp_ids, expires_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(token_hash) DO UPDATE SET synced_guest = excluded.synced_guest, "
                "synced_mcp_ids = excluded.synced_mcp_ids, expires_at = excluded.expires_at",
                (login.token_hash, guest, value, login.expires_at),
            )
