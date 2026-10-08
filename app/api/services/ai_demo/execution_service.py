"""agentic_ai ``/chat/stream`` 이벤트를 Portal UI 용 실행 결과로 바꾼다.

Portal BFF 에서 안전하게 할 수 있는 변환만 한다:
- resolve 단계 message(``"<STATUS> <recipe_id>"``)에서 판정과, 고른 recipe 가
  고정 질문의 expected_recipe_id 와 같은지
- tool 단계 message(``"<tool> 완료" / "<tool> 실패"``)에서 tool 이름과 성공 여부
- result 의 answer
- 각 단계 Tool 에 그 Tool 을 가진 logical MCP 이름 (steps[].mcp_name, label_steps)

브라우저로 내보내지 않는 것: recipe_id 원문, expected_* 값, 지도 명령(commands) 본문.
"""

import logging

from ...integrations.agentic_ai.agentic_ai_client import ChatStreamReply
from ...integrations.krri_asap.gateway_client import GatewayUnavailable
from ..catalog.catalog_service import card
from .question_service import DemoQuestion

logger = logging.getLogger(__name__)

RESOLVE_NODE = "resolve"
DONE_SUFFIX = " 완료"
FAILED_SUFFIX = " 실패"

LIMITATION_TOOL_IO_MOCK = (
    "기존 agentic_ai /chat/stream 이벤트에는 tool 단위 Request/Response 가 없습니다. "
    "지금 보이는 Request/Response 는 mock 예시값입니다."
)
LIMITATION_TOOL_IO_NONE = (
    "기존 agentic_ai /chat/stream 이벤트에는 tool 단위 Request/Response 가 없어 표시하지 않습니다."
)


def _tool_step(event: dict) -> dict | None:
    message = event.get("message") or ""
    for suffix, status in ((DONE_SUFFIX, "success"), (FAILED_SUFFIX, "failed")):
        if message.endswith(suffix):
            return {"node": event.get("node"), "tool": message[: -len(suffix)], "status": status}
    return None


def to_execution(question: DemoQuestion, reply: ChatStreamReply, source: str) -> dict:
    resolve_status = None
    resolved_recipe = None
    steps: list[dict] = []
    answer = ""
    map_command_count = 0

    for event in reply.events:
        kind = event.get("type")
        if kind == "step_end" and event.get("node") == RESOLVE_NODE:
            parts = (event.get("message") or "").split()
            resolve_status = parts[0] if parts else None
            resolved_recipe = parts[1] if len(parts) > 1 else None
        elif kind == "step_end":
            step = _tool_step(event)
            if step:
                steps.append(step)
        elif kind == "result":
            answer = event.get("answer") or ""
            map_command_count = len(event.get("commands") or [])

    for i, step in enumerate(steps):
        io = reply.tool_io[i] if reply.tool_io and i < len(reply.tool_io) else None
        step["request"] = io.get("request") if io else None
        step["response"] = io.get("response") if io else None

    expected_tools = [t.split("/", 1)[-1] for t in question.expected_tools]
    return {
        "question_id": question.question_id,
        "display_text": question.display_text,
        "source": source,
        "resolve_status": resolve_status,
        "matches_expected_recipe": (
            resolved_recipe == question.expected_recipe_id if question.expected_recipe_id else None
        ),
        "matches_expected_tools": [s["tool"] for s in steps] == expected_tools if expected_tools else None,
        "steps": steps,
        "answer": answer,
        "map_command_count": map_command_count,
        "limitations": [LIMITATION_TOOL_IO_NONE if reply.tool_io is None else LIMITATION_TOOL_IO_MOCK],
    }


def label_steps(steps: list[dict], question: DemoQuestion, state) -> None:
    """각 단계 Tool 에 그 Tool 을 가진 logical MCP 이름을 붙인다 (steps[].mcp_name).

    후보는 질문의 expected_mcp_ids 뿐이고, 소속은 Gateway group 의 Tool 로만 판단한다.
    후보 중 정확히 하나에 있을 때만 붙이고, 아니면 null. 이름표일 뿐이라 Gateway 를 못 읽어도
    실행 결과는 그대로 돌려준다.
    """
    try:
        mcps = {m["mcp_id"]: m for m in state.gateway.list_mcps()}
    except GatewayUnavailable as exc:
        logger.warning("step MCP labels skipped: %s", exc)
        mcps = {}
    candidates = [mcps[i] for i in question.expected_mcp_ids if i in mcps]
    for step in steps:
        owners = [m for m in candidates if any(t["name"] == step["tool"] for t in m.get("tools") or [])]
        step["mcp_name"] = (
            card(owners[0], state.presentation, state.gateway.source)["display_name"] if len(owners) == 1 else None
        )
