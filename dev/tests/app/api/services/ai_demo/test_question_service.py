"""question_service — 「AI에게 이렇게 물어보세요」 고정 질문 읽기 (mcp_definitions/demo_questions.yaml).

- 실행 질문 = expected_recipe_id 가 있는 질문. 없으면 예시로만 보인다 (runnable false). enabled 는 기본 true.
- 질문을 잘못 붙이면 BFF 가 뜨지 않는다: 같은 question_id 두 번 · 개발 중 MCP 의 질문 · expected_mcp_ids 에 없는 mcp_id.
"""

import pytest

from app.api.main import create_app, load_settings
from app.api.services.ai_demo.question_service import load_demo_questions


@pytest.mark.parametrize("yaml_text,error", [
    ("questions:\n  - {question_id: q, mcp_id: gtfs-accessibility-aro, display_text: x}\n", "in development"),
    ("questions:\n  - {question_id: q, mcp_id: krri-road-cctv, display_text: x, expected_mcp_ids: [krri-map-location]}\n",
     "not in expected_mcp_ids"),
])
def test_invalid_question_ownership_fails_startup(tmp_path, monkeypatch, yaml_text, error):
    settings = load_settings()
    for name in ("presentation.yaml", "planned_mcps.yaml"):
        (tmp_path / name).write_text((settings.mcp_definitions_dir / name).read_text())
    (tmp_path / "demo_questions.yaml").write_text(yaml_text)
    monkeypatch.setenv("KEM_MCP_DEFINITIONS_DIR", str(tmp_path))
    with pytest.raises(ValueError, match=error):
        create_app()


def test_duplicate_question_id_fails_loading(tmp_path):
    (tmp_path / "demo_questions.yaml").write_text(
        "questions:\n"
        "  - {question_id: q, mcp_id: krri-map-location, display_text: a}\n"
        "  - {question_id: q, mcp_id: krri-road-cctv, display_text: b}\n"
    )
    with pytest.raises(ValueError, match="duplicate question_id"):
        load_demo_questions(tmp_path, {})


def test_question_is_runnable_only_with_expected_recipe_and_enabled_by_default(tmp_path):
    (tmp_path / "demo_questions.yaml").write_text(
        "questions:\n"
        "  - {question_id: run, mcp_id: krri-map-location, display_text: a, expected_recipe_id: recipe_001}\n"
        "  - {question_id: example, mcp_id: krri-dem, display_text: b}\n"
        "  - {question_id: disabled, mcp_id: krri-dem, display_text: c, enabled: false}\n"
    )
    questions = load_demo_questions(tmp_path, {})
    assert (questions["run"].runnable, questions["run"].enabled) == (True, True)
    assert (questions["example"].runnable, questions["example"].enabled) == (False, True)
    assert questions["disabled"].enabled is False
