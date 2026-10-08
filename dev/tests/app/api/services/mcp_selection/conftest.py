"""mcp_selection: 가짜 Gateway 를 쓰는 BFF(services/conftest.py 의 app)에 붙은 브라우저 하나 ``live_client``."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def live_client(app):
    return TestClient(app)
