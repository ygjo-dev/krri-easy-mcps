"""agentic_ai 쪽 boundary. **existing agentic_ai API 만 부른다.**

향후 실제 client 가 부를 창구는 agentic_ai 의 기존 ``POST /chat/stream`` 이다
(agentic_ai app/api/main.py, 2026-09-22 read-only 확인):

    요청  {"text": <발화>, "context": {}}
    응답  text/event-stream. 한 줄에 ``data: <json>``, 끝은 ``data: [DONE]``
          {"type": "step_start", "node": "resolve", "message": "발화를 해석하고 있습니다..."}
          {"type": "step_end",   "node": "resolve", "message": "<STATUS> <recipe_id>"}
          {"type": "step_start", "node": <node>,    "message": "<tool> 호출 중입니다..."}
          {"type": "step_end",   "node": <node>,    "message": "<tool> 완료" | "<tool> 실패"}
          ...
          {"type": "result", "answer": <문자열>, "commands": [<지도 명령>]}

Portal 은 고정 질문의 display_text 를 발화로 보낼 뿐이다. recipe_id 를 지정하거나
Resolve 를 건너뛰지 않는다. Resolve · recipe 선택 · workflow materialization ·
실행은 전부 agentic_ai 기존 pipeline 이 한다.

**limitation**: 기존 이벤트에는 tool 단위 Request/Response 가 없다. 그래서 live 의
``tool_io`` 는 None 이다. 아래 mock 의 tool_io 는 UI 모양을 보이기 위한 예시값이다.
tool 단계 이벤트는 agentic 이 KRRI 실행을 마친 뒤 한꺼번에 낸다 (진행 중 표시가 아니다).

두 구현이 있다. KEM_AGENTIC_AI_MODE 로 고른다. live 가 실패해도 mock 으로 넘어가지 않는다.

- MockAgenticAiClient  고정 이벤트. tests · local 용
- RealAgenticAiClient  agentic_ai 의 기존 POST /chat/stream 을 부른다. 요청은 {text, context: {}} 뿐이다.
                       expected_recipe_id · expected_tools 는 보내지 않는다 (검증용 metadata 다)

agentic_ai 코드를 import 하지 않는다. 이벤트는 필요한 칸만 읽고, 모르는 type · 칸은 그대로 둔다
(agentic 이 status · failed 같은 칸을 더해도 깨지지 않게).
"""

import codecs
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

SOURCE_MOCK = "mock"
SOURCE_LIVE = "live"
CHAT_STREAM_PATH = "/chat/stream"
DONE = "[DONE]"

# agentic 한 요청은 LLM 해석 + KRRI 실행(agentic 쪽 KRRI 호출 제한 300초)이다. 그보다 길게 기다린다.
DEFAULT_TIMEOUT_SECONDS = 360.0
CONNECT_TIMEOUT_SECONDS = 10.0


class AgenticAiUnavailable(RuntimeError):
    """agentic_ai 를 못 불렀거나 알아볼 수 없는 흐름이 왔다. 메시지는 서버 로그용이다 (URL · 본문 없음)."""


@dataclass(frozen=True)
class ChatStreamReply:
    # /chat/stream 이 내는 이벤트 그대로 ([DONE] 제외).
    events: list[dict]
    # tool 단계별 {"request": ..., "response": ...}. 기존 API 에 없으므로 real 은 None.
    tool_io: list[dict] | None = None


def _events(recipe_id: str, steps: list[tuple[str, str]], answer: str, commands: list[dict]) -> list[dict]:
    events = [
        {"type": "step_start", "node": "resolve", "message": "발화를 해석하고 있습니다..."},
        {"type": "step_end", "node": "resolve", "message": f"SELECT {recipe_id}"},
    ]
    for node, tool in steps:
        events.append({"type": "step_start", "node": node, "message": f"{tool} 호출 중입니다..."})
        events.append({"type": "step_end", "node": node, "message": f"{tool} 완료"})
    events.append({"type": "result", "answer": answer, "commands": commands})
    return events


# 발화 → mock 응답. node · tool 순서는 해당 recipe 의 execution.workflow 를 따랐다.
# 좌표 · 건수 · 답 문구는 예시값이다.
_MOCK_REPLIES: dict[str, ChatStreamReply] = {
    "익산역 위치 보여줘": ChatStreamReply(
        events=_events(
            "recipe_001",
            [("geocode_place", "geo.geocode")],
            "익산역의 위치를 지도에 표시했습니다.",
            [{"op": "map.flyTo", "args": {}}],
        ),
        tool_io=[
            {
                "request": {"query": "익산역"},
                "response": {"location": [126.946, 35.940], "address": "전북특별자치도 익산시 (mock)"},
            },
        ],
    ),
    "천안역에 무슨 노선 다녀": ChatStreamReply(
        events=_events(
            "recipe_003",
            [("get_railway_lines", "geo.getRailwayLines")],
            "천안역을 지나는 철도 노선을 지도에 표시했습니다.",
            [{"op": "map.addLayer", "args": {}}],
        ),
        tool_io=[
            {
                "request": {"stationName": "천안역"},
                "response": {"type": "FeatureCollection", "features": ["… (mock, 생략)"]},
            },
        ],
    ),
    "부산역이 무슨 구에 있어": ChatStreamReply(
        events=_events(
            "recipe_034",
            [("geocode_place", "geo.geocode"), ("find_admin_boundary_by_point", "adminBoundary.findBoundaryByPoint")],
            "부산역은 부산광역시 동구에 있습니다.",
            [],
        ),
        tool_io=[
            {"request": {"query": "부산역"}, "response": {"location": [129.041, 35.115]}},
            {
                "request": {"lon": 129.041, "lat": 35.115, "layer": "sigungu"},
                "response": {"features": [{"sido": "부산광역시", "sigungu": "동구"}]},
            },
        ],
    ),
    "수원역 근처 CCTV 띄워줘": ChatStreamReply(
        events=_events(
            "recipe_036",
            [("geocode_place", "geo.geocode"), ("find_cctv", "road.getCctv")],
            "수원역 반경 15km 안의 CCTV 를 지도에 표시했습니다.",
            [{"op": "map.addLayer", "args": {}}],
        ),
        tool_io=[
            {"request": {"query": "수원역"}, "response": {"location": [127.000, 37.266]}},
            {
                "request": {"minLon": 126.83, "minLat": 37.13, "maxLon": 127.17, "maxLat": 37.40},
                "response": {"count": 42, "items": ["… (mock, 생략)"]},
            },
        ],
    ),
}

_MOCK_NO_MATCH = ChatStreamReply(
    events=[
        {"type": "step_start", "node": "resolve", "message": "발화를 해석하고 있습니다..."},
        {"type": "step_end", "node": "resolve", "message": "NO_MATCH"},
        {"type": "result", "answer": "맞는 기능을 찾지 못했습니다.", "commands": []},
    ],
)


class MockAgenticAiClient:
    """``POST /chat/stream`` 과 같은 이벤트를 돌려주는 mock."""

    source = SOURCE_MOCK

    async def chat_stream(self, text: str) -> ChatStreamReply:
        return _MOCK_REPLIES.get(text, _MOCK_NO_MATCH)


async def read_sse_events(chunks: AsyncIterator[bytes]) -> list[dict]:
    """agentic /chat/stream 의 SSE 를 이벤트 목록으로. ``data: [DONE]`` 까지 읽는다.

    규칙  한 이벤트 = 빈 줄로 끝나는 ``data:`` 줄들 (여러 줄이면 \n 으로 잇는다)
          ``event:`` · ``id:`` · ``:`` 주석 줄은 무시한다
          data 는 JSON object 여야 한다. 모르는 type · 칸도 그대로 담는다
    실패  UTF-8 이 아님 · JSON 이 아님 · object 가 아님 · [DONE] 전에 끝남 · result 이벤트 없음
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    events: list[dict] = []
    data_lines: list[str] = []
    pending = ""
    done = False

    def dispatch() -> bool:
        nonlocal data_lines
        if not data_lines:
            return False
        data = "\n".join(data_lines)
        data_lines = []
        if data == DONE:
            return True
        try:
            event = json.loads(data)
        except ValueError:
            raise AgenticAiUnavailable("malformed JSON event") from None
        if not isinstance(event, dict):
            raise AgenticAiUnavailable("event is not an object")
        events.append(event)
        return False

    try:
        async for chunk in chunks:
            pending += decoder.decode(chunk)
            *lines, pending = pending.split("\n")
            for line in lines:
                line = line.rstrip("\r")
                if line == "":
                    done = dispatch()
                elif line.startswith("data:"):
                    value = line[5:]
                    data_lines.append(value[1:] if value.startswith(" ") else value)
                if done:
                    break
            if done:
                break
        if not done:
            pending += decoder.decode(b"", final=True)
            if pending.rstrip("\r").startswith("data:"):
                value = pending.rstrip("\r")[5:]
                data_lines.append(value[1:] if value.startswith(" ") else value)
            done = dispatch()
    except UnicodeDecodeError:
        raise AgenticAiUnavailable("stream is not UTF-8") from None

    if not done:
        raise AgenticAiUnavailable("stream ended before [DONE]")
    if not any(e.get("type") == "result" for e in events):
        raise AgenticAiUnavailable("stream has no result event")
    return events


class RealAgenticAiClient:
    """agentic_ai 의 기존 POST /chat/stream. 흐름을 끝까지 읽어 이벤트 목록으로 돌려준다."""

    source = SOURCE_LIVE

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(CONNECT_TIMEOUT_SECONDS, timeout_seconds))
        self._transport = transport

    async def chat_stream(self, text: str) -> ChatStreamReply:
        body = {"text": text, "context": {}}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                async with client.stream(
                    "POST", CHAT_STREAM_PATH, json=body, headers={"Accept": "text/event-stream"}
                ) as response:
                    if response.status_code != 200:
                        raise AgenticAiUnavailable(f"HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "")
                    if not content_type.startswith("text/event-stream"):
                        raise AgenticAiUnavailable("unexpected content type")
                    events = await read_sse_events(response.aiter_bytes())
        except AgenticAiUnavailable:
            raise
        except httpx.TimeoutException:
            raise AgenticAiUnavailable("timeout") from None
        except httpx.HTTPError as exc:
            # httpx 예외 문구에는 URL 이 들어 있다. 종류만 남긴다.
            raise AgenticAiUnavailable(type(exc).__name__) from None
        return ChatStreamReply(events=events, tool_io=None)


def make_agentic_ai_client(mode: str, base_url: str = "", timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
    if mode == SOURCE_MOCK:
        return MockAgenticAiClient()
    if mode == SOURCE_LIVE:
        if not base_url:
            raise ValueError("KEM_AGENTIC_AI_MODE=live requires KEM_AGENTIC_AI_BASE_URL")
        return RealAgenticAiClient(base_url, timeout_seconds=timeout_seconds)
    raise ValueError(f"unknown KEM_AGENTIC_AI_MODE {mode!r} (mock | live)")
