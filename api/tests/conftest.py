"""테스트는 실제 EASY DB(data/easy.db)를 쓰지 않는다.

app.main 은 import 때 create_app() 을 한 번 부르므로, test 모듈을 읽기 전에 KEM_DB_PATH 를 임시 폴더로 돌린다.
그리고 테스트마다 새 DB 를 쓴다 (계정 · 세션 · 계정 도구함이 테스트 사이에 새지 않게).
"""

import os
import tempfile
from pathlib import Path

import pytest

os.environ["KEM_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="kem-test-db-")) / "import.db")


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KEM_DB_PATH", str(tmp_path / "easy.db"))
    for name in ("KEM_SESSION_HOURS", "KEM_ADMIN_USERNAME", "KEM_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
