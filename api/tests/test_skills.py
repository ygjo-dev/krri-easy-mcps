"""KRRI AI Skills: ADMIN 전용 library · ZIP 검증 · canonical → ChatGPT / Claude export.

sample skill 은 테스트 fixture 다 (실제 업무 Skill 이 아니다). DB · skills 폴더는 테스트마다 임시다 (conftest.py).
"""

import io
import json
import sqlite3
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import skills as skills_module
from app.accounts import SESSION_COOKIE
from app.main import create_app
from app.settings import load_settings

ADMIN = {"username": "admin", "password": "admin"}
SKILL_MD = """---
name: meeting-notes-example
description: 회의 메모를 받아 결정 사항 · 할 일 · 담당자로 정리한다. 회의록 정리를 요청할 때 쓴다.
metadata:
  author: test-fixture
  version: "0.3"
---

# 회의 내용 정리 (테스트 예시)

1. 결정 사항을 먼저 적는다.
2. `references/format.md` 형식을 따른다.
"""


def make_zip(files: dict[str, bytes | str], *, folder="meeting-notes-example", symlinks=(), modes=None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for path, content in files.items():
            name = f"{folder}/{path}" if folder else path
            info = zipfile.ZipInfo(name)
            info.external_attr = ((modes or {}).get(path, stat.S_IFREG | 0o644)) << 16
            z.writestr(info, content.encode() if isinstance(content, str) else content)
        for name, target in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, target)
    return out.getvalue()


SAMPLE = {
    "SKILL.md": SKILL_MD,
    "references/format.md": "# 형식\n- 결정\n- 할 일\n",
    "assets/template.docx": b"PK\x03\x04binary-template",
    "examples/sample-input.md": "회의 메모 예시 입력\n",
}


@pytest.fixture
def app():
    return create_app()


def login(c, creds=ADMIN):
    r = c.post("/api/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def admin(app):
    return login(TestClient(app))


@pytest.fixture
def user(app):
    app.state.accounts.create_user("member", "member-pw")
    return login(TestClient(app), {"username": "member", "password": "member-pw"})


def upload(c, data: bytes, **query):
    return c.post("/api/skills/upload", params=query, content=data, headers={"content-type": "application/zip"})


def zip_names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return sorted(z.namelist())


def zip_read(data: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(name)


# ── 권한: 서버가 막는다 ──────────────────────────────────────


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
    assert not any((load_settings().skills_dir).iterdir())


def test_expired_session_is_401(app, admin):
    with sqlite3.connect(load_settings().db_path) as db:
        db.execute("UPDATE sessions SET expires_at = 0")
    assert admin.get("/api/skills").status_code == 401


def test_admin_gets_empty_library(admin):
    r = admin.get("/api/skills")
    assert r.status_code == 200 and r.json() == []


# ── 등록 · 목록 · 상세 ───────────────────────────────────────


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


def test_zip_with_skill_md_at_root_and_lowercase_name(admin):
    files = {"skill.md": SKILL_MD, "references/a.md": "a"}
    body = upload(admin, make_zip(files, folder="")).json()
    assert body["main_file"] == "skill.md" and body["author"] == "test-fixture"


def test_macos_junk_is_ignored(admin):
    data = make_zip({**SAMPLE, ".DS_Store": b"x"})
    with zipfile.ZipFile(io.BytesIO(data), "a") as z:
        z.writestr("__MACOSX/meeting-notes-example/._SKILL.md", b"junk")
    body = upload(admin, data).json()
    assert ".DS_Store" not in [f["path"] for f in body["files"]] and body["file_count"] == 4


def test_simple_create_builds_canonical_package(admin):
    r = admin.post("/api/skills", json={
        "id": "weekly-report-example", "title": "주간 보고 정리 (예시)", "description": "주간 업무를 표로 정리한다.",
        "version": "1.0", "author": "테스트", "tags": ["보고"], "instructions": "1. 표로 정리한다.",
        "example": "입력: ...\n출력: ...",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["skill_md"].startswith("---\nname: weekly-report-example\ndescription: 주간 업무를 표로 정리한다.\n---\n")
    assert "# 주간 보고 정리 (예시)" in body["skill_md"]
    assert [f["path"] for f in body["files"]] == ["SKILL.md", "examples/example.md"]
    data = admin.get("/api/skills/weekly-report-example/download?target=claude").content
    assert zip_names(data) == ["weekly-report-example/SKILL.md", "weekly-report-example/examples/example.md"]


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


def test_new_version_keeps_display_metadata_left_blank(admin):
    plain = {"SKILL.md": SKILL_MD.replace('metadata:\n  author: test-fixture\n  version: "0.3"\n', "")}
    upload(admin, make_zip(plain), title="회의 정리", version="1.0", author="연구실", tags="회의,정리")
    body = admin.put("/api/skills/meeting-notes-example/package", params={"version": "1.1"},
                     content=make_zip(plain)).json()
    assert (body["title"], body["version"], body["author"], body["tags"]) == ("회의 정리", "1.1", "연구실", ["회의", "정리"])


def test_new_version_with_other_name_is_rejected(admin):
    upload(admin, make_zip(SAMPLE))
    other = make_zip({"SKILL.md": SKILL_MD.replace("meeting-notes-example", "other-skill")}, folder="other-skill")
    r = admin.put("/api/skills/meeting-notes-example/package", content=other)
    assert r.status_code == 400 and "name" in r.json()["detail"]
    assert admin.get("/api/skills/other-skill").status_code == 404


def test_delete(admin):
    upload(admin, make_zip(SAMPLE))
    assert admin.delete("/api/skills/meeting-notes-example").status_code == 204
    assert admin.get("/api/skills").json() == []
    assert not (load_settings().skills_dir / "meeting-notes-example").exists()
    assert admin.delete("/api/skills/meeting-notes-example").status_code == 404


@pytest.mark.parametrize("skill_id", ["nope", "..", "..%2F..%2Fetc", "Bad", "a" * 65])
def test_unknown_or_invalid_id_is_404(admin, skill_id):
    assert admin.get(f"/api/skills/{skill_id}").status_code in (404,)
    assert admin.get(f"/api/skills/{skill_id}/download?target=claude").status_code == 404


# ── export: canonical 한 벌 → target packaging ───────────────


def test_chatgpt_export(admin):
    upload(admin, make_zip(SAMPLE))
    r = admin.get("/api/skills/meeting-notes-example/download?target=chatgpt")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="meeting-notes-example-chatgpt.zip"' in r.headers["content-disposition"]
    assert zip_names(r.content) == [
        "meeting-notes-example/SKILL.md", "meeting-notes-example/assets/template.docx",
        "meeting-notes-example/examples/sample-input.md", "meeting-notes-example/references/format.md"]


def test_claude_export(admin):
    upload(admin, make_zip(SAMPLE))
    r = admin.get("/api/skills/meeting-notes-example/download?target=claude")
    names = zip_names(r.content)
    # Claude 는 ZIP 의 top-level <name>/ 아래 SKILL.md 를 찾는다. folder 이름 = frontmatter name
    assert names[0] == "meeting-notes-example/SKILL.md"
    assert {n.split("/")[0] for n in names} == {"meeting-notes-example"}


def test_source_export_keeps_uploaded_main_file_name(admin):
    upload(admin, make_zip({"skill.md": SKILL_MD, "references/a.md": "a"}))
    source = admin.get("/api/skills/meeting-notes-example/download?target=source").content
    assert zip_names(source) == ["meeting-notes-example/references/a.md", "meeting-notes-example/skill.md"]
    # 제품용 export 는 main 파일 이름만 맞춘다. 내용은 같다
    chatgpt = admin.get("/api/skills/meeting-notes-example/download?target=chatgpt").content
    assert zip_read(chatgpt, "meeting-notes-example/SKILL.md") == zip_read(source, "meeting-notes-example/skill.md")
    assert admin.get("/api/skills/meeting-notes-example/download").content == source  # 기본 target=source


def test_exports_share_one_canonical_source(admin):
    upload(admin, make_zip(SAMPLE))
    zips = {t: admin.get(f"/api/skills/meeting-notes-example/download?target={t}").content
            for t in ("chatgpt", "claude", "source")}
    contents = {t: {n.split("/", 1)[1].lower(): zip_read(z, n) for n in zip_names(z)} for t, z in zips.items()}
    assert contents["chatgpt"] == contents["claude"] == contents["source"]


def test_resources_are_preserved_byte_for_byte(admin):
    upload(admin, make_zip(SAMPLE))
    for target in ("chatgpt", "claude", "source"):
        data = admin.get(f"/api/skills/meeting-notes-example/download?target={target}").content
        assert zip_read(data, "meeting-notes-example/assets/template.docx") == b"PK\x03\x04binary-template"
        assert zip_read(data, "meeting-notes-example/references/format.md") == SAMPLE["references/format.md"].encode()


def test_unknown_target_is_400(admin):
    upload(admin, make_zip(SAMPLE))
    r = admin.get("/api/skills/meeting-notes-example/download?target=gemini")
    assert r.status_code == 400


def test_exported_entries_are_plain_non_executable_files(admin):
    upload(admin, make_zip({**SAMPLE, "scripts/run.sh": "#!/bin/sh\necho hi\n"},
                           modes={"scripts/run.sh": stat.S_IFREG | 0o755}))
    data = admin.get("/api/skills/meeting-notes-example/download?target=chatgpt").content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            assert info.external_attr >> 16 == stat.S_IFREG | 0o644, info.filename


# ── 서버는 script 를 실행하지 않는다 ──────────────────────────


def test_scripts_are_stored_but_never_executed(admin, tmp_path):
    marker = tmp_path / "executed"
    py = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
    sh = f"#!/bin/sh\ntouch {marker}\n"
    files = {**SAMPLE, "scripts/run.py": py, "scripts/run.sh": sh, "scripts/__init__.py": py, "conftest.py": py,
             "setup.py": py}
    r = upload(admin, make_zip(files, modes={"scripts/run.sh": stat.S_IFREG | 0o755}))
    assert r.status_code == 201
    admin.get("/api/skills/meeting-notes-example")
    for target in ("chatgpt", "claude", "source"):
        admin.get(f"/api/skills/meeting-notes-example/download?target={target}")
    assert not marker.exists()
    stored = load_settings().skills_dir / "meeting-notes-example" / "source" / "scripts" / "run.sh"
    assert stored.read_text() == sh
    assert stored.stat().st_mode & 0o777 == 0o644  # 실행 권한 없이 보관


# ── ZIP 보안 · 비정상 package 거부 ────────────────────────────


def raw_zip(entries: list[tuple[str, bytes]], mode=stat.S_IFREG | 0o644) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, content in entries:
            info = zipfile.ZipInfo("x")
            info.filename = name  # ZipInfo 생성자는 일부 이름을 고쳐 쓴다. 공격 이름을 그대로 넣는다
            info.orig_filename = name
            info.external_attr = mode << 16
            z.writestr(info, content)
    return out.getvalue()


@pytest.mark.parametrize("evil", [
    "../evil.txt",
    "meeting-notes-example/../../evil.txt",
    "meeting-notes-example/../evil.txt",
    "/etc/evil.txt",
    "C:/evil.txt",
    "meeting-notes-example\\..\\evil.txt",
    "meeting-notes-example/./a.txt",
    "meeting-notes-example//a.txt",
])
def test_zip_path_traversal_is_rejected(admin, evil, tmp_path):
    data = raw_zip([("meeting-notes-example/SKILL.md", SKILL_MD.encode()), (evil, b"pwned")])
    r = upload(admin, data)
    assert r.status_code == 400, (evil, r.text)
    assert any(k in r.json()["detail"] for k in ("경로", "파일 이름")), r.json()
    assert admin.get("/api/skills").json() == []
    root = load_settings().db_path.parent
    assert not any(p.name == "evil.txt" for p in root.rglob("*"))
    assert not (Path("/etc/evil.txt")).exists()


def test_symlink_entry_is_rejected(admin):
    data = make_zip(SAMPLE, symlinks=[("meeting-notes-example/link", "/etc/passwd")])
    r = upload(admin, data)
    assert r.status_code == 400 and "symlink" in r.json()["detail"]


def test_special_file_entry_is_rejected(admin):
    data = raw_zip([("meeting-notes-example/SKILL.md", SKILL_MD.encode())], mode=stat.S_IFIFO | 0o644)
    assert upload(admin, data).status_code == 400


def test_encrypted_entry_is_rejected(admin):
    data = bytearray(make_zip(SAMPLE))
    # 첫 local header 와 central directory 의 general purpose flag 에 암호화 bit 를 세운다
    data[6] |= 0x1
    central = data.rfind(b"PK\x01\x02", 0, len(data))
    first_central = data.find(b"PK\x01\x02")
    data[first_central + 8] |= 0x1
    assert central >= first_central
    assert upload(admin, bytes(data)).status_code == 400


@pytest.mark.parametrize("files,folder,detail", [
    ({"README.md": "x"}, "meeting-notes-example", "SKILL.md 가 없습니다"),
    ({"SKILL.md": SKILL_MD, "sub/SKILL.md": SKILL_MD}, "meeting-notes-example", "하나만"),
    ({"nested/SKILL.md": SKILL_MD}, "meeting-notes-example", "바로 아래"),
    ({"SKILL.md": "no frontmatter"}, "meeting-notes-example", "frontmatter"),
    ({"SKILL.md": "---\nname: [x\n---\n"}, "meeting-notes-example", "YAML"),
    ({"SKILL.md": "---\n- a\n---\n"}, "meeting-notes-example", "key: value"),
    ({"SKILL.md": "---\nname: x\ndescription: d\n"}, "meeting-notes-example", "닫히지"),
    ({"SKILL.md": "---\ndescription: d\n---\n"}, "meeting-notes-example", "name"),
    ({"SKILL.md": "---\nname: Bad_Name\ndescription: d\n---\n"}, "meeting-notes-example", "name"),
    ({"SKILL.md": "---\nname: -bad\ndescription: d\n---\n"}, "meeting-notes-example", "name"),
    ({"SKILL.md": "---\nname: a--b\ndescription: d\n---\n"}, "meeting-notes-example", "name"),
    ({"SKILL.md": "---\nname: ok\ndescription: \"\"\n---\n"}, "meeting-notes-example", "description"),
    ({"SKILL.md": "---\nname: ok\ndescription: " + "x" * 1025 + "\n---\n"}, "meeting-notes-example", "1024"),
    ({"SKILL.md": b"---\nname: ok\ndescription: \xff\n---\n"}, "meeting-notes-example", "UTF-8"),
])
def test_invalid_package_is_rejected(admin, files, folder, detail):
    r = upload(admin, make_zip(files, folder=folder))
    assert r.status_code == 400, r.text
    assert detail in r.json()["detail"]
    assert admin.get("/api/skills").json() == []


def test_two_top_level_folders_are_rejected(admin):
    data = raw_zip([("a/SKILL.md", SKILL_MD.encode()), ("b/x.md", b"x")])
    assert "folder 하나" in upload(admin, data).json()["detail"]


def test_case_insensitive_duplicate_paths_are_rejected(admin):
    data = make_zip({**SAMPLE, "references/Format.md": "dup"})
    assert "대소문자" in upload(admin, data).json()["detail"]


@pytest.mark.parametrize("data,detail", [(b"", "ZIP 파일을 보내"), (b"not a zip", "읽을 수 없습니다")])
def test_non_zip_body_is_rejected(admin, data, detail):
    r = upload(admin, data)
    assert r.status_code == 400 and detail in r.json()["detail"]


def test_limits(admin, monkeypatch):
    monkeypatch.setattr(skills_module, "MAX_FILES", 3)
    r = upload(admin, make_zip(SAMPLE))  # 4 files
    assert r.status_code == 413 and "너무 많습니다" in r.json()["detail"]
    monkeypatch.setattr(skills_module, "MAX_FILES", 200)
    monkeypatch.setattr(skills_module, "MAX_FILE_BYTES", 100)
    assert upload(admin, make_zip({**SAMPLE, "assets/big.bin": b"x" * 101})).status_code == 413
    monkeypatch.setattr(skills_module, "MAX_FILE_BYTES", 10_000)
    monkeypatch.setattr(skills_module, "MAX_TOTAL_BYTES", 500)
    assert upload(admin, make_zip({**SAMPLE, "assets/a.bin": b"x" * 300, "assets/b.bin": b"y" * 300})).status_code == 413
    assert admin.get("/api/skills").json() == []


def test_highly_compressed_entry_is_rejected(admin, monkeypatch):
    """1MB 의 0 이 수 KB 로 압축된 entry (zip bomb 모양). 풀린 크기 상한으로 거부하고 아무것도 저장하지 않는다."""
    monkeypatch.setattr(skills_module, "MAX_FILE_BYTES", 1000)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meeting-notes-example/SKILL.md", SKILL_MD)
        z.writestr("meeting-notes-example/assets/bomb.bin", b"\0" * 1_000_000)
    assert len(out.getvalue()) < 10_000
    assert upload(admin, out.getvalue()).status_code == 413
    assert admin.get("/api/skills").json() == []


def test_upload_body_limit(admin, monkeypatch):
    monkeypatch.setattr("app.routes.skills.MAX_UPLOAD_BYTES", 1000)
    r = upload(admin, b"x" * 2000)
    assert r.status_code == 413


def test_claude_specific_rules_are_shown_not_hidden(admin):
    md = "---\nname: claude-helper\ndescription: <b>bold</b> 설명\nversion: 1\n---\n본문\n"
    body = upload(admin, make_zip({"SKILL.md": md}, folder="claude-helper")).json()
    assert body["compat"] == {"chatgpt": True, "claude": False}
    assert any("anthropic · claude" in w for w in body["warnings"])
    assert any("XML" in w for w in body["warnings"])
    assert any("version" in w for w in body["warnings"])  # 규격 밖 frontmatter


# ── 비밀 노출 없음 · 기존 기능과 분리 ─────────────────────────


def test_skill_responses_carry_no_auth_secrets(admin):
    token = admin.cookies.get(SESSION_COOKIE)
    texts = [upload(admin, make_zip(SAMPLE)).text, admin.get("/api/skills").text,
             admin.get("/api/skills/meeting-notes-example").text,
             admin.post("/api/skills", json={"id": "x-y", "description": "d", "instructions": "i"}).text]
    with sqlite3.connect(load_settings().db_path) as db:
        [stored_hash] = db.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()
    for text in texts:
        for marker in (token, stored_hash, "password", "scrypt", "token_hash", str(load_settings().skills_dir)):
            assert marker not in text


def test_skill_files_live_under_skills_dir_not_repo(admin):
    upload(admin, make_zip(SAMPLE))
    settings = load_settings()
    assert (settings.skills_dir / "meeting-notes-example" / "source" / "SKILL.md").is_file()
    assert settings.skills_dir == settings.db_path.parent / "skills"
    with sqlite3.connect(settings.db_path) as db:
        [(tags,)] = db.execute("SELECT tags FROM skills").fetchall()
    assert json.loads(tags) == []


def test_skills_do_not_touch_toolbox_or_mcp_routes(admin):
    upload(admin, make_zip(SAMPLE))
    assert "meeting-notes-example" not in admin.get("/api/mcps").text
    assert admin.get("/api/toolbox").json()["mcp_ids"] == []


def test_author_is_never_the_shared_admin_login(admin):
    """공용 ADMIN 계정 환경: 작성자를 비우면 빈 값이다 (로그인 이름 admin 으로 채우지 않는다)."""
    plain = {"SKILL.md": SKILL_MD.replace('metadata:\n  author: test-fixture\n  version: "0.3"\n', "")}
    body = upload(admin, make_zip(plain)).json()
    assert body["author"] == ""
    created = admin.post("/api/skills", json={"id": "plain-skill", "description": "설명", "instructions": "1. 한다."}).json()
    assert created["author"] == ""
