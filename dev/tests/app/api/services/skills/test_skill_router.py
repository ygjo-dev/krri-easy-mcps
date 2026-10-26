"""/api/skills — AI Skills HTTP contract. **모든 경로가 EASY ADMIN 전용이다** (비로그인 401 · ADMIN 아님 403).

- 등록: 간단히 만들기(JSON) · ZIP 업로드(body 그대로, application/zip) → 201. 같은 id 는 409, 새 버전은 PUT /{id}/package.
- 표시 정보(title · version · author · tags)는 query 로 오고, 비면 frontmatter metadata 에서 채운다.
- 내려받기 ?target=chatgpt|claude|source → application/zip + 파일 이름. 모르는 target 400, 모르는 id 404.
- 응답에 세션 token · password hash · 저장 경로가 없다. MCP · 내 MCP API 와 섞이지 않는다.
- AI 자동 정리: POST /analyze (ZIP body, 업로드와 같은 검증) · POST /{id}/analyze 는 제안만 돌려주고 저장하지 않는다.
  검토한 표시 정보는 PATCH /{id} 로 저장한다. 모델 실패는 502 + 정해진 문구 (내부 주소 · 모델 응답 없음).
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api.main import SKILL_AI_UNAVAILABLE_DETAIL, load_settings
from app.api.services.auth.account_service import SESSION_COOKIE
from tests.app.api.integrations.skill_ai.skill_ai_fake import API_KEY, BASE_URL, GOOD_RESULT, MODEL, Model, client_for
from tests.app.api.services.skills.skill_packages import SAMPLE, SKILL_MD, make_zip, upload, zip_names, zip_read


ROUTES = [
    ("get", "/api/skills", {}),
    ("get", "/api/skills/meeting-notes-example", {}),
    ("post", "/api/skills", {"json": {"id": "x", "description": "d", "instructions": "i"}}),
    ("post", "/api/skills/upload", {"content": b"PK", "headers": {"content-type": "application/zip"}}),
    ("put", "/api/skills/meeting-notes-example/package", {"content": b"PK"}),
    ("delete", "/api/skills/meeting-notes-example", {}),
    ("get", "/api/skills/meeting-notes-example/download?target=chatgpt", {}),
    ("get", "/api/skills/meeting-notes-example/download?target=claude", {}),
    ("get", "/api/skills/meeting-notes-example/download?target=source", {}),
    ("post", "/api/skills/analyze", {"content": b"PK", "headers": {"content-type": "application/zip"}}),
    ("post", "/api/skills/meeting-notes-example/analyze", {}),
    ("patch", "/api/skills/meeting-notes-example", {"json": {"summary": "x"}}),
]


@pytest.mark.parametrize("method,path,kw", ROUTES)
def test_anonymous_gets_401(app, method, path, kw):
    r = getattr(TestClient(app), method)(path, **kw)
    assert r.status_code == 401
    assert r.json() == {"detail": "로그인이 필요합니다."}


@pytest.mark.parametrize("method,path,kw", ROUTES)
def test_user_role_gets_403(user, method, path, kw):
    r = getattr(user, method)(path, **kw)
    assert r.status_code == 403
    assert r.json() == {"detail": "관리자만 사용할 수 있습니다."}


def test_forbidden_requests_do_not_write(app, user):
    upload(user, make_zip(SAMPLE))
    user.post("/api/skills", json={"id": "x-skill", "description": "d", "instructions": "i"})
    assert app.state.skills.list() == []
    assert not any((load_settings().skill_packages_dir).iterdir())


def test_expired_session_is_401(app, admin):
    with sqlite3.connect(load_settings().accounts_db) as db:
        db.execute("UPDATE sessions SET expires_at = 0")
    assert admin.get("/api/skills").status_code == 401


def test_admin_gets_empty_library(admin):
    r = admin.get("/api/skills")
    assert r.status_code == 200 and r.json() == []


def test_upload_zip_then_list_and_detail(admin):
    r = upload(admin, make_zip(SAMPLE), title="회의 내용 정리 (예시)", tags="회의, 문서작성 ,회의")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "meeting-notes-example"
    assert body["title"] == "회의 내용 정리 (예시)"
    assert body["version"] == "0.3" and body["author"] == "test-fixture"  # frontmatter metadata 에서
    assert body["tags"] == ["회의", "문서작성"]
    assert body["compat"] == {"chatgpt": True, "claude": True}
    assert body["main_file"] == "SKILL.md" and body["skill_md"].startswith("---\nname: meeting-notes-example")
    assert [f["path"] for f in body["files"]] == [
        "SKILL.md", "assets/template.docx", "examples/sample-input.md", "references/format.md"]
    assert body["examples"] == [{"path": "examples/sample-input.md", "content": "회의 메모 예시 입력\n"}]
    assert body["created_by"] == "admin" and body["warnings"] == []
    [card] = admin.get("/api/skills").json()
    assert card["id"] == "meeting-notes-example" and card["file_count"] == 4
    assert set(card) == {"id", "title", "description", "version", "author", "tags", "compat", "file_count",
                         "created_at", "updated_at",
                         # 공유용 표시 정보 (AI 자동 정리 · 사람 검토). 정리 전이면 비어 있다
                         "summary", "use_cases", "recommended_for", "example_prompts", "enrichment_source"}
    assert (card["summary"], card["use_cases"], card["recommended_for"], card["example_prompts"],
            card["enrichment_source"]) == (None, [], None, [], None)
    assert admin.get("/api/skills/meeting-notes-example").json() == body


def test_query_metadata_overrides_frontmatter(admin):
    body = upload(admin, make_zip(SAMPLE), version="1.2", author="철도AI융합연구실").json()
    assert body["version"] == "1.2" and body["author"] == "철도AI융합연구실"


@pytest.mark.parametrize("payload,detail", [
    ({"id": "Bad Name", "description": "d", "instructions": "i"}, "frontmatter name"),
    ({"id": "ok-name", "description": "", "instructions": "i"}, "description"),
    ({"id": "ok-name", "description": "d", "instructions": "  "}, "지시사항"),
])
def test_simple_create_validation(admin, payload, detail):
    r = admin.post("/api/skills", json=payload)
    assert r.status_code == 400 and detail in r.json()["detail"]


def test_duplicate_id_is_409_and_new_version_replaces(admin):
    upload(admin, make_zip(SAMPLE), version="1.0")
    assert upload(admin, make_zip(SAMPLE)).status_code == 409
    first = admin.get("/api/skills/meeting-notes-example").json()
    v2 = {**SAMPLE, "references/format.md": "# v2\n"}
    del v2["assets/template.docx"]
    r = admin.put("/api/skills/meeting-notes-example/package", params={"version": "2.0", "title": "새 이름"},
                  content=make_zip(v2))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "2.0" and body["created_at"] == first["created_at"]
    assert "assets/template.docx" not in [f["path"] for f in body["files"]]
    src = zip_read(admin.get("/api/skills/meeting-notes-example/download").content,
                   "meeting-notes-example/references/format.md")
    assert src == b"# v2\n"


@pytest.mark.parametrize("skill_id", ["nope", "..", "..%2F..%2Fetc", "Bad", "a" * 65])
def test_unknown_or_invalid_id_is_404(admin, skill_id):
    assert admin.get(f"/api/skills/{skill_id}").status_code in (404,)
    assert admin.get(f"/api/skills/{skill_id}/download?target=claude").status_code == 404


def test_chatgpt_export(admin):
    upload(admin, make_zip(SAMPLE))
    r = admin.get("/api/skills/meeting-notes-example/download?target=chatgpt")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="meeting-notes-example-chatgpt.zip"' in r.headers["content-disposition"]
    assert zip_names(r.content) == [
        "meeting-notes-example/SKILL.md", "meeting-notes-example/assets/template.docx",
        "meeting-notes-example/examples/sample-input.md", "meeting-notes-example/references/format.md"]


def test_unknown_target_is_400(admin):
    upload(admin, make_zip(SAMPLE))
    r = admin.get("/api/skills/meeting-notes-example/download?target=gemini")
    assert r.status_code == 400


@pytest.mark.parametrize("data,detail", [(b"", "ZIP 파일을 보내"), (b"not a zip", "읽을 수 없습니다")])
def test_non_zip_body_is_rejected(admin, data, detail):
    r = upload(admin, data)
    assert r.status_code == 400 and detail in r.json()["detail"]


def test_upload_body_limit(admin, monkeypatch):
    monkeypatch.setattr("app.api.services.skills.skill_router.MAX_UPLOAD_BYTES", 1000)
    r = upload(admin, b"x" * 2000)
    assert r.status_code == 413


def test_skill_responses_carry_no_auth_secrets(admin):
    token = admin.cookies.get(SESSION_COOKIE)
    texts = [upload(admin, make_zip(SAMPLE)).text, admin.get("/api/skills").text,
             admin.get("/api/skills/meeting-notes-example").text,
             admin.post("/api/skills", json={"id": "x-y", "description": "d", "instructions": "i"}).text]
    with sqlite3.connect(load_settings().accounts_db) as db:
        [stored_hash] = db.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()
    for text in texts:
        for marker in (token, stored_hash, "password", "scrypt", "token_hash", str(load_settings().skill_packages_dir)):
            assert marker not in text


def test_skills_do_not_touch_toolbox_or_mcp_routes(admin):
    upload(admin, make_zip(SAMPLE))
    assert "meeting-notes-example" not in admin.get("/api/mcps").text
    assert admin.get("/api/toolbox").json()["mcp_ids"] == []


# ── AI 자동 정리 ─────────────────────────────────────────────────────


def analyze(c, data: bytes):
    return c.post("/api/skills/analyze", content=data, headers={"content-type": "application/zip"})


def skill_rows() -> int:
    with sqlite3.connect(load_settings().skills_db) as db:
        return db.execute("SELECT COUNT(*) FROM skills").fetchone()[0]


def test_analyze_with_mock_returns_suggestion_without_saving(app, admin):
    r = analyze(admin, make_zip(SAMPLE))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"package", "suggestion", "analysis_source"}
    assert body["analysis_source"] == "mock"
    assert body["package"]["id"] == "meeting-notes-example"
    assert body["package"]["version"] == "0.3" and body["package"]["author"] == "test-fixture"
    assert body["suggestion"]["title"] == "회의 내용 정리 (테스트 예시)"
    assert set(body["suggestion"]) == {"title", "summary", "tags", "use_cases", "recommended_for", "example_prompts"}
    # 분석은 미리보기다. 저장하지 않는다
    assert skill_rows() == 0 and admin.get("/api/skills").json() == []
    assert not any(load_settings().skill_packages_dir.iterdir())


def test_analyze_with_live_model(app, admin):
    model = Model()
    app.state.skill_ai = client_for(model, api_key=API_KEY)
    r = analyze(admin, make_zip(SAMPLE))
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"] == GOOD_RESULT and r.json()["analysis_source"] == "live"
    assert len(model.requests) == 1
    assert skill_rows() == 0
    for leaked in (BASE_URL, MODEL, API_KEY, "<<<SKILL PACKAGE>>>", "큐레이터"):
        assert leaked not in r.text


@pytest.mark.parametrize("model", [
    Model(status=500, raw=f"Traceback ... {BASE_URL} key={API_KEY}".encode()),
    Model({"choices": [{"message": {"content": "회의록 Skill 입니다."}, "finish_reason": "stop"}]}),
    Model({"choices": [{"message": {"content": json.dumps({"title": ""})}, "finish_reason": "stop"}]}),
], ids=["http500", "plain-text", "invalid-fields"])
def test_analysis_failure_is_sanitized_502_and_does_not_save(app, admin, model, caplog):
    app.state.skill_ai = client_for(model, api_key=API_KEY)
    r = analyze(admin, make_zip(SAMPLE))
    assert r.status_code == 502
    assert r.json() == {"detail": SKILL_AI_UNAVAILABLE_DETAIL}
    assert "skill AI unavailable on /api/skills/analyze" in caplog.text
    for leaked in (BASE_URL, API_KEY, "Traceback", MODEL):
        assert leaked not in r.text
        assert leaked not in caplog.text  # 서버 로그에도 원인 종류만
    assert "회의 메모" not in caplog.text  # Skill 내용을 로그에 남기지 않는다
    assert skill_rows() == 0


@pytest.mark.parametrize("data,status,detail", [
    (b"", 400, "ZIP 파일을 보내"),
    (b"not a zip", 400, "읽을 수 없습니다"),
    (make_zip({"references/a.md": "a"}), 400, "SKILL.md 가 없습니다"),
    (make_zip({"SKILL.md": "no frontmatter"}), 400, "frontmatter"),
    (make_zip({"SKILL.md": SKILL_MD, "../evil.md": "x"}, folder=""), 400, "상위 폴더"),
])
def test_analyze_uses_the_same_package_validation(app, admin, data, status, detail):
    model = Model()
    app.state.skill_ai = client_for(model)
    r = analyze(admin, data)
    assert r.status_code == status and detail in r.json()["detail"]
    assert model.requests == []  # 검증에 실패하면 모델을 부르지 않는다


def test_analyze_body_limit(admin, monkeypatch):
    monkeypatch.setattr("app.api.services.skills.skill_router.MAX_UPLOAD_BYTES", 1000)
    assert analyze(admin, b"x" * 2000).status_code == 413


def test_register_flow_upload_then_patch_saves_reviewed_info(admin):
    """화면 흐름: 분석 → 사람이 고침 → 업로드(이름 · 버전 · 작성자 · 태그) → PATCH(요약 · 활용 · 추천 · 예시)."""
    suggestion = analyze(admin, make_zip(SAMPLE)).json()["suggestion"]
    created = upload(admin, make_zip(SAMPLE), title="회의록 자동 정리", tags="회의록,요약").json()
    r = admin.patch(f"/api/skills/{created['id']}", json={
        "summary": suggestion["summary"] + " 고친 문장.",
        "use_cases": ["회의 메모 정리", "후속 조치 추출"],
        "recommended_for": "회의를 자주 주관하는 연구원",
        "example_prompts": ["이 메모를 회의록으로 정리해줘"],
        "enrichment_source": "mock",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "회의록 자동 정리" and body["tags"] == ["회의록", "요약"]
    assert body["summary"].endswith("고친 문장.")
    assert body["use_cases"] == ["회의 메모 정리", "후속 조치 추출"]
    assert body["recommended_for"] == "회의를 자주 주관하는 연구원"
    assert body["example_prompts"] == ["이 메모를 회의록으로 정리해줘"]
    assert body["enrichment_source"] == "mock"
    # 원본 description 은 AI · 사람 수정과 별개다
    assert body["description"] == "회의 메모를 받아 결정 사항 · 할 일 · 담당자로 정리한다. 회의록 정리를 요청할 때 쓴다."
    [card] = admin.get("/api/skills").json()
    assert card["summary"] == body["summary"] and card["use_cases"] == body["use_cases"]
    assert admin.get("/api/skills/meeting-notes-example").json() == body


def test_patch_only_changes_sent_fields_and_can_clear_summary(admin):
    upload(admin, make_zip(SAMPLE), title="처음 이름", tags="회의")
    admin.patch("/api/skills/meeting-notes-example", json={"summary": "요약", "use_cases": ["a"]})
    body = admin.patch("/api/skills/meeting-notes-example", json={"summary": "", "title": "  "}).json()
    assert body["summary"] is None  # 비우면 화면은 원본 description 을 보인다
    assert body["use_cases"] == ["a"] and body["tags"] == ["회의"]
    assert body["title"] == "meeting-notes-example"  # 빈 이름은 Skill ID
    assert body["version"] == "0.3"


@pytest.mark.parametrize("payload,status", [
    ({"summary": "가" * 1001}, 400),
    ({"use_cases": [f"u{i}" for i in range(6)]}, 400),
    ({"tags": [f"t{i}" for i in range(11)]}, 400),
    ({"enrichment_source": "gpt"}, 422),
    ({"use_cases": "문자열"}, 422),
])
def test_patch_validation(admin, payload, status):
    upload(admin, make_zip(SAMPLE))
    before = admin.get("/api/skills/meeting-notes-example").json()
    r = admin.patch("/api/skills/meeting-notes-example", json=payload)
    assert r.status_code == status
    assert admin.get("/api/skills/meeting-notes-example").json() == before


def test_patch_and_reanalyze_unknown_skill_is_404(admin):
    assert admin.patch("/api/skills/nope", json={"summary": "x"}).status_code == 404
    assert admin.post("/api/skills/nope/analyze").status_code == 404
    assert admin.post("/api/skills/Bad..Id/analyze").status_code == 404


def test_reanalyze_stored_package_returns_suggestion_without_saving(app, admin):
    upload(admin, make_zip(SAMPLE), title="그대로")
    before = admin.get("/api/skills/meeting-notes-example").json()
    source = admin.get("/api/skills/meeting-notes-example/download").content
    model = Model()
    app.state.skill_ai = client_for(model)
    r = admin.post("/api/skills/meeting-notes-example/analyze")
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"] == GOOD_RESULT and r.json()["package"]["id"] == "meeting-notes-example"
    assert "회의 내용 정리 (테스트 예시)" in json.loads(model.requests[0].content)["messages"][1]["content"]
    assert admin.get("/api/skills/meeting-notes-example").json() == before
    assert admin.get("/api/skills/meeting-notes-example/download").content == source


def test_reanalyze_failure_is_502(app, admin):
    upload(admin, make_zip(SAMPLE))
    app.state.skill_ai = client_for(Model(status=503, raw=b"down"))
    r = admin.post("/api/skills/meeting-notes-example/analyze")
    assert r.status_code == 502 and r.json() == {"detail": SKILL_AI_UNAVAILABLE_DETAIL}


def test_old_upload_endpoint_still_works_without_ai(admin):
    """AI 자동 정리는 더한 기능이다. 기존 ZIP 업로드 · 간단히 만들기는 그대로 된다 (표시 정보는 비어 있다)."""
    body = upload(admin, make_zip(SAMPLE), title="옛 방식").json()
    assert body["title"] == "옛 방식" and body["summary"] is None and body["enrichment_source"] is None
    made = admin.post("/api/skills", json={"id": "x-y", "description": "d", "instructions": "i"})
    assert made.status_code == 201 and made.json()["use_cases"] == []
