"""app/api/mcp_definitions/*.yaml — EASY 가 소유한 MCP 정의의 내용 규칙.

기준 catalog 는 fixtures/gateway_catalog_20261002.json (실제 Gateway 를 BFF 와 같은 normalize 로 읽은 snapshot).
같은 coverage 검사를 지금 Gateway 에 하려면 KEM_LIVE_GATEWAY_URL=http://127.0.0.1:3000 을 주고 돌린다 (GET 만 한다).

- presentation.yaml: KRRI 계열 group 은 모두 「KRRI 정책현안 분석도구」 분류다.
- demo_questions.yaml: 모든 logical MCP 가 1~3개의 짧고 서로 다른 읽기 전용 예제를 갖는다. 예제는 한 MCP 의 Tool 을 부르고,
  expected_mcp_ids 는 expected_tools 를 가진 group 과 같다. 실행 질문은 agentic_ai recipe 가 있는 MCP 에만 있다.
- planned_mcps.yaml: 개발 중 MCP 는 Gateway 에 없고(Tool 없음), 예제 대상에서 빠지는 유일한 정책 예외다.
"""

import json
import os
import re
from pathlib import Path

import pytest

from app.api.integrations.krri_asap.gateway_client import make_gateway_client
from app.api.main import load_settings
from app.api.services.ai_demo.question_service import load_demo_questions
from app.api.services.catalog.catalog_service import load_planned_mcps


SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "gateway_catalog_20261002.json").read_text())

# 예제가 부르면 안 되는 쓰기 Tool (지우기 · 바꾸기)
WRITE_TOOLS = {"knowledge.deleteDoc", "bim.updateModel", "bim.deleteModel"}

MAX_PER_MCP = 3


def by_id(cards):
    return {c["mcp_id"]: c for c in cards}


@pytest.fixture(scope="module")
def questions():
    settings = load_settings()
    return [q for q in load_demo_questions(settings.mcp_definitions_dir, load_planned_mcps(settings.mcp_definitions_dir)).values() if q.enabled]


def check_coverage(mcps: list[dict], questions) -> None:
    by_mcp = {m["mcp_id"]: [q for q in questions if q.mcp_id == m["mcp_id"]] for m in mcps}
    missing = [mcp_id for mcp_id, qs in by_mcp.items() if not qs]
    assert missing == [], f"예제 질문이 없는 logical MCP: {missing}"
    tools = {ref: m["mcp_id"] for m in mcps for ref in m["tools"]}
    for q in questions:
        assert q.mcp_id in by_mcp, f"{q.question_id}: catalog 에 없는 MCP {q.mcp_id}"
        for ref in q.expected_tools:
            assert ref in tools, f"{q.question_id}: 지금 catalog 에 없는 Tool {ref}"
        # 대표 Tool 은 그 MCP 의 Tool 이어야 한다 (지도/위치 검색 geocode 는 장소 이름을 좌표로 받는 도우미)
        assert any(tools[ref] == q.mcp_id for ref in q.expected_tools), q.question_id


def test_every_catalog_mcp_has_examples(questions):
    check_coverage(SNAPSHOT["mcps"], questions)
    assert len(SNAPSHOT["mcps"]) == 14


def test_examples_are_small_distinct_and_read_only(questions):
    per_mcp: dict[str, list] = {}
    for q in questions:
        per_mcp.setdefault(q.mcp_id, []).append(q)
        assert not WRITE_TOOLS & {ref.split("/", 1)[1] for ref in q.expected_tools}, q.question_id
        # 사용자가 Tool 이름을 알 필요가 없다
        assert not re.search(r"\b[a-z]+\.[a-z]+[A-Z]\w*\b", q.display_text), q.question_id
        assert len(q.display_text) <= 60, q.question_id
    assert all(1 <= len(qs) <= MAX_PER_MCP for qs in per_mcp.values())
    texts = [q.display_text for q in questions]
    assert len(texts) == len(set(texts))


def test_example_targets_one_mcp(questions):
    """기본 예제는 한 MCP 의 Tool 을 부른다. 다른 MCP 는 장소 이름 → 좌표 도우미(지도/위치 검색)만 허용."""
    for q in questions:
        others = set(q.expected_mcp_ids) - {q.mcp_id}
        assert others <= {"krri-map-location"}, q.question_id
        if others:
            assert q.expected_tools[0] == "asap-mcp-core/geo.geocode", q.question_id


def test_runnable_means_agentic_recipe(questions):
    runnable = {q.mcp_id for q in questions if q.runnable}
    examples_only = {q.mcp_id for q in questions} - runnable
    # agentic_ai 에 recipe 가 없는 MCP (2026-10-02, KRRI_Ontology_Registry/recipes) 는 예시만
    assert examples_only == {"krri-vworld-representative-data", "krri-bim-viewer", "krri-dem",
                             "krri-election-pledges-2026", "web-research"}


def test_planned_mcps_are_the_only_policy_exception():
    settings = load_settings()
    planned = load_planned_mcps(settings.mcp_definitions_dir)
    snapshot_ids = {m["mcp_id"] for m in SNAPSHOT["mcps"]}
    assert planned and not set(planned) & snapshot_ids  # 개발 중 MCP 는 Gateway 에 없다 (Tool 이 없다)


def test_question_expectations_match_gateway_groups(client):
    """expected_mcp_ids 는 expected_tools 를 가진 group 과 같아야 한다 (실제 Gateway catalog snapshot 기준)."""
    snapshot = json.loads((Path(__file__).parent / "fixtures" / "gateway_catalog_20261002.json").read_text())
    for q in client.app.state.demo_questions.values():
        owners = {m["mcp_id"] for ref in q.expected_tools for m in snapshot["mcps"] if ref in m["tools"]}
        assert q.expected_tools and owners == set(q.expected_mcp_ids), q.question_id


def test_web_research_card_uses_presentation_name_and_policy_category(client):
    web = by_id(client.get("/api/mcps").json())["web-research"]
    assert web["display_name"] == "Web Search MCP"
    assert web["category"] == "KRRI 정책현안 분석도구"


def test_every_krri_group_has_policy_category(client):
    for c in client.get("/api/mcps").json():
        if c["mcp_id"].startswith("krri-"):
            assert c["category"] == "KRRI 정책현안 분석도구", c


@pytest.mark.skipif(not os.environ.get("KEM_LIVE_GATEWAY_URL"), reason="KEM_LIVE_GATEWAY_URL 없음 (live Gateway 검사는 opt-in)")
def test_live_gateway_catalog_has_examples(questions):
    gateway = make_gateway_client("live", os.environ["KEM_LIVE_GATEWAY_URL"], 0)
    mcps = [{"mcp_id": m["mcp_id"], "tools": [f"{t['server_id']}/{t['name']}" for t in m["tools"]]}
            for m in gateway.list_mcps()]
    check_coverage(mcps, questions)
