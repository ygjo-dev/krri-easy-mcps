"""MCP catalog / detail API (/api/mcps). 카드 · 목록 규칙은 catalog_service.py."""

from fastapi import APIRouter, HTTPException, Request

from .catalog_service import (
    EMPTY_GATEWAY_DETAIL,
    NOT_FOUND_DETAIL,
    card,
    find_planned,
    ordered_mcps,
    parameters,
    planned_card,
    planned_only,
)

router = APIRouter(prefix="/api/mcps", tags=["catalog"])


@router.get("")
def list_mcps(request: Request) -> list[dict]:
    state = request.app.state
    mcps = state.gateway.list_mcps()
    return [card(m, state.presentation, state.gateway.source) for m in ordered_mcps(mcps, state.presentation)] + [
        planned_card(p) for p in planned_only(state, mcps)
    ]


@router.get("/{mcp_id}")
def get_mcp(mcp_id: str, request: Request) -> dict:
    state = request.app.state
    mcp = state.gateway.get_mcp(mcp_id)
    if mcp is None:
        planned = find_planned(state, mcp_id)
        if planned is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
        # Gateway 에 없으므로 상세 정보도 없다. 가짜 값을 채우지 않는다.
        return {**planned_card(planned), **EMPTY_GATEWAY_DETAIL, "tools": []}
    detail = card(mcp, state.presentation, state.gateway.source)
    detail.update({
        "long_description": mcp.get("long_description") or "",
        "tags": list(mcp.get("tags") or []),
        "connected_datasets": [dict(d) for d in mcp.get("connected_datasets") or []],
        "updated_at": mcp.get("updated_at"),
    })
    detail["tools"] = [
        {
            "name": t["name"],
            "description": t.get("description") or "",
            "parameters": parameters(t.get("input_schema") or {}),
        }
        for t in mcp.get("tools") or []
    ]
    return detail
