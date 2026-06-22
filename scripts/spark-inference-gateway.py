#!/usr/bin/env python3
"""Spark Inference Gateway: unified stable /v1 endpoint on :9000.

Forwards to the active engine (eugr/ds4 on :8000 or llama on :8081).
- Reads active profile from core (state + runtime checks).
- Optional model aliases + auto-switch on chat/completions (triggers background switch).
- Returns 503 + Retry-After while no active or switching.
- Basic normalization (e.g. ds4 thinking disabled).
- Streaming-aware forwarding for SSE / completions.
- Passthrough most /v1/* ; special handling for models + chat.

Usage:
  python scripts/spark-inference-gateway.py --serve --port 9000
  # or via wrapper

Clients: http://sparky:9000/v1   (base_url for Hermes, Open WebUI, etc.)
Stable forever; backend port moves on `spark inference up <profile>`.

See docs/reference/inference-stack.md .
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path("/opt/spark")
SPEC = importlib.util.spec_from_file_location(
    "inference_core", ROOT / "scripts" / "spark-inference.py"
)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("failed to load spark-inference core")
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)

DEFAULT_PORT = 9000
UPSTREAM_HOST = "127.0.0.1"

# Model alias -> profile_id map. Extend as needed.
ALIASES: dict[str, str] = {
    "hermes-local": "nousresearch-hermes-4-14b-eugr",
    "hermes-14b": "nousresearch-hermes-4-14b-eugr",
    "qwen-local": "qwen-qwen3-6-27b-dflash-eugr",
    "qwen3-6-27b": "qwen-qwen3-6-27b-dflash-eugr",
    "qwen3.6-27b-dflash": "qwen-qwen3-6-27b-dflash-eugr",
    "step-3-7-flash": "stepfun-ai-step-3-7-flash-llama",
}

THINKING_DISABLED_ENGINES = {"ds4"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _get_active(self) -> tuple[int | None, str | None, str | None, dict[str, Any] | None]:
        try:
            active = core.detect_active_profile()
            if not active:
                return None, None, None, None
            recipe = active.get("recipe", {}) or {}
            port = int(recipe.get("port") or (8000 if recipe.get("engine") != "llamacpp" else 8081))
            served = recipe.get("served_name")
            prof = active.get("profile")
            return port, served, prof, active
        except Exception as exc:
            sys.stderr.write(f"gateway active lookup error: {exc}\n")
            return None, None, None, None

    def _is_switching(self) -> bool:
        try:
            job = core.active_switch_job()
            return bool(job.get("running"))
        except Exception:
            return False

    def _resolve_alias(self, model: str) -> str | None:
        if not model:
            return None
        model = str(model).strip()
        if model in ALIASES:
            return ALIASES[model]
        if core.validate_profile_id(model):
            return model
        return None

    def _inject_ds4_defaults(self, body: bytes, engine: str | None) -> bytes:
        if not body or engine not in THINKING_DISABLED_ENGINES:
            return body
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return body
            payload["thinking"] = {"type": "disabled"}
            payload["think"] = False
            payload.pop("reasoning_effort", None)
            return json.dumps(payload).encode()
        except (json.JSONDecodeError, TypeError):
            return body

    def _forward(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        port, served, prof, active = self._get_active()
        if not port:
            self._send_503("no active inference profile — run: spark inference up <profile>")
            return

        if self._is_switching():
            self._send_503(
                "profile switch in progress",
                retry_after=30,
                extra={"switching": True, "profile": prof},
            )
            return

        if not self._upstream_ready(port):
            self._send_503(
                "active engine not ready yet (loading or cold start)",
                retry_after=15,
                extra={"port": port, "profile": prof},
            )
            return

        recipe = (active or {}).get("recipe", {}) or {}
        engine = recipe.get("engine")

        upstream = f"http://{UPSTREAM_HOST}:{port}{path}"
        headers: dict[str, str] = {}
        for k, v in self.headers.items():
            kl = k.lower()
            if kl not in ("host", "connection", "content-length"):
                headers[k] = v
        if extra_headers:
            headers.update(extra_headers)
        if body is not None:
            headers.setdefault("Content-Type", "application/json")

        req = Request(upstream, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=600) as resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                status = resp.status
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Spark-Active-Profile", prof or "")
                self.send_header("X-Spark-Upstream-Port", str(port))
                if served:
                    self.send_header("X-Spark-Served-Model", served)
                self._cors()
                self.end_headers()

                chunk_size = 8192
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    try:
                        self.wfile.flush()
                    except Exception:
                        pass
        except HTTPError as exc:
            ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
            self.send_response(exc.code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            body = exc.read()
            if body:
                self.wfile.write(body)
        except URLError as exc:
            payload = json.dumps(
                {"error": {"message": f"upstream error: {exc.reason}", "type": "gateway_upstream"}}
            ).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            payload = json.dumps(
                {"error": {"message": f"gateway error: {exc}", "type": "gateway"}}
            ).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

    def _upstream_ready(self, port: int) -> bool:
        try:
            url = f"http://{UPSTREAM_HOST}:{port}/v1/models"
            with urlopen(url, timeout=3.0) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def _send_503(self, message: str, retry_after: int = 30, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "error": {
                "message": message,
                "type": "inference_unavailable",
            }
        }
        if extra:
            payload.update(extra)
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Retry-After", str(retry_after))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length > 0 else b""

    def do_GET(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return
        self._forward("GET", self.path)

    def do_POST(self) -> None:
        if not self.path.startswith("/v1/"):
            self.send_error(404)
            return

        body = self._read_body()

        if "chat/completions" in self.path or "completions" in self.path:
            try:
                payload = json.loads(body) if body else {}
                if isinstance(payload, dict):
                    orig_model = str(payload.get("model", "")).strip()
                    profile = self._resolve_alias(orig_model)
                    port, served, prof, active = self._get_active()
                    engine = (active or {}).get("recipe", {}).get("engine") if active else None

                    if profile and prof and profile != prof:
                        try:
                            ok, msg, job = core.start_switch_job(profile)
                            retry = 60 if "heavy" in str((active or {}).get("recipe", {}).get("tier", "") or "").lower() else 20
                            self._send_503(
                                f"Switching to profile '{profile}' (model '{orig_model}'). Retry ~{retry}s.",
                                retry_after=retry,
                                extra={"switching": True, "target_profile": profile, "job": job},
                            )
                            return
                        except Exception as sw_exc:
                            sys.stderr.write(f"gateway auto-switch error: {sw_exc}\n")

                    if served and orig_model:
                        payload["model"] = served
                        body = json.dumps(payload).encode()

                    body = self._inject_ds4_defaults(body, engine)

            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        self._forward("POST", self.path, body=body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()


def main() -> int:
    parser = argparse.ArgumentParser(description="Spark unified inference gateway")
    parser.add_argument("--serve", action="store_true", help="Run server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--list-aliases", action="store_true")
    args = parser.parse_args()

    if args.list_aliases:
        print(json.dumps(ALIASES, indent=2))
        return 0

    if not args.serve:
        parser.print_help()
        print("\nRun: /opt/spark/scripts/spark-inference-gateway --serve --port 9000")
        return 1

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"spark-inference-gateway listening on http://{args.host}:{args.port}/v1")
    print(f"  Stable client endpoint: http://sparky:{args.port}/v1")
    print(f"  Aliases configured: {list(ALIASES.keys())}")
    print("  Forwarding to active engine per spark inference state.")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
