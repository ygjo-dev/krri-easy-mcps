"""KRRI EASY MCPs thin BFF. 실행: uvicorn app.main:app --port 8610 (api/ 에서)."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .clients.agentic_ai import make_agentic_ai_client
from .clients.gateway import GatewayUnavailable, MockGatewayClient, make_gateway_client
from .metadata import load_demo_questions, load_presentation
from .routes import catalog, demo, registration
from .settings import Settings, load_settings

logger = logging.getLogger(__name__)

# Gateway 를 못 읽었을 때 브라우저로 나가는 문구. 원인(내부 URL · 응답 본문)은 서버 로그에만 남는다.
GATEWAY_UNAVAILABLE_DETAIL = "Gateway 에서 MCP 정보를 가져오지 못했습니다."


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="KRRI EASY MCPs BFF", version="0.1.0")
    app.state.presentation = load_presentation(settings.config_dir)
    app.state.demo_questions = load_demo_questions(settings.config_dir)
    app.state.gateway = make_gateway_client(
        settings.gateway_mode, settings.gateway_base_url, settings.gateway_cache_seconds
    )
    # 등록 미리보기는 mode 와 무관하게 아직 mock 이다 (Track A-2).
    app.state.registration_inspector = MockGatewayClient()

    @app.exception_handler(GatewayUnavailable)
    async def gateway_unavailable(request: Request, exc: GatewayUnavailable) -> JSONResponse:
        logger.warning("Gateway unavailable on %s: %s", request.url.path, exc)
        return JSONResponse(status_code=502, content={"detail": GATEWAY_UNAVAILABLE_DETAIL})
    app.state.agentic_ai = make_agentic_ai_client(settings.agentic_ai_mode)

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "gateway": app.state.gateway.source,
            "agentic_ai": app.state.agentic_ai.source,
        }

    app.include_router(catalog.router)
    app.include_router(demo.router)
    app.include_router(registration.router)
    return app


app = create_app()
