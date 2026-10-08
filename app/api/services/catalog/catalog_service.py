"""Catalog 의 MCP 목록 · 카드. 사용자-facing 단위는 logical MCP (mcp_id) 다.

두 출처를 한 목록으로 합친다.
- Gateway logical MCP (lifecycle "available"): Gateway market group + mcp_definitions/presentation.yaml 을 mcp_id 로 join.
  presentation 에 entry 가 없는 group 도 숨기지 않는다. Gateway 값으로 채우고 분류는 「기타」.
  presentation 은 이름 · 요약 · 분류 · 제공만 덮는다. 상세의 long_description · tags · connected_datasets ·
  updated_at 은 Gateway group 값만 쓴다 (EASY 정의 파일에 두지 않는다).
- planned MCP (lifecycle "development"): mcp_definitions/planned_mcps.yaml. Gateway 에 없다. status · tool_count 가 null 이다
  (Tool 0개 · 사용 불가가 아니라 아직 없는 것). 같은 id 의 Gateway group 이 있으면 Gateway 쪽을 쓴다.

브라우저로 physical server id · toolRefs 를 내보내지 않는다.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# 개발 중 MCP 의 단계. 지금은 이것 하나다. 공개되면 Gateway group 이 되고 planned 에서 빠진다.
STAGE_DEVELOPMENT = "development"


@dataclass(frozen=True)
class PlannedMcp:
    """아직 Gateway server · group 이 없는 MCP. Catalog 에 「개발 중」으로만 보인다.

    Tool · status 가 없다 (0개 · offline 이 아니라 아직 없는 것). 내 MCP 등록 · AI 실행 대상이 아니다.
    """

    mcp_id: str
    display_name: str
    summary: str
    category: str
    organization: str
    stage: str


def read_definition(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_presentation(definitions_dir: Path) -> dict[str, dict]:
    return read_definition(definitions_dir / "presentation.yaml").get("mcps") or {}


def load_planned_mcps(definitions_dir: Path) -> dict[str, PlannedMcp]:
    planned = {}
    for raw in read_definition(definitions_dir / "planned_mcps.yaml").get("planned") or []:
        mcp = PlannedMcp(
            mcp_id=raw["mcp_id"],
            display_name=raw["display_name"],
            summary=raw.get("summary") or "",
            category=raw["category"],
            organization=raw.get("organization") or "",
            stage=raw["stage"],
        )
        if mcp.stage != STAGE_DEVELOPMENT:
            raise ValueError(f"planned MCP {mcp.mcp_id}: unknown stage {mcp.stage!r}")
        if mcp.mcp_id in planned:
            raise ValueError(f"duplicate planned mcp_id: {mcp.mcp_id}")
        planned[mcp.mcp_id] = mcp
    return planned


FALLBACK_CATEGORY = "기타"
LIFECYCLE_AVAILABLE = "available"
LIFECYCLE_DEVELOPMENT = "development"
SOURCE_PLANNED = "planned"

NOT_FOUND_DETAIL = "MCP 를 찾을 수 없습니다."
# Gateway group 에서만 오는 상세 칸의 빈 값 (개발 중 MCP 용).
EMPTY_GATEWAY_DETAIL = {"long_description": "", "tags": [], "connected_datasets": [], "updated_at": None}


def card(mcp: dict, presentation: dict, source: str) -> dict:
    """Gateway logical MCP → 브라우저 카드."""
    p = presentation.get(mcp["mcp_id"]) or {}
    return {
        "mcp_id": mcp["mcp_id"],
        "display_name": p.get("display_name") or mcp.get("name") or mcp["mcp_id"],
        "summary": p.get("summary") or mcp.get("description") or "",
        "category": p.get("category") or FALLBACK_CATEGORY,
        "organization": p.get("organization") or mcp.get("author") or "",
        "lifecycle": LIFECYCLE_AVAILABLE,
        "status": mcp.get("status") or "unknown",
        "tool_count": len(mcp.get("tools") or []),
        "source": source,
    }


def planned_card(mcp: PlannedMcp) -> dict:
    """개발 중 MCP → 브라우저 카드. Gateway 값처럼 보이는 칸(status · tool_count)은 null."""
    return {
        "mcp_id": mcp.mcp_id,
        "display_name": mcp.display_name,
        "summary": mcp.summary,
        "category": mcp.category,
        "organization": mcp.organization,
        "lifecycle": LIFECYCLE_DEVELOPMENT,
        "status": None,
        "tool_count": None,
        "source": SOURCE_PLANNED,
    }


def ordered_mcps(mcps: list[dict], presentation: dict) -> list[dict]:
    """presentation.yaml 순서, 거기 없는 group 은 뒤에 id 순."""
    rank = {mcp_id: i for i, mcp_id in enumerate(presentation)}
    return sorted(mcps, key=lambda m: (rank.get(m["mcp_id"], len(rank)), m["mcp_id"]))


def planned_only(state, mcps: list[dict]) -> list[PlannedMcp]:
    """Gateway 에 아직 없는 planned MCP. 같은 id 의 group 이 생겼으면 planned 를 버린다."""
    live_ids = {m["mcp_id"] for m in mcps}
    shadowed = [p.mcp_id for p in state.planned_mcps.values() if p.mcp_id in live_ids]
    if shadowed:
        logger.warning("planned MCP ids now exist in Gateway, planned entries ignored: %s", shadowed)
    return [p for p in state.planned_mcps.values() if p.mcp_id not in live_ids]


def find_planned(state, mcp_id: str) -> PlannedMcp | None:
    """Gateway 에 없는 개발 중 MCP 면 그것을, 아니면 None. Gateway 를 읽는다 (cache 됨)."""
    planned = state.planned_mcps.get(mcp_id)
    if planned is None or state.gateway.get_mcp(mcp_id) is not None:
        return None
    return planned


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


def parameters(input_schema: dict) -> list[dict]:
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
