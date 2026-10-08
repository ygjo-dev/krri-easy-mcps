"""catalog: live 모드 BFF 에 가짜 Gateway catalog(gateway_catalog_fake)와 시계를 끼운 앱 ``live_client``."""

import pytest
from fastapi.testclient import TestClient

from app.api.integrations.krri_asap.gateway_client import RealGatewayClient
from app.api.main import create_app
from tests.app.api.integrations.krri_asap.gateway_catalog_fake import BASE_URL, Clock, FakeGateway


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def live_client(gateway, clock):
    app = create_app()
    app.state.gateway = RealGatewayClient(BASE_URL, cache_seconds=60, fetch_json=gateway, clock=clock)
    return TestClient(app)
