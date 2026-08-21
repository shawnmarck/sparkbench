#!/usr/bin/env python3
"""Client activity API — reads gateway JSONL, serves summary + recent sessions.

Binds on :8769 (LAN-only, proxied by nginx as /api/activity).
Reads run/inference-activity.jsonl with 1h/24h rollups.
Folds token-bearing rows into run/inference-usage.json (24h / 30d / lifetime).
Maintains in-memory active-client map (IP + app, 5-min TTL).

Usage:
  python scripts/spark-client-activity.py --serve --port 8769
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path("/opt/spark")
SPARKY_ALIAS_IDS = frozenset({"sparky", "sparky-think", "sparky-fast"})
JSONL_PATH: Path = ROOT / "run" / "inference-activity.jsonl"
USAGE_PATH: Path = ROOT / "run" / "inference-usage.json"
ACTIVE_TTL = 300  # 5 min
CLEANUP_INTERVAL = 60
DOCKER_IP_TTL = 30.0
USAGE_HOUR_KEEP_S = 25 * 3600
USAGE_DAY_KEEP_S = 366 * 86400
USAGE_WINDOW_24H_S = 86400
USAGE_WINDOW_30D_S = 30 * 86400
USAGE_SEEN_KEEP_S = 8 * 86400
CONTAINER_APPS = {
    "spark-open-webui": "open-webui",
    "spark-bot": "hermes",
}

_ACTIVE_LOCK = threading.Lock()
_ACTIVE: dict[str, dict[str, Any]] = {}

_STATS_CACHE: dict[str, Any] = {}
_STATS_CACHE_LOCK = threading.Lock()
_STATS_CACHE_TTL = 2.0

_DOCKER_IP_MAP: dict[str, str] = {}
_DOCKER_IP_MAP_AT = 0.0
_DOCKER_IP_LOCK = threading.Lock()

_USAGE_LOCK = threading.Lock()
_USAGE: dict[str, Any] | None = None


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


def _docker_ip_map() -> dict[str, str]:
    """Map container IPs on the Docker bridge to app names (Open WebUI, Hermes)."""
    global _DOCKER_IP_MAP, _DOCKER_IP_MAP_AT
    now = time.time()
    with _DOCKER_IP_LOCK:
        if _DOCKER_IP_MAP and now - _DOCKER_IP_MAP_AT < DOCKER_IP_TTL:
            return _DOCKER_IP_MAP
        mapping: dict[str, str] = {}
        for name, app in CONTAINER_APPS.items():
            try:
                out = subprocess.check_output(
                    [
                        "docker",
                        "inspect",
                        "-f",
                        "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
                        name,
                    ],
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5,
                )
            except (
                subprocess.CalledProcessError,
                FileNotFoundError,
                OSError,
                subprocess.TimeoutExpired,
            ):
                continue
            for ip in out.split():
                ip = ip.strip()
                if ip:
                    mapping[ip] = app
        _DOCKER_IP_MAP = mapping
        _DOCKER_IP_MAP_AT = now
        return mapping


def _resolve_app(row: dict[str, Any], ip_map: dict[str, str]) -> str:
    app = str(row.get("app") or "unknown")
    if app and app not in ("unknown", "?", ""):
        return app
    ip = str(row.get("client_ip") or "").strip()
    return ip_map.get(ip) or app


def _parse_ts(ts: str) -> float:
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0


def _empty_counts() -> dict[str, int]:
    return {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _copy_counts(src: dict[str, Any] | None) -> dict[str, int]:
    src = src or {}
    return {
        "requests": int(src.get("requests") or 0),
        "prompt_tokens": int(src.get("prompt_tokens") or 0),
        "completion_tokens": int(src.get("completion_tokens") or 0),
    }


def _add_counts(dst: dict[str, int], src: dict[str, Any]) -> None:
    dst["requests"] = int(dst.get("requests") or 0) + int(src.get("requests") or 0)
    dst["prompt_tokens"] = int(dst.get("prompt_tokens") or 0) + int(src.get("prompt_tokens") or 0)
    dst["completion_tokens"] = int(dst.get("completion_tokens") or 0) + int(src.get("completion_tokens") or 0)


def _hour_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H")


def _day_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _hour_start(key: str) -> float:
    try:
        return datetime.strptime(key, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _day_start(key: str) -> float:
    try:
        return datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _row_tokens(row: dict[str, Any]) -> tuple[int, int]:
    try:
        pt = int(row.get("prompt_tokens") or 0)
    except (TypeError, ValueError):
        pt = 0
    try:
        ct = int(row.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        ct = 0
    return max(pt, 0), max(ct, 0)


def _row_profile(row: dict[str, Any]) -> str:
    prof = str(row.get("profile") or "").strip()
    return prof or "unknown"


def _decorate_session(row: dict[str, Any]) -> dict[str, Any]:
    """Prefer the served profile when the client asked for the sparky alias."""
    out = dict(row)
    model = str(out.get("model") or "").strip()
    prof = str(out.get("profile") or "").strip()
    req = str(out.get("requested_model") or "").strip()
    if model.lower() in SPARKY_ALIAS_IDS and prof:
        if not req:
            out["requested_model"] = model
        out["model"] = prof
    return out


def _ensure_slot(bucket: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bucket.get("all"), dict):
        bucket["all"] = _empty_counts()
    if not isinstance(bucket.get("profiles"), dict):
        bucket["profiles"] = {}
    return bucket


def _apply_row(store: dict[str, Any], row: dict[str, Any], ts: float) -> None:
    pt, ct = _row_tokens(row)
    if pt + ct <= 0:
        return
    delta = {"requests": 1, "prompt_tokens": pt, "completion_tokens": ct}
    _add_counts(store["lifetime"], delta)
    prof = _row_profile(row)
    lp = store["lifetime_profiles"]
    if prof not in lp:
        lp[prof] = _empty_counts()
    _add_counts(lp[prof], delta)

    hk = _hour_key(ts)
    hours = store["hours"]
    if hk not in hours:
        hours[hk] = {"all": _empty_counts(), "profiles": {}}
    slot = _ensure_slot(hours[hk])
    _add_counts(slot["all"], delta)
    if prof not in slot["profiles"]:
        slot["profiles"][prof] = _empty_counts()
    _add_counts(slot["profiles"][prof], delta)

    dk = _day_key(ts)
    days = store["days"]
    if dk not in days:
        days[dk] = {"all": _empty_counts(), "profiles": {}}
    slot = _ensure_slot(days[dk])
    _add_counts(slot["all"], delta)
    if prof not in slot["profiles"]:
        slot["profiles"][prof] = _empty_counts()
    _add_counts(slot["profiles"][prof], delta)


def _prune_usage(store: dict[str, Any], now: float) -> bool:
    changed = False
    hours = store.get("hours") or {}
    kept_h = {k: v for k, v in hours.items() if _hour_start(k) >= now - USAGE_HOUR_KEEP_S}
    if len(kept_h) != len(hours):
        store["hours"] = kept_h
        changed = True
    days = store.get("days") or {}
    kept_d = {k: v for k, v in days.items() if _day_start(k) >= now - USAGE_DAY_KEEP_S}
    if len(kept_d) != len(days):
        store["days"] = kept_d
        changed = True
    return changed


def _load_usage() -> dict[str, Any]:
    store: dict[str, Any] = {
        "updated_at": "",
        "lifetime": _empty_counts(),
        "lifetime_profiles": {},
        "hours": {},
        "days": {},
        "seen": {},
        "backfills": [],
    }
    if not USAGE_PATH.exists():
        return store
    try:
        with open(USAGE_PATH, "r") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return store
    if not isinstance(raw, dict):
        return store
    store["updated_at"] = str(raw.get("updated_at") or "")
    store["lifetime"] = _copy_counts(raw.get("lifetime"))
    lp = raw.get("lifetime_profiles") or {}
    if isinstance(lp, dict):
        store["lifetime_profiles"] = {str(k): _copy_counts(v) for k, v in lp.items() if isinstance(v, dict)}
    for kind in ("hours", "days"):
        src = raw.get(kind) or {}
        if not isinstance(src, dict):
            continue
        out: dict[str, Any] = {}
        for key, bucket in src.items():
            if not isinstance(bucket, dict):
                continue
            profiles: dict[str, dict[str, int]] = {}
            for pid, pv in (bucket.get("profiles") or {}).items():
                if isinstance(pv, dict):
                    profiles[str(pid)] = _copy_counts(pv)
            out[str(key)] = {"all": _copy_counts(bucket.get("all")), "profiles": profiles}
        store[kind] = out
    seen_map: dict[str, float] = {}
    raw_seen = raw.get("seen")
    if isinstance(raw_seen, dict):
        for sid, ts in raw_seen.items():
            try:
                seen_map[str(sid)] = float(ts)
            except (TypeError, ValueError):
                continue
    else:
        for sid in raw.get("seen_ids") or []:
            if sid:
                seen_map[str(sid)] = 0.0
    store["seen"] = seen_map
    raw_bf = raw.get("backfills") or []
    if isinstance(raw_bf, list):
        store["backfills"] = [x for x in raw_bf if isinstance(x, dict)]
    return store


def _save_usage(store: dict[str, Any]) -> None:
    payload = {
        "updated_at": store.get("updated_at") or "",
        "lifetime": _copy_counts(store.get("lifetime")),
        "lifetime_profiles": {
            k: _copy_counts(v) for k, v in (store.get("lifetime_profiles") or {}).items()
        },
        "hours": store.get("hours") or {},
        "days": store.get("days") or {},
        "seen": {str(k): float(v) for k, v in (store.get("seen") or {}).items()},
        "backfills": [x for x in (store.get("backfills") or []) if isinstance(x, dict)],
    }
    try:
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = USAGE_PATH.with_name(USAGE_PATH.name + ".tmp")
        with open(tmp, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
            f.write("\n")
        os.replace(str(tmp), str(USAGE_PATH))
    except OSError:
        pass


def _sum_buckets(
    buckets: dict[str, Any], keys: list[str]
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    total = _empty_counts()
    profiles: dict[str, dict[str, int]] = {}
    for key in keys:
        bucket = buckets.get(key) or {}
        _add_counts(total, bucket.get("all") or {})
        for pid, pv in (bucket.get("profiles") or {}).items():
            if pid not in profiles:
                profiles[pid] = _empty_counts()
            _add_counts(profiles[pid], pv)
    return total, profiles


def _usage_view(store: dict[str, Any], now: float) -> dict[str, Any]:
    hour_keys = [k for k in (store.get("hours") or {}) if _hour_start(k) >= now - USAGE_WINDOW_24H_S]
    day_keys = [k for k in (store.get("days") or {}) if _day_start(k) >= now - USAGE_WINDOW_30D_S]
    w24, p24 = _sum_buckets(store.get("hours") or {}, hour_keys)
    w30, p30 = _sum_buckets(store.get("days") or {}, day_keys)
    wall = _copy_counts(store.get("lifetime"))
    pall = {k: _copy_counts(v) for k, v in (store.get("lifetime_profiles") or {}).items()}
    ids = set(p24) | set(p30) | set(pall)
    profiles = []
    for pid in ids:
        profiles.append({
            "id": pid,
            "24h": p24.get(pid) or _empty_counts(),
            "30d": p30.get(pid) or _empty_counts(),
            "all": pall.get(pid) or _empty_counts(),
        })
    profiles.sort(
        key=lambda p: (
            -(int(p["24h"]["prompt_tokens"]) + int(p["24h"]["completion_tokens"])),
            -(int(p["30d"]["prompt_tokens"]) + int(p["30d"]["completion_tokens"])),
            -(int(p["all"]["prompt_tokens"]) + int(p["all"]["completion_tokens"])),
            p["id"],
        )
    )
    days_out = []
    for dk in sorted(store.get("days") or {}):
        bucket = (store.get("days") or {}).get(dk) or {}
        allc = _copy_counts(bucket.get("all"))
        day_profiles: dict[str, dict[str, int]] = {}
        for pid, pv in (bucket.get("profiles") or {}).items():
            copied = _copy_counts(pv)
            if copied["requests"] or copied["prompt_tokens"] or copied["completion_tokens"]:
                day_profiles[str(pid)] = copied
        row = {
            "date": dk,
            "requests": allc["requests"],
            "prompt_tokens": allc["prompt_tokens"],
            "completion_tokens": allc["completion_tokens"],
        }
        if day_profiles:
            row["profiles"] = day_profiles
        days_out.append(row)
    return {
        "windows": {"24h": w24, "30d": w30, "all": wall},
        "profiles": profiles,
        "days": days_out,
    }


def fold_usage(rows: list[dict[str, Any]], *, jsonl_read_ok: bool = True) -> dict[str, Any]:
    """Fold unseen JSONL rows into durable counters. Safe to call on every poll."""
    global _USAGE
    now = time.time()
    with _USAGE_LOCK:
        if _USAGE is None:
            _USAGE = _load_usage()
        store = _USAGE
        seen: dict[str, float] = store["seen"]
        applied = 0
        for row in rows if jsonl_read_ok else []:
            rid = str(row.get("id") or "").strip()
            ts = _parse_ts(row.get("at", ""))
            if ts <= 0 or not rid:
                continue
            if rid in seen:
                continue
            _apply_row(store, row, ts)
            seen[rid] = ts
            applied += 1
        pruned = _prune_usage(store, now)
        stale = [sid for sid, sts in seen.items() if now - float(sts or 0) > USAGE_SEEN_KEEP_S]
        if stale:
            for sid in stale:
                del seen[sid]
            pruned = True
        store["seen"] = seen
        if applied or pruned:
            store["updated_at"] = datetime.fromtimestamp(now, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            _save_usage(store)
        return _usage_view(store, now)


def read_jsonl() -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    if not JSONL_PATH.exists():
        return rows, True
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
        return rows, True
    except OSError:
        return rows, False


def compute_stats(window: str = "24h") -> dict[str, Any]:
    now = time.time()
    with _STATS_CACHE_LOCK:
        cached = _STATS_CACHE.get(window)
        if cached and now - cached["ts"] < _STATS_CACHE_TTL:
            return cached["data"]
    rows, jsonl_ok = read_jsonl()
    usage = fold_usage(rows, jsonl_read_ok=jsonl_ok)
    ip_map = _docker_ip_map()
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
    resolved_rows: list[dict[str, Any]] = []
    weighted_tokens = 0.0
    weighted_wall_s = 0.0

    for row in rows:
        ts = _parse_ts(row.get("at", ""))
        if ts <= 0:
            continue
        resolved = {**row, "app": _resolve_app(row, ip_map)}
        resolved_rows.append(resolved)
        if ts >= cutoff24:
            sessions_24h += 1
        if ts >= cutoff:
            sessions_1h += 1
            tok = resolved.get("tok_s")
            if tok and tok > 0:
                tok_s_values.append(tok)
            try:
                ct = float(resolved.get("completion_tokens") or 0)
                dur_ms = float(resolved.get("duration_ms") or 0)
            except (TypeError, ValueError):
                ct, dur_ms = 0.0, 0.0
            if ct > 0 and dur_ms > 0:
                weighted_tokens += ct
                weighted_wall_s += dur_ms / 1000.0
            _touch_active(resolved.get("client_ip", ""), resolved.get("app", "unknown"), ts)

    recent_list = [r for r in resolved_rows if _parse_ts(r.get("at", "")) > cutoff]
    recent_list.sort(key=lambda r: r.get("at", ""), reverse=True)
    recent = [_decorate_session(r) for r in recent_list[:20]]

    avg_tok_s = 0.0
    if tok_s_values:
        avg_tok_s = round(sum(tok_s_values) / len(tok_s_values), 1)
    avg_tok_s_weighted = round(weighted_tokens / weighted_wall_s, 1) if weighted_wall_s > 0 else 0.0

    active = _active_clients()
    apps: dict[str, int] = {}
    for client in active:
        app = str(client.get("app") or "unknown")
        apps[app] = apps.get(app, 0) + 1

    data = {
        "summary": {
            "active_clients": len(active),
            "sessions_1h": sessions_1h,
            "sessions_24h": sessions_24h,
            "avg_tok_s": avg_tok_s,
            "avg_tok_s_weighted": avg_tok_s_weighted,
            "apps": apps,
        },
        "active": active[:50],
        "recent": recent,
        "usage": usage,
    }
    with _STATS_CACHE_LOCK:
        _STATS_CACHE[window] = {"ts": now, "data": data}
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return

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
