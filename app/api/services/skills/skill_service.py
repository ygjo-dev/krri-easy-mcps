"""KRRI AI Skills library — EASY 가 소유하는 사용자용 Skill 저장 · 조회 · export (ADMIN 전용, skill_router.py).

package 형식 · 검증 · ZIP 은 package_service.py.

저장 (app/runtime_data/skills/)
    skills.db skills 표                목록 · 상세용 metadata (화면 이름 · 버전 · 작성자 · 태그 · 호환 · 경고)
    uploaded_packages/<id>/source/    canonical package 파일 그대로 (main 파일 이름도 올린 그대로: SKILL.md 또는 skill.md)
"""

import json
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..runtime_db import open_db
from .package_service import EXPORT_MAIN_FILE, TARGETS, Package, SkillPackageError, build_zip, valid_skill_id

PREVIEW_TEXT_BYTES = 64 * 1024
MAX_EXAMPLES = 5
EXAMPLE_DIRS = ("examples", "example")
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".py", ".sh", ".js", ".ts", ".html", ".xml", ".toml"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    version     TEXT NOT NULL,
    author      TEXT NOT NULL,
    tags        TEXT NOT NULL,
    main_file   TEXT NOT NULL,
    file_count  INTEGER NOT NULL,
    total_bytes INTEGER NOT NULL,
    compat      TEXT NOT NULL,
    warnings    TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
"""


class SkillNotFound(LookupError):
    pass


class SkillExists(ValueError):
    pass


@dataclass(frozen=True)
class SkillMeta:
    """EASY library 표시 정보. package 안이 아니라 DB 에 둔다 (export 내용에 섞지 않는다)."""

    title: str
    version: str
    author: str
    tags: tuple[str, ...]


# ── 미리보기 ─────────────────────────────────────────────────────────


def _is_text(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in TEXT_SUFFIXES


def _decode_preview(raw: bytes) -> str:
    return raw[:PREVIEW_TEXT_BYTES].decode("utf-8", errors="replace")


# ── library ──────────────────────────────────────────────────────────


class SkillLibrary:
    def __init__(self, db_path: Path, packages_dir: Path, *, clock: Callable[[], float] = time.time):
        self._db_path = Path(db_path)
        self._dir = Path(packages_dir)
        self._clock = clock
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._dir.mkdir(parents=True, exist_ok=True)
        with open_db(self._db_path) as db:
            db.executescript(_SCHEMA)

    def _source(self, skill_id: str) -> Path:
        if not valid_skill_id(skill_id):  # 경로 조각으로 쓰기 전에 다시 막는다
            raise SkillNotFound(skill_id)
        return self._dir / skill_id / "source"

    # ── 읽기 ──

    def list(self) -> list[dict]:
        with open_db(self._db_path) as db:
            rows = db.execute("SELECT * FROM skills ORDER BY updated_at DESC, id").fetchall()
            names = [c[0] for c in db.execute("SELECT * FROM skills LIMIT 0").description]
        return [self._card(dict(zip(names, row))) for row in rows]

    def _row(self, skill_id: str) -> dict:
        if not valid_skill_id(skill_id):
            raise SkillNotFound(skill_id)
        with open_db(self._db_path) as db:
            cur = db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
            row = cur.fetchone()
            names = [c[0] for c in cur.description]
        if row is None:
            raise SkillNotFound(skill_id)
        return dict(zip(names, row))

    @staticmethod
    def _card(row: dict) -> dict:
        return {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "version": row["version"],
            "author": row["author"],
            "tags": json.loads(row["tags"]),
            "compat": json.loads(row["compat"]),
            "file_count": row["file_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def files(self, skill_id: str) -> dict[str, bytes]:
        root = self._source(skill_id)
        if not root.is_dir():
            raise SkillNotFound(skill_id)
        return {
            p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink()
        }

    def detail(self, skill_id: str) -> dict:
        row = self._row(skill_id)
        files = self.files(skill_id)
        main = row["main_file"]
        examples = [
            {"path": path, "content": _decode_preview(raw)}
            for path, raw in files.items()
            if PurePosixPath(path).parts[0].lower() in EXAMPLE_DIRS and _is_text(path)
        ][:MAX_EXAMPLES]
        return {
            **self._card(row),
            "main_file": main,
            "skill_md": _decode_preview(files.get(main, b"")),
            "files": [{"path": path, "size": len(raw)} for path, raw in files.items()],
            "examples": examples,
            "warnings": json.loads(row["warnings"]),
            "created_by": row["created_by"],
        }

    def export(self, skill_id: str, target: str) -> tuple[str, bytes]:
        """(파일 이름, ZIP). 내용은 canonical 그대로, target 에 따라 main 파일 이름만 맞춘다."""
        if target not in TARGETS:
            raise ValueError(target)
        row = self._row(skill_id)
        files = self.files(skill_id)
        if target in EXPORT_MAIN_FILE:
            main = row["main_file"]
            files = {(EXPORT_MAIN_FILE[target] if p == main else p): b for p, b in files.items()}
        return f"{skill_id}-{target}.zip", build_zip(skill_id, files, row["updated_at"])

    # ── 쓰기 ──

    def save(self, package: Package, meta: SkillMeta, *, created_by: str, replace_id: str | None = None) -> dict:
        """새 Skill 저장 (같은 id 가 있으면 SkillExists). replace_id 면 그 Skill 의 새 버전으로 package 를 바꾼다."""
        skill_id = package.name
        if replace_id is not None:
            if replace_id != skill_id:
                raise SkillPackageError(f"새 버전의 frontmatter name 이 이 Skill({replace_id}) 과 다릅니다.")
            existing = self._row(replace_id)
        else:
            existing = None
            with open_db(self._db_path) as db:
                if db.execute("SELECT 1 FROM skills WHERE id = ?", (skill_id,)).fetchone():
                    raise SkillExists(skill_id)

        source = self._source(skill_id)
        staging = source.parent / f".staging-{uuid.uuid4().hex}"
        for path, raw in package.files.items():
            target = staging.joinpath(*PurePosixPath(path).parts)
            if staging not in target.parents:  # validate 를 거쳤지만 한 번 더
                raise SkillPackageError("허용되지 않는 경로입니다.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            target.chmod(0o644)

        # 새 버전에서 비운 표시 정보는 이전 값을 그대로 쓴다.
        before = existing or {}
        tags = list(meta.tags) or (json.loads(before["tags"]) if before else [])
        now = self._clock()
        row = {
            "id": skill_id,
            "title": meta.title.strip() or before.get("title") or skill_id,
            "description": package.description,
            "version": meta.version.strip() or before.get("version") or "1.0.0",
            # 공용 ADMIN 계정이라 로그인 이름(admin)을 작성자로 채우지 않는다. 비우면 빈 값이다.
            "author": meta.author.strip() or before.get("author") or "",
            "tags": json.dumps(tags, ensure_ascii=False),
            "main_file": package.main_file,
            "file_count": len(package.files),
            "total_bytes": sum(len(b) for b in package.files.values()),
            "compat": json.dumps(package.compat),
            "warnings": json.dumps(list(package.warnings), ensure_ascii=False),
            "created_by": existing["created_by"] if existing else created_by,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        old = source.parent / f".old-{uuid.uuid4().hex}"
        try:
            with open_db(self._db_path) as db:
                columns = ", ".join(row)
                marks = ", ".join("?" for _ in row)
                # 새 버전은 행을 지우지 않고 칸만 바꾼다 (INSERT OR REPLACE 는 행을 지웠다 다시 넣어서,
                # 이 Skill 을 참조하는 다른 표의 행이 FK cascade 로 함께 지워질 수 있다).
                upsert = (" ON CONFLICT(id) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in row if c != "id")
                          if existing else "")
                db.execute(f"INSERT INTO skills ({columns}) VALUES ({marks}){upsert}", tuple(row.values()))
                if source.exists():
                    source.rename(old)
                staging.rename(source)
        except BaseException:
            if old.exists() and not source.exists():
                old.rename(source)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(old, ignore_errors=True)
        return self.detail(skill_id)

    def delete(self, skill_id: str) -> None:
        self._row(skill_id)
        with open_db(self._db_path) as db:
            db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        shutil.rmtree(self._dir / skill_id, ignore_errors=True)
