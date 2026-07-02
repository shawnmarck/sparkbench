#!/opt/spark/venv/bin/python3
"""HTTP API for Benchmaster queue control (:8770, proxied as /api/benchmaster/)."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path("/opt/spark")
_CORE_PATH = ROOT / "scripts" / "spark-benchmaster.py"


def _load_core():
    spec = importlib.util.spec_from_file_location("benchmaster_core", _CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load spark-benchmaster.py")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core


core = _load_core()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _handle_stream(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query or "")
        since = int((qs.get("since") or ["0"])[0] or 0)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()

        offset = since
        heartbeat = 0
        while True:
            events = core.tail_events(since=offset, limit=50)
            for ev in events:
                offset += 1
                payload = json.dumps(ev, separators=(",", ":"))
                self.wfile.write(f"event: benchmaster\ndata: {payload}\n\n".encode())
                self.wfile.flush()
            st = core.status()
            payload = json.dumps(st, separators=(",", ":"))
            self.wfile.write(f"event: status\ndata: {payload}\n\n".encode())
            self.wfile.flush()
            heartbeat += 1
            if heartbeat > 600:
                break
            time.sleep(2)

    def _dispatch(self, method: str) -> None:
        path = self.path.split("?", 1)[0]

        if method == "GET" and path == "/api/benchmaster/stream":
            try:
                self._handle_stream()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        body: dict[str, Any] | None = {} if method in {"GET", "OPTIONS"} else None
        if method in {"POST"}:
            body = self._read_json_body()
            if body is None:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return

        result = core.api_dispatch(method, path, body)
        if result is None:
            self.send_error(404)
            return
        code, payload = result
        self._json(code, payload)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def log_message(self, *_args: object) -> None:
        return


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        core.start_worker()
        core.RUN_DIR.mkdir(parents=True, exist_ok=True)
        if not core.QUEUE_FILE.is_file():
            core.save_queue(core.default_queue())
        ThreadingHTTPServer(("127.0.0.1", 8770), Handler).serve_forever()
        return 0
    print(json.dumps({"ok": True, **core.status()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
