"""agentic_ai_client — KRRI EASY 가 agentic_ai 를 부르는 contract.

부르는 것: agentic_ai 의 **기존** ``POST /chat/stream`` 하나 (EASY 전용 API 를 만들지 않는다).
    요청  {"text": <고정 질문의 display_text>, "context": {}} — recipe_id · expected_* 를 보내지 않는다.
          Resolve · recipe 선택 · 실행은 agentic_ai pipeline 이 한다 (EASY 가 Resolve 를 건너뛰지 않는다).
    응답  text/event-stream, ``data: <json>`` 줄들, 끝은 ``data: [DONE]``. 모르는 type · 칸도 그대로 담는다.
실패: 연결 실패 · timeout · 200 아님 · SSE 아님 · JSON/object 아님 · UTF-8 아님 · [DONE] 전에 끝남 · result 없음 → AgenticAiUnavailable.
      메시지에 URL 을 싣지 않고, mock 답으로 바꾸지 않는다.
"""

import json

import httpx
import pytest

from app.api.integrations.agentic_ai.agentic_ai_client import (
    AgenticAiUnavailable,
    MockAgenticAiClient,
    RealAgenticAiClient,
    make_agentic_ai_client,
    read_sse_events,
)
from tests.app.api.integrations.agentic_ai.agentic_fake import BASE_URL, CCTV_EVENTS, Agentic, client_for, run, sse


async def chunks(*parts: bytes):
    for p in parts:
        yield p


# ── 요청 ────────────────────────────────────────────────────────────


def test_request_sends_display_text_as_utterance_without_recipe_id():
    agentic = Agentic(sse(CCTV_EVENTS))
    run(client_for(agentic).chat_stream("수원역 근처 CCTV 띄워줘"))
    (request,) = agentic.requests
    assert request.method == "POST"
    assert request.url.path == "/chat/stream"
    assert json.loads(request.content) == {"text": "수원역 근처 CCTV 띄워줘", "context": {}}
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers
    assert request.headers["accept"] == "text/event-stream"


# ── 응답 (SSE) ───────────────────────────────────────────────────────


def test_valid_stream_keeps_events_in_order_with_korean_and_unknown_fields():
    agentic = Agentic(sse(CCTV_EVENTS))
    reply = run(client_for(agentic).chat_stream("수원역 근처 CCTV 띄워줘"))
    assert reply.events == CCTV_EVENTS
    assert reply.tool_io is None
    assert reply.events[-1]["answer"] == "수원역 반경 15km 안에 CCTV 42대가 있습니다."


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


# ── 실패 ────────────────────────────────────────────────────────────


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


def test_real_http_error_becomes_unavailable():
    # 127.0.0.1:9 (discard) 는 열려 있지 않다.
    with pytest.raises(AgenticAiUnavailable):
        run(RealAgenticAiClient("http://127.0.0.1:9", timeout_seconds=2).chat_stream("x"))


def test_live_failure_raises_instead_of_returning_a_mock_reply():
    """mock 이 답을 아는 발화라도 live 가 실패하면 예외다. live → mock 자동 전환이 없다."""
    text = "수원역 근처 CCTV 띄워줘"
    assert run(MockAgenticAiClient().chat_stream(text)).events  # 같은 발화를 mock 은 안다
    with pytest.raises(AgenticAiUnavailable):
        run(client_for(Agentic(b"Service Unavailable", status=503, content_type="text/plain")).chat_stream(text))


def test_factory_requires_base_url_for_live_and_rejects_unknown_mode():
    assert make_agentic_ai_client("mock").source == "mock"
    assert make_agentic_ai_client("live", BASE_URL).source == "live"
    with pytest.raises(ValueError):
        make_agentic_ai_client("live", "")
    with pytest.raises(ValueError):
        make_agentic_ai_client("nope")
