"""skill_ai_client — EASY 가 AI Skills 자동 정리 모델(독파모, OpenAI 호환 vLLM)을 부르는 contract.

부르는 것: ``POST {base}/v1/chat/completions`` 하나. agentic_ai 의 /chat/stream 이 아니다.
    요청  model · system/user messages · response_format json_schema(strict) · reasoning_effort "none" · 낮은 temperature · max_tokens.
          key 가 있을 때만 Authorization Bearer.
    응답  choices[0].message.content 의 JSON object. ```json 울타리만 벗긴다.
실패: 연결 실패 · timeout · 200 아님 · 응답 모양 다름 · content 가 JSON object 아님 · 잘림 → SkillAiUnavailable.
      메시지에 URL · key · 응답 본문을 싣지 않고, mock 결과로 바꾸지 않는다.
"""

import asyncio
import json

import httpx
import pytest

from app.api.integrations.skill_ai.skill_ai_client import (
    CHAT_COMPLETIONS_PATH,
    MAX_TOKENS,
    MockSkillAiClient,
    RealSkillAiClient,
    SkillAiUnavailable,
    make_skill_ai_client,
    parse_json_object,
)
from tests.app.api.integrations.skill_ai.skill_ai_fake import (
    API_KEY,
    BASE_URL,
    GOOD_RESULT,
    MODEL,
    Model,
    analysis_request,
    client_for,
    completion,
    run,
)

# ── 요청 ────────────────────────────────────────────────────────────


def test_request_is_openai_chat_completion_with_json_schema():
    model = Model()
    request = analysis_request(schema={"type": "object", "properties": {"title": {"type": "string"}}})
    assert run(client_for(model).analyze(request)) == GOOD_RESULT
    (sent,) = model.requests
    assert sent.method == "POST"
    assert str(sent.url) == BASE_URL + CHAT_COMPLETIONS_PATH == BASE_URL + "/v1/chat/completions"
    body = json.loads(sent.content)
    assert body["model"] == MODEL
    assert body["messages"] == [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "USER"}]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "skill_library_metadata", "schema": request.schema, "strict": True},
    }
    # 빼면 모델 기본값(high)으로 추론 token 을 먼저 낸다
    assert body["reasoning_effort"] == "none"
    assert 0 <= body["temperature"] <= 0.3
    assert 0 < body["max_tokens"] == MAX_TOKENS <= 2048
    assert "stream" not in body
    # package 사실 칸(mock 용)은 보내지 않는다
    assert not {"skill_id", "paths", "heading", "sections"} & set(body)


def test_base_url_trailing_slash_and_no_key_means_no_authorization_header():
    model = Model()
    run(RealSkillAiClient(BASE_URL + "/", MODEL, transport=httpx.MockTransport(model)).analyze(analysis_request()))
    (sent,) = model.requests
    assert sent.url.path == "/v1/chat/completions"
    assert "authorization" not in sent.headers
    assert "cookie" not in sent.headers


def test_api_key_is_sent_as_bearer_only_when_configured():
    model = Model()
    run(client_for(model, api_key=API_KEY).analyze(analysis_request()))
    assert model.requests[0].headers["authorization"] == f"Bearer {API_KEY}"


def test_timeout_setting_is_applied():
    client = RealSkillAiClient(BASE_URL, MODEL, timeout_seconds=42)
    assert client._timeout.read == 42 and client._timeout.connect == 10


def test_client_keeps_no_state_between_requests():
    """동시에 두 분석이 와도 섞이지 않는다: 요청마다 연결을 열고, 결과는 그 요청의 응답이다."""
    first, second = {**GOOD_RESULT, "title": "첫째"}, {**GOOD_RESULT, "title": "둘째"}
    seen = []

    def handler(request):
        user = json.loads(request.content)["messages"][1]["content"]
        seen.append(user)
        return httpx.Response(200, json=completion(json.dumps(first if user == "A" else second, ensure_ascii=False)))

    client = RealSkillAiClient(BASE_URL, MODEL, transport=httpx.MockTransport(handler))

    async def both():
        return await asyncio.gather(client.analyze(analysis_request(user_prompt="A")),
                                    client.analyze(analysis_request(user_prompt="B")))

    a, b = run(both())
    assert (a["title"], b["title"]) == ("첫째", "둘째")


# ── 응답 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("content", [
    json.dumps(GOOD_RESULT, ensure_ascii=False),
    "```json\n" + json.dumps(GOOD_RESULT, ensure_ascii=False) + "\n```",
    "```\n" + json.dumps(GOOD_RESULT, ensure_ascii=False, indent=2) + "\n```",
    "\n  " + json.dumps(GOOD_RESULT, ensure_ascii=False) + "  \n",
], ids=["plain", "json-fence", "bare-fence", "whitespace"])
def test_json_object_content_is_returned(content):
    assert run(client_for(Model(completion(content))).analyze(analysis_request())) == GOOD_RESULT


@pytest.mark.parametrize("content", [
    "회의록을 정리하는 Skill 입니다.",
    "[]",
    "null",
    '{"title": "깨진 JSON"',
    '결과: {"title": "x"}',  # 앞에 설명이 붙은 글에서 JSON 을 억지로 찾지 않는다
    '"just a string"',
], ids=["plain-text", "array", "null", "broken", "prose-prefix", "string"])
def test_non_object_content_is_unavailable(content):
    with pytest.raises(SkillAiUnavailable):
        run(client_for(Model(completion(content))).analyze(analysis_request()))


def test_parse_json_object_contract():
    assert parse_json_object('{"a": 1}') == {"a": 1}
    with pytest.raises(SkillAiUnavailable):
        parse_json_object("")


# ── 실패 ────────────────────────────────────────────────────────────

TRACE = f"Traceback (most recent call last): File /srv/vllm/engine.py, url={BASE_URL}, key={API_KEY}"


@pytest.mark.parametrize("model", [
    Model(status=500, raw=TRACE.encode()),
    Model({"error": {"message": TRACE}}, status=400),
    Model(status=200, raw=b"<html>gateway</html>"),
    Model({"choices": []}),
    Model({"object": "chat.completion"}),
    Model(completion(None)),
    Model(completion("")),
    Model(completion(json.dumps(GOOD_RESULT, ensure_ascii=False), finish_reason="length")),
    Model(raise_exc=lambda r: httpx.ConnectError(f"refused {BASE_URL}", request=r)),
    Model(raise_exc=lambda r: httpx.ReadTimeout(f"timed out {BASE_URL}", request=r)),
], ids=["http500-trace", "http400", "html-200", "no-choices", "no-choices-key", "null-content", "empty-content",
        "cut-off", "connect-refused", "timeout"])
def test_failures_raise_unavailable_without_url_key_or_body(model):
    with pytest.raises(SkillAiUnavailable) as info:
        run(client_for(model, api_key=API_KEY).analyze(analysis_request()))
    message = str(info.value)
    for leaked in (BASE_URL, "model.internal", API_KEY, "Traceback", "/srv/vllm"):
        assert leaked not in message


def test_real_http_error_becomes_unavailable():
    # 127.0.0.1:9 (discard) 는 열려 있지 않다.
    with pytest.raises(SkillAiUnavailable):
        run(RealSkillAiClient("http://127.0.0.1:9", MODEL, timeout_seconds=2).analyze(analysis_request()))


def test_live_failure_raises_instead_of_returning_a_mock_result():
    assert run(MockSkillAiClient().analyze(analysis_request()))["title"]
    with pytest.raises(SkillAiUnavailable):
        run(client_for(Model(status=503, raw=b"Service Unavailable")).analyze(analysis_request()))


# ── mock ────────────────────────────────────────────────────────────


def test_mock_is_deterministic_and_reflects_the_package():
    request = analysis_request()
    first, again = run(MockSkillAiClient().analyze(request)), run(MockSkillAiClient().analyze(request))
    assert first == again
    assert first["title"] == "회의록 정리"  # SKILL.md 첫 제목
    assert first["summary"].startswith("회의 메모를 회의록으로 정리한다.")  # 원본 description
    assert first["use_cases"] == ["입력", "작성 순서"]  # ## 소제목
    assert {"참고자료", "예시 포함"} <= set(first["tags"])  # 폴더
    assert "meeting" in first["tags"] and "notes" in first["tags"]  # Skill ID
    assert set(first) == set(GOOD_RESULT)


def test_mock_differs_between_packages():
    other = analysis_request(skill_id="weekly-report", description="Writes weekly reports.", heading="", sections=(),
                             paths=("SKILL.md", "scripts/run.py"))
    a = run(MockSkillAiClient().analyze(analysis_request()))
    b = run(MockSkillAiClient().analyze(other))
    assert a != b
    assert b["title"] == "weekly report" and "스크립트 포함" in b["tags"]
    assert b["use_cases"] == ["Writes weekly reports."]


# ── factory ─────────────────────────────────────────────────────────


def test_factory_modes():
    assert make_skill_ai_client("mock").source == "mock"
    live = make_skill_ai_client("live", BASE_URL, MODEL, "", 30)
    assert live.source == "live" and isinstance(live, RealSkillAiClient)
    for args in (("live", "", MODEL), ("live", BASE_URL, ""), ("nope",)):
        with pytest.raises(ValueError) as info:
            make_skill_ai_client(*args)
        assert API_KEY not in str(info.value)
