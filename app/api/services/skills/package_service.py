"""Skill package 형식 · 검증 · ZIP (KRRI AI Skills, 저장은 skill_service.py).

KRRI_ASAP orchestrator 의 내부 skill 과 무관하다. 그것을 읽거나 노출하지 않는다.

**Skill package** = Agent Skills 규격(agentskills.io/specification) 의 folder 하나:
``<name>/SKILL.md`` (YAML frontmatter ``name`` · ``description`` + Markdown 지시) 와 references/ · assets/ · scripts/ 등.
ChatGPT 와 Claude 가 같은 규격을 읽는다. EASY 는 실제로 업로드할 수 있는 ZIP 을 내려줄 뿐,
두 서비스 계정에 설치하지 않는다 (공식 설치 API 를 흉내 내지 않는다).
id 는 frontmatter ``name`` 이다 (규격상 folder 이름과 같아야 한다).

**한 벌의 canonical source.** ChatGPT · Claude export 는 같은 파일을 쓰고 packaging 만 맞춘다:
ZIP 의 단일 top-level folder ``<id>/`` 와 main 파일 이름(EXPORT_MAIN_FILE). 내용은 바꾸지 않는다.

**올린 package 는 보관 · 미리보기 · export 대상일 뿐이다.** 서버는 그 안의 script 를 실행 · import 하지 않고,
파일은 실행 권한 없이(0644) 적는다. ZIP 은 path traversal · 절대 경로 · symlink · 암호화 entry · 개수/크기 초과를 거부한다.
"""

import io
import re
import stat
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

# ── 제한 ─────────────────────────────────────────────────────────────
# ChatGPT(OpenAI skills: zip 50MB · 500 파일 · 파일 25MB) 보다 좁게 둔다.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_FILES = 200
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_SKILL_MD_BYTES = 512 * 1024

# Agent Skills 규격: 1-64자, 소문자 · 숫자 · 하이픈, 하이픈으로 시작 · 끝 · 연속 금지.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Claude 는 skill name 에 이 낱말을 쓰지 못한다.
CLAUDE_RESERVED = ("anthropic", "claude")
LONG_SKILL_MD_LINES = 500

MAIN_FILE_LOWER = "skill.md"
TARGETS = ("chatgpt", "claude", "source")
# export 때 main 파일 이름. 두 서비스 모두 공식 문서가 <name>/SKILL.md 를 쓴다
# (Claude: "Claude looks for <skill-name>/SKILL.md inside the archive", OpenAI: 이름 매칭은 대소문자 무시).
# source 는 올린 이름 그대로다.
EXPORT_MAIN_FILE = {"chatgpt": "SKILL.md", "claude": "SKILL.md"}
# macOS Finder 압축이 넣는 부산물. 조용히 버린다.
JUNK_DIRS = {"__MACOSX"}
JUNK_FILES = {".DS_Store", "Thumbs.db"}


class SkillPackageError(ValueError):
    """올린 package 가 받아들일 수 없는 모양. 메시지는 사용자에게 그대로 보인다 (내부 경로를 넣지 않는다)."""


class SkillTooLarge(SkillPackageError):
    pass


def valid_skill_id(value: str) -> bool:
    return bool(value) and len(value) <= MAX_NAME and NAME_PATTERN.match(value) is not None


@dataclass(frozen=True)
class Package:
    """검증을 마친 package. files 의 key 는 package root 기준 상대 경로(POSIX)."""

    name: str
    description: str
    main_file: str
    files: dict[str, bytes]
    frontmatter: dict
    warnings: tuple[str, ...]
    compat: dict = field(default_factory=dict)


# ── package 검증 ─────────────────────────────────────────────────────


def _parse_skill_md(raw: bytes) -> tuple[dict, str]:
    if len(raw) > MAX_SKILL_MD_BYTES:
        raise SkillPackageError("SKILL.md 가 너무 큽니다.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SkillPackageError("SKILL.md 는 UTF-8 텍스트여야 합니다.") from None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillPackageError("SKILL.md 가 YAML frontmatter(---) 로 시작하지 않습니다.")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise SkillPackageError("SKILL.md frontmatter 가 --- 로 닫히지 않습니다.") from None
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        raise SkillPackageError("SKILL.md frontmatter 를 YAML 로 읽을 수 없습니다.") from None
    if not isinstance(data, dict):
        raise SkillPackageError("SKILL.md frontmatter 가 key: value 모양이 아닙니다.")
    return data, "\n".join(lines[end + 1:])


def validate_package(files: dict[str, bytes]) -> Package:
    """package root 기준 파일들 → 검증된 Package. root 에 skill.md(대소문자 무시)가 정확히 하나 있어야 한다."""
    if not files:
        raise SkillPackageError("package 에 파일이 없습니다.")
    if len(files) > MAX_FILES:
        raise SkillTooLarge(f"파일이 너무 많습니다 (최대 {MAX_FILES}개).")
    if sum(len(b) for b in files.values()) > MAX_TOTAL_BYTES:
        raise SkillTooLarge("package 전체 크기가 너무 큽니다.")
    mains = [p for p in files if PurePosixPath(p).name.lower() == MAIN_FILE_LOWER]
    if not mains:
        raise SkillPackageError("SKILL.md 가 없습니다.")
    if len(mains) > 1:
        raise SkillPackageError("SKILL.md 는 package 에 하나만 있어야 합니다.")
    [main] = mains
    if "/" in main:
        raise SkillPackageError("SKILL.md 는 skill folder 바로 아래에 있어야 합니다.")

    frontmatter, body = _parse_skill_md(files[main])
    name, description = frontmatter.get("name"), frontmatter.get("description")
    if not isinstance(name, str) or not valid_skill_id(name):
        raise SkillPackageError(
            "frontmatter name 은 영문 소문자 · 숫자 · 하이픈(-)만, 64자 이하여야 합니다 (예: meeting-notes)."
        )
    if not isinstance(description, str) or not description.strip():
        raise SkillPackageError("frontmatter description 이 비어 있습니다.")
    if len(description) > MAX_DESCRIPTION:
        raise SkillPackageError(f"frontmatter description 은 {MAX_DESCRIPTION}자 이하여야 합니다.")

    warnings = []
    unknown = sorted(str(k) for k in frontmatter if k not in SPEC_FIELDS)
    if unknown:
        warnings.append(f"규격에 없는 frontmatter 항목: {', '.join(unknown)} (일부 서비스가 거부할 수 있습니다)")
    if len(body.splitlines()) > LONG_SKILL_MD_LINES:
        warnings.append(f"SKILL.md 가 {LONG_SKILL_MD_LINES}줄을 넘습니다. 긴 내용은 references/ 로 나누는 것을 권장합니다.")
    claude_issues = []
    if any(word in name for word in CLAUDE_RESERVED):
        claude_issues.append("Claude 는 name 에 anthropic · claude 를 쓸 수 없습니다.")
    if "<" in description or ">" in description:
        claude_issues.append("Claude 는 description 의 XML 태그(< >)를 허용하지 않습니다.")
    warnings.extend(claude_issues)
    return Package(
        name=name,
        description=description.strip(),
        main_file=main,
        files=dict(files),
        frontmatter=frontmatter,
        warnings=tuple(warnings),
        compat={"chatgpt": True, "claude": not claude_issues},
    )


def _safe_parts(name: str) -> tuple[str, ...]:
    """ZIP entry 이름 → 경로 조각. 위험한 이름이면 SkillPackageError."""
    if not name or "\\" in name or "\x00" in name or any(ord(c) < 32 for c in name):
        raise SkillPackageError("ZIP 안에 허용되지 않는 파일 이름이 있습니다.")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise SkillPackageError("ZIP 안에 절대 경로가 있습니다.")
    parts = tuple(name.rstrip("/").split("/"))
    if any(p in ("", ".", "..") for p in parts):
        raise SkillPackageError("ZIP 안에 상위 폴더(..)나 비정상 경로가 있습니다.")
    return parts


def read_zip(data: bytes) -> dict[str, bytes]:
    """올린 ZIP → package root 기준 파일들. 실행 · 압축 해제를 디스크에 하지 않고 메모리에서 읽는다.

    허용 모양: ``<folder>/SKILL.md ...`` (folder 하나) 또는 root 에 바로 ``SKILL.md ...``.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise SkillTooLarge("ZIP 파일이 너무 큽니다.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError):
        raise SkillPackageError("ZIP 파일을 읽을 수 없습니다.") from None
    entries: list[tuple[tuple[str, ...], zipfile.ZipInfo]] = []
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES * 2:
            raise SkillTooLarge(f"파일이 너무 많습니다 (최대 {MAX_FILES}개).")
        for info in infos:
            parts = _safe_parts(info.filename)
            if parts[0] in JUNK_DIRS or parts[-1] in JUNK_FILES:
                continue
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if info.flag_bits & 0x1:
                raise SkillPackageError("암호화된 ZIP entry 는 받을 수 없습니다.")
            if kind == stat.S_IFLNK:
                raise SkillPackageError("ZIP 안에 symlink 가 있습니다.")
            if info.is_dir():
                continue
            if kind not in (0, stat.S_IFREG):
                raise SkillPackageError("ZIP 안에 일반 파일이 아닌 entry 가 있습니다.")
            entries.append((parts, info))
        if not entries:
            raise SkillPackageError("ZIP 안에 파일이 없습니다.")
        if len(entries) > MAX_FILES:
            raise SkillTooLarge(f"파일이 너무 많습니다 (최대 {MAX_FILES}개).")

        # root: 모든 파일이 folder 하나 아래면 그 folder, root 에 SKILL.md 가 있으면 root.
        tops = {parts[0] for parts, _ in entries}
        at_root = any(len(parts) == 1 and parts[0].lower() == MAIN_FILE_LOWER for parts, _ in entries)
        if at_root:
            strip = 0
        elif len(tops) == 1 and all(len(parts) > 1 for parts, _ in entries):
            strip = 1
        else:
            raise SkillPackageError("ZIP 은 skill folder 하나(그 안에 SKILL.md)만 담아야 합니다.")

        files: dict[str, bytes] = {}
        seen: set[str] = set()
        total = 0
        for parts, info in entries:
            path = "/".join(parts[strip:])
            if path.lower() in seen:
                raise SkillPackageError("ZIP 안에 대소문자만 다른 같은 이름의 파일이 있습니다.")
            seen.add(path.lower())
            if info.file_size > MAX_FILE_BYTES:
                raise SkillTooLarge("ZIP 안에 너무 큰 파일이 있습니다.")
            # header 의 크기를 믿지 않고 실제로 읽은 만큼 센다 (zip bomb).
            chunks, size = [], 0
            try:
                with archive.open(info) as handle:
                    while chunk := handle.read(64 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_FILE_BYTES:
                            raise SkillTooLarge("ZIP 안에 너무 큰 파일이 있습니다.")
                        if total > MAX_TOTAL_BYTES:
                            raise SkillTooLarge("package 전체 크기가 너무 큽니다.")
                        chunks.append(chunk)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError):
                raise SkillPackageError("ZIP 안의 파일을 읽을 수 없습니다.") from None
            files[path] = b"".join(chunks)
    return files


def build_package(name: str, description: str, title: str, instructions: str, example: str = "") -> dict[str, bytes]:
    """「간단히 만들기」 입력 → canonical package 파일 (규격 frontmatter name · description 만)."""
    frontmatter = yaml.safe_dump({"name": name, "description": description}, allow_unicode=True, sort_keys=False)
    body = f"# {title.strip() or name}\n\n{instructions.strip()}\n"
    if example.strip():
        body += "\n## 예시\n\n`examples/example.md` 의 입력 · 출력 예시를 따르세요.\n"
    files = {"SKILL.md": f"---\n{frontmatter}---\n\n{body}".encode()}
    if example.strip():
        files["examples/example.md"] = (example.strip() + "\n").encode()
    return files


def build_zip(folder: str, files: dict[str, bytes], when: float) -> bytes:
    """단일 top-level folder ZIP. 모든 entry 를 일반 파일 0644 로 적는다 (실행 권한 없음)."""
    stamp = time.localtime(max(when, 315532800))[:6]  # ZIP 은 1980 년 이전을 못 적는다
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(f"{folder}/{path}", date_time=stamp)
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[path])
    return out.getvalue()
