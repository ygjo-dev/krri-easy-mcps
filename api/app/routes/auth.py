"""EASY 자체 로그인. KRRI_ASAP 로그인(Keycloak/JWT)과 별개다 (accounts.py).

응답은 모두 ``{"user": null}`` 또는 ``{"user": {"username", "role"}}`` 다. password · hash · 세션 token 은 싣지 않는다.
세션은 cookie ``kem_session`` (opaque token, HttpOnly · SameSite=Lax · Path=/ · https 면 Secure · 세션 수명만큼).
Gateway guest cookie(asap_mcp_guest) 와 따로다. 로그인 · 로그아웃이 guest cookie 를 바꾸거나 지우지 않는다
(로그인 때 guest 가 아직 없어 Gateway 가 새로 발급한 경우만 내 MCP API 처럼 그 cookie 를 담는다).
"""

import logging

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ..accounts import SESSION_COOKIE, SESSION_COOKIE_PATH, current_login
from ..clients.gateway import GatewayUnavailable
from . import toolbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_FAILED_DETAIL = "아이디 또는 비밀번호가 올바르지 않습니다."
LOGIN_INVALID_DETAIL = "아이디와 비밀번호를 입력하세요."
# 이보다 긴 값은 hash 하지 않고 실패로 본다.
MAX_USERNAME = 64
MAX_PASSWORD = 256


def _auth_body(login) -> dict:
    return {"user": login.user.public() if login else None}


@router.get("/me")
def me(request: Request) -> dict:
    return _auth_body(current_login(request))


@router.post("/login")
async def login(request: Request):
    # pydantic 검증 오류(422)는 입력값을 되돌려 보내므로(비밀번호 포함) body 를 직접 읽는다.
    # JSON 만 받는다: 다른 사이트의 form(text/plain) POST 로 이 브라우저를 남의 계정에 로그인시키지 못하게.
    body = None
    if request.headers.get("content-type", "").split(";")[0].strip().lower() == "application/json":
        try:
            body = await request.json()
        except ValueError:
            pass
    username = body.get("username") if isinstance(body, dict) else None
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
        return JSONResponse(status_code=400, content={"detail": LOGIN_INVALID_DETAIL})
    if len(username) > MAX_USERNAME or len(password) > MAX_PASSWORD:
        return JSONResponse(status_code=401, content={"detail": LOGIN_FAILED_DETAIL})
    return await run_in_threadpool(_login, request, username, password)


def _login(request: Request, username: str, password: str):
    accounts = request.app.state.accounts
    user = accounts.authenticate(username, password)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": LOGIN_FAILED_DETAIL})
    # 이전 세션 token 이 있으면 버리고 새로 만든다.
    accounts.delete_session(request.cookies.get(SESSION_COOKIE))
    token = accounts.create_session(user)
    login = accounts.login(token)
    response = JSONResponse(content=_auth_body(login))
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(accounts.session_seconds), path=SESSION_COOKIE_PATH,
        httponly=True, samesite="lax", secure=request.url.scheme == "https",
    )
    # 계정 내 MCP ↔ 이 브라우저의 Gateway guest selection 을 바로 맞춘다. Gateway 가 실패해도 로그인은 성공이다 —
    # 세션이 아직 이 guest 와 맞추지 않은 상태로 남아 다음 내 MCP 요청에서 다시 맞춘다.
    try:
        toolbox.sync_login(request, response, login)
    except GatewayUnavailable as exc:
        logger.warning("toolbox sync after login failed: %s", exc)
    return response


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    """EASY 세션만 끝낸다. guest cookie · Gateway selection(KRRI ASAP 와 공유)은 그대로 둔다."""
    request.app.state.accounts.delete_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(
        SESSION_COOKIE, path=SESSION_COOKIE_PATH, httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
    )
    return {"user": None}
