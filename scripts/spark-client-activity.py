#!/usr/bin/env python3
"""Client activity API — reads gateway JSONL, serves summary + recent sessions.

Binds on :8769 (LAN-only, proxied by nginx as /api/activity).
Reads run/inference-activity.jsonl with 1h/24h rollups.
Folds unique session ids into run/inference-usage.json (24h / 30d / lifetime).
Per-profile ledger rates live in run/inference-pricing.json.
Maintains in-memory active-client map (IP + app, 5-min TTL).

Usage:
    python scripts/spark-client-activity.py --serve --port 8769
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path("/opt/spark")
SPARKY_ALIAS_IDS = frozenset({"sparky", "sparky-think", "sparky-fast"})
JSONL_PATH: Path = ROOT / "run" / "inference-activity.jsonl"
USAGE_PATH: Path = ROOT / "run" / "inference-usage.json"
PRICING_PATH: Path = ROOT / "run" / "inference-pricing.json"
ACTIVE_TTL = 300  # 5 min
CLEANUP_INTERVAL = 60
DOCKER_IP_TTL = 30.0
USAGE_HOUR_KEEP_S = 25 * 3600
USAGE_DAY_KEEP_S = 366 * 86400
USAGE_WINDOW_24H_S = 86400
USAGE_WINDOW_30D_S = 30 * 86400
USAGE_FOLD_VERSION = 3
LEDGER_GRAINS = ("day", "month", "qtr", "year")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
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

_PRICING_LOCK = threading.Lock()
_PRICING: dict[str, Any] | None = None


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


def _blank_store(*, version: int = USAGE_FOLD_VERSION) -> dict[str, Any]:
    return {
        "updated_at": "",
        "fold_version": version,
        "lifetime": _empty_counts(),
        "lifetime_profiles": {},
        "hours": {},
        "days": {},
        "seen": {},
        "backfills": [],
    }


def _load_usage() -> dict[str, Any]:
    store = _blank_store(version=0)
    if not USAGE_PATH.exists():
        store["fold_version"] = USAGE_FOLD_VERSION
        return store
    try:
        with open(USAGE_PATH, "r") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        store["fold_version"] = USAGE_FOLD_VERSION
        return store
    if not isinstance(raw, dict):
        store["fold_version"] = USAGE_FOLD_VERSION
        return store
    store["updated_at"] = str(raw.get("updated_at") or "")
    try:
        store["fold_version"] = int(raw.get("fold_version") or 0)
    except (TypeError, ValueError):
        store["fold_version"] = 0
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
        "fold_version": int(store.get("fold_version") or USAGE_FOLD_VERSION),
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


def _backup_usage_once() -> None:
    if not USAGE_PATH.exists():
        return
    bak = USAGE_PATH.with_name(f"inference-usage.json.pre-v{USAGE_FOLD_VERSION}")
    if bak.exists():
        return
    try:
        shutil.copy2(USAGE_PATH, bak)
    except OSError:
        pass


def _stamp(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_even(total: int, n: int) -> list[int]:
    n = max(1, n)
    total = max(0, int(total))
    base = total // n
    extra = total - base * n
    return [base + (1 if i < extra else 0) for i in range(n)]


def _apply_delta(
    store: dict[str, Any],
    prof: str,
    delta: dict[str, int],
    *,
    day: str | None = None,
) -> None:
    if (delta.get("prompt_tokens") or 0) + (delta.get("completion_tokens") or 0) + (
        delta.get("requests") or 0
    ) <= 0:
        return
    _add_counts(store["lifetime"], delta)
    lp = store["lifetime_profiles"]
    if prof not in lp:
        lp[prof] = _empty_counts()
    _add_counts(lp[prof], delta)
    if not day:
        return
    days = store["days"]
    if day not in days:
        days[day] = {"all": _empty_counts(), "profiles": {}}
    slot = _ensure_slot(days[day])
    _add_counts(slot["all"], delta)
    if prof not in slot["profiles"]:
        slot["profiles"][prof] = _empty_counts()
    _add_counts(slot["profiles"][prof], delta)


def _apply_backfill(store: dict[str, Any], raw: dict[str, Any]) -> None:
    bid = str(raw.get("id") or "").strip()
    if not bid:
        return
    have = {str(x.get("id") or "") for x in (store.get("backfills") or []) if isinstance(x, dict)}
    if bid in have:
        return
    pt, ct = _row_tokens(raw)
    req = 0
    try:
        req = max(0, int(raw.get("requests") or 0))
    except (TypeError, ValueError):
        req = 0
    if pt + ct + req <= 0:
        return
    prof = _row_profile(raw)
    spread = raw.get("spread_days") or raw.get("days") or []
    days = [str(d)[:10] for d in spread if str(d).strip()]
    if days:
        pts = _split_even(pt, len(days))
        cts = _split_even(ct, len(days))
        reqs = _split_even(req, len(days))
        for day, dpt, dct, dreq in zip(days, pts, cts, reqs):
            _apply_delta(
                store,
                prof,
                {"requests": dreq, "prompt_tokens": dpt, "completion_tokens": dct},
                day=day,
            )
    else:
        _apply_delta(
            store,
            prof,
            {"requests": req, "prompt_tokens": pt, "completion_tokens": ct},
        )
    store.setdefault("backfills", []).append(dict(raw))


def _seed_backfills_from_bak() -> list[dict[str, Any]]:
    bak = USAGE_PATH.with_name("inference-usage.json.bak-20260821-qwen36-split")
    if not bak.exists():
        return []
    try:
        raw = json.loads(bak.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    out = []
    for item in raw.get("backfills") or []:
        if not isinstance(item, dict):
            continue
        if item.get("id") != "hermes-qwen36-mtp-split-from-ornith-mix":
            continue
        bf = dict(item)
        bf["spread_days"] = [
            "2026-08-02",
            "2026-08-03",
            "2026-08-04",
            "2026-08-05",
            "2026-08-06",
        ]
        out.append(bf)
    return out


def _collect_backfills(store: dict[str, Any]) -> list[dict[str, Any]]:
    existing = [dict(x) for x in (store.get("backfills") or []) if isinstance(x, dict)]
    ids = {str(x.get("id") or "") for x in existing}
    for seed in _seed_backfills_from_bak():
        sid = str(seed.get("id") or "")
        if sid and sid not in ids:
            existing.append(seed)
            ids.add(sid)
    return existing


def _rebuild_from_rows(
    rows: list[dict[str, Any]],
    now: float,
    backfills: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild aggregates from unique JSONL session ids, then re-apply backfills."""
    store = _blank_store()
    seen: dict[str, float] = store["seen"]
    for row in rows:
        rid = str(row.get("id") or "").strip()
        ts = _parse_ts(row.get("at", ""))
        if ts <= 0 or not rid or rid in seen:
            continue
        _apply_row(store, row, ts)
        seen[rid] = ts
    store["seen"] = seen
    for bf in backfills or []:
        _apply_backfill(store, bf)
    _prune_usage(store, now)
    store["updated_at"] = _stamp(now)
    return store


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
    pricing = _load_pricing()
    for pid in ids:
        allc = pall.get(pid) or _empty_counts()
        ledger = _profile_ledger(store, pricing, pid, allc)
        profiles.append({
            "id": pid,
            "24h": p24.get(pid) or _empty_counts(),
            "30d": p30.get(pid) or _empty_counts(),
            "all": allc,
            "usd": None if ledger is None else ledger["usd"],
            "priced": ledger is not None,
            "in_per_m": None if ledger is None else ledger["in_per_m"],
            "out_per_m": None if ledger is None else ledger["out_per_m"],
        })
    profiles.sort(
        key=lambda p: (
            0 if p.get("usd") is not None else 1,
            -(float(p["usd"]) if p.get("usd") is not None else 0.0),
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
        "fold_version": int(store.get("fold_version") or 0),
    }


def fold_usage(rows: list[dict[str, Any]], *, jsonl_read_ok: bool = True) -> dict[str, Any]:
    """Fold unseen JSONL rows into durable counters. Safe to call on every poll.

    `seen` must stay aligned with IDs still in the JSONL. The gateway keeps the
    file by mtime/size, so rows can be older than any TTL. Forgetting those IDs
    by age re-folds the same sessions into lifetime on every /api/activity poll.
    """
    global _USAGE
    now = time.time()
    with _USAGE_LOCK:
        if _USAGE is None:
            _USAGE = _load_usage()
        if jsonl_read_ok and int(_USAGE.get("fold_version") or 0) < USAGE_FOLD_VERSION:
            _backup_usage_once()
            _USAGE = _rebuild_from_rows(
                rows,
                now,
                backfills=_collect_backfills(_USAGE),
            )
            _save_usage(_USAGE)
            return _usage_view(_USAGE, now)
        store = _USAGE
        seen: dict[str, float] = store["seen"]
        applied = 0
        present: set[str] = set()
        for row in rows if jsonl_read_ok else []:
            rid = str(row.get("id") or "").strip()
            ts = _parse_ts(row.get("at", ""))
            if ts <= 0 or not rid:
                continue
            present.add(rid)
            if rid in seen:
                continue
            _apply_row(store, row, ts)
            seen[rid] = ts
            applied += 1
        pruned = _prune_usage(store, now)
        # Drop IDs that rotated out of the JSONL. Never drop IDs still present,
        # even when the session is older than the file's 7-day age cap.
        if jsonl_read_ok:
            stale = [sid for sid in seen if sid not in present]
            if stale:
                for sid in stale:
                    del seen[sid]
                pruned = True
        store["seen"] = seen
        if applied or pruned:
            store["updated_at"] = _stamp(now)
            _save_usage(store)
        return _usage_view(store, now)


def _bust_stats() -> None:
    with _STATS_CACHE_LOCK:
        _STATS_CACHE.clear()


def _money(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    if x != x or x < 0 or x > 1_000_000:
        return 0.0
    return round(x, 6)


def _usd(pt: int, ct: int, inn: float, out: float) -> float:
    return (int(pt) * float(inn) + int(ct) * float(out)) / 1e6


def _quarter_key(day: str) -> str:
    y = day[:4]
    try:
        month = int(day[5:7])
    except (TypeError, ValueError):
        month = 1
    return f"{y}-Q{(month - 1) // 3 + 1}"


def _grain_key(day: str, grain: str) -> str:
    if grain == "month":
        return day[:7]
    if grain == "qtr":
        return _quarter_key(day)
    if grain == "year":
        return day[:4]
    return day


def _grain_label(key: str, grain: str) -> str:
    try:
        if grain == "day" and len(key) >= 10:
            return f"{_MONTHS[int(key[5:7]) - 1]} {int(key[8:10])}, {key[:4]}"
        if grain == "month" and len(key) >= 7:
            return f"{_MONTHS[int(key[5:7]) - 1]} {key[:4]}"
        if grain == "qtr" and "-Q" in key:
            y, q = key.split("-Q", 1)
            return f"Q{q} {y}"
        if grain == "year":
            return key[:4]
    except (TypeError, ValueError, IndexError):
        pass
    return key


def _empty_pricing() -> dict[str, Any]:
    return {"updated_at": "", "profiles": {}}


def _normalize_profile_pricing(raw: dict[str, Any]) -> dict[str, Any]:
    overrides: list[dict[str, Any]] = []
    for item in raw.get("overrides") or []:
        if not isinstance(item, dict):
            continue
        grain = str(item.get("grain") or "")
        key = str(item.get("key") or "").strip()
        if grain not in LEDGER_GRAINS or not key:
            continue
        overrides.append({
            "grain": grain,
            "key": key,
            "in_per_m": _money(item.get("in_per_m")),
            "out_per_m": _money(item.get("out_per_m")),
        })
    history: list[dict[str, Any]] = []
    for item in raw.get("history") or []:
        if not isinstance(item, dict):
            continue
        fr = str(item.get("from") or "").strip()[:10]
        to = str(item.get("to") or "").strip()[:10]
        if len(fr) < 10 or len(to) < 10 or fr > to:
            continue
        history.append({
            "from": fr,
            "to": to,
            "in_per_m": _money(item.get("in_per_m")),
            "out_per_m": _money(item.get("out_per_m")),
        })
    history.sort(key=lambda h: (h["from"], h["to"]))
    return {
        "in_per_m": _money(raw.get("in_per_m")),
        "out_per_m": _money(raw.get("out_per_m")),
        "overrides": overrides,
        "history": history,
    }


def _read_pricing_file() -> dict[str, Any]:
    store = _empty_pricing()
    if not PRICING_PATH.exists():
        return store
    try:
        with open(PRICING_PATH, "r") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return store
    if not isinstance(raw, dict):
        return store
    store["updated_at"] = str(raw.get("updated_at") or "")
    profs = raw.get("profiles") or {}
    if isinstance(profs, dict):
        store["profiles"] = {
            str(k): _normalize_profile_pricing(v)
            for k, v in profs.items()
            if isinstance(v, dict)
        }
    return store


def _write_pricing(store: dict[str, Any]) -> None:
    payload = {
        "updated_at": store.get("updated_at") or "",
        "profiles": store.get("profiles") or {},
    }
    try:
        PRICING_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PRICING_PATH.with_name(PRICING_PATH.name + ".tmp")
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(str(tmp), str(PRICING_PATH))
    except OSError:
        pass


def _load_pricing() -> dict[str, Any]:
    global _PRICING
    with _PRICING_LOCK:
        if _PRICING is None:
            _PRICING = _read_pricing_file()
        return _PRICING


def _profile_pricing(store: dict[str, Any], pid: str) -> dict[str, Any]:
    p = (store.get("profiles") or {}).get(pid)
    if not isinstance(p, dict):
        return {"in_per_m": 0.0, "out_per_m": 0.0, "overrides": [], "history": []}
    return p


def _profile_is_priced(p: dict[str, Any]) -> bool:
    if _money(p.get("in_per_m")) or _money(p.get("out_per_m")):
        return True
    if p.get("overrides") or p.get("history"):
        return True
    return False


def _rate_for_day(p: dict[str, Any], day: str) -> tuple[float, float, str]:
    by = {(o["grain"], o["key"]): o for o in p.get("overrides") or []}
    for grain, key in (
        ("day", day),
        ("month", _grain_key(day, "month")),
        ("qtr", _grain_key(day, "qtr")),
        ("year", _grain_key(day, "year")),
    ):
        o = by.get((grain, key))
        if o is not None:
            return o["in_per_m"], o["out_per_m"], grain
    for h in p.get("history") or []:
        if h["from"] <= day <= h["to"]:
            return h["in_per_m"], h["out_per_m"], "history"
    return float(p.get("in_per_m") or 0), float(p.get("out_per_m") or 0), "default"


def _profile_ledger(
    usage_store: dict[str, Any],
    pricing: dict[str, Any],
    pid: str,
    allc: dict[str, int],
) -> dict[str, float | None] | None:
    p = _profile_pricing(pricing, pid)
    if not _profile_is_priced(p):
        return None
    in_num = 0.0
    out_num = 0.0
    priced_pt = 0
    priced_ct = 0
    for dk, bucket in (usage_store.get("days") or {}).items():
        pv = (bucket.get("profiles") or {}).get(pid)
        if not isinstance(pv, dict):
            continue
        pt = int(pv.get("prompt_tokens") or 0)
        ct = int(pv.get("completion_tokens") or 0)
        if pt + ct <= 0:
            continue
        inn, out, _src = _rate_for_day(p, dk)
        in_num += pt * inn
        out_num += ct * out
        priced_pt += pt
        priced_ct += ct
    rem_pt = max(0, int(allc.get("prompt_tokens") or 0) - priced_pt)
    rem_ct = max(0, int(allc.get("completion_tokens") or 0) - priced_ct)
    if rem_pt + rem_ct:
        hist = p.get("history") or []
        fallback = hist[0]["from"] if hist else _day_key(time.time())
        inn, out, _src = _rate_for_day(p, fallback)
        in_num += rem_pt * inn
        out_num += rem_ct * out
        priced_pt += rem_pt
        priced_ct += rem_ct
    return {
        "usd": round((in_num + out_num) / 1e6, 6),
        "in_per_m": round(in_num / priced_pt, 6) if priced_pt else None,
        "out_per_m": round(out_num / priced_ct, 6) if priced_ct else None,
    }


def build_ledger(profile: str, grain: str) -> dict[str, Any]:
    global _USAGE
    grain = grain if grain in LEDGER_GRAINS else "day"
    now = time.time()
    with _USAGE_LOCK:
        if _USAGE is None:
            _USAGE = _load_usage()
        store = _USAGE
        view_now = now
    pricing = _load_pricing()
    p = _profile_pricing(pricing, profile)
    buckets: dict[str, dict[str, Any]] = {}
    for dk, bucket in (store.get("days") or {}).items():
        pv = (bucket.get("profiles") or {}).get(profile)
        if not isinstance(pv, dict):
            continue
        pt = int(pv.get("prompt_tokens") or 0)
        ct = int(pv.get("completion_tokens") or 0)
        req = int(pv.get("requests") or 0)
        if pt + ct + req <= 0:
            continue
        gk = _grain_key(dk, grain)
        slot = buckets.get(gk)
        if slot is None:
            slot = {
                "key": gk,
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "usd": 0.0,
                "sources": set(),
                "in_rates": set(),
                "out_rates": set(),
            }
            buckets[gk] = slot
        inn, out, src = _rate_for_day(p, dk)
        slot["requests"] += req
        slot["prompt_tokens"] += pt
        slot["completion_tokens"] += ct
        slot["usd"] += _usd(pt, ct, inn, out)
        slot["sources"].add(src)
        slot["in_rates"].add(inn)
        slot["out_rates"].add(out)

    override_keys = {
        (o["grain"], o["key"]) for o in p.get("overrides") or []
    }
    rows = []
    for key in sorted(buckets):
        slot = buckets[key]
        sources = slot["sources"]
        in_rates = slot["in_rates"]
        out_rates = slot["out_rates"]
        mixed = len(in_rates) > 1 or len(out_rates) > 1 or len(sources) > 1
        source = "mixed" if mixed else next(iter(sources), "default")
        rows.append({
            "key": key,
            "label": _grain_label(key, grain),
            "requests": slot["requests"],
            "prompt_tokens": slot["prompt_tokens"],
            "completion_tokens": slot["completion_tokens"],
            "in_per_m": next(iter(in_rates)) if len(in_rates) == 1 else None,
            "out_per_m": next(iter(out_rates)) if len(out_rates) == 1 else None,
            "source": source,
            "usd": round(slot["usd"], 6),
            "override": (grain, key) in override_keys,
        })

    tot_req = sum(r["requests"] for r in rows)
    tot_pt = sum(r["prompt_tokens"] for r in rows)
    tot_ct = sum(r["completion_tokens"] for r in rows)
    tot_usd = round(sum(r["usd"] for r in rows), 6)
    return {
        "profile": profile,
        "grain": grain,
        "priced": _profile_is_priced(p),
        "default": {"in_per_m": p["in_per_m"], "out_per_m": p["out_per_m"]},
        "history": p.get("history") or [],
        "overrides": p.get("overrides") or [],
        "rows": rows,
        "totals": {
            "requests": tot_req,
            "prompt_tokens": tot_pt,
            "completion_tokens": tot_ct,
            "usd": tot_usd if _profile_is_priced(p) else None,
        },
        "updated_at": store.get("updated_at") or _stamp(view_now),
    }


def put_pricing(body: dict[str, Any]) -> dict[str, Any]:
    global _PRICING
    profile = str(body.get("profile") or "").strip()
    if not profile:
        raise ValueError("profile required")
    now = time.time()
    with _PRICING_LOCK:
        if _PRICING is None:
            _PRICING = _read_pricing_file()
        store = _PRICING
        profs: dict[str, Any] = store.setdefault("profiles", {})
        current = _normalize_profile_pricing(profs.get(profile) or {})
        default = body.get("default")
        if isinstance(default, dict):
            if "in_per_m" in default:
                current["in_per_m"] = _money(default.get("in_per_m"))
            if "out_per_m" in default:
                current["out_per_m"] = _money(default.get("out_per_m"))
        if "history" in body:
            raw_hist = body.get("history")
            if not isinstance(raw_hist, list):
                raise ValueError("history must be a list")
            current["history"] = _normalize_profile_pricing({"history": raw_hist}).get("history") or []
        clear = body.get("clear_override")
        if isinstance(clear, dict):
            grain = str(clear.get("grain") or "")
            key = str(clear.get("key") or "").strip()
            current["overrides"] = [
                o for o in current["overrides"]
                if not (o["grain"] == grain and o["key"] == key)
            ]
        override = body.get("override")
        if isinstance(override, dict):
            grain = str(override.get("grain") or "")
            key = str(override.get("key") or "").strip()
            if grain not in LEDGER_GRAINS or not key:
                raise ValueError("override needs grain and key")
            current["overrides"] = [
                o for o in current["overrides"]
                if not (o["grain"] == grain and o["key"] == key)
            ]
            current["overrides"].append({
                "grain": grain,
                "key": key,
                "in_per_m": _money(override.get("in_per_m")),
                "out_per_m": _money(override.get("out_per_m")),
            })
            current["overrides"].sort(key=lambda o: (o["grain"], o["key"]))
        profs[profile] = current
        store["updated_at"] = _stamp(now)
        _write_pricing(store)
    _bust_stats()
    return build_ledger(profile, str(body.get("grain") or "day"))


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
    vis_1h = {"requests": 0, "image_tokens": 0}
    vis_24h = {"requests": 0, "image_tokens": 0}
    last_vis: dict[str, Any] | None = None
    last_vis_ts = 0.0

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

        try:
            img = int(resolved.get("image_tokens") or 0)
        except (TypeError, ValueError):
            img = 0
        if img > 0:
            if ts >= cutoff24:
                vis_24h["requests"] += 1
                vis_24h["image_tokens"] += img
            if ts >= cutoff:
                vis_1h["requests"] += 1
                vis_1h["image_tokens"] += img
            if ts >= last_vis_ts:
                last_vis_ts = ts
                last_vis = {
                    "at": resolved.get("at"),
                    "image_tokens": img,
                    "prompt_tokens": resolved.get("prompt_tokens") or 0,
                    "duration_ms": resolved.get("duration_ms") or 0,
                }

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
            "vision": {
                "h1": vis_1h,
                "h24": vis_24h,
                "last": last_vis,
            },
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

    def _route(self) -> tuple[str, dict[str, str]]:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        return path, qs

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            n = 0
        if n < 0 or n > 65536:
            raise ValueError("body too large")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid json") from exc
        if not isinstance(payload, dict):
            raise ValueError("json object required")
        return payload

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path, params = self._route()
        if path == "/api/activity/ledger":
            profile = unquote(params.get("profile") or "").strip()
            if not profile:
                self._json(400, {"error": "profile required"})
                return
            grain = params.get("grain", "day")
            try:
                rows, ok = read_jsonl()
                fold_usage(rows, jsonl_read_ok=ok)
                self._json(200, build_ledger(profile, grain))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path != "/api/activity":
            self.send_error(404)
            return
        window = params.get("window", "24h")
        if window not in ("1h", "24h"):
            window = "24h"
        try:
            self._json(200, compute_stats(window))
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def do_PUT(self) -> None:
        path, _params = self._route()
        if path != "/api/activity/pricing":
            self.send_error(404)
            return
        try:
            body = self._read_json()
            rows, ok = read_jsonl()
            fold_usage(rows, jsonl_read_ok=ok)
            self._json(200, put_pricing(body))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
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
