"""KRRI EASY MCPs thin BFF. 실행: uvicorn app.main:app --port 8610 (api/ 에서)."""

from fastapi import FastAPI

from .clients.agentic_ai import make_agentic_ai_client
from .clients.gateway import make_gateway_client
from .metadata import load_demo_questions, load_presentation
from .routes import catalog, demo, registration
from .settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="KRRI EASY MCPs BFF", version="0.1.0")
    app.state.presentation = load_presentation(settings.config_dir)
    app.state.demo_questions = load_demo_questions(settings.config_dir)
    app.state.gateway = make_gateway_client(settings.gateway_mode)
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
