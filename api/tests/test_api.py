import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import load_settings

TRUSTED_KEYS = ("recipe_id", "expected_recipe_id", "expected_tools", "semantic_values", "context_preset")
INTERNAL_MARKERS = ("http://", "https://", "host.docker.internal", "Authorization", "token", "password", "secret")


@pytest.fixture
def client():
    return TestClient(create_app())


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "gateway": "mock", "agentic_ai": "mock"}


def test_catalog_lists_four_servers_joined_with_presentation(client):
    cards = client.get("/api/mcps").json()
    assert [c["server_id"] for c in cards] == ["asap-mcp-core", "otp-router", "r5-server", "web-search"]
    core = cards[0]
    assert core["display_name"] == "ASAP Core MCP"
    assert core["tool_count"] == 4
    assert core["source"] == "mock"
    assert {"summary", "category", "organization", "status"} <= core.keys()


def test_catalog_has_no_internal_endpoint_or_credential(client):
    body = json.dumps([client.get("/api/mcps").json()] + [
        client.get(f"/api/mcps/{c['server_id']}").json() for c in client.get("/api/mcps").json()
    ])
    for marker in INTERNAL_MARKERS:
        assert marker not in body


def test_detail_tools_have_parameters_not_raw_schema(client):
    detail = client.get("/api/mcps/asap-mcp-core").json()
    geocode = next(t for t in detail["tools"] if t["name"] == "geo.geocode")
    assert geocode["parameters"] == [
        {"name": "query", "type": "string", "required": True, "description": "", "default": None, "enum": None}
    ]
    assert "input_schema" not in geocode


def test_detail_unknown_server_404(client):
    assert client.get("/api/mcps/nope").status_code == 404


def test_demo_questions_expose_only_id_and_text(client):
    questions = client.get("/api/mcps/asap-mcp-core/demo-questions").json()
    assert len(questions) == 4
    for q in questions:
        assert set(q) == {"question_id", "display_text"}
    assert client.get("/api/mcps/web-search/demo-questions").json() == []


def test_disabled_question_hidden_and_not_executable(tmp_path, monkeypatch):
    settings = load_settings()
    (tmp_path / "presentation.yaml").write_text((settings.config_dir / "presentation.yaml").read_text())
    (tmp_path / "demo_questions.yaml").write_text(
        "questions:\n"
        "  - {question_id: off, mcp_server_id: asap-mcp-core, display_text: x, enabled: false}\n"
    )
    monkeypatch.setenv("KEM_CONFIG_DIR", str(tmp_path))
    c = TestClient(create_app())
    assert c.get("/api/mcps/asap-mcp-core/demo-questions").json() == []
    assert c.post("/api/demo/questions/off/execute").status_code == 404


def test_execute_mock_returns_trace_and_answer(client):
    r = client.post("/api/demo/questions/suwon-station-cctv/execute")
    assert r.status_code == 200
    body = r.json()
    assert body["resolve_status"] == "SELECT"
    assert body["matches_expected_recipe"] is True
    assert body["matches_expected_tools"] is True
    assert [(s["tool"], s["status"]) for s in body["steps"]] == [("geo.geocode", "success"), ("road.getCctv", "success")]
    assert body["steps"][0]["request"] == {"query": "수원역"}
    assert "CCTV" in body["answer"]
    assert body["map_command_count"] == 1
    assert body["limitations"]


def test_every_enabled_question_resolves_as_expected(client):
    for q in client.get("/api/mcps/asap-mcp-core/demo-questions").json():
        body = client.post(f"/api/demo/questions/{q['question_id']}/execute").json()
        assert body["matches_expected_recipe"] is True, q
        assert body["matches_expected_tools"] is True, q


def test_execute_response_has_no_trusted_metadata_or_commands(client):
    body = client.post("/api/demo/questions/busan-station-district/execute").json()
    text = json.dumps(body, ensure_ascii=False)
    for key in TRUSTED_KEYS:
        assert f'"{key}"' not in text
    assert "recipe_034" not in text
    assert "commands" not in body


def test_execute_unknown_question_404(client):
    assert client.post("/api/demo/questions/nope/execute").status_code == 404


def test_registration_inspect_mock(client):
    body = client.post("/api/registration/inspect", json={"endpoint": "https://example.org/mcp"}).json()
    assert body["source"] == "mock"
    assert body["server_info"]["name"]
    assert body["capabilities"]
    assert body["tools"][0]["name"]


def test_registration_inspect_rejects_non_http(client):
    assert client.post("/api/registration/inspect", json={"endpoint": "file:///etc/passwd"}).status_code == 422
