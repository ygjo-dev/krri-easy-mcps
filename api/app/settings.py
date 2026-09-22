"""BFF 설정. 내부 서비스 주소는 여기(backend 환경변수)에서만 읽는다.

브라우저는 이 값을 보지 못한다. frontend env 에 내부 URL 을 두지 않는다.
"""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MOCK = "mock"


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    gateway_mode: str
    agentic_ai_mode: str
    # 향후 live client 가 쓸 주소. 지금은 읽기만 하고 호출하지 않는다.
    gateway_base_url: str
    agentic_ai_base_url: str


def load_settings() -> Settings:
    return Settings(
        config_dir=Path(os.environ.get("KEM_CONFIG_DIR", REPO_ROOT / "config")),
        gateway_mode=os.environ.get("KEM_GATEWAY_MODE", MOCK),
        agentic_ai_mode=os.environ.get("KEM_AGENTIC_AI_MODE", MOCK),
        gateway_base_url=os.environ.get("KEM_GATEWAY_BASE_URL", ""),
        agentic_ai_base_url=os.environ.get("KEM_AGENTIC_AI_BASE_URL", ""),
    )
