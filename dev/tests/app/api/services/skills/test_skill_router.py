"""/api/skills — AI Skills HTTP contract. **모든 경로가 EASY ADMIN 전용이다** (비로그인 401 · ADMIN 아님 403).

- 등록: 간단히 만들기(JSON) · ZIP 업로드(body 그대로, application/zip) → 201. 같은 id 는 409, 새 버전은 PUT /{id}/package.
- 표시 정보(title · version · author · tags)는 query 로 오고, 비면 frontmatter metadata 에서 채운다.
- 내려받기 ?target=chatgpt|claude|source → application/zip + 파일 이름. 모르는 target 400, 모르는 id 404.
- 응답에 세션 token · password hash · 저장 경로가 없다. MCP · 내 MCP API 와 섞이지 않는다.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api.main import load_settings
from app.api.services.auth.account_service import SESSION_COOKIE
from tests.app.api.services.skills.skill_packages import SAMPLE, make_zip, upload, zip_names, zip_read


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
                         "created_at", "updated_at"}
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
