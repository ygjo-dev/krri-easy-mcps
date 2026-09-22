"""AI로 사용해보기. 브라우저는 question_id 만 보낸다.

실행 시 BFF 가 question_id → trusted display_text 를 찾아 agentic_ai 기존 API 에
발화로 보낸다. recipe_id 를 지정하거나 Resolve 를 건너뛰지 않는다.
"""

from fastapi import APIRouter, HTTPException, Request

from ..trace import to_execution

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/mcps/{server_id}/demo-questions")
def list_demo_questions(server_id: str, request: Request) -> list[dict]:
    return [
        {"question_id": q.question_id, "display_text": q.display_text}
        for q in request.app.state.demo_questions.values()
        if q.enabled and q.mcp_server_id == server_id
    ]


@router.post("/demo/questions/{question_id}/execute")
async def execute_demo_question(question_id: str, request: Request) -> dict:
    state = request.app.state
    question = state.demo_questions.get(question_id)
    if question is None or not question.enabled:
        raise HTTPException(status_code=404, detail="질문을 찾을 수 없습니다.")
    reply = await state.agentic_ai.chat_stream(question.display_text)
    return to_execution(question, reply, state.agentic_ai.source)
