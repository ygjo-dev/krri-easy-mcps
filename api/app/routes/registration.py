"""도구함 · MCP 등록 미리보기. 실제 등록 · registry write · publish 는 하지 않는다."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..clients.gateway import InvalidEndpoint

router = APIRouter(prefix="/api/registration", tags=["registration"])


class InspectRequest(BaseModel):
    endpoint: str


@router.post("/inspect")
def inspect(form: InspectRequest, request: Request) -> dict:
    try:
        return request.app.state.registration_inspector.inspect(form.endpoint.strip())
    except InvalidEndpoint as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
