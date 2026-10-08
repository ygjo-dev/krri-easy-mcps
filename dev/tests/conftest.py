"""모든 테스트에 공통인 준비.

- 테스트는 실제 EASY runtime data(app/runtime_data/)를 쓰지 않는다.
  app.api.main 은 import 때 create_app() 을 한 번 부르므로, test 모듈을 읽기 전에 KEM_RUNTIME_DATA_DIR 를 임시 폴더로 돌린다.
  그리고 테스트마다 새 runtime data 폴더를 쓴다 (계정 · 세션 · 계정 내 MCP · Skill 이 테스트 사이에 새지 않게).
- ``client``: 기본 설정(Gateway · agentic_ai 모두 mock)으로 조립한 BFF 하나.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

os.environ["KEM_RUNTIME_DATA_DIR"] = tempfile.mkdtemp(prefix="kem-test-runtime-")

from app.api.main import create_app  # noqa: E402 — 위 환경변수를 먼저 정한다


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KEM_RUNTIME_DATA_DIR", str(tmp_path / "runtime_data"))
    for name in ("KEM_SESSION_HOURS", "KEM_ADMIN_USERNAME", "KEM_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client():
    return TestClient(create_app())
