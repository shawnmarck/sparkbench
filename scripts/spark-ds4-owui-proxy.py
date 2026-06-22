#!/usr/bin/env python3
"""Proxy ds4 for Open WebUI — inject thinking disabled on chat completions."""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UPSTREAM = "http://127.0.0.1:8000"
DEFAULT_PORT = 8002


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _forward(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes, str]:
        url = UPSTREAM + path
        headers: dict[str, str] = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=600) as resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                return resp.status, resp.read(), ctype
        except HTTPError as exc:
            ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
            return exc.code, exc.read(), ctype
        except URLError as exc:
            payload = json.dumps({"error": {"message": str(exc.reason), "type": "upstream_error"}}).encode()
            return 502, payload, "application/json"

    def _inject_chat_defaults(self, body: bytes) -> bytes:
        if not body:
            return body
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return body
        if not isinstance(payload, dict):
            return body
        if "thinking" not in payload:
            payload["thinking"] = {"type": "disabled"}
        return json.dumps(payload).encode()

    def do_GET(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return
        status, data, ctype = self._forward("GET", self.path)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        if "chat/completions" in self.path:
            body = self._inject_chat_defaults(body)
        status, data, ctype = self._forward("POST", self.path, body)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()


def main() -> int:
    global UPSTREAM
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="Run HTTP server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--upstream", default=UPSTREAM)
    args = parser.parse_args()
    if not args.serve:
        parser.print_help()
        return 1
    UPSTREAM = args.upstream.rstrip("/")
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"ds4 Open WebUI proxy on :{args.port} -> {UPSTREAM}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
