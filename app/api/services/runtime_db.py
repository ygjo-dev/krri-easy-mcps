"""EASY runtime DB(SQLite, stdlib 만) 연결. 계정 · 내 MCP selection · AI Skills 가 각자 DB 파일을 가지고 이 연결을 쓴다.

DB 파일은 app/runtime_data/ 아래에 실행 때 생긴다 (gitignore). 경로는 main.Settings 가 정한다.
"""

import sqlite3
from contextlib import closing
from pathlib import Path


def open_db(path: Path) -> "_Transaction":
    """요청마다 짧게 여는 연결. ``with open_db(path) as db`` 한 덩어리가 transaction 하나다."""
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
