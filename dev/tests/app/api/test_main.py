"""app/api/main.py — BFF 조립: KEM_* 설정, client mode, runtime data 위치, /api/health.

- Gateway · agentic_ai · skill_ai(AI Skills 자동 정리) 는 각각 mock | live 다. live 는 base URL(skill_ai 는 model 도)이 없으면
  뜨지 않는다 (틀린 곳을 조용히 부르지 않는다).
- /api/health 는 상태와 client mode 만 알려 준다. 내부 주소는 싣지 않는다.
- runtime data(계정 · 내 MCP · Skill)는 KEM_RUNTIME_DATA_DIR 아래 정해진 자리에 생긴다.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app, load_settings
from tests.app.api.integrations.agentic_ai.agentic_fake import BASE_URL
from tests.app.api.integrations.skill_ai import skill_ai_fake

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_health_reports_ok_and_client_modes(client):
    assert client.get("/api/health").json() == {"status": "ok", "gateway": "mock", "agentic_ai": "mock", "skill_ai": "mock"}


def test_health_reports_live_agentic(monkeypatch):
    monkeypatch.setenv("KEM_AGENTIC_AI_MODE", "live")
    monkeypatch.setenv("KEM_AGENTIC_AI_BASE_URL", BASE_URL)
    body = TestClient(create_app()).get("/api/health").json()
    assert body["agentic_ai"] == "live"
    assert BASE_URL not in json.dumps(body)


def test_live_agentic_mode_without_base_url_fails_at_startup(monkeypatch):
    monkeypatch.setenv("KEM_AGENTIC_AI_MODE", "live")
    monkeypatch.delenv("KEM_AGENTIC_AI_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        create_app()


def test_health_reports_live_skill_ai_without_internal_details(monkeypatch):
    monkeypatch.setenv("KEM_SKILL_AI_MODE", "live")
    monkeypatch.setenv("KEM_SKILL_AI_BASE_URL", skill_ai_fake.BASE_URL)
    monkeypatch.setenv("KEM_SKILL_AI_MODEL", skill_ai_fake.MODEL)
    monkeypatch.setenv("KEM_SKILL_AI_API_KEY", skill_ai_fake.API_KEY)
    monkeypatch.setenv("KEM_SKILL_AI_TIMEOUT_SECONDS", "77")
    app = create_app()
    body = TestClient(app).get("/api/health").json()
    assert body["skill_ai"] == "live"
    for hidden in (skill_ai_fake.BASE_URL, skill_ai_fake.MODEL, skill_ai_fake.API_KEY):
        assert hidden not in json.dumps(body)
    assert app.state.skill_ai._timeout.read == 77


@pytest.mark.parametrize("missing", ["KEM_SKILL_AI_BASE_URL", "KEM_SKILL_AI_MODEL"])
def test_live_skill_ai_without_base_url_or_model_fails_at_startup(monkeypatch, missing):
    monkeypatch.setenv("KEM_SKILL_AI_MODE", "live")
    monkeypatch.setenv("KEM_SKILL_AI_BASE_URL", skill_ai_fake.BASE_URL)
    monkeypatch.setenv("KEM_SKILL_AI_MODEL", skill_ai_fake.MODEL)
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError):
        create_app()


def test_unknown_skill_ai_mode_fails_at_startup(monkeypatch):
    monkeypatch.setenv("KEM_SKILL_AI_MODE", "gpt")
    with pytest.raises(ValueError):
        create_app()


def test_skill_ai_defaults_to_mock_with_a_long_timeout(monkeypatch):
    for name in ("KEM_SKILL_AI_MODE", "KEM_SKILL_AI_BASE_URL", "KEM_SKILL_AI_MODEL", "KEM_SKILL_AI_API_KEY",
                 "KEM_SKILL_AI_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()
    assert (settings.skill_ai_mode, settings.skill_ai_base_url, settings.skill_ai_api_key) == ("mock", "", "")
    assert 60 <= settings.skill_ai_timeout_seconds <= 180


def test_runtime_data_layout_follows_kem_runtime_data_dir(tmp_path, monkeypatch):
    """계정 · 내 MCP · Skill 은 DB 파일이 따로다. 폴더는 앱이 처음 뜰 때 만든다."""
    monkeypatch.setenv("KEM_RUNTIME_DATA_DIR", str(tmp_path / "rt"))
    settings = load_settings()
    assert settings.accounts_db == tmp_path / "rt" / "accounts" / "accounts.db"
    assert settings.selections_db == tmp_path / "rt" / "mcp_selections" / "selections.db"
    assert settings.skills_db == tmp_path / "rt" / "skills" / "skills.db"
    assert settings.skill_packages_dir == tmp_path / "rt" / "skills" / "uploaded_packages"
    create_app()
    for path in (settings.accounts_db, settings.selections_db, settings.skills_db):
        assert path.is_file()
    assert settings.skill_packages_dir.is_dir()


def test_default_paths_are_inside_the_repository(monkeypatch):
    """설정이 없으면 MCP 정의는 app/api/mcp_definitions/, runtime data 는 app/runtime_data/ (gitignore) 다."""
    for name in ("KEM_RUNTIME_DATA_DIR", "KEM_MCP_DEFINITIONS_DIR"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()
    assert settings.runtime_data_dir == REPO_ROOT / "app" / "runtime_data"
    assert settings.mcp_definitions_dir == REPO_ROOT / "app" / "api" / "mcp_definitions"
    assert sorted(p.name for p in settings.mcp_definitions_dir.glob("*.yaml")) == [
        "demo_questions.yaml", "planned_mcps.yaml", "presentation.yaml"]
