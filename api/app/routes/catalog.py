"""MCP catalog / detail. technical(Gateway client) + presentation(config) 을 server_id 로 join."""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/mcps", tags=["catalog"])


def _card(server: dict, presentation: dict, source: str) -> dict:
    p = presentation.get(server["server_id"]) or {}
    return {
        "server_id": server["server_id"],
        "display_name": p.get("display_name") or server["server_id"],
        "summary": p.get("summary") or "",
        "category": p.get("category") or "",
        "organization": p.get("organization") or "",
        "status": server.get("status") or "unknown",
        "tool_count": len(server.get("tools") or []),
        "source": source,
    }


def _parameters(input_schema: dict) -> list[dict]:
    """inputSchema 를 화면이 그릴 parameter 목록으로. raw schema 는 내보내지 않는다."""
    required = set(input_schema.get("required") or [])
    params = []
    for name, spec in (input_schema.get("properties") or {}).items():
        params.append({
            "name": name,
            "type": spec.get("type") or "any",
            "required": name in required,
            "description": spec.get("description") or "",
            "default": spec.get("default"),
            "enum": spec.get("enum"),
        })
    return params


@router.get("")
def list_mcps(request: Request) -> list[dict]:
    state = request.app.state
    return [_card(s, state.presentation, state.gateway.source) for s in state.gateway.list_servers()]


@router.get("/{server_id}")
def get_mcp(server_id: str, request: Request) -> dict:
    state = request.app.state
    server = state.gateway.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP 를 찾을 수 없습니다.")
    detail = _card(server, state.presentation, state.gateway.source)
    detail["tools"] = [
        {
            "name": t["name"],
            "description": t.get("description") or "",
            "parameters": _parameters(t.get("input_schema") or {}),
        }
        for t in server.get("tools") or []
    ]
    return detail
