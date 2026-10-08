"""skill_service — Skill library 저장 · 버전 · export (API 로 관찰).

- canonical 한 벌: 올린 파일을 그대로 보관한다. ChatGPT · Claude export 는 같은 내용에 packaging(top-level <id>/ · SKILL.md)만 맞춘다.
  source export 는 올린 main 파일 이름(SKILL.md / skill.md) 그대로다.
- 새 버전은 같은 frontmatter name 이어야 하고, 비운 표시 정보는 이전 값을 쓴다. 작성자를 로그인 이름(공용 admin)으로 채우지 않는다.
- 파일은 runtime data 의 skills/uploaded_packages/<id>/source/ 에 실행 권한 없이(0644) 저장하고, 서버는 script 를 실행하지 않는다.
- 삭제는 metadata 와 파일을 같이 지운다.
"""

import json
import sqlite3
import stat

from app.api.main import load_settings
from tests.app.api.services.skills.skill_packages import SAMPLE, SKILL_MD, make_zip, upload, zip_names, zip_read


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


def test_delete_removes_metadata_and_package_files(admin):
    upload(admin, make_zip(SAMPLE))
    assert admin.delete("/api/skills/meeting-notes-example").status_code == 204
    assert admin.get("/api/skills").json() == []
    assert not (load_settings().skill_packages_dir / "meeting-notes-example").exists()
    assert admin.delete("/api/skills/meeting-notes-example").status_code == 404


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
    stored = load_settings().skill_packages_dir / "meeting-notes-example" / "source" / "scripts" / "run.sh"
    assert stored.read_text() == sh
    assert stored.stat().st_mode & 0o777 == 0o644  # 실행 권한 없이 보관


def test_skill_files_live_under_runtime_uploaded_packages_not_repo(admin):
    upload(admin, make_zip(SAMPLE))
    settings = load_settings()
    assert (settings.skill_packages_dir / "meeting-notes-example" / "source" / "SKILL.md").is_file()
    assert settings.skill_packages_dir == settings.runtime_data_dir / "skills" / "uploaded_packages"
    with sqlite3.connect(settings.skills_db) as db:
        [(tags,)] = db.execute("SELECT tags FROM skills").fetchall()
    assert json.loads(tags) == []


def test_author_is_never_the_shared_admin_login(admin):
    """공용 ADMIN 계정 환경: 작성자를 비우면 빈 값이다 (로그인 이름 admin 으로 채우지 않는다)."""
    plain = {"SKILL.md": SKILL_MD.replace('metadata:\n  author: test-fixture\n  version: "0.3"\n', "")}
    body = upload(admin, make_zip(plain)).json()
    assert body["author"] == ""
    created = admin.post("/api/skills", json={"id": "plain-skill", "description": "설명", "instructions": "1. 한다."}).json()
    assert created["author"] == ""
