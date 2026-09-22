"""KRRI_ASAP Gateway 쪽 boundary: technical MCP catalog · tools · status. (도구함 selection 은 selection.py)

Portal 내부 technical model (route 는 이 모양만 안다):

    {"server_id", "name", "description", "status": "online|offline|unknown",
     "tools": [{"name", "description", "input_schema"}]}

두 구현이 있다. KEM_GATEWAY_MODE 로 고른다. live 실패 시 mock 으로 넘어가지 않는다.

- MockGatewayClient  고정 데이터. tests · local 용. 대표 subset 이고 production catalog 가 아니다.
- RealGatewayClient  실제 Gateway 를 GET 으로만 읽는다. 아래 두 endpoint 만 쓴다.

**Gateway 읽기 경로 (KRRI_ASAP/ASAP-Gateway, 2026-09-22 read-only 확인)**

GET /api/tools          (권한 ANYONE)
    tool name · description · inputSchema · serverId 의 authoritative source.
    **write 는 아니지만 부를 때마다 registry.refreshTools() 를 일으킨다** — 등록된 모든 MCP 에
    tools/list 를 보내고 Gateway 메모리의 tool cache · server status 를 갈아 끼운다
    (servers.json 등 registry 설정은 안 바뀐다). ASAP-orchestrator 도 같은 경로를 쓴다.
    그래서 BFF 가 결과를 cache_seconds 동안 재사용하고, 그 안에서는 다시 부르지 않는다.

GET /api/mcp-market     (권한 ANYONE)
    **MCP server catalog 가 아니라 tool-group(market) catalog 다.** item 하나 ≠ server 하나.
    serverIds 로 server id 를 discover 하고, single-server group 의 status 만 참고한다.
    application behavior 가 있다: 요청마다 guest cookie(asap_mcp_guest) 를 새로 발급하고
    guest selection 을 DB 에서 SELECT 한다. Gateway tool cache 가 비어 있으면 이 GET 도
    refreshTools 를 일으킨다. /api/tools 직후에 한 번만 부른다.

쓰지 않는 것: /api/admin/mcp-servers[/:id] (Keycloak ADMIN JWT 필요, 응답에 url · headers 포함),
admin POST/PUT/DELETE/refresh/test. 향후 Gateway 에 safe read-only server catalog 가 생기면
이 파일 안에서만 source 를 바꾼다.

**status (보수적)**

online   이번 /api/tools refresh 결과에 그 server 의 tool 이 실제로 있다 (tools/list 가 방금 성공).
offline  그 server 하나만 담은 mcp-market group 이 error 또는 disabled 라고 명시한다.
unknown  그 밖의 모든 경우. registry 에 있다는 것만으로 online 이 아니고, multi-server group
         (예: route-accessibility → [otp-router, r5-server]) 의 status 는 개별 server 로 옮기지 않는다.

Mock 데이터의 tool name · description · inputSchema 는 agentic_ai 의 live tools/list 스냅샷
(dev/tools/probe_out/tools.json, 2026-08 수집)에서 일부만 옮겼다. mock status 는 임의 값이다.
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

MOCK_SERVERS: list[dict] = [
    {
        "server_id": "asap-mcp-core",
        "status": "online",
        "tools": [
            {
                "name": "geo.geocode",
                "description": "장소명으로 좌표와 bbox를 반환",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "geo.getRailwayLines",
                "description": "철도 노선명 또는 역명으로 철도 노선(LineString)을 조회하여 반환 (EPSG:4326 좌표계로 변환됨)",
                "input_schema": {
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
                "name": "adminBoundary.findBoundaryByPoint",
                "description": "EPSG:4326 좌표가 포함되는 시도·시군구·읍면동 계층을 조회. 기본은 geometry 없는 LLM용 요약",
                "input_schema": {
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
                "name": "road.getCctv",
                "description": "좌표 범위(bbox) 내의 CCTV 목록을 반환",
                "input_schema": {
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
        ],
    },
    {
        "server_id": "otp-router",
        "status": "online",
        "tools": [
            {
                "name": "otp_plan_trip",
                "description": "OTP로 좌표 기반 경로를 계산한다. date / time_kst 는 Asia/Seoul (KST) 기준.",
                "input_schema": {
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
                "name": "otp_health_check",
                "description": "OTP GraphQL 서버가 살아있는지 확인한다.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ],
    },
    {
        "server_id": "r5-server",
        "status": "online",
        "tools": [
            {
                "name": "compute_isochrone",
                "description": "단일 출발지에서 도달 가능한 영역을 계산합니다.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "origin_lon": {"type": "number"},
                        "origin_lat": {"type": "number"},
                        "max_minutes": {"type": "integer", "default": 30},
                    },
                    "required": ["origin_lon", "origin_lat"],
                },
            },
            {
                "name": "health_check",
                "description": "R5 Java 서버 및 네트워크 상태를 확인합니다.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ],
    },
    {
        "server_id": "web-search",
        "status": "offline",
        "tools": [
            {
                "name": "web.search",
                "description": "인터넷에서 최신 공개 정보를 검색합니다.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "검색어"},
                        "maxResults": {"type": "integer", "default": 5, "description": "반환할 최대 검색 결과 수"},
                    },
                    "required": ["query"],
                },
            },
        ],
    },
]


# mock market group → server. multi-server group 하나를 일부러 둔다 (실제 Gateway 와 같은 모양).
MOCK_GROUP_SERVERS: dict[str, list[str]] = {
    "krri-road-cctv": ["asap-mcp-core"],
    "krri-map-location": ["asap-mcp-core"],
    "route-accessibility": ["otp-router", "r5-server"],
    "web-research": ["web-search"],
}


class GatewayUnavailable(RuntimeError):
    """Gateway 를 읽지 못했다. 메시지는 서버 로그용이고 브라우저로 내보내지 않는다."""


class MockGatewayClient:
    """고정 데이터. tests · local 용."""

    source = SOURCE_MOCK

    def list_servers(self) -> list[dict]:
        return MOCK_SERVERS

    def get_server(self, server_id: str) -> dict | None:
        return next((s for s in MOCK_SERVERS if s["server_id"] == server_id), None)

    def group_servers(self) -> dict[str, list[str]]:
        return MOCK_GROUP_SERVERS


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
        self._cached: tuple[list[dict], dict[str, list[str]]] | None = None
        self._cached_at = 0.0

    def list_servers(self) -> list[dict]:
        return self._snapshot()[0]

    def get_server(self, server_id: str) -> dict | None:
        return next((s for s in self.list_servers() if s["server_id"] == server_id), None)

    def group_servers(self) -> dict[str, list[str]]:
        """market group id → serverIds. 도구함 해제 때 그 server 를 담은 group 을 찾는 데만 쓴다."""
        return self._snapshot()[1]

    def _snapshot(self) -> tuple[list[dict], dict[str, list[str]]]:
        # lock 안에서 채운다. 동시에 온 Catalog/Detail 요청이 /api/tools 를 두 번 부르지 않게.
        with self._lock:
            if self._cached is not None and self._clock() - self._cached_at < self._cache_seconds:
                return self._cached
            tools = self._get_list("/api/tools")
            market = self._get_list("/api/mcp-market")
            self._cached = (normalize_gateway_catalog(tools, market), normalize_group_servers(market))
            self._cached_at = self._clock()
            return self._cached

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
    """GET /api/tools + GET /api/mcp-market → Portal technical model. Gateway 응답 모양은 여기서 끝난다."""
    tools_by_server: dict[str, list[dict]] = {}
    for tool in tools:
        if not isinstance(tool, dict) or not tool.get("serverId") or not tool.get("name"):
            continue
        tools_by_server.setdefault(str(tool["serverId"]), []).append({
            "name": str(tool["name"]),
            "description": tool.get("description") or "",
            "input_schema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {},
        })

    server_ids = set(tools_by_server)
    single_server_groups: dict[str, list[dict]] = {}
    for group in market:
        if not isinstance(group, dict):
            continue
        ids = [str(i) for i in group.get("serverIds") or [] if i]
        server_ids.update(ids)
        if len(ids) == 1:
            single_server_groups.setdefault(ids[0], []).append(group)

    servers = []
    for server_id in sorted(server_ids):
        groups = single_server_groups.get(server_id, [])
        # Gateway 는 group 정의에 안 걸린 server 에 id=server_id 인 fallback group 을 만들고,
        # 그 name/description 에 server 정의의 name/description 을 싣는다. 그것만 technical 이름으로 쓴다.
        own = next((g for g in groups if g.get("id") == server_id), None)
        servers.append({
            "server_id": server_id,
            "name": (own or {}).get("name") or server_id,
            "description": (own or {}).get("description") or "",
            "status": _status(tools_by_server.get(server_id), groups),
            "tools": tools_by_server.get(server_id, []),
        })
    return servers


def normalize_group_servers(market: list) -> dict[str, list[str]]:
    return {
        str(g["id"]): [str(i) for i in g.get("serverIds") or [] if i]
        for g in market
        if isinstance(g, dict) and g.get("id")
    }


def _status(tools: list[dict] | None, single_server_groups: list[dict]) -> str:
    if tools:
        return "online"
    if any(g.get("status") in ("error", "disabled") for g in single_server_groups):
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
