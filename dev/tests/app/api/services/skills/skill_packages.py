"""AI Skills 테스트용 package · ZIP 도우미. sample skill 은 테스트 fixture 다 (실제 업무 Skill 이 아니다)."""

import io
import stat
import zipfile


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


def login(c, creds=ADMIN):
    r = c.post("/api/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return c


def upload(c, data: bytes, **query):
    return c.post("/api/skills/upload", params=query, content=data, headers={"content-type": "application/zip"})


def zip_names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return sorted(z.namelist())


def zip_read(data: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(name)


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
