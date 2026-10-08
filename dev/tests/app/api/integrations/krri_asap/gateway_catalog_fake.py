"""KRRI_ASAP Gateway catalog 읽기(GET /api/tools + GET /api/mcp-market)의 가짜 응답.

모양은 2026-09-29 실제 Gateway 응답에서 필요한 칸만 줄여 옮겼다. RealGatewayClient(fetch_json=FakeGateway(...)) 로 주입한다.
일부러 넣은 값: 내부 credential(headers) · lastError 의 내부 주소 · Data Library 실행 설정 · 이름 없는 항목 · 중복 id.
"""


BASE_URL = "http://gateway.internal.example:3000"

TOOLS = [
    {
        "name": "geo.geocode",
        "description": "장소명으로 좌표와 bbox를 반환",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "serverId": "asap-mcp-core",
        "qualifiedName": "asap-mcp-core/geo.geocode",
    },
    {
        "name": "road.getCctv",
        "description": "좌표 범위(bbox) 내의 CCTV 목록을 반환",
        "inputSchema": {"type": "object", "properties": {"minLon": {"type": "number"}}},
        "serverId": "asap-mcp-core",
    },
    {
        "name": "web.search",
        "description": "인터넷에서 최신 공개 정보를 검색합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색어"},
                "domains": {"type": "array", "items": {"type": "string"}},
                "cutoffs": {"anyOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "null"}], "default": None},
                "odd": {"$ref": "#/defs/x", "description": "지원 안 하는 schema"},
            },
        },
        "serverId": "web-search",
    },
    # 이름 없는 항목 · serverId 없는 항목은 버린다.
    {"description": "no name", "serverId": "asap-mcp-core"},
    {"name": "orphan"},
]

MARKET = [
    {"id": "krri-road-cctv", "name": "도로/CCTV 조회", "description": "지도 범위 내 도로 CCTV 조회 도구를 제공합니다.",
     "serverIds": ["asap-mcp-core"], "toolRefs": ["asap-mcp-core/road.getcctv"],
     "resolvedToolRefs": ["asap-mcp-core/road.getcctv"], "status": "ready", "enabled": True, "category": "추천",
     "headers": {"Authorization": "Bearer secret-token"},
     # MCP 상세 metadata (실제 market 모양)
     "longDescription": "선택 위치나 현재 지도 범위 주변의 ITS CCTV 정보를 조회합니다.",
     "tags": ["도로", "CCTV", "도로", " ", 3, "ready"], "author": "KRRI ASAP", "version": "group",
     "updatedAt": "2026-09-29T01:18:49.165Z", "rating": 5, "downloads": 0,
     "features": ["road.getCctv: 현재 지도 bbox 안의 ITS 도로 CCTV 위치를 조회합니다."],
     "layerDatasets": [
         {"id": "mcp_cctv", "name": "CCTV 위치", "description": "현재 화면 CCTV", "geometryKind": "point",
          "toolRef": "asap-mcp-core/road.getcctv", "input": {"limit": 500}, "defaultStyle": {"pointColor": "#ff0000"},
          "geometryJoin": {"toolRef": "system/adminBoundary.searchBoundaries"}},
         {"id": "no-name", "toolRef": "asap-mcp-core/road.getcctv"},
         "not-a-dict",
     ]},
    {"id": "krri-map-location", "name": "지도/위치 검색", "serverIds": ["asap-mcp-core"],
     "toolRefs": ["asap-mcp-core/geo.geocode"], "resolvedToolRefs": ["asap-mcp-core/geo.geocode"], "status": "ready"},
    # multi-server group. otp-router 는 이번 refresh 에 Tool 을 안 냈다.
    {"id": "route-accessibility", "name": "경로/접근성 분석", "serverIds": ["otp-router", "r5-server"],
     "toolRefs": ["otp-router/*", "r5-server/*"], "resolvedToolRefs": ["r5-server/compute_isochrone"],
     "status": "error", "lastError": "connect EHOSTUNREACH 192.168.71.236:8001"},
    {"id": "web-research", "name": "웹 리서치", "serverIds": ["web-search"], "toolRefs": ["web-search/*"],
     "resolvedToolRefs": ["web-search/web.search"], "status": "ready"},
    # group 정의에 안 걸린 server 는 Gateway 가 id=server_id fallback group 을 만든다. 그것도 MCP 하나다.
    {"id": "new-mcp", "name": "New MCP Server", "description": "새로 등록된 서버", "version": "registered",
     "serverIds": ["new-mcp"], "toolRefs": ["new-mcp/*"], "resolvedToolRefs": [], "status": "error"},
    {"id": "off-mcp", "name": "off-mcp", "serverIds": ["off-mcp"], "toolRefs": ["off-mcp/*"], "resolvedToolRefs": [],
     "status": "disabled", "enabled": False},
    {"id": "idle-mcp", "name": "idle-mcp", "serverIds": ["idle-mcp"], "toolRefs": ["idle-mcp/*"], "resolvedToolRefs": [],
     "status": "ready"},
    # id 없는 항목 · 중복 id 는 버린다.
    {"name": "no id"},
    {"id": "krri-map-location", "name": "dup"},
]

TOOLS.append({"name": "compute_isochrone", "description": "등시선", "inputSchema": {}, "serverId": "r5-server"})


class FakeGateway:
    def __init__(self, tools=TOOLS, market=MARKET):
        self.responses = {"/api/tools": tools, "/api/mcp-market": market}
        self.calls: list[str] = []
        self.fail: Exception | None = None

    def __call__(self, path):
        self.calls.append(path)
        if self.fail:
            raise self.fail
        return self.responses[path]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now
