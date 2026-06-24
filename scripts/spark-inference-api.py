#!/opt/spark/venv/bin/python3
"""HTTP API for spark-inference (portal + gateway)."""
from __future__ import annotations

import importlib.util
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path("/opt/spark")
_CORE_PATH = ROOT / "scripts" / "spark-inference.py"


def _load_core():
    spec = importlib.util.spec_from_file_location("inference_core", _CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load spark-inference.py")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    return core


core = _load_core()


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
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

    def _dispatch(self, method: str) -> None:
        global core
        core = _load_core()
        body: dict[str, Any] | None = {} if method in {"GET", "OPTIONS"} else None
        if method in {"POST", "PATCH"}:
            body = self._read_json_body()
            if body is None:
                self._json(400, {"ok": False, "error": "invalid JSON"})
                return
        result = core.api_dispatch(method, self.path, body)
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

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def log_message(self, *_args: object) -> None:
        return


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        HTTPServer(("127.0.0.1", 8767), Handler).serve_forever()
        return 0
    print(json.dumps({"ok": True, **_load_core().api_status()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
