"""MCP catalog / detail. technical(Gateway client) + presentation(config) 을 server_id 로 join.

presentation.yaml 에 entry 가 없는 server 도 숨기지 않는다. technical 값으로 채운다.
"""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/mcps", tags=["catalog"])

FALLBACK_CATEGORY = "기타"


def card(server: dict, presentation: dict, source: str) -> dict:
    p = presentation.get(server["server_id"]) or {}
    technical_name = server.get("name") or server["server_id"]
    return {
        "server_id": server["server_id"],
        "technical_name": technical_name,
        "display_name": p.get("display_name") or technical_name,
        "summary": p.get("summary") or server.get("description") or "",
        "category": p.get("category") or FALLBACK_CATEGORY,
        "organization": p.get("organization") or "",
        "status": server.get("status") or "unknown",
        "tool_count": len(server.get("tools") or []),
        "source": source,
    }


def _type_label(spec: dict) -> str:
    """parameter type 한 줄. anyOf/oneOf · type 목록 · array items 까지만 읽고, 나머지는 any."""
    if not isinstance(spec, dict):
        return "any"
    options = spec.get("anyOf") or spec.get("oneOf")
    if isinstance(options, list) and options:
        return " | ".join(_type_label(o) for o in options)
    kind = spec.get("type")
    if isinstance(kind, list):
        return " | ".join(str(k) for k in kind)
    if kind == "array" and isinstance(spec.get("items"), dict) and spec["items"].get("type"):
        return f"array<{_type_label(spec['items'])}>"
    return str(kind) if kind else "any"


def _parameters(input_schema: dict) -> list[dict]:
    """inputSchema 를 화면이 그릴 parameter 목록으로. raw schema 는 내보내지 않는다."""
    required = set(input_schema.get("required") or [])
    properties = input_schema.get("properties")
    params = []
    for name, spec in (properties if isinstance(properties, dict) else {}).items():
        spec = spec if isinstance(spec, dict) else {}
        params.append({
            "name": name,
            "type": _type_label(spec),
            "required": name in required,
            "description": spec.get("description") or "",
            "default": spec.get("default"),
            "enum": spec.get("enum"),
        })
    return params


@router.get("")
def list_mcps(request: Request) -> list[dict]:
    state = request.app.state
    return [card(s, state.presentation, state.gateway.source) for s in state.gateway.list_servers()]


@router.get("/{server_id}")
def get_mcp(server_id: str, request: Request) -> dict:
    state = request.app.state
    server = state.gateway.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP 를 찾을 수 없습니다.")
    detail = card(server, state.presentation, state.gateway.source)
    detail["tools"] = [
        {
            "name": t["name"],
            "description": t.get("description") or "",
            "parameters": _parameters(t.get("input_schema") or {}),
        }
        for t in server.get("tools") or []
    ]
    return detail
