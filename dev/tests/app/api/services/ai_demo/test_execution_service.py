"""execution_service — agentic /chat/stream 이벤트 → 화면용 실행 결과.

이벤트 모양은 agentic_ai 의 현재 흐름(2026-09-22 read-only 확인)을 따른다.
해석 끝 message 는 "<STATUS> <recipe_id>" (CLARIFY · NO_MATCH 는 recipe 없이 STATUS 만),
단계 끝 message 는 "<tool> 완료" / "<tool> 실패". 모르는 event · 칸은 무시한다.
결과에는 판정 · 기대 recipe/Tool 과 맞는지 · 단계 · 답 · 지도 명령 개수만 싣는다 (recipe_id 원문 · expected_* · 명령 본문 없음).
단계 Tool 의 MCP 이름(mcp_name)은 질문의 expected_mcp_ids 중 그 Tool 을 가진 MCP 가 정확히 하나일 때만 붙인다.
"""

import json
from types import SimpleNamespace

from app.api.integrations.agentic_ai.agentic_ai_client import ChatStreamReply
from app.api.integrations.krri_asap.gateway_client import GatewayUnavailable
from app.api.services.ai_demo.execution_service import LIMITATION_TOOL_IO_NONE, label_steps, to_execution
from app.api.services.ai_demo.question_service import DemoQuestion


Q = DemoQuestion(
    question_id="suwon-station-cctv",
    mcp_id="krri-road-cctv",
    display_text="수원역 근처 CCTV 띄워줘",
    expected_recipe_id="recipe_036",
    expected_mcp_ids=("krri-map-location", "krri-road-cctv"),
    expected_tools=("asap-mcp-core/geo.geocode", "asap-mcp-core/road.getCctv"),
    enabled=True,
)


def resolve(message):
    return [
        {"type": "step_start", "node": "resolve", "message": "발화를 해석하고 있습니다..."},
        {"type": "step_end", "node": "resolve", "message": message},
    ]


def step(node, tool, failed=False):
    return [
        {"type": "step_start", "node": node, "message": f"{tool} 호출 중입니다..."},
        {"type": "step_end", "node": node, "message": f"{tool} {'실패' if failed else '완료'}", "failed": failed},
    ]


def result(answer="답", commands=None, **extra):
    return [{"type": "result", "answer": answer, "commands": commands or [], **extra}]


def execute(events, question=Q):
    return to_execution(question, ChatStreamReply(events=events, tool_io=None), "live")


def test_select_with_expected_recipe_and_tools():
    out = execute(resolve("SELECT recipe_036") + step("geocode_place", "geo.geocode") + step("find_cctv", "road.getCctv") + result())
    assert out["resolve_status"] == "SELECT"
    assert out["matches_expected_recipe"] is True
    assert out["matches_expected_tools"] is True


def test_select_with_unexpected_recipe():
    out = execute(resolve("SELECT recipe_001") + step("geocode_place", "geo.geocode") + result())
    assert out["resolve_status"] == "SELECT"
    assert out["matches_expected_recipe"] is False
    assert out["matches_expected_tools"] is False


def test_no_match_and_clarify_have_no_steps():
    for status in ("NO_MATCH", "CLARIFY"):
        out = execute(resolve(status) + result("맞는 것이 없습니다."))
        assert out["resolve_status"] == status
        assert out["matches_expected_recipe"] is False
        assert out["steps"] == []
        assert out["answer"] == "맞는 것이 없습니다."


def test_one_successful_step_matches_expected_tools():
    q = DemoQuestion("iksan", "krri-map-location", "익산역 위치 보여줘", "recipe_001", ("krri-map-location",),
                     ("asap-mcp-core/geo.geocode",), True)
    out = execute(resolve("SELECT recipe_001") + step("geocode_place", "geo.geocode") + result(), q)
    assert [(s["tool"], s["status"]) for s in out["steps"]] == [("geo.geocode", "success")]
    assert out["matches_expected_tools"] is True


def test_multi_step_order_and_failed_step():
    out = execute(
        resolve("SELECT recipe_036") + step("geocode_place", "geo.geocode") + step("find_cctv", "road.getCctv", failed=True)
        + result("CCTV 조회에 실패했습니다.", status="failed")
    )
    assert [(s["node"], s["tool"], s["status"]) for s in out["steps"]] == [
        ("geocode_place", "geo.geocode", "success"),
        ("find_cctv", "road.getCctv", "failed"),
    ]
    assert out["answer"] == "CCTV 조회에 실패했습니다."


def test_executor_unreachable_select_without_steps():
    out = execute(resolve("SELECT recipe_036") + result("실행 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."))
    assert out["matches_expected_recipe"] is True
    assert out["steps"] == []
    assert out["matches_expected_tools"] is False


def test_answer_and_commands_count():
    out = execute(resolve("SELECT recipe_036") + result("표시했습니다.", commands=[{"op": "a"}, {"op": "b"}]))
    assert out["answer"] == "표시했습니다."
    assert out["map_command_count"] == 2


def test_unknown_events_and_additive_fields_are_ignored():
    events = (
        [{"type": "hello", "anything": 1}]
        + resolve("SELECT recipe_036")
        + [{"type": "step_end", "node": "x", "message": "알 수 없는 문구"}]  # 완료/실패 꼴이 아님 → 단계로 치지 않음
        + step("geocode_place", "geo.geocode") + step("find_cctv", "road.getCctv")
        + [{"type": "telemetry", "elapsed_ms": 9}]
        + result("답", status="success", trace_id="t-1")
    )
    out = execute(events)
    assert [s["tool"] for s in out["steps"]] == ["geo.geocode", "road.getCctv"]
    assert out["matches_expected_tools"] is True


def test_live_reply_has_no_request_response_and_explains_why():
    out = execute(resolve("SELECT recipe_036") + step("geocode_place", "geo.geocode") + result())
    assert out["steps"][0]["request"] is None and out["steps"][0]["response"] is None
    assert out["limitations"] == [LIMITATION_TOOL_IO_NONE]
    assert out["source"] == "live"


def test_output_has_no_recipe_id_expected_metadata_or_raw_commands():
    out = execute(resolve("SELECT recipe_036") + step("geocode_place", "geo.geocode") + result(commands=[{"op": "map.addLayer", "args": {"geojson": {}}}]))
    text = json.dumps(out, ensure_ascii=False)
    for marker in ("recipe_036", '"expected_recipe_id"', '"expected_tools"', '"expected_mcp_ids"', '"commands"', "geojson", "map.addLayer"):
        assert marker not in text, marker


# ── 단계 MCP 이름 ───────────────────────────────────────────────────


def test_step_labels_are_optional_when_gateway_is_down(client):
    def down():
        raise GatewayUnavailable("down")

    client.app.state.gateway.list_mcps = down
    body = client.post("/api/demo/questions/busan-station-district/execute").json()
    assert body["matches_expected_tools"] is True
    assert [s["mcp_name"] for s in body["steps"]] == [None, None]


def test_step_label_needs_exactly_one_expected_mcp_owning_the_tool():
    """Tool 소속은 Gateway group 의 Tool 로만 본다. 후보(expected_mcp_ids) 둘이 같은 Tool 을 가지면 이름을 붙이지 않는다."""
    def mcp(mcp_id, name, tools):
        return {"mcp_id": mcp_id, "name": name, "tools": [{"name": t} for t in tools]}

    def labels(mcps):
        state = SimpleNamespace(gateway=SimpleNamespace(list_mcps=lambda: mcps, source="live"), presentation={})
        steps = [{"tool": "geo.geocode"}, {"tool": "road.getCctv"}]
        label_steps(steps, Q, state)
        return [s["mcp_name"] for s in steps]

    owners = [mcp("krri-map-location", "지도", ["geo.geocode"]), mcp("krri-road-cctv", "CCTV", ["road.getCctv"])]
    assert labels(owners) == ["지도", "CCTV"]
    shared = [mcp("krri-map-location", "지도", ["geo.geocode"]), mcp("krri-road-cctv", "CCTV", ["geo.geocode", "road.getCctv"])]
    assert labels(shared) == [None, "CCTV"]
    assert labels([mcp("other-mcp", "기타", ["geo.geocode", "road.getCctv"])]) == [None, None]  # 후보 밖 MCP 는 안 본다
