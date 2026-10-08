"""/api/mcps/{id}/demo-questions · /api/demo/questions/{id}/execute — AI로 사용해보기 HTTP contract.

- 브라우저는 question_id 만 보낸다. 질문 목록은 {question_id, display_text, runnable} 뿐이다.
- 실행 질문은 BFF 가 trusted display_text 를 agentic_ai 기존 /chat/stream 에 발화로 보낸다. recipe_id 를 지정하지 않는다.
- 예시 질문(runnable false)은 409 이고 agentic_ai 를 부르지 않는다. 모르는 · 꺼진 질문은 404.
- 응답에는 recipe_id 원문 · expected_* · 지도 명령 본문 · 내부 주소가 없다. agentic_ai 실패는 502 (mock 으로 넘어가지 않는다).
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.main import AGENTIC_AI_UNAVAILABLE_DETAIL, create_app, load_settings
from tests.app.api.integrations.agentic_ai.agentic_fake import BASE_URL, CCTV_EVENTS, Agentic, client_for, sse


TRUSTED_KEYS = ("recipe_id", "expected_recipe_id", "expected_tools", "expected_mcp_ids", "semantic_values", "context_preset")


def test_demo_questions_belong_to_one_logical_mcp_each(client):
    owners = {
        "krri-map-location": ["iksan-station-location", "cheongju-airport-location"],
        "krri-railway-network": ["cheonan-station-lines", "gyeongbu-line-section", "chungbuk-line-stations"],
        "krri-admin-boundary": ["nonsan-boundary", "busan-station-district"],
        "krri-road-cctv": ["suwon-station-cctv"],
        "web-research": ["web-rail-policy-news", "web-fetch-krri-home"],
    }
    for mcp_id, expected in owners.items():
        questions = client.get(f"/api/mcps/{mcp_id}/demo-questions").json()
        assert [q["question_id"] for q in questions] == expected
        for q in questions:
            assert set(q) == {"question_id", "display_text", "runnable"}
    # agentic_ai 에 recipe 가 없는 MCP 의 질문은 예시다
    assert {q["runnable"] for q in client.get("/api/mcps/web-research/demo-questions").json()} == {False}
    assert {q["runnable"] for q in client.get("/api/mcps/krri-road-cctv/demo-questions").json()} == {True}


def test_disabled_question_hidden_and_not_executable(tmp_path, monkeypatch):
    settings = load_settings()
    (tmp_path / "presentation.yaml").write_text((settings.mcp_definitions_dir / "presentation.yaml").read_text())
    (tmp_path / "demo_questions.yaml").write_text(
        "questions:\n"
        "  - {question_id: off, mcp_id: krri-map-location, display_text: x, enabled: false}\n"
    )
    (tmp_path / "planned_mcps.yaml").write_text((settings.mcp_definitions_dir / "planned_mcps.yaml").read_text())
    monkeypatch.setenv("KEM_MCP_DEFINITIONS_DIR", str(tmp_path))
    c = TestClient(create_app())
    assert c.get("/api/mcps/krri-map-location/demo-questions").json() == []
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
    # 한 질문이 두 logical MCP 의 Tool 을 쓴다. 단계마다 그 Tool 의 MCP 이름.
    assert [s["mcp_name"] for s in body["steps"]] == ["지도/위치 검색", "도로/CCTV 조회"]
    assert "CCTV" in body["answer"]
    assert body["map_command_count"] == 1
    assert body["limitations"]


def test_every_enabled_question_resolves_as_expected(client):
    runnable = [q for q in client.app.state.demo_questions.values() if q.runnable]
    assert len(runnable) >= 14
    for q in runnable:
        body = client.post(f"/api/demo/questions/{q.question_id}/execute").json()
        assert body["matches_expected_recipe"] is True, q
        assert body["matches_expected_tools"] is True, q


def test_example_only_questions_are_not_executed(client):
    examples = [q for q in client.app.state.demo_questions.values() if not q.runnable]
    assert examples
    for q in examples:
        r = client.post(f"/api/demo/questions/{q.question_id}/execute")
        assert r.status_code == 409 and "예시" in r.json()["detail"], q.question_id


def test_execute_response_has_no_trusted_metadata_or_commands(client):
    body = client.post("/api/demo/questions/busan-station-district/execute").json()
    text = json.dumps(body, ensure_ascii=False)
    for key in TRUSTED_KEYS:
        assert f'"{key}"' not in text
    assert "recipe_034" not in text
    assert "commands" not in body


def test_execute_unknown_question_404(client):
    assert client.post("/api/demo/questions/nope/execute").status_code == 404


# ── live agentic_ai (가짜 /chat/stream) ─────────────────────────────


def live_app(agentic: Agentic) -> TestClient:
    app = create_app()
    app.state.agentic_ai = client_for(agentic)
    return TestClient(app)


def test_execute_live_returns_normalized_execution():
    agentic = Agentic(sse(CCTV_EVENTS))
    c = live_app(agentic)
    r = c.post("/api/demo/questions/suwon-station-cctv/execute")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "live"
    assert body["resolve_status"] == "SELECT"
    assert body["matches_expected_recipe"] is True
    assert body["matches_expected_tools"] is True
    assert [(s["tool"], s["status"]) for s in body["steps"]] == [("geo.geocode", "success"), ("road.getCctv", "success")]
    assert all(s["request"] is None and s["response"] is None for s in body["steps"])
    assert body["answer"] == "수원역 반경 15km 안에 CCTV 42대가 있습니다."
    assert body["map_command_count"] == 1
    assert body["limitations"] == ["기존 agentic_ai /chat/stream 이벤트에는 tool 단위 Request/Response 가 없어 표시하지 않습니다."]
    # 요청에는 trusted display_text 만 갔다
    assert json.loads(agentic.requests[0].content) == {"text": "수원역 근처 CCTV 띄워줘", "context": {}}


def test_execute_live_response_has_no_internal_or_trusted_values():
    c = live_app(Agentic(sse(CCTV_EVENTS)))
    body = c.post("/api/demo/questions/suwon-station-cctv/execute").json()
    text = json.dumps(body, ensure_ascii=False)
    for marker in ("recipe_036", '"expected_recipe_id"', '"expected_tools"', '"expected_mcp_ids"', '"commands"', "geojson", "map.addLayer",
                   BASE_URL, "agentic.internal", "telemetry", "future", "(mock"):
        assert marker not in text, marker
    # agentic 의 result.status 는 public DTO 로 옮기지 않는다 (steps[].status 는 기존 DTO 칸)
    assert "status" not in body and "extra" not in body


@pytest.mark.parametrize(
    "agentic",
    [
        Agentic(b'{"detail": "Traceback at /srv/app.py secret"}', status=500, content_type="application/json"),
        Agentic(sse(CCTV_EVENTS, done=False)),
        Agentic(raise_exc=lambda r: httpx.ConnectError(f"refused {BASE_URL}", request=r)),
    ],
    ids=["http500", "missing-done", "connect-refused"],
)
def test_execute_live_failure_is_sanitized_502(agentic):
    r = live_app(agentic).post("/api/demo/questions/suwon-station-cctv/execute")
    assert r.status_code == 502
    assert r.json() == {"detail": AGENTIC_AI_UNAVAILABLE_DETAIL}


def test_execute_unknown_question_does_not_call_agentic():
    agentic = Agentic(sse(CCTV_EVENTS))
    assert live_app(agentic).post("/api/demo/questions/nope/execute").status_code == 404
    assert agentic.requests == []


def test_example_only_question_is_409_without_calling_agentic():
    """agentic_ai 에 recipe 가 없는 MCP 의 질문은 예시다. 실행 버튼이 와도 agentic_ai 로 보내지 않는다."""
    agentic = Agentic(sse(CCTV_EVENTS))
    c = live_app(agentic)
    example = next(q for q in c.app.state.demo_questions.values() if q.enabled and not q.runnable)
    r = c.post(f"/api/demo/questions/{example.question_id}/execute")
    assert r.status_code == 409 and "예시" in r.json()["detail"]
    assert agentic.requests == []


def test_mock_mode_execute_unchanged():
    body = TestClient(create_app()).post("/api/demo/questions/suwon-station-cctv/execute").json()
    assert body["source"] == "mock"
    assert body["steps"][0]["request"] == {"query": "수원역"}
