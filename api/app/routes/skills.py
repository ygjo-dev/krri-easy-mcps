"""KRRI AI Skills API. **모든 경로가 EASY ADMIN 전용이다** (router dependency require_admin: 비로그인 401 · ADMIN 아님 403).

화면의 메뉴 숨김과 상관없이 서버가 막는다. KRRI_ASAP 의 Keycloak role 은 보지 않는다.

ZIP 은 multipart 가 아니라 요청 body 그대로 받는다 (Content-Type application/zip, 새 dependency 없이).
화면용 표시 정보(title · version · author · tags)는 query 로 온다. package 내용은 app/skills.py 가 검증한다.
"""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..accounts import Login, require_admin
from ..skills import (
    MAX_UPLOAD_BYTES,
    TARGETS,
    SkillExists,
    SkillMeta,
    SkillNotFound,
    SkillPackageError,
    SkillTooLarge,
    build_package,
    read_zip,
    validate_package,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"], dependencies=[Depends(require_admin)])

NOT_FOUND_DETAIL = "Skill 을 찾을 수 없습니다."
EXISTS_DETAIL = "같은 ID 의 Skill 이 이미 있습니다. 새 버전은 Skill 상세에서 올리세요."
TARGET_DETAIL = "target 은 chatgpt · claude · source 중 하나입니다."
EMPTY_BODY_DETAIL = "ZIP 파일을 보내 주세요."
MAX_TAGS = 10
MAX_TAG = 30
MAX_META = 100


def _tags(raw) -> tuple[str, ...]:
    values = raw.split(",") if isinstance(raw, str) else list(raw or [])
    tags = [str(t).strip()[:MAX_TAG] for t in values if str(t).strip()]
    return tuple(dict.fromkeys(tags))[:MAX_TAGS]


def _meta(title: str, version: str, author: str, tags) -> SkillMeta:
    return SkillMeta(title=title[:MAX_META], version=version[:MAX_META // 4], author=author[:MAX_META], tags=_tags(tags))


def _meta_from_query(request: Request, package) -> SkillMeta:
    """query 가 비면 frontmatter metadata(author · version, 규격의 문자열 map)에서 채운다."""
    q = request.query_params
    extra = package.frontmatter.get("metadata")
    extra = extra if isinstance(extra, dict) else {}
    return _meta(
        q.get("title", ""),
        q.get("version") or str(extra.get("version") or ""),
        q.get("author") or str(extra.get("author") or ""),
        q.get("tags", ""),
    )


def _package_error(exc: SkillPackageError) -> JSONResponse:
    return JSONResponse(status_code=413 if isinstance(exc, SkillTooLarge) else 400, content={"detail": str(exc)})


async def _zip_body(request: Request) -> bytes:
    """body 를 상한까지만 읽는다 (넘으면 413). 디스크에 풀지 않는다."""
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise SkillTooLarge("ZIP 파일이 너무 큽니다.")
        chunks.append(chunk)
    if not size:
        raise SkillPackageError(EMPTY_BODY_DETAIL)
    return b"".join(chunks)


@router.get("")
def list_skills(request: Request) -> list[dict]:
    return request.app.state.skills.list()


@router.get("/{skill_id}")
def get_skill(skill_id: str, request: Request) -> dict:
    try:
        return request.app.state.skills.detail(skill_id)
    except SkillNotFound:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL) from None


class CreateSkill(BaseModel):
    """「간단히 만들기」. id 는 frontmatter name 이 된다."""

    id: str
    title: str = ""
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: list[str] = []
    instructions: str
    example: str = ""


@router.post("", status_code=201)
def create_skill(body: CreateSkill, request: Request, login: Login = Depends(require_admin)):
    if not body.instructions.strip():
        return JSONResponse(status_code=400, content={"detail": "지시사항을 입력하세요."})
    try:
        package = validate_package(build_package(body.id, body.description, body.title, body.instructions, body.example))
        meta = _meta(body.title, body.version, body.author, body.tags)
        return request.app.state.skills.save(package, meta, created_by=login.user.username)
    except SkillExists:
        return JSONResponse(status_code=409, content={"detail": EXISTS_DETAIL})
    except SkillPackageError as exc:
        return _package_error(exc)


@router.post("/upload", status_code=201)
async def upload_skill(request: Request, login: Login = Depends(require_admin)):
    """ZIP 으로 새 Skill 등록."""
    return await _upload(request, login, None)


@router.put("/{skill_id}/package")
async def upload_new_version(skill_id: str, request: Request, login: Login = Depends(require_admin)):
    """같은 Skill 의 새 버전 ZIP. frontmatter name 이 skill_id 와 같아야 한다."""
    return await _upload(request, login, skill_id)


async def _upload(request: Request, login: Login, replace_id: str | None):
    try:
        data = await _zip_body(request)
        package = await run_in_threadpool(lambda: validate_package(read_zip(data)))
        meta = _meta_from_query(request, package)
        detail = await run_in_threadpool(
            request.app.state.skills.save, package, meta, created_by=login.user.username, replace_id=replace_id
        )
    except SkillExists:
        return JSONResponse(status_code=409, content={"detail": EXISTS_DETAIL})
    except SkillNotFound:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL) from None
    except SkillPackageError as exc:
        return _package_error(exc)
    return JSONResponse(status_code=200 if replace_id else 201, content=detail)


@router.delete("/{skill_id}", status_code=204)
def delete_skill(skill_id: str, request: Request):
    try:
        request.app.state.skills.delete(skill_id)
    except SkillNotFound:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL) from None
    return Response(status_code=204)


@router.get("/{skill_id}/download")
def download_skill(skill_id: str, request: Request, target: str = "source"):
    if target not in TARGETS:
        return JSONResponse(status_code=400, content={"detail": TARGET_DETAIL})
    try:
        filename, data = request.app.state.skills.export(skill_id, target)
    except SkillNotFound:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL) from None
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )
