"""package_service — Skill package 형식 · ZIP 검증 · export packaging (API 로 관찰).

- 형식: Agent Skills 규격. SKILL.md(대소문자 무시) 하나, YAML frontmatter name(소문자 · 숫자 · 하이픈 64자) · description(1024자).
- ZIP 은 경로 탈출 · 절대 경로 · 역슬래시 · symlink · 특수 파일 · 암호화 entry · 대소문자만 다른 중복 · top-level 폴더 둘 이상을 거부한다.
  개수 · 크기 상한은 실제로 풀린 바이트로 센다 (413). macOS 부산물은 조용히 버린다.
- export ZIP 의 entry 는 실행 권한 없는 일반 파일이다. Claude 전용 제약은 숨기지 않고 compat · warnings 로 보인다.
"""

import io
import stat
import zipfile
from pathlib import Path

import pytest

from app.api.main import load_settings
from app.api.services.skills import package_service as skills_module
from tests.app.api.services.skills.skill_packages import SAMPLE, SKILL_MD, make_zip, raw_zip, upload, zip_names


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


def test_exported_entries_are_plain_non_executable_files(admin):
    upload(admin, make_zip({**SAMPLE, "scripts/run.sh": "#!/bin/sh\necho hi\n"},
                           modes={"scripts/run.sh": stat.S_IFREG | 0o755}))
    data = admin.get("/api/skills/meeting-notes-example/download?target=chatgpt").content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            assert info.external_attr >> 16 == stat.S_IFREG | 0o644, info.filename


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
    root = load_settings().runtime_data_dir
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


def test_file_count_and_size_limits_are_413(admin, monkeypatch):
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


def test_claude_specific_rules_are_shown_not_hidden(admin):
    md = "---\nname: claude-helper\ndescription: <b>bold</b> 설명\nversion: 1\n---\n본문\n"
    body = upload(admin, make_zip({"SKILL.md": md}, folder="claude-helper")).json()
    assert body["compat"] == {"chatgpt": True, "claude": False}
    assert any("anthropic · claude" in w for w in body["warnings"])
    assert any("XML" in w for w in body["warnings"])
    assert any("version" in w for w in body["warnings"])  # 규격 밖 frontmatter
