"""AI Skills 자동 정리 모델(OpenAI 호환 vLLM POST /v1/chat/completions)의 가짜 (httpx.MockTransport 뒤).

응답 모양은 agentic_ai 가 같은 모델을 부를 때 읽는 칸(choices[0].message.content, 2026-10-14 read-only 확인)과 같다.
"""

import asyncio
import json

import httpx

from app.api.integrations.skill_ai.skill_ai_client import AnalysisRequest, RealSkillAiClient

BASE_URL = "http://model.internal.example:18000"
MODEL = "test-model-250b"
API_KEY = "sk-test-secret-key-0000"

GOOD_RESULT = {
    "title": "회의록 자동 정리",
    "summary": "회의 메모를 받아 결정 사항과 후속 조치를 정리한 회의록을 만들어 주는 Skill 입니다.",
    "tags": ["회의록", "요약", "후속조치"],
    "use_cases": ["회의 메모를 회의록으로 정리", "결정 사항과 담당자 추출"],
    "recommended_for": "회의 후 결과 정리가 필요한 연구원",
    "example_prompts": ["이 회의 메모를 회의록으로 정리해줘", "결정 사항과 담당자를 표로 보여줘"],
}


def completion(content, *, finish_reason="stop") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content, "reasoning_content": None},
                     "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 200, "total_tokens": 1100},
    }


class Model:
    """MockTransport 뒤의 가짜 모델 서버. 받은 요청을 기억한다."""

    def __init__(self, payload=None, *, status=200, raw: bytes | None = None, raise_exc=None):
        self.payload = completion(json.dumps(GOOD_RESULT, ensure_ascii=False)) if payload is None else payload
        self.status, self.raw, self.raise_exc = status, raw, raise_exc
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_exc:
            raise self.raise_exc(request)
        if self.raw is not None:
            return httpx.Response(self.status, content=self.raw, headers={"content-type": "text/plain"})
        return httpx.Response(self.status, json=self.payload)


def client_for(model: Model, **kw) -> RealSkillAiClient:
    return RealSkillAiClient(BASE_URL, MODEL, transport=httpx.MockTransport(model), **kw)


def analysis_request(**overrides) -> AnalysisRequest:
    values = dict(
        system_prompt="SYSTEM", user_prompt="USER", schema={"type": "object"}, skill_id="meeting-notes",
        description="회의 메모를 회의록으로 정리한다.", heading="회의록 정리", sections=("입력", "작성 순서"),
        paths=("SKILL.md", "examples/a.md", "references/format.md"),
    )
    return AnalysisRequest(**{**values, **overrides})


def run(coro):
    return asyncio.run(coro)
