"""AI Skills: 기본 BFF ``app``, 로그인한 ADMIN ``admin``, 로그인한 일반 사용자 ``user``."""

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from tests.app.api.services.skills.skill_packages import login


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def admin(app):
    return login(TestClient(app))


@pytest.fixture
def user(app):
    app.state.accounts.create_user("member", "member-pw")
    return login(TestClient(app), {"username": "member", "password": "member-pw"})
