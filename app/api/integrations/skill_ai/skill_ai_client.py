"""AI Skills 자동 정리용 모델(독파모) boundary. **Skill library 표시 정보(metadata)만 만든다.**

원본 Skill package 는 이 client 에 오지 않는다. enrichment_service.py 가 package 에서 텍스트를 골라
prompt 를 만들고, 여기서는 모델 호출 · 응답 JSON 꺼내기만 한다. 결과는 DB 의 표시 정보가 될 뿐,
SKILL.md 등 package 파일에 들어가지 않는다.

live 계약 (agentic_ai 가 같은 모델을 부르는 방식, 2026-10-14 read-only 확인. agentic_ai 코드를 import 하지 않는다):

    POST {base}/v1/chat/completions   OpenAI 호환 (vLLM). streaming 없음
    {"model": <이름>, "messages": [...],
     "response_format": {"type": "json_schema", "json_schema": {"name", "schema", "strict": true}},
     "reasoning_effort": "none",      빼면 모델 기본값(high)으로 추론 token 을 먼저 낸다
     "temperature": 0, "seed": 0, "max_tokens": ...}
    응답  choices[0].message.content = JSON 문자열

agentic_ai 의 /chat/stream(MCP 실행 pipeline)은 부르지 않는다. 같은 모델 서버를 EASY 가 따로 부른다.

두 구현이 있다. KEM_SKILL_AI_MODE 로 고른다. live 가 실패해도 mock 으로 넘어가지 않는다 (가짜 정리 결과를 내지 않는다).

- MockSkillAiClient  package 의 이름 · 설명 · 제목 · 파일 이름으로 정해진 결과를 만든다. tests · local 용
- RealSkillAiClient  모델 서버를 부른다. client 는 상태가 없다 (요청마다 연결을 연다)

로그 · 예외 메시지에 내부 URL · API key · 응답 본문 · prompt 를 싣지 않는다.
"""

import json
import re
from dataclasses import dataclass

import httpx

SOURCE_MOCK = "mock"
SOURCE_LIVE = "live"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"

# 같은 모델에서 JSON 하나(한국어 수백 자)를 받는 데 수십 초 걸린다. 넉넉히 기다리고 retry 하지 않는다 (사용자가 다시 누른다).
DEFAULT_TIMEOUT_SECONDS = 120.0
CONNECT_TIMEOUT_SECONDS = 10.0
# 결과는 짧은 JSON 하나다. schema 의 maxLength · maxItems 가 길이를 막고, 이 값은 그 위의 안전판이다.
MAX_TOKENS = 1536
# 표시 정보 추출이라 창작 여지를 두지 않는다. 같은 package 면 같은 결과가 나오게.
TEMPERATURE = 0
SEED = 0

# 모델이 앞뒤를 ```json … ``` 으로 감싼 경우만 벗긴다. 그 밖의 글에서 JSON 을 억지로 찾지 않는다.
_FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)


class SkillAiUnavailable(RuntimeError):
    """모델을 못 불렀거나 쓸 수 있는 JSON 이 오지 않았다. 메시지는 서버 로그용 (URL · 본문 · key 없음)."""


@dataclass(frozen=True)
class AnalysisRequest:
    """enrichment_service 가 만든 요청 한 건.

    live 는 system · user prompt 와 JSON schema 만 보낸다. 나머지 칸은 mock 이 결과를 만들 때 쓰는 package 사실이다.
    """

    system_prompt: str
    user_prompt: str
    schema: dict
    skill_id: str
    description: str
    heading: str
    sections: tuple[str, ...]
    paths: tuple[str, ...]


def parse_json_object(content: str) -> dict:
    """모델 content → JSON object. object 가 아니면 SkillAiUnavailable."""
    text = content.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except ValueError:
        raise SkillAiUnavailable("model output is not JSON") from None
    if not isinstance(value, dict):
        raise SkillAiUnavailable("model output is not a JSON object")
    return value


# ── mock ─────────────────────────────────────────────────────────────

# package 의 top-level 폴더 → mock 태그
_FOLDER_TAGS = {"references": "참고자료", "examples": "예시 포함", "example": "예시 포함", "templates": "템플릿",
                "assets": "첨부 자료", "scripts": "스크립트 포함"}


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    match = re.search(r"^(.+?[.!?。]|.+?다\.)(\s|$)", text)
    return (match.group(1) if match else text)[:200]


class MockSkillAiClient:
    """모델 없이 package 사실로 정해진 결과를 만든다. 같은 입력이면 같은 결과다 (화면 · 테스트 확인용)."""

    source = SOURCE_MOCK

    async def analyze(self, request: AnalysisRequest) -> dict:
        title = request.heading or request.skill_id.replace("-", " ")
        tags = ["AI Skill", *dict.fromkeys(
            _FOLDER_TAGS[p.split("/", 1)[0]] for p in request.paths if "/" in p and p.split("/", 1)[0] in _FOLDER_TAGS
        )]
        tags += [word for word in request.skill_id.split("-") if len(word) > 1 and word not in tags][:7 - len(tags)]
        use_cases = list(request.sections[:3]) or [_first_sentence(request.description)]
        return {
            "title": title,
            "summary": f"{_first_sentence(request.description)} (mock 자동 정리)",
            "tags": tags[:7],
            "use_cases": use_cases,
            "recommended_for": f"「{title}」 작업을 자주 하는 연구원",
            "example_prompts": [f"{title} Skill 로 첨부한 자료를 정리해줘", f"{title} 결과를 표로 보여줘"],
        }


# ── live ─────────────────────────────────────────────────────────────


class RealSkillAiClient:
    source = SOURCE_LIVE

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(CONNECT_TIMEOUT_SECONDS, timeout_seconds))
        self._transport = transport

    def _body(self, request: AnalysisRequest) -> dict:
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "skill_library_metadata", "schema": request.schema, "strict": True},
            },
            "reasoning_effort": "none",
            "temperature": TEMPERATURE,
            "seed": SEED,
            "max_tokens": MAX_TOKENS,
        }

    async def analyze(self, request: AnalysisRequest) -> dict:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(CHAT_COMPLETIONS_PATH, json=self._body(request), headers=headers)
        except httpx.TimeoutException:
            raise SkillAiUnavailable("timeout") from None
        except httpx.HTTPError as exc:
            # httpx 예외 문구에는 URL 이 들어 있다. 종류만 남긴다.
            raise SkillAiUnavailable(type(exc).__name__) from None
        if response.status_code != 200:
            raise SkillAiUnavailable(f"HTTP {response.status_code}")
        try:
            payload = response.json()
            choice = payload["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise SkillAiUnavailable("unexpected response shape") from None
        if not isinstance(content, str) or not content.strip():
            raise SkillAiUnavailable("empty model output")
        if choice.get("finish_reason") == "length":
            raise SkillAiUnavailable("model output was cut off")
        return parse_json_object(content)


def make_skill_ai_client(
    mode: str,
    base_url: str = "",
    model: str = "",
    api_key: str = "",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
):
    if mode == SOURCE_MOCK:
        return MockSkillAiClient()
    if mode == SOURCE_LIVE:
        if not base_url:
            raise ValueError("KEM_SKILL_AI_MODE=live requires KEM_SKILL_AI_BASE_URL")
        if not model:
            raise ValueError("KEM_SKILL_AI_MODE=live requires KEM_SKILL_AI_MODEL")
        return RealSkillAiClient(base_url, model, api_key=api_key, timeout_seconds=timeout_seconds)
    raise ValueError(f"unknown KEM_SKILL_AI_MODE {mode!r} (mock | live)")
