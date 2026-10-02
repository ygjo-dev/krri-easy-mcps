"""BFF 설정. 내부 서비스 주소는 여기(backend 환경변수)에서만 읽는다.

브라우저는 이 값을 보지 못한다. frontend env 에 내부 URL 을 두지 않는다.
"""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MOCK = "mock"
LIVE = "live"


@dataclass(frozen=True)
class Settings:
    config_dir: Path
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
    # EASY 자체 계정 · 세션 · 계정 도구함 DB (SQLite). KRRI_ASAP 로그인과 별개다. commit 하지 않는다 (data/ 는 gitignore).
    db_path: Path
    # EASY 로그인 세션 수명 (시간). 지나면 다시 로그인한다.
    session_hours: float
    # 개발용 초기 관리자 계정. DB 에 이 이름이 없을 때 한 번만 만든다 (이미 있으면 비밀번호를 바꾸지 않는다).
    admin_username: str
    admin_password: str


def load_settings() -> Settings:
    return Settings(
        config_dir=Path(os.environ.get("KEM_CONFIG_DIR", REPO_ROOT / "config")),
        gateway_mode=os.environ.get("KEM_GATEWAY_MODE", MOCK),
        agentic_ai_mode=os.environ.get("KEM_AGENTIC_AI_MODE", MOCK),
        gateway_base_url=os.environ.get("KEM_GATEWAY_BASE_URL", ""),
        gateway_cache_seconds=float(os.environ.get("KEM_GATEWAY_CACHE_SECONDS", "60")),
        agentic_ai_base_url=os.environ.get("KEM_AGENTIC_AI_BASE_URL", ""),
        agentic_ai_timeout_seconds=float(os.environ.get("KEM_AGENTIC_AI_TIMEOUT_SECONDS", "360")),
        db_path=Path(os.environ.get("KEM_DB_PATH", REPO_ROOT / "data" / "easy.db")),
        session_hours=float(os.environ.get("KEM_SESSION_HOURS", "168")),
        admin_username=os.environ.get("KEM_ADMIN_USERNAME", "admin"),
        admin_password=os.environ.get("KEM_ADMIN_PASSWORD", "admin"),
    )
