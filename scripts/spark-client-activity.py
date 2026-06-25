#!/usr/bin/env python3
"""Client activity API — reads gateway JSONL, serves summary + recent sessions.

Binds on :8769 (LAN-only, proxied by nginx as /api/activity).
Reads run/inference-activity.jsonl with 1h/24h rollups.
Maintains in-memory active-client map (IP + app, 5-min TTL).

Usage:
  python scripts/spark-client-activity.py --serve --port 8769

See docs/roadmap/tasks/TASK-001-client-activity-dashboard.md
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path("/opt/spark")
JSONL_PATH: Path = ROOT / "run" / "inference-activity.jsonl"
ACTIVE_TTL = 300  # 5 min
CLEANUP_INTERVAL = 60

_ACTIVE_LOCK = threading.Lock()
_ACTIVE: dict[str, dict[str, Any]] = {}

_STATS_CACHE: dict[str, Any] = {}
_STATS_CACHE_LOCK = threading.Lock()
_STATS_CACHE_TTL = 2.0


def _classify_app(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "hermes" in ua:
        return "hermes"
    if "open-webui" in ua or "openwebui" in ua:
        return "open-webui"
    if "opencode" in ua:
        return "opencode"
    if any(k in ua for k in ("curl", "python-requests", "httpx", "fetch", "wget")):
        return "script"
    return "unknown"


def _touch_active(client_ip: str, app: str, ts: float) -> None:
    key = f"{client_ip}/{app}"
    with _ACTIVE_LOCK:
        existing = _ACTIVE.get(key)
        if existing and existing.get("last_seen", 0) >= ts:
            return
        _ACTIVE[key] = {
            "ip": client_ip,
            "app": app,
            "last_seen": ts,
        }


def _cleanup_active() -> None:
    now = time.time()
    with _ACTIVE_LOCK:
        keysToRemove = [k for k, v in _ACTIVE.items() if now - v["last_seen"] > ACTIVE_TTL]
        for k in keysToRemove:
            del _ACTIVE[k]


def _active_clients() -> list[dict[str, Any]]:
    now = time.time()
    with _ACTIVE_LOCK:
        return [
            v for v in _ACTIVE.values()
            if now - v.get("last_seen", 0) <= ACTIVE_TTL
        ]


_cleanup_timer: Any = None


def _start_cleanup_timer() -> None:
    global _cleanup_timer
    def loop():
        while True:
            time.sleep(CLEANUP_INTERVAL)
            _cleanup_active()
    t = threading.Thread(target=loop, daemon=True)
    t.start()


def _parse_ts(ts: str) -> float:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0


def read_jsonl() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not JSONL_PATH.exists():
        return rows
    try:
        with open(JSONL_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def compute_stats(window: str = "24h") -> dict[str, Any]:
    now = time.time()
    with _STATS_CACHE_LOCK:
        cached = _STATS_CACHE.get(window)
        if cached and now - cached["ts"] < _STATS_CACHE_TTL:
            return cached["data"]
    rows = read_jsonl()
    if window == "1h":
        cutoff = now - 3600
        cutoff24 = now - 86400
    else:
        cutoff = now - 86400
        cutoff24 = now - 86400

    sessions_1h = 0
    sessions_24h = 0
    tok_s_values: list[float] = []
    recent: list[dict[str, Any]] = []

    for row in rows:
        ts = _parse_ts(row.get("at", ""))
        if ts <= 0:
            continue
        if now - ts <= cutoff24:
            sessions_24h += 1
        if now - ts <= cutoff:
            sessions_1h += 1
            tok = row.get("tok_s")
            if tok and tok > 0:
                tok_s_values.append(tok)
            _touch_active(row.get("client_ip", ""), row.get("app", "unknown"), ts)

    recent_list = [r for r in rows if _parse_ts(r.get("at", "")) > cutoff]
    recent_list.sort(key=lambda r: r.get("at", ""), reverse=True)
    recent = recent_list[:20]

    avg_tok_s = 0.0
    if tok_s_values:
        avg_tok_s = round(sum(tok_s_values) / len(tok_s_values), 1)

    active = _active_clients()

    data = {
        "summary": {
            "active_clients": len(active),
            "sessions_1h": sessions_1h,
            "sessions_24h": sessions_24h,
            "avg_tok_s": avg_tok_s,
        },
        "active": active[:50],
        "recent": recent,
    }
    with _STATS_CACHE_LOCK:
        _STATS_CACHE[window] = {"ts": now, "data": data}
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"activity-api: {fmt % args}\n")

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        if not self.path.startswith("/api/activity"):
            self.send_error(404)
            return

        params = {}
        if "?" in self.path:
            qs = self.path.split("?", 1)[1]
            for pair in qs.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v
        window = params.get("window", "24h")
        if window not in ("1h", "24h"):
            window = "24h"

        try:
            stats = compute_stats(window)
            self._json(200, stats)
        except Exception as exc:
            self._json(500, {"error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser(description="Spark client activity API")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if not args.serve:
        parser.print_help()
        return 1

    _start_cleanup_timer()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"spark-client-activity listening on http://{args.host}:{args.port}/api/activity")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())