"""EASY 자체 계정 · 로그인 세션 · 계정 내 MCP (SQLite, stdlib 만).

**KRRI_ASAP 로그인(Keycloak/JWT)과 별개다.** Gateway 에 EASY 계정을 알리지 않고, Gateway 는 계속 브라우저의
guest cookie(asap_mcp_guest) 로만 사용자를 구분한다. EASY 계정은 그 guest selection 을 계정에 저장 · 복원할 뿐이다
(규칙은 routes/toolbox.py).

표
    users             username · password_hash(scrypt + salt) · role(USER | ADMIN)
    account_toolboxes 계정 내 MCP(mcp_id JSON 목록). **행이 없으면 아직 초기화 안 됨**, "[]" 이면 일부러 비운 내 MCP
    sessions          token_hash(SHA-256) · user · 만료 시각 · 이 세션이 마지막으로 맞춘 guest(SHA-256) 와 내 MCP

세션 token 원문은 브라우저 cookie 에만 있다. DB 에는 hash 만 둔다. password · hash · token 은 JSON · 로그에 싣지 않는다.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request

SESSION_COOKIE = "kem_session"
SESSION_COOKIE_PATH = "/"

ROLE_USER = "USER"
ROLE_ADMIN = "ADMIN"
ROLES = (ROLE_USER, ROLE_ADMIN)

# hashlib.scrypt 비용. 한 번 ~50ms, 메모리 16MB (128 * r * n).
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('USER', 'ADMIN')),
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS account_toolboxes (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    mcp_ids    TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash     TEXT PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at     REAL NOT NULL,
    expires_at     REAL NOT NULL,
    synced_guest   TEXT,
    synced_mcp_ids TEXT
);
CREATE INDEX IF NOT EXISTS sessions_expires_at ON sessions(expires_at);
"""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(digest) // 2)
    except ValueError:
        return False
    return hmac.compare_digest(actual.hex(), digest)


# 없는 사용자도 같은 비용으로 검사한다 (응답 시간으로 사용자 존재를 덜 드러내게).
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def guest_key(guest_id: str | None) -> str | None:
    """세션에 적는 guest 표시. guest id 원문 대신 hash 를 둔다 (같은 guest 인지만 본다)."""
    return _digest(guest_id) if guest_id else None


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str

    def public(self) -> dict:
        """브라우저로 나가는 사용자 정보. 이것 말고는 내보내지 않는다."""
        return {"username": self.username, "role": self.role}


@dataclass(frozen=True)
class Login:
    """로그인된 요청 한 건. synced_* 는 이 세션이 마지막으로 계정과 맞춘 guest(hash) · 내 MCP (없으면 None)."""

    token_hash: str
    user: User
    synced_guest: str | None
    synced_mcp_ids: tuple[str, ...] | None


class AccountStore:
    def __init__(
        self,
        path: Path,
        *,
        session_seconds: float,
        admin_username: str,
        admin_password: str,
        clock: Callable[[], float] = time.time,
    ):
        self._path = Path(path)
        self._session_seconds = session_seconds
        self._clock = clock
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(_SCHEMA)
        if admin_username and self._user_row(admin_username) is None:
            self.create_user(admin_username, admin_password, ROLE_ADMIN)

    @property
    def session_seconds(self) -> float:
        return self._session_seconds

    def _db(self):
        return open_db(self._path)

    # ── users ─────────────────────────────────────────────

    def create_user(self, username: str, password: str, role: str = ROLE_USER) -> User:
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        with self._db() as db:
            cur = db.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, hash_password(password), role, self._clock()),
            )
        return User(cur.lastrowid, username, role)

    def _user_row(self, username: str):
        with self._db() as db:
            return db.execute(
                "SELECT id, username, role, password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()

    def authenticate(self, username: str, password: str) -> User | None:
        row = self._user_row(username)
        if row is None:
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, row[3]):
            return None
        return User(row[0], row[1], row[2])

    # ── sessions ──────────────────────────────────────────

    def create_session(self, user: User) -> str:
        """새 세션 token(원문)을 돌려준다. 원문은 cookie 로만 나가고 DB 에는 hash 만 남는다. 만료된 세션은 지운다."""
        token = secrets.token_urlsafe(32)
        now = self._clock()
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            db.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_digest(token), user.id, now, now + self._session_seconds),
            )
        return token

    def login(self, token: str | None) -> Login | None:
        """cookie 의 token → 살아 있는 세션. 없거나 만료면 None (만료 행은 지운다)."""
        if not token:
            return None
        token_hash = _digest(token)
        with self._db() as db:
            row = db.execute(
                "SELECT s.expires_at, u.id, u.username, u.role, s.synced_guest, s.synced_mcp_ids "
                "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            if row[0] <= self._clock():
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
        synced = tuple(json.loads(row[5])) if row[5] is not None else None
        return Login(token_hash, User(row[1], row[2], row[3]), row[4], synced)

    def delete_session(self, token: str | None) -> None:
        if token:
            with self._db() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))

    # ── account toolbox ───────────────────────────────────

    def toolbox(self, user: User) -> list[str] | None:
        """계정 내 MCP. None = 아직 한 번도 초기화 안 됨 ([] 은 일부러 비운 내 MCP)."""
        with self._db() as db:
            row = db.execute("SELECT mcp_ids FROM account_toolboxes WHERE user_id = ?", (user.id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_toolbox(self, login: Login, guest: str | None, mcp_ids: list[str]) -> None:
        """Gateway 가 실제로 반영한 내 MCP을 계정에 저장하고, 이 세션이 그 guest 와 맞췄다고 적는다 (한 transaction)."""
        value = json.dumps(list(mcp_ids))
        with self._db() as db:
            db.execute(
                "INSERT INTO account_toolboxes (user_id, mcp_ids, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET mcp_ids = excluded.mcp_ids, updated_at = excluded.updated_at",
                (login.user.id, value, self._clock()),
            )
            db.execute(
                "UPDATE sessions SET synced_guest = ?, synced_mcp_ids = ? WHERE token_hash = ?",
                (guest, value, login.token_hash),
            )


def open_db(path: Path) -> "_Transaction":
    """요청마다 짧게 여는 연결. ``with open_db(path) as db`` 한 덩어리가 transaction 하나다 (skills.py 도 같은 DB)."""
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    return _Transaction(conn)


class _Transaction:
    """sqlite3 연결의 ``with`` 는 commit/rollback 만 하고 닫지 않는다. 여기서는 닫기까지 한다."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self._conn.__enter__()

    def __exit__(self, *exc):
        with closing(self._conn):
            return self._conn.__exit__(*exc)


LOGIN_REQUIRED_DETAIL = "로그인이 필요합니다."
ADMIN_REQUIRED_DETAIL = "관리자만 사용할 수 있습니다."


def current_login(request: Request) -> Login | None:
    return request.app.state.accounts.login(request.cookies.get(SESSION_COOKIE))


def require_admin(request: Request) -> Login:
    """서버 쪽 ADMIN 검사 (FastAPI dependency). 로그인 안 함 → 401, ADMIN 아님 → 403. EASY 자체 role 만 본다."""
    login = current_login(request)
    if login is None:
        raise HTTPException(status_code=401, detail=LOGIN_REQUIRED_DETAIL)
    if login.user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail=ADMIN_REQUIRED_DETAIL)
    return login
