"""Portal 이 소유한 metadata: 표시 정보(presentation)와 고정 질문(demo questions)."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class DemoQuestion:
    question_id: str
    mcp_server_id: str
    display_text: str
    # 검증·설명용. agentic_ai 에 실행 명령으로 보내지 않고, 브라우저로도 내보내지 않는다.
    expected_recipe_id: str | None
    expected_tools: tuple[str, ...]
    enabled: bool


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_presentation(config_dir: Path) -> dict[str, dict]:
    return _read(config_dir / "presentation.yaml").get("servers") or {}


def load_demo_questions(config_dir: Path) -> dict[str, DemoQuestion]:
    questions = {}
    for raw in _read(config_dir / "demo_questions.yaml").get("questions") or []:
        q = DemoQuestion(
            question_id=raw["question_id"],
            mcp_server_id=raw["mcp_server_id"],
            display_text=raw["display_text"],
            expected_recipe_id=raw.get("expected_recipe_id"),
            expected_tools=tuple(raw.get("expected_tools") or ()),
            enabled=bool(raw.get("enabled", True)),
        )
        if q.question_id in questions:
            raise ValueError(f"duplicate question_id: {q.question_id}")
        questions[q.question_id] = q
    return questions
