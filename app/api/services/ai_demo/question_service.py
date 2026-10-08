"""「AI에게 이렇게 물어보세요」 고정 질문 (mcp_definitions/demo_questions.yaml).

질문은 logical MCP id 로 묶인다. 개발 중 MCP(planned) 에 붙은 질문은 뜨지 않게 막는다 (Tool 이 없어 실행 · 예시 대상이 아니다).
"""

from dataclasses import dataclass
from pathlib import Path

from ..catalog.catalog_service import PlannedMcp, read_definition


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


def load_demo_questions(definitions_dir: Path, planned: dict[str, PlannedMcp] | None = None) -> dict[str, DemoQuestion]:
    planned = planned or {}
    questions = {}
    for raw in read_definition(definitions_dir / "demo_questions.yaml").get("questions") or []:
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
