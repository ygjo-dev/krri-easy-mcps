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

**limitation**: 기존 이벤트에는 tool 단위 Request/Response 가 없다. 그래서 실제 연결 뒤
``tool_io`` 는 None 이다. 아래 mock 의 tool_io 는 UI 모양을 보이기 위한 예시값이다.

**지금은 MOCK 이다.** agentic_ai 를 부르지 않고, agentic_ai 코드를 import 하지 않는다.
"""

from dataclasses import dataclass

SOURCE_MOCK = "mock"


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


def make_agentic_ai_client(mode: str) -> MockAgenticAiClient:
    if mode == SOURCE_MOCK:
        return MockAgenticAiClient()
    raise NotImplementedError(f"agentic_ai mode {mode!r} is not implemented yet (only 'mock')")
