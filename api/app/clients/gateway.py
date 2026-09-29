"""KRRI_ASAP Gateway 쪽 boundary: logical MCP catalog · tools · status. (도구함 selection 은 selection.py)

**Portal 의 MCP 하나 = Gateway market tool-group 하나.** 사용자에게 보이는 단위는 physical MCP server 가
아니라 Gateway ``ASAP-Gateway/data/tool-groups.json`` 이 정의한 logical group 이고, group id 가 곧 Portal
``mcp_id`` 다. 어떤 Tool 이 어느 group 에 속하는지는 Gateway 가 정한 값(``resolvedToolRefs``)만 쓴다.
Portal 은 tool 이름 등을 보고 group 을 만들거나 고치지 않는다. physical server 는 runtime 구현 세부다.

Portal 내부 technical model (route 는 이 모양만 안다):

    {"mcp_id", "name", "description", "status": "online|offline|unknown", "enabled",
     "server_ids": [...], "tool_refs": [...],          # physical. BFF 안에서만 쓰고 브라우저로 안 나간다
     "tools": [{"name", "description", "input_schema", "server_id"}]}

한 logical MCP 는 여러 server(route-accessibility → otp-router, r5-server)와 한 server 의 일부
Tool(krri-road-cctv → asap-mcp-core/road.getCctv)을 가질 수 있다.

두 구현이 있다. KEM_GATEWAY_MODE 로 고른다. live 실패 시 mock 으로 넘어가지 않는다.

- MockGatewayClient  고정 fixture 를 live 와 같은 normalize 로 읽는다. tests · local 용. 대표 subset.
- RealGatewayClient  실제 Gateway 를 GET 으로만 읽는다. 아래 두 endpoint 만 쓴다.

**Gateway 읽기 경로 (KRRI_ASAP/ASAP-Gateway, 2026-09-29 read-only 재확인)**

GET /api/tools          (권한 ANYONE)
    tool name · description · inputSchema · serverId 의 authoritative source.
    **write 는 아니지만 부를 때마다 registry.refreshTools() 를 일으킨다** — 등록된 모든 MCP 에
    tools/list 를 보내고 Gateway 메모리의 tool cache · server status 를 갈아 끼운다
    (servers.json 등 registry 설정은 안 바뀐다). ASAP-orchestrator 도 같은 경로를 쓴다.
    그래서 BFF 가 결과를 cache_seconds 동안 재사용하고, 그 안에서는 다시 부르지 않는다.

GET /api/mcp-market     (권한 ANYONE)
    tool-group(market) catalog. item 하나가 Portal MCP 하나다. id · name · description ·
    serverIds · toolRefs(정의) · resolvedToolRefs(지금 Tool 로 펼친 값) · status · enabled 를 쓴다.
    Gateway 는 어떤 group 에도 안 걸린 server 에 id=server_id 인 fallback group 을 만든다.
    그 group 도 그대로 MCP 하나로 보인다. category 는 ASAP-web market tab(추천/일반…) 값이라 안 쓴다.
    application behavior 가 있다: 요청마다 guest cookie(asap_mcp_guest) 를 새로 발급하고
    guest selection 을 DB 에서 SELECT 한다. Gateway tool cache 가 비어 있으면 이 GET 도
    refreshTools 를 일으킨다. /api/tools 직후에 한 번만 부른다.

쓰지 않는 것: /api/admin/mcp-servers[/:id] (Keycloak ADMIN JWT 필요, 응답에 url · headers 포함),
admin POST/PUT/DELETE/refresh/test.

**status (보수적)**

online   group 에 Tool 이 있고, group 의 모든 server 가 이번 /api/tools refresh 에 Tool 을 냈다.
offline  group 에 Tool 이 하나도 없고, Gateway 가 group status 를 error 또는 disabled 라고 명시한다.
unknown  그 밖의 모든 경우 (일부 server 만 응답한 multi-server group, ready 인데 Tool 0개 등).
"""

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

SOURCE_MOCK = "mock"
SOURCE_LIVE = "live"

# Mock fixture. Gateway 응답 모양(GET /api/tools · GET /api/mcp-market)에서 쓰는 칸만 옮겼다.
# tool name · description · inputSchema 는 agentic_ai 의 live tools/list 스냅샷
# (dev/tools/probe_out/tools.json, 2026-08 수집)에서 일부만, group 은 2026-09-29 tool-groups.json 에서 일부만.
# mock status 는 임의 값이다 (web-search 는 일부러 응답이 없는 server 로 둔다).
MOCK_TOOLS: list[dict] = [
    {
        "serverId": "asap-mcp-core",
        "name": "geo.geocode",
        "description": "장소명으로 좌표와 bbox를 반환",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "serverId": "asap-mcp-core",
        "name": "geo.getRailwayLines",
        "description": "철도 노선명 또는 역명으로 철도 노선(LineString)을 조회하여 반환 (EPSG:4326 좌표계로 변환됨)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "railwayName": {"type": "string", "description": "철도 노선명 (예: 경부선, 호남선 등)"},
                "stationName": {"type": "string", "description": "역명 (예: 서울역, 부산역 등)"},
                "bbox": {"type": "array", "description": "[minLon, minLat, maxLon, maxLat] 조회 범위"},
                "includeStations": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "serverId": "asap-mcp-core",
        "name": "adminBoundary.findBoundaryByPoint",
        "description": "EPSG:4326 좌표가 포함되는 시도·시군구·읍면동 계층을 조회. 기본은 geometry 없는 LLM용 요약",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lon": {"type": "number", "description": "경도 longitude"},
                "lat": {"type": "number", "description": "위도 latitude"},
                "layer": {
                    "type": "string",
                    "enum": ["sido", "sigungu", "emd"],
                    "description": "선택 행정구역 레이어. 생략 시 포함되는 전체 계층 반환",
                },
            },
            "required": ["lon", "lat"],
        },
    },
    {
        "serverId": "asap-mcp-core",
        "name": "road.getCctv",
        "description": "좌표 범위(bbox) 내의 CCTV 목록을 반환",
        "inputSchema": {
            "type": "object",
            "properties": {
                "minLon": {"type": "number"},
                "minLat": {"type": "number"},
                "maxLon": {"type": "number"},
                "maxLat": {"type": "number"},
            },
            "required": ["minLon", "minLat", "maxLon", "maxLat"],
        },
    },
    {
        "serverId": "otp-router",
        "name": "otp_plan_trip",
        "description": "OTP로 좌표 기반 경로를 계산한다. date / time_kst 는 Asia/Seoul (KST) 기준.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_lat": {"type": "number"},
                "from_lon": {"type": "number"},
                "to_lat": {"type": "number"},
                "to_lon": {"type": "number"},
                "date": {"type": "string", "description": "YYYY-MM-DD (KST)"},
                "time_kst": {"type": "string", "description": "HH:MM (KST)"},
            },
            "required": ["from_lat", "from_lon", "to_lat", "to_lon"],
        },
    },
    {
        "serverId": "r5-server",
        "name": "compute_isochrone",
        "description": "단일 출발지에서 도달 가능한 영역을 계산합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin_lon": {"type": "number"},
                "origin_lat": {"type": "number"},
                "max_minutes": {"type": "integer", "default": 30},
            },
            "required": ["origin_lon", "origin_lat"],
        },
    },
]


def _mock_group(group_id: str, name: str, description: str, tool_refs: list[str], status: str = "ready") -> dict:
    resolved = [
        f"{t['serverId']}/{t['name']}".lower()
        for t in MOCK_TOOLS
        if any(ref == f"{t['serverId']}/*" or ref == f"{t['serverId']}/{t['name']}" for ref in tool_refs)
    ]
    return {
        "id": group_id,
        "name": name,
        "description": description,
        "serverIds": sorted({ref.split("/", 1)[0] for ref in tool_refs}),
        "toolRefs": [ref.lower() for ref in tool_refs],
        "resolvedToolRefs": resolved,
        "status": status,
        "enabled": True,
    }


MOCK_MARKET: list[dict] = [
    _mock_group("krri-map-location", "지도/위치 검색", "장소명 기반 좌표 검색과 지도 이동에 필요한 기본 위치 도구를 제공합니다.",
                ["asap-mcp-core/geo.geocode"]),
    _mock_group("krri-railway-network", "철도망/노선 조회", "철도 노선, 역, 구간 geometry 조회 도구를 제공합니다.",
                ["asap-mcp-core/geo.getRailwayLines"]),
    _mock_group("krri-admin-boundary", "행정구역 경계 조회", "좌표가 속한 시도·시군구·읍면동을 찾고 행정구역 경계를 조회합니다.",
                ["asap-mcp-core/adminBoundary.findBoundaryByPoint"]),
    _mock_group("krri-road-cctv", "도로/CCTV 조회", "지도 범위 내 도로 CCTV 조회 도구를 제공합니다.",
                ["asap-mcp-core/road.getCctv"]),
    _mock_group("route-accessibility", "경로/접근성 분석", "OTP 경로 탐색과 R5 도달권/접근성 분석 도구를 하나의 실행 후보 그룹으로 제공합니다.",
                ["otp-router/*", "r5-server/*"]),
    _mock_group("web-research", "웹 리서치", "인터넷 검색과 공개 웹 페이지 본문 조회 도구를 제공합니다.",
                ["web-search/*"], status="error"),
]


class GatewayUnavailable(RuntimeError):
    """Gateway 를 읽지 못했다. 메시지는 서버 로그용이고 브라우저로 내보내지 않는다."""


class MockGatewayClient:
    """고정 fixture. tests · local 용. live 와 같은 normalize 를 거친다."""

    source = SOURCE_MOCK

    def __init__(self):
        self._mcps = normalize_gateway_catalog(MOCK_TOOLS, MOCK_MARKET)

    def list_mcps(self) -> list[dict]:
        return self._mcps

    def get_mcp(self, mcp_id: str) -> dict | None:
        return next((m for m in self._mcps if m["mcp_id"] == mcp_id), None)


class RealGatewayClient:
    """실제 Gateway 를 GET 으로만 읽는다. 결과를 cache_seconds 동안 한 벌로 재사용한다."""

    source = SOURCE_LIVE

    def __init__(
        self,
        base_url: str,
        *,
        cache_seconds: float = 60,
        timeout_seconds: float = 30,
        fetch_json: Callable[[str], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._base_url = base_url.rstrip("/")
        self._cache_seconds = cache_seconds
        self._timeout = timeout_seconds
        self._fetch_json = fetch_json or self._urllib_get_json
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: list[dict] | None = None
        self._cached_at = 0.0

    def list_mcps(self) -> list[dict]:
        # lock 안에서 채운다. 동시에 온 Catalog/Detail 요청이 /api/tools 를 두 번 부르지 않게.
        with self._lock:
            if self._cached is not None and self._clock() - self._cached_at < self._cache_seconds:
                return self._cached
            tools = self._get_list("/api/tools")
            market = self._get_list("/api/mcp-market")
            self._cached = normalize_gateway_catalog(tools, market)
            self._cached_at = self._clock()
            return self._cached

    def get_mcp(self, mcp_id: str) -> dict | None:
        return next((m for m in self.list_mcps() if m["mcp_id"] == mcp_id), None)

    def _get_list(self, path: str) -> list:
        try:
            data = self._fetch_json(path)
        except GatewayUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — 무엇이든 "Gateway 를 못 읽었다" 하나로 모은다.
            raise GatewayUnavailable(f"GET {path} failed: {exc}") from exc
        if not isinstance(data, list):
            raise GatewayUnavailable(f"GET {path} returned {type(data).__name__}, expected list")
        return data

    def _urllib_get_json(self, path: str) -> Any:
        request = urllib.request.Request(self._base_url + path, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise GatewayUnavailable(f"GET {path} failed: {exc}") from exc


def normalize_gateway_catalog(tools: list, market: list) -> list[dict]:
    """GET /api/tools + GET /api/mcp-market → logical MCP 목록. Gateway 응답 모양은 여기서 끝난다.

    group 의 Tool 은 Gateway 가 펼친 resolvedToolRefs 로만 /api/tools 에서 찾는다 (소문자 비교).
    """
    tools_by_ref: dict[str, dict] = {}
    servers_with_tools: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict) or not tool.get("serverId") or not tool.get("name"):
            continue
        server_id = str(tool["serverId"])
        servers_with_tools.add(server_id.lower())
        tools_by_ref.setdefault(f"{server_id}/{tool['name']}".lower(), {
            "name": str(tool["name"]),
            "description": tool.get("description") or "",
            "input_schema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {},
            "server_id": server_id,
        })

    mcps = []
    seen: set[str] = set()
    for group in market:
        if not isinstance(group, dict) or not group.get("id") or str(group["id"]) in seen:
            continue
        mcp_id = str(group["id"])
        seen.add(mcp_id)
        server_ids = [str(i) for i in group.get("serverIds") or [] if i]
        resolved = [str(r).lower() for r in group.get("resolvedToolRefs") or [] if r]
        group_tools = [tools_by_ref[r] for r in dict.fromkeys(resolved) if r in tools_by_ref]
        mcps.append({
            "mcp_id": mcp_id,
            "name": group.get("name") or mcp_id,
            "description": group.get("description") or "",
            "status": _status(group_tools, server_ids, servers_with_tools, group.get("status")),
            "enabled": group.get("enabled") is not False,
            "server_ids": server_ids,
            "tool_refs": [str(r).lower() for r in group.get("toolRefs") or [] if r],
            "tools": group_tools,
        })
    return mcps


def _status(tools: list[dict], server_ids: list[str], servers_with_tools: set[str], group_status) -> str:
    if tools and server_ids and all(s.lower() in servers_with_tools for s in server_ids):
        return "online"
    if not tools and group_status in ("error", "disabled"):
        return "offline"
    return "unknown"


def make_gateway_client(mode: str, base_url: str = "", cache_seconds: float = 60):
    if mode == SOURCE_MOCK:
        return MockGatewayClient()
    if mode == SOURCE_LIVE:
        if not base_url:
            raise ValueError("KEM_GATEWAY_MODE=live requires KEM_GATEWAY_BASE_URL")
        return RealGatewayClient(base_url, cache_seconds=cache_seconds)
    raise ValueError(f"unknown KEM_GATEWAY_MODE {mode!r} (mock | live)")
