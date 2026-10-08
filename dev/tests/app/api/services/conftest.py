"""auth · mcp_selection 공통: live 모드 BFF 에 가짜 Gateway(catalog + selection)를 끼운 앱.

``gw`` 는 FakeSelectionGateway (selection 저장 · 호출 기록), ``app`` 은 그 Gateway 를 쓰는 BFF 다.
"""

import pytest

from app.api.integrations.krri_asap.gateway_client import RealGatewayClient
from app.api.integrations.krri_asap.selection_client import RealSelectionClient
from app.api.main import create_app
from tests.app.api.integrations.krri_asap.gateway_selection_fake import BASE_URL, MARKET, TOOLS, FakeSelectionGateway


@pytest.fixture
def gw():
    return FakeSelectionGateway()


@pytest.fixture
def app(gw):
    app = create_app()
    responses = {"/api/tools": TOOLS, "/api/mcp-market": MARKET}
    app.state.gateway = RealGatewayClient(BASE_URL, fetch_json=responses.__getitem__)
    app.state.selection = RealSelectionClient(BASE_URL, transport=gw)
    return app
