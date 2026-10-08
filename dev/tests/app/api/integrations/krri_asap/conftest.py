"""KRRI_ASAP client 를 실제 HTTP 로 부르는 기록용 가짜 Gateway (127.0.0.1, 임의 port).

client 가 실제로 보낸 method · path · header · body 를 그대로 기록한다. 그래서 test 가 「무엇을 부르고 무엇은 부르지 않는지」를
fetch 함수 주입 없이 HTTP 수준에서 확인할 수 있다. 등록하지 않은 (method, path) 는 404 다.
"""

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class RecordingGateway:
    url: str = ""
    requests: list[Recorded] = field(default_factory=list)
    routes: dict[tuple[str, str], tuple[int, dict[str, str], bytes]] = field(default_factory=dict)

    def reply(self, method: str, path: str, *, status: int = 200, json_body=None, body: bytes = b"",
              headers: dict[str, str] | None = None):
        headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode()
            headers.setdefault("Content-Type", "application/json")
        self.routes[(method, path)] = (status, headers, body)

    def calls(self) -> list[tuple[str, str]]:
        return [(r.method, r.path) for r in self.requests]


@pytest.fixture
def recording_gateway():
    gateway = RecordingGateway()

    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            length = int(self.headers.get("Content-Length") or 0)
            gateway.requests.append(Recorded(
                self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, self.rfile.read(length)))
            status, headers, body = gateway.routes.get((self.command, self.path), (404, {}, b""))
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_PUT = do_POST = do_DELETE = do_PATCH = _handle

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    gateway.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield gateway
    server.shutdown()
    server.server_close()
