"""agentic_ai 기존 POST /chat/stream 의 가짜 (httpx.MockTransport 뒤).

이벤트 모양은 agentic_ai app/api/main.py · execution/workflow_execution.py 의 현재 흐름(2026-09-22 read-only 확인)에서
필요한 칸만 옮겼다. step_end.failed · result.status 는 agentic 이 더한 칸이고, 모르는 type · 칸(telemetry · extra)도 섞었다.
"""

import asyncio
import json

import httpx

from app.api.integrations.agentic_ai.agentic_ai_client import RealAgenticAiClient


BASE_URL = "http://agentic.internal.example:8000"

CCTV_EVENTS = [
    {"type": "step_start", "node": "resolve", "message": "발화를 해석하고 있습니다..."},
    {"type": "step_end", "node": "resolve", "message": "SELECT recipe_036"},
    {"type": "step_start", "node": "geocode_place", "message": "geo.geocode 호출 중입니다..."},
    {"type": "step_end", "node": "geocode_place", "message": "geo.geocode 완료", "failed": False},
    {"type": "step_start", "node": "find_cctv", "message": "road.getCctv 호출 중입니다..."},
    {"type": "step_end", "node": "find_cctv", "message": "road.getCctv 완료", "failed": False},
    {"type": "telemetry", "elapsed_ms": 1234},  # 모르는 type
    {
        "type": "result",
        "answer": "수원역 반경 15km 안에 CCTV 42대가 있습니다.",
        "commands": [{"op": "map.addLayer", "args": {"geojson": {"features": []}}}],
        "status": "success",
        "extra": {"future": True},  # 모르는 칸
    },
]


def sse(events, *, done=True, crlf=False) -> bytes:
    nl = "\r\n" if crlf else "\n"
    body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}{nl}{nl}" for e in events)
    if done:
        body += f"data: [DONE]{nl}{nl}"
    return body.encode("utf-8")


class Agentic:
    """MockTransport 뒤의 가짜 agentic. 받은 요청을 기억한다."""

    def __init__(self, body: bytes = b"", status=200, content_type="text/event-stream", raise_exc=None, stream=None):
        self.body, self.status, self.content_type = body, status, content_type
        self.raise_exc, self.stream = raise_exc, stream
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_exc:
            raise self.raise_exc(request)
        headers = {"content-type": self.content_type}
        if self.stream is not None:
            return httpx.Response(self.status, headers=headers, content=self.stream())
        return httpx.Response(self.status, headers=headers, content=self.body)


def client_for(agentic: Agentic) -> RealAgenticAiClient:
    return RealAgenticAiClient(BASE_URL, transport=httpx.MockTransport(agentic))


def run(coro):
    return asyncio.run(coro)
