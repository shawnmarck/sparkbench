#!/opt/spark/venv/bin/python3
"""HTTP API for spark-hf (portal HF Explorer)."""
from __future__ import annotations

import importlib.util
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path("/opt/spark")
CORE_SCRIPT = ROOT / "scripts" / "spark-hf.py"
_core_mtime: float = 0.0
_core: Any = None


def get_core() -> Any:
    global _core, _core_mtime
    mtime = CORE_SCRIPT.stat().st_mtime
    if _core is not None and mtime == _core_mtime:
        return _core
    spec = importlib.util.spec_from_file_location("hf_core", CORE_SCRIPT)
    if spec is None or spec.loader is None:
        raise SystemExit("failed to load spark-hf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _core = mod
    _core_mtime = mtime
    return _core


class Handler(BaseHTTPRequestHandler):
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

    def _dispatch(self, method: str, body: dict[str, Any] | None = None) -> None:
        result = get_core().api_dispatch(method, self.path, body)
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
        data = self._read_json_body()
        if data is None:
            self._json(400, {"ok": False, "error": "invalid JSON"})
            return
        self._dispatch("POST", data)

    def log_message(self, *_args: object) -> None:
        return


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        get_core()
        HTTPServer(("127.0.0.1", 8768), Handler).serve_forever()
        return 0
    print(json.dumps({"ok": True, **get_core().api_status()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())