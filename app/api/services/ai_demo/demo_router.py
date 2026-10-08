"""AI로 사용해보기 · 「AI에게 이렇게 물어보세요」. 브라우저는 question_id 만 보낸다.

실행 시 BFF 가 question_id → trusted display_text 를 찾아 agentic_ai 기존 API 에
발화로 보낸다. recipe_id 를 지정하거나 Resolve 를 건너뛰지 않는다.
agentic_ai 에 맞는 recipe 가 없는 MCP 의 질문(runnable false)은 예시로만 보이고 실행하지 않는다 (409).
"""

from fastapi import APIRouter, HTTPException, Request

from .execution_service import label_steps, to_execution

router = APIRouter(prefix="/api", tags=["demo"])

NOT_RUNNABLE_DETAIL = "이 질문은 예시입니다. 아직 EASY 에서 AI 로 실행할 수 없습니다."


@router.get("/mcps/{mcp_id}/demo-questions")
def list_demo_questions(mcp_id: str, request: Request) -> list[dict]:
    return [
        {"question_id": q.question_id, "display_text": q.display_text, "runnable": q.runnable}
        for q in request.app.state.demo_questions.values()
        if q.enabled and q.mcp_id == mcp_id
    ]


@router.post("/demo/questions/{question_id}/execute")
async def execute_demo_question(question_id: str, request: Request) -> dict:
    state = request.app.state
    question = state.demo_questions.get(question_id)
    if question is None or not question.enabled:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다.")
    if not question.runnable:
        raise HTTPException(status_code=409, detail=NOT_RUNNABLE_DETAIL)
    reply = await state.agentic_ai.chat_stream(question.display_text)
    execution = to_execution(question, reply, state.agentic_ai.source)
    label_steps(execution["steps"], question, state)
    return execution
