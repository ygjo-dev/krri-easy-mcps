"""RealAgenticAiClient: agentic_ai 기존 POST /chat/stream 을 httpx.MockTransport 로 흉내 내 검증.

fixture 이벤트 모양은 agentic_ai app/api/main.py · execution/workflow_execution.py 의 현재 흐름
(2026-09-22 read-only 확인)에서 필요한 칸만 옮겼다. step_end.failed · result.status 는 agentic 이
더한 칸이고, 모르는 칸도 그대로 통과해야 한다.
"""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.agentic_ai import (
    AgenticAiUnavailable,
    RealAgenticAiClient,
    make_agentic_ai_client,
    read_sse_events,
)
from app.main import AGENTIC_AI_UNAVAILABLE_DETAIL, create_app

BASE_URL = "http://agentic.internal.example:8000"

CCTV_EVENTS = [
    {"type": "step_start", "node": "resolve", "message": "발화를 해석하고 있습니다..."},
    {"type": "step_end", "node": "resolve", "message": "SELECT recipe_036"},
    {"type": "step_start", "node": "geocode_place", "message": "geo.geocode 호출 중입니다..."},
    {"type": "step_end", "node": "geocode_place", "message": "geo.geocode 완료", "failed": False},
    {"type": "step_start", "node": "find_cctv", "message": "road.getCctv 호출 중입니다..."},
    {"type": "step_end", "node": "find_cctv", "message": "road.getCctv 완료", "failed": False},
    {"type": "telemetry", "elapsed_ms": 1234},  # 모르는 type
    {
        "type": "result",
        "answer": "수원역 반경 15km 안에 CCTV 42대가 있습니다.",
        "commands": [{"op": "map.addLayer", "args": {"geojson": {"features": []}}}],
        "status": "success",
        "extra": {"future": True},  # 모르는 칸
    },
]


def sse(events, *, done=True, crlf=False) -> bytes:
    nl = "\r\n" if crlf else "\n"
    body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}{nl}{nl}" for e in events)
    if done:
        body += f"data: [DONE]{nl}{nl}"
    return body.encode("utf-8")


class Agentic:
    """MockTransport 뒤의 가짜 agentic. 받은 요청을 기억한다."""

    def __init__(self, body: bytes = b"", status=200, content_type="text/event-stream", raise_exc=None, stream=None):
        self.body, self.status, self.content_type = body, status, content_type
        self.raise_exc, self.stream = raise_exc, stream
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_exc:
            raise self.raise_exc(request)
        headers = {"content-type": self.content_type}
        if self.stream is not None:
            return httpx.Response(self.status, headers=headers, content=self.stream())
        return httpx.Response(self.status, headers=headers, content=self.body)


def client_for(agentic: Agentic) -> RealAgenticAiClient:
    return RealAgenticAiClient(BASE_URL, transport=httpx.MockTransport(agentic))


def run(coro):
    return asyncio.run(coro)


async def chunks(*parts: bytes):
    for p in parts:
        yield p


# ── SSE parser / client ─────────────────────────────────────────────


def test_valid_stream_keeps_events_in_order_with_korean_and_unknown_fields():
    agentic = Agentic(sse(CCTV_EVENTS))
    reply = run(client_for(agentic).chat_stream("수원역 근처 CCTV 띄워줘"))
    assert reply.events == CCTV_EVENTS
    assert reply.tool_io is None
    assert reply.events[-1]["answer"] == "수원역 반경 15km 안에 CCTV 42대가 있습니다."


def test_request_is_only_text_and_empty_context():
    agentic = Agentic(sse(CCTV_EVENTS))
    run(client_for(agentic).chat_stream("수원역 근처 CCTV 띄워줘"))
    (request,) = agentic.requests
    assert request.method == "POST"
    assert request.url.path == "/chat/stream"
    assert json.loads(request.content) == {"text": "수원역 근처 CCTV 띄워줘", "context": {}}
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


def test_parser_handles_chunk_splits_crlf_and_multibyte_boundaries():
    body = sse(CCTV_EVENTS, crlf=True)
    # 한글 한 글자 중간에서 자른다
    cut = body.index("수원역".encode()) + 1
    events = run(read_sse_events(chunks(body[:cut], body[cut:cut + 3], body[cut + 3:])))
    assert events == CCTV_EVENTS


def test_parser_ignores_comments_event_and_id_lines_and_joins_multiline_data():
    body = (
        ": keep-alive\n\n"
        "event: message\nid: 1\ndata: {\"type\": \"result\",\ndata: \"answer\": \"ok\", \"commands\": []}\n\n"
        "data: [DONE]\n\n"
    ).encode()
    assert run(read_sse_events(chunks(body))) == [{"type": "result", "answer": "ok", "commands": []}]


def test_done_without_trailing_blank_line_is_accepted_and_after_done_is_ignored():
    body = sse(CCTV_EVENTS, done=False) + b"data: [DONE]"
    assert run(read_sse_events(chunks(body))) == CCTV_EVENTS
    body = sse(CCTV_EVENTS) + b"data: {not json}\n\n"
    assert run(read_sse_events(chunks(body))) == CCTV_EVENTS


@pytest.mark.parametrize(
    "agentic",
    [
        Agentic(b'{"detail": "boom"}', status=500, content_type="application/json"),
        Agentic(b"<html>502</html>", status=502, content_type="text/html"),
        Agentic(sse(CCTV_EVENTS), content_type="application/json"),  # 200 이어도 SSE 가 아니면 실패
        Agentic(b"data: {oops}\n\n", content_type="text/event-stream"),  # JSON 아님
        Agentic(b'data: ["list"]\n\ndata: [DONE]\n\n'),  # object 아님
        Agentic(sse(CCTV_EVENTS, done=False)),  # [DONE] 없이 끝남
        Agentic(sse(CCTV_EVENTS[:-2])),  # result 없음
        Agentic(b"data: \xff\xfe\n\n"),  # UTF-8 아님
        Agentic(raise_exc=lambda r: httpx.ConnectError(f"refused {BASE_URL}", request=r)),
        Agentic(raise_exc=lambda r: httpx.ReadTimeout("timed out", request=r)),
    ],
    ids=["http500", "http502-html", "wrong-content-type", "malformed-json", "non-object", "missing-done",
         "missing-result", "not-utf8", "connect-refused", "timeout"],
)
def test_failures_raise_agentic_unavailable_without_url(agentic):
    with pytest.raises(AgenticAiUnavailable) as info:
        run(client_for(agentic).chat_stream("수원역 근처 CCTV 띄워줘"))
    assert BASE_URL not in str(info.value)
    assert "agentic.internal" not in str(info.value)


def test_stream_cut_mid_body_is_failure():
    async def cut():
        yield sse(CCTV_EVENTS[:3], done=False)
        raise httpx.ReadError("connection reset")

    with pytest.raises(AgenticAiUnavailable):
        run(client_for(Agentic(stream=cut)).chat_stream("x"))


def test_factory_modes():
    assert make_agentic_ai_client("mock").source == "mock"
    assert make_agentic_ai_client("live", BASE_URL).source == "live"
    with pytest.raises(ValueError):
        make_agentic_ai_client("live", "")
    with pytest.raises(ValueError):
        make_agentic_ai_client("nope")


def test_live_mode_requires_base_url_at_app_start(monkeypatch):
    monkeypatch.setenv("KEM_AGENTIC_AI_MODE", "live")
    monkeypatch.delenv("KEM_AGENTIC_AI_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        create_app()


def test_real_http_error_becomes_unavailable():
    # 127.0.0.1:9 (discard) 는 열려 있지 않다.
    with pytest.raises(AgenticAiUnavailable):
        run(RealAgenticAiClient("http://127.0.0.1:9", timeout_seconds=2).chat_stream("x"))


# ── execute endpoint (live) ─────────────────────────────────────────


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
    for marker in ("recipe_036", '"expected_recipe_id"', '"expected_tools"', '"commands"', "geojson", "map.addLayer",
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


def test_health_reports_live_agentic(monkeypatch):
    monkeypatch.setenv("KEM_AGENTIC_AI_MODE", "live")
    monkeypatch.setenv("KEM_AGENTIC_AI_BASE_URL", BASE_URL)
    body = TestClient(create_app()).get("/api/health").json()
    assert body["agentic_ai"] == "live"
    assert BASE_URL not in json.dumps(body)


def test_mock_mode_execute_unchanged():
    body = TestClient(create_app()).post("/api/demo/questions/suwon-station-cctv/execute").json()
    assert body["source"] == "mock"
    assert body["steps"][0]["request"] == {"query": "수원역"}
