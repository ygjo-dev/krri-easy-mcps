"""AI로 사용해보기. 브라우저는 question_id 만 보낸다.

실행 시 BFF 가 question_id → trusted display_text 를 찾아 agentic_ai 기존 API 에
발화로 보낸다. recipe_id 를 지정하거나 Resolve 를 건너뛰지 않는다.
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from ..clients.gateway import GatewayUnavailable
from ..metadata import DemoQuestion
from ..trace import to_execution
from .catalog import card

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/mcps/{mcp_id}/demo-questions")
def list_demo_questions(mcp_id: str, request: Request) -> list[dict]:
    return [
        {"question_id": q.question_id, "display_text": q.display_text}
        for q in request.app.state.demo_questions.values()
        if q.enabled and q.mcp_id == mcp_id
    ]


@router.post("/demo/questions/{question_id}/execute")
async def execute_demo_question(question_id: str, request: Request) -> dict:
    state = request.app.state
    question = state.demo_questions.get(question_id)
    if question is None or not question.enabled:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다.")
    reply = await state.agentic_ai.chat_stream(question.display_text)
    execution = to_execution(question, reply, state.agentic_ai.source)
    _label_steps(execution["steps"], question, state)
    return execution


def _label_steps(steps: list[dict], question: DemoQuestion, state) -> None:
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
