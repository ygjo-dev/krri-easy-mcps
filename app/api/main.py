"""KRRI EASY MCPs thin BFF. 실행 (저장소 root 에서): uvicorn app.api.main:app --host 127.0.0.1 --port 8610

여기서 하는 일: KEM_* 환경변수(Settings) 읽기, client · 저장소 조립, router 연결, /api/health.
내부 서비스 주소는 backend 환경변수에서만 읽는다. 브라우저는 이 값을 보지 못한다 (frontend env 에 내부 URL 을 두지 않는다).
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .integrations.agentic_ai.agentic_ai_client import AgenticAiUnavailable, make_agentic_ai_client
from .integrations.krri_asap.gateway_client import GatewayUnavailable, make_gateway_client
from .integrations.krri_asap.selection_client import make_selection_client
from .services.ai_demo import demo_router
from .services.ai_demo.question_service import load_demo_questions
from .services.auth import auth_router
from .services.auth.account_service import AccountStore
from .services.catalog import catalog_router
from .services.catalog.catalog_service import load_planned_mcps, load_presentation
from .services.mcp_selection import selection_router
from .services.mcp_selection.selection_repository import SelectionStore
from .services.skills import skill_router
from .services.skills.skill_service import SkillLibrary

logger = logging.getLogger(__name__)

# 저장소에 들어 있는 MCP 정의 파일 (presentation · planned · demo questions).
MCP_DEFINITIONS_DIR = Path(__file__).resolve().parent / "mcp_definitions"
# 실행 때 생기는 EASY 데이터 (계정 · 내 MCP · Skill). gitignore. 폴더는 저장소가 처음 열 때 만든다.
RUNTIME_DATA_DIR = Path(__file__).resolve().parents[1] / "runtime_data"

MOCK = "mock"
LIVE = "live"

# Gateway 를 못 읽었을 때 브라우저로 나가는 문구. 원인(내부 URL · 응답 본문)은 서버 로그에만 남는다.
GATEWAY_UNAVAILABLE_DETAIL = "Gateway 에서 MCP 정보를 가져오지 못했습니다."
AGENTIC_AI_UNAVAILABLE_DETAIL = "AI 실행 서비스에 연결하지 못했습니다."


@dataclass(frozen=True)
class Settings:
    mcp_definitions_dir: Path
    gateway_mode: str
    agentic_ai_mode: str
    # KEM_GATEWAY_MODE=live 에서 필수. 기본값을 두지 않는다 (틀린 Gateway 를 조용히 부르지 않게).
    gateway_base_url: str
    # Gateway GET /api/tools 는 부를 때마다 모든 MCP 에 tools/list refresh 를 일으킨다. 그 결과를 이만큼 재사용한다.
    gateway_cache_seconds: float
    # KEM_AGENTIC_AI_MODE=live 에서 필수. 기본값을 두지 않는다.
    agentic_ai_base_url: str
    # agentic 한 요청(LLM 해석 + KRRI 실행)을 기다리는 시간.
    agentic_ai_timeout_seconds: float
    # EASY runtime data 폴더 (SQLite DB 3개 + Skill package 파일). KRRI_ASAP 로그인과 별개다. commit 하지 않는다.
    runtime_data_dir: Path
    # EASY 로그인 세션 수명 (시간). 지나면 다시 로그인한다.
    session_hours: float
    # 개발용 초기 관리자 계정. DB 에 이 이름이 없을 때 한 번만 만든다 (이미 있으면 비밀번호를 바꾸지 않는다).
    admin_username: str
    admin_password: str

    @property
    def accounts_db(self) -> Path:
        """EASY 계정 · 로그인 세션."""
        return self.runtime_data_dir / "accounts" / "accounts.db"

    @property
    def selections_db(self) -> Path:
        """계정 내 MCP · 세션별 동기화 기록."""
        return self.runtime_data_dir / "mcp_selections" / "selections.db"

    @property
    def skills_db(self) -> Path:
        """AI Skills metadata."""
        return self.runtime_data_dir / "skills" / "skills.db"

    @property
    def skill_packages_dir(self) -> Path:
        """AI Skills package 파일 (<id>/source/)."""
        return self.runtime_data_dir / "skills" / "uploaded_packages"


def load_settings() -> Settings:
    return Settings(
        mcp_definitions_dir=Path(os.environ.get("KEM_MCP_DEFINITIONS_DIR", MCP_DEFINITIONS_DIR)),
        gateway_mode=os.environ.get("KEM_GATEWAY_MODE", MOCK),
        agentic_ai_mode=os.environ.get("KEM_AGENTIC_AI_MODE", MOCK),
        gateway_base_url=os.environ.get("KEM_GATEWAY_BASE_URL", ""),
        gateway_cache_seconds=float(os.environ.get("KEM_GATEWAY_CACHE_SECONDS", "60")),
        agentic_ai_base_url=os.environ.get("KEM_AGENTIC_AI_BASE_URL", ""),
        agentic_ai_timeout_seconds=float(os.environ.get("KEM_AGENTIC_AI_TIMEOUT_SECONDS", "360")),
        runtime_data_dir=Path(os.environ.get("KEM_RUNTIME_DATA_DIR", RUNTIME_DATA_DIR)),
        session_hours=float(os.environ.get("KEM_SESSION_HOURS", "168")),
        admin_username=os.environ.get("KEM_ADMIN_USERNAME", "admin"),
        admin_password=os.environ.get("KEM_ADMIN_PASSWORD", "admin"),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="KRRI EASY MCPs BFF", version="0.1.0")
    app.state.presentation = load_presentation(settings.mcp_definitions_dir)
    app.state.planned_mcps = load_planned_mcps(settings.mcp_definitions_dir)
    app.state.demo_questions = load_demo_questions(settings.mcp_definitions_dir, app.state.planned_mcps)
    app.state.gateway = make_gateway_client(
        settings.gateway_mode, settings.gateway_base_url, settings.gateway_cache_seconds
    )
    app.state.selection = make_selection_client(settings.gateway_mode, settings.gateway_base_url)
    # EASY 자체 계정 · 세션. KRRI_ASAP 로그인과 별개다.
    app.state.accounts = AccountStore(
        settings.accounts_db,
        session_seconds=settings.session_hours * 3600,
        admin_username=settings.admin_username,
        admin_password=settings.admin_password,
    )
    # 계정 내 MCP (로그인 사용자의 Gateway guest selection 저장 · 복원).
    app.state.selections = SelectionStore(settings.selections_db)
    # KRRI AI Skills (ADMIN 전용). metadata 는 skills.db, package 파일은 uploaded_packages/. MCP 기능과 섞지 않는다.
    app.state.skills = SkillLibrary(settings.skills_db, settings.skill_packages_dir)

    @app.exception_handler(GatewayUnavailable)
    async def gateway_unavailable(request: Request, exc: GatewayUnavailable) -> JSONResponse:
        logger.warning("Gateway unavailable on %s: %s", request.url.path, exc)
        return JSONResponse(status_code=502, content={"detail": GATEWAY_UNAVAILABLE_DETAIL})
    app.state.agentic_ai = make_agentic_ai_client(
        settings.agentic_ai_mode, settings.agentic_ai_base_url, settings.agentic_ai_timeout_seconds
    )

    @app.exception_handler(AgenticAiUnavailable)
    async def agentic_ai_unavailable(request: Request, exc: AgenticAiUnavailable) -> JSONResponse:
        logger.warning("agentic_ai unavailable on %s: %s", request.url.path, exc)
        return JSONResponse(status_code=502, content={"detail": AGENTIC_AI_UNAVAILABLE_DETAIL})

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "gateway": app.state.gateway.source,
            "agentic_ai": app.state.agentic_ai.source,
        }

    app.include_router(auth_router.router)
    app.include_router(catalog_router.router)
    app.include_router(demo_router.router)
    app.include_router(selection_router.router)
    app.include_router(skill_router.router)
    return app


app = create_app()
