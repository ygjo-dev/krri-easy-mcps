"""Portal 이 소유한 metadata: 표시 정보(presentation) · 개발 중 MCP(planned) · 고정 질문(demo questions).

셋 다 logical MCP id(= Gateway market group id, 개발 중이면 Portal 이 정한 id)로 묶인다.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

# 개발 중 MCP 의 단계. 지금은 이것 하나다. 공개되면 Gateway group 이 되고 planned 에서 빠진다.
STAGE_DEVELOPMENT = "development"


@dataclass(frozen=True)
class PlannedMcp:
    """아직 Gateway server · group 이 없는 MCP. Catalog 에 「개발 중」으로만 보인다.

    Tool · status 가 없다 (0개 · offline 이 아니라 아직 없는 것). 도구함 등록 · AI 실행 대상이 아니다.
    """

    mcp_id: str
    display_name: str
    summary: str
    category: str
    organization: str
    stage: str


@dataclass(frozen=True)
class DemoQuestion:
    question_id: str
    # 이 질문을 대화 예시로 보여 줄 MCP (상세 화면 하나).
    mcp_id: str
    display_text: str
    # 검증·설명용. agentic_ai 에 실행 명령으로 보내지 않고, 브라우저로도 내보내지 않는다.
    expected_recipe_id: str | None
    # 실행이 거칠 것으로 예상하는 logical MCP. 한 recipe 가 여러 MCP 의 Tool 을 쓸 수 있다.
    expected_mcp_ids: tuple[str, ...]
    # 실행이 거칠 것으로 예상하는 Tool (physical "<server_id>/<tool>", 호출 순서대로).
    expected_tools: tuple[str, ...]
    enabled: bool

    @property
    def runnable(self) -> bool:
        """EASY 「AI로 사용해보기」(agentic_ai /chat/stream)로 실행할 수 있는 질문인가.

        agentic_ai 에 이 기능의 recipe 가 있을 때만 그렇다 (expected_recipe_id). 없으면 화면에 예시로만 보인다.
        """
        return self.expected_recipe_id is not None


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_presentation(config_dir: Path) -> dict[str, dict]:
    return _read(config_dir / "presentation.yaml").get("mcps") or {}


def load_planned_mcps(config_dir: Path) -> dict[str, PlannedMcp]:
    planned = {}
    for raw in _read(config_dir / "planned_mcps.yaml").get("planned") or []:
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


def load_demo_questions(config_dir: Path, planned: dict[str, PlannedMcp] | None = None) -> dict[str, DemoQuestion]:
    planned = planned or {}
    questions = {}
    for raw in _read(config_dir / "demo_questions.yaml").get("questions") or []:
        q = DemoQuestion(
            question_id=raw["question_id"],
            mcp_id=raw["mcp_id"],
            display_text=raw["display_text"],
            expected_recipe_id=raw.get("expected_recipe_id"),
            expected_mcp_ids=tuple(raw.get("expected_mcp_ids") or ()),
            expected_tools=tuple(raw.get("expected_tools") or ()),
            enabled=bool(raw.get("enabled", True)),
        )
        if q.question_id in questions:
            raise ValueError(f"duplicate question_id: {q.question_id}")
        if q.mcp_id in planned:
            raise ValueError(f"question {q.question_id}: {q.mcp_id} is in development and cannot run")
        if q.expected_mcp_ids and q.mcp_id not in q.expected_mcp_ids:
            raise ValueError(f"question {q.question_id}: mcp_id {q.mcp_id} is not in expected_mcp_ids")
        questions[q.question_id] = q
    return questions
