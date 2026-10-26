"""skill_service — Skill library 저장 · 버전 · export (API 로 관찰).

- canonical 한 벌: 올린 파일을 그대로 보관한다. ChatGPT · Claude export 는 같은 내용에 packaging(top-level <id>/ · SKILL.md)만 맞춘다.
  source export 는 올린 main 파일 이름(SKILL.md / skill.md) 그대로다.
- 새 버전은 같은 frontmatter name 이어야 하고, 비운 표시 정보는 이전 값을 쓴다. 작성자를 로그인 이름(공용 admin)으로 채우지 않는다.
- 파일은 runtime data 의 skills/uploaded_packages/<id>/source/ 에 실행 권한 없이(0644) 저장하고, 서버는 script 를 실행하지 않는다.
- 삭제는 metadata 와 파일을 같이 지운다.
- 공유용 표시 정보(요약 · 할 수 있는 일 · 추천 대상 · 사용 예시 · 정리 출처)는 skills.db 에만 있다.
  AI 정리 · 수정 · 새 버전 뒤에도 export 내용은 올린 원본과 같다. 기존 DB 는 앱이 뜰 때 없는 칸만 더한다.
"""

import json
import sqlite3
import stat

from fastapi.testclient import TestClient

from app.api.main import create_app, load_settings
from app.api.services.skills.skill_service import SkillLibrary
from tests.app.api.services.skills.skill_packages import SAMPLE, SKILL_MD, login, make_zip, upload, zip_names, zip_read


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


# ── 공유용 표시 정보 (AI 자동 정리) ─────────────────────────────────

ENRICHMENT = {
    "summary": "회의 메모를 회의록으로 정리해 주는 Skill 입니다.",
    "use_cases": ["회의 메모 정리", "후속 조치 추출"],
    "recommended_for": "회의를 자주 하는 연구원",
    "example_prompts": ["이 메모를 회의록으로 정리해줘"],
    "enrichment_source": "live",
}

# 표 칸을 더하기 전(2026-10-02 f89ffe8) 의 skills 표 그대로.
OLD_SCHEMA = """
CREATE TABLE skills (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, version TEXT NOT NULL, author TEXT NOT NULL,
    tags TEXT NOT NULL, main_file TEXT NOT NULL, file_count INTEGER NOT NULL, total_bytes INTEGER NOT NULL,
    compat TEXT NOT NULL, warnings TEXT NOT NULL, created_by TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
"""


def source_contents(c) -> dict[str, bytes]:
    data = c.get("/api/skills/meeting-notes-example/download?target=source").content
    return {n.split("/", 1)[1]: zip_read(data, n) for n in zip_names(data)}


def original_files() -> dict[str, bytes]:
    return {k: v.encode() if isinstance(v, str) else v for k, v in SAMPLE.items()}


def test_old_db_is_migrated_additively_and_old_rows_still_read():
    settings = load_settings()
    settings.skills_db.parent.mkdir(parents=True)
    source = settings.skill_packages_dir / "meeting-notes-example" / "source"
    (source / "references").mkdir(parents=True)
    (source / "SKILL.md").write_text(SKILL_MD)
    (source / "references" / "format.md").write_text("# 형식\n")
    with sqlite3.connect(settings.skills_db) as db:
        db.executescript(OLD_SCHEMA)
        db.execute("INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "meeting-notes-example", "예전 Skill", "원본 설명", "1.0", "연구실", '["회의"]', "SKILL.md", 2, 100,
            '{"chatgpt": true, "claude": true}', "[]", "admin", 1000.0, 2000.0))

    admin = login(TestClient(create_app()))  # 앱이 뜰 때 migration
    with sqlite3.connect(settings.skills_db) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(skills)")]
    assert columns[:14] == ["id", "title", "description", "version", "author", "tags", "main_file", "file_count",
                            "total_bytes", "compat", "warnings", "created_by", "created_at", "updated_at"]
    assert columns[14:] == ["summary", "use_cases", "recommended_for", "example_prompts", "enrichment_source"]

    [card] = admin.get("/api/skills").json()
    assert (card["title"], card["description"], card["tags"], card["updated_at"]) == ("예전 Skill", "원본 설명", ["회의"], 2000.0)
    assert (card["summary"], card["use_cases"], card["recommended_for"], card["example_prompts"],
            card["enrichment_source"]) == (None, [], None, [], None)
    detail = admin.get("/api/skills/meeting-notes-example").json()
    assert detail["summary"] is None and detail["skill_md"] == SKILL_MD
    # 다시 떠도 같다 (이미 있는 칸은 건드리지 않는다)
    create_app()
    assert login(TestClient(create_app())).get("/api/skills").json() == [card]
    # 옛 행에도 표시 정보를 저장할 수 있다
    assert admin.patch("/api/skills/meeting-notes-example", json=ENRICHMENT).json()["summary"] == ENRICHMENT["summary"]


def test_migration_is_idempotent_on_a_fresh_db(tmp_path):
    SkillLibrary(tmp_path / "s.db", tmp_path / "p")
    SkillLibrary(tmp_path / "s.db", tmp_path / "p")
    with sqlite3.connect(tmp_path / "s.db") as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(skills)")]
    assert len(columns) == len(set(columns)) == 19


def test_enrichment_never_enters_exported_packages(app, admin):
    """AI 분석 · 등록 · 표시 정보 수정 · 다시 정리 뒤에도 내려받는 package 는 올린 원본과 bytes 단위로 같다."""
    data = make_zip(SAMPLE)
    admin.post("/api/skills/analyze", content=data, headers={"content-type": "application/zip"})
    upload(admin, data, title="AI 가 정한 이름", tags="회의록,요약")
    admin.patch("/api/skills/meeting-notes-example", json={**ENRICHMENT, "title": "또 바꾼 이름"})
    admin.post("/api/skills/meeting-notes-example/analyze")

    assert source_contents(admin) == original_files()
    for target in ("chatgpt", "claude"):
        z = admin.get(f"/api/skills/meeting-notes-example/download?target={target}").content
        contents = {n.split("/", 1)[1]: zip_read(z, n) for n in zip_names(z)}
        assert contents == original_files()
        blob = b"".join(contents.values()).decode("utf-8", errors="replace")
        for value in ("AI 가 정한 이름", "또 바꾼 이름", ENRICHMENT["summary"], *ENRICHMENT["use_cases"],
                      ENRICHMENT["recommended_for"], *ENRICHMENT["example_prompts"], "회의록,요약"):
            assert value not in blob
    stored = load_settings().skill_packages_dir / "meeting-notes-example" / "source"
    assert {p.relative_to(stored).as_posix(): p.read_bytes() for p in stored.rglob("*") if p.is_file()} == original_files()


def test_new_version_keeps_reviewed_info_and_replaces_only_the_package(admin):
    upload(admin, make_zip(SAMPLE))
    admin.patch("/api/skills/meeting-notes-example", json=ENRICHMENT)
    v2 = {**SAMPLE, "references/format.md": "# v2\n"}
    body = admin.put("/api/skills/meeting-notes-example/package", params={"version": "2.0"}, content=make_zip(v2)).json()
    assert body["version"] == "2.0"
    assert {k: body[k] for k in ENRICHMENT} == ENRICHMENT
    assert source_contents(admin)["references/format.md"] == b"# v2\n"


def test_delete_after_enrichment_removes_everything(admin):
    upload(admin, make_zip(SAMPLE))
    admin.patch("/api/skills/meeting-notes-example", json=ENRICHMENT)
    assert admin.delete("/api/skills/meeting-notes-example").status_code == 204
    assert admin.get("/api/skills").json() == []
    with sqlite3.connect(load_settings().skills_db) as db:
        assert db.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 0
    assert upload(admin, make_zip(SAMPLE)).json()["summary"] is None  # 같은 id 로 다시 올리면 새로 시작


def test_patch_does_not_touch_package_identity(admin):
    upload(admin, make_zip(SAMPLE))
    before = admin.get("/api/skills/meeting-notes-example").json()
    after = admin.patch("/api/skills/meeting-notes-example", json={**ENRICHMENT, "title": "새 이름"}).json()
    for key in ("id", "description", "main_file", "skill_md", "files", "examples", "compat", "warnings", "created_at",
                "created_by", "file_count"):
        assert after[key] == before[key]
    assert after["updated_at"] >= before["updated_at"]
