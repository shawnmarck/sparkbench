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
SPEC = importlib.util.spec_from_file_location(
    "inference_core", ROOT / "scripts" / "spark-inference.py"
)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("failed to load spark-inference.py")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


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

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/inference/status":
            self._json(200, {"ok": True, **core.api_status()})
            return

        if self.path.startswith("/api/inference/logs"):
            lines = 30
            if "?" in self.path:
                for part in self.path.split("?", 1)[1].split("&"):
                    if part.startswith("lines="):
                        try:
                            lines = max(5, min(200, int(part.split("=", 1)[1])))
                        except ValueError:
                            pass
            self._json(200, core.api_inference_logs(lines))
            return

        self.send_error(404)

    def do_POST(self) -> None:
        data = self._read_json_body()
        if data is None:
            self._json(400, {"ok": False, "error": "invalid JSON"})
            return

        if self.path == "/api/inference/switch":
            if not data.get("confirm"):
                self._json(400, {"ok": False, "error": "confirmation required"})
                return
            profile = str(data.get("profile", "")).strip()
            if not core.validate_profile_id(profile):
                self._json(400, {"ok": False, "error": "unknown or disabled profile"})
                return
            recipe = core.load_recipe(profile)
            if recipe.get("tier") == "heavy" and not data.get("confirm_heavy"):
                self._json(
                    400,
                    {
                        "ok": False,
                        "error": "heavy tier requires confirm_heavy",
                        "profile": profile,
                        "notes": (recipe.get("notes") or "").strip(),
                    },
                )
                return
            ok, message, job = core.start_switch_job(profile)
            if not ok:
                code = 409 if "already" in message else 400
                self._json(code, {"ok": False, "error": message, "job": job})
                return
            self._json(
                202,
                {"ok": True, "message": message, "profile": profile, "job": job},
            )
            return

        if self.path == "/api/inference/down":
            if not data.get("confirm"):
                self._json(400, {"ok": False, "error": "confirmation required"})
                return
            try:
                status = core.api_down()
            except RuntimeError as exc:
                self._json(409, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "message": "stopped", **status})
            return

        self.send_error(404)

    def log_message(self, *_args: object) -> None:
        return


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        HTTPServer(("127.0.0.1", 8767), Handler).serve_forever()
        return 0
    print(json.dumps({"ok": True, **core.api_status()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())