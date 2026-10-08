"""KRRI_ASAP Gateway 내 MCP selection(/api/me/mcp-selections, /events)의 가짜.

FakeSelectionGateway 는 Gateway mcpMarket.service 의 정규화를 필요한 만큼 흉내 낸다:
groupIds 는 아는 group 만, toolRefs = group 의 정의 refs + 명시 refs 중 등록된 server 것만 (소문자 · 중복 제거),
cookie 가 없으면 guest UUID 를 새로 만들어 Set-Cookie 로 준다. RealSelectionClient(transport=...) 로 주입한다.
「KRRI ASAP 에서 바꿈」은 같은 guest 의 store 행을 직접 바꾸는 것으로 모사한다 (ASAP-web 은 같은 cookie 로 {groupIds} 를 PUT 한다).

FakeGatewayEvents 는 GET /api/me/mcp-selections/events 흐름을 httpx.MockTransport 로 흉내 낸다 (끝이 있는 흐름).
"""

import uuid

import httpx

from app.api.integrations.krri_asap.selection_client import GATEWAY_GUEST_COOKIE


BASE_URL = "http://gateway.internal.example:3000"

TOOLS = [
    {"name": "geo.geocode", "serverId": "asap-mcp-core", "inputSchema": {}},
    {"name": "road.getCctv", "serverId": "asap-mcp-core", "inputSchema": {}},
    {"name": "otp_plan_trip", "serverId": "otp-router", "inputSchema": {}},
    {"name": "compute_isochrone", "serverId": "r5-server", "inputSchema": {}},
    {"name": "web.search", "serverId": "web-search", "inputSchema": {}},
]

GROUP_REFS = {
    "krri-map-location": ["asap-mcp-core/geo.geocode"],
    "krri-road-cctv": ["asap-mcp-core/road.getcctv"],
    "route-accessibility": ["otp-router/*", "r5-server/*"],
    "web-research": ["web-search/*"],
}

RESOLVED = {
    "krri-map-location": ["asap-mcp-core/geo.geocode"],
    "krri-road-cctv": ["asap-mcp-core/road.getcctv"],
    "route-accessibility": ["otp-router/otp_plan_trip", "r5-server/compute_isochrone"],
    "web-research": ["web-search/web.search"],
}

MARKET = [
    {"id": g, "name": g, "serverIds": sorted({r.split("/")[0] for r in refs}), "toolRefs": refs,
     "resolvedToolRefs": RESOLVED[g], "status": "ready"}
    for g, refs in GROUP_REFS.items()
]

AVAILABLE = {"asap-mcp-core", "otp-router", "r5-server", "web-search"}


class FakeSelectionGateway:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.calls: list[tuple[str, str | None]] = []
        self.bodies: list[dict] = []
        self.fail: Exception | None = None
        self.drop_group: str | None = None  # Gateway 가 이 group 을 조용히 버리는 경우 (예: disabled)

    def seed(self, group_ids, tool_refs) -> str:
        guest = str(uuid.uuid4())
        self.store[guest] = self._normalize(group_ids, tool_refs)
        return guest

    def _normalize(self, group_ids, tool_refs):
        groups = [g for g in dict.fromkeys(group_ids) if g in GROUP_REFS and g != self.drop_group]
        refs = [r.lower() for g in groups for r in GROUP_REFS[g]] + [r.lower() for r in tool_refs]
        refs = [r for r in dict.fromkeys(refs) if r.split("/")[0] in AVAILABLE]
        return {"groupIds": groups, "serverIds": sorted({r.split("/")[0] for r in refs}), "toolRefs": refs}

    def __call__(self, method, path, body, cookie):
        assert path == "/api/me/mcp-selections"
        guest = cookie.split("=", 1)[1] if cookie else None
        self.calls.append((method, guest))
        if self.fail:
            raise self.fail
        set_cookies = []
        if not guest:
            guest = str(uuid.uuid4())
            set_cookies = [f"{GATEWAY_GUEST_COOKIE}={guest}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax"]
        if method == "PUT":
            assert set(body) <= {"groupIds", "toolRefs", "serverIds"}
            self.bodies.append(body)
            self.store[guest] = self._normalize(body.get("groupIds", []), body.get("toolRefs", []))
        return self.store.get(guest, {"groupIds": [], "serverIds": [], "toolRefs": []}), set_cookies

    def puts(self):
        return [c for c in self.calls if c[0] == "PUT"]


STREAM = b": connected\n\nevent: selection_changed\ndata: {}\n\n: ping\n\n"


class FakeGatewayEvents:
    def __init__(self, status=200, body=STREAM, issue=None):
        self.status = status
        self.body = body
        self.issue = issue
        self.requests: list[httpx.Request] = []
        self.closed = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        headers = {"content-type": "text/event-stream"}
        if self.issue:
            headers["set-cookie"] = f"{GATEWAY_GUEST_COOKIE}={self.issue}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax"
        fake = self

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                for i in range(0, len(fake.body), 16):
                    yield fake.body[i:i + 16]

            async def aclose(self):
                fake.closed += 1

        return httpx.Response(self.status, headers=headers, stream=Body())
