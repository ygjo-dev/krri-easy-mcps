"""trace.to_execution: agentic /chat/stream 이벤트 → Portal Execution DTO.

이벤트 모양은 agentic_ai 의 현재 흐름(2026-09-22 read-only 확인)을 따른다.
해석 끝 message 는 "<STATUS> <recipe_id>" (CLARIFY · NO_MATCH 는 recipe 없이 STATUS 만),
단계 끝 message 는 "<tool> 완료" / "<tool> 실패".
"""

import json

from app.clients.agentic_ai import ChatStreamReply
from app.metadata import DemoQuestion
from app.trace import LIMITATION_TOOL_IO_NONE, to_execution

Q = DemoQuestion(
    question_id="suwon-station-cctv",
    mcp_server_id="asap-mcp-core",
    display_text="수원역 근처 CCTV 띄워줘",
    expected_recipe_id="recipe_036",
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


def test_one_step_success():
    q = DemoQuestion("iksan", "asap-mcp-core", "익산역 위치 보여줘", "recipe_001", ("asap-mcp-core/geo.geocode",), True)
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
    for marker in ("recipe_036", '"expected_recipe_id"', '"expected_tools"', '"commands"', "geojson", "map.addLayer"):
        assert marker not in text, marker
