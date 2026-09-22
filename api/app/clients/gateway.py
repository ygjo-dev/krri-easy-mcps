"""KRRI_ASAP Gateway 쪽 boundary: technical MCP catalog · status · registration inspect.

**지금은 MOCK 이다.** 실제 Gateway 를 부르지 않는다.
technical 정보(status · tools · inputSchema)의 source of truth 는 향후
Gateway / live MCP tools/list 이고, 아래 MOCK_SERVERS 는 UI 구조를 검증하기 위한
대표 subset 이다. production catalog 로 쓰지 않는다.

tool name · description · inputSchema 는 agentic_ai 의 live tools/list 스냅샷
(dev/tools/probe_out/tools.json, 2026-08 수집)에서 일부만 옮겼다. 긴 schema 는 줄였다.
status 는 임의의 mock 값이다.
"""

from urllib.parse import urlparse

SOURCE_MOCK = "mock"

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


class InvalidEndpoint(ValueError):
    pass


class MockGatewayClient:
    """향후 Gateway catalog / MCP server test API 를 부를 자리. 지금은 고정 데이터."""

    source = SOURCE_MOCK

    def list_servers(self) -> list[dict]:
        return MOCK_SERVERS

    def get_server(self, server_id: str) -> dict | None:
        return next((s for s in MOCK_SERVERS if s["server_id"] == server_id), None)

    def inspect(self, endpoint: str) -> dict:
        """등록 전 미리보기. **endpoint 를 실제로 호출하지 않는다.**

        향후 KRRI_ASAP Gateway 의 기존 MCP server test 기능으로 교체한다.
        Portal 이 임의 endpoint 를 직접 호출하지 않는다.
        """
        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise InvalidEndpoint("http(s) URL 을 입력하세요.")
        return {
            "source": SOURCE_MOCK,
            "endpoint": endpoint,
            "server_info": {"name": "example-mcp-server", "version": "0.1.0"},
            "protocol_version": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "tools": [
                {
                    "name": "example.echo",
                    "description": "입력한 문자열을 그대로 돌려줍니다. (mock)",
                    "input_schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string", "description": "돌려받을 문자열"}},
                        "required": ["text"],
                    },
                },
            ],
        }


def make_gateway_client(mode: str) -> MockGatewayClient:
    if mode == SOURCE_MOCK:
        return MockGatewayClient()
    raise NotImplementedError(f"gateway mode {mode!r} is not implemented yet (only 'mock')")
