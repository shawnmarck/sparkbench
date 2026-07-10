#!/usr/bin/env python3
"""Perfbench-metrics (PBM) — fixed fill ladder: 4k / 50k / 100k decode tok/s.

Does NOT overwrite model-verification headlines (those stay on bench-agent-v2 /
golden until a human promotes a PBM fill for display). Results land in
data/perfbench-metrics.yaml keyed by profile_id.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SPARK_ROOT", "/opt/spark"))
PBM_FILE = ROOT / "data" / "perfbench-metrics.yaml"
PBM_VERSION = "1.0"
PBM_METHOD = "perfbench-metrics"
# Fixed ladder (tokens). Skip a rung when recipe loaded ctx cannot fit fill+headroom.
PBM_FILLS = (4096, 50000, 100000)
PBM_HEADROOM = 8192
PBM_MEASURED_SESSIONS = int(os.environ.get("PBM_MEASURED_SESSIONS", "1"))
PBM_WARMUP = os.environ.get("PBM_WARMUP", "1") not in ("0", "false", "no")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def recipe_max_ctx(recipe: dict[str, Any]) -> int:
    ctx = recipe.get("context") or {}
    for key in ("effective", "default", "native"):
        if ctx.get(key):
            return int(ctx[key])
    return int(recipe.get("max_model_len") or 32768)


def fills_for_ctx(max_ctx: int) -> list[int]:
    usable = max(0, max_ctx - PBM_HEADROOM)
    return [f for f in PBM_FILLS if f <= usable]



def live_max_model_len(recipe: dict[str, Any]) -> int | None:
    """Read max_model_len from the running OpenAI-compatible /v1/models."""
    import json
    from urllib.request import urlopen
    port = int(recipe.get("port") or 0)
    if not port:
        return None
    try:
        with urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=5) as resp:
            data = json.loads(resp.read().decode())
        for m in data.get("data") or []:
            if m.get("max_model_len"):
                return int(m["max_model_len"])
    except Exception:
        return None
    return None

def load_ctx_for_fills(fills: list[int], recipe: dict[str, Any]) -> int:
    """Load once at enough ctx for the largest attempted fill."""
    need = (max(fills) if fills else 4096) + PBM_HEADROOM
    return min(recipe_max_ctx(recipe), max(need, 8192))


def record_pbm(profile_id: str, recipe: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    store = _load_yaml(PBM_FILE)
    profiles = store.setdefault("profiles", {})
    entry = {
        "method": PBM_METHOD,
        "version": PBM_VERSION,
        "engine": recipe.get("engine"),
        "inventory_path": recipe.get("inventory_path"),
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "loaded_ctx": result.get("loaded_ctx"),
        "fills": result.get("fills") or {},
        "skipped": result.get("skipped") or {},
        "primary_fill": result.get("primary_fill"),
        "note": result.get("note"),
    }
    # Convenience flat fields for site/filter (tok_s_4k / tok_s_50k / tok_s_100k)
    for fill, cell in (entry["fills"] or {}).items():
        label = {4096: "4k", 50000: "50k", 100000: "100k"}.get(int(fill), str(fill))
        if isinstance(cell, dict) and cell.get("tok_s") is not None:
            entry[f"tok_s_{label}"] = cell["tok_s"]
    profiles[profile_id] = entry
    store["updated_at"] = entry["measured_at"]
    store["standard"] = {
        "id": PBM_METHOD,
        "version": PBM_VERSION,
        "fills": list(PBM_FILLS),
        "headroom_tokens": PBM_HEADROOM,
    }
    _save_yaml(PBM_FILE, store)
    return entry


def run_pbm_on_active(
    *,
    profile_id: str,
    recipe: dict[str, Any],
    engine_ready: Any,
) -> dict[str, Any]:
    """Run PBM ladder against the already-up profile. Does not start/stop engines."""
    benchv2 = _load_module(
        "spark_inference_bench_v2", ROOT / "scripts" / "spark-inference-bench-v2.py"
    )
    if not engine_ready(recipe):
        raise RuntimeError("active profile not ready — wait for /v1/models")

    max_ctx = recipe_max_ctx(recipe)
    # Prefer LIVE engine max_model_len — recipe context.default often stays at golden 32k
    # even when `spark inference up --ctx 108192` loaded a larger window.
    loaded = live_max_model_len(recipe) or int(
        (recipe.get("context") or {}).get("effective")
        or recipe.get("loaded_ctx")
        or max_ctx
    )
    fills = fills_for_ctx(loaded)
    skipped = {
        str(f): f"needs>={f + PBM_HEADROOM} ctx (loaded={loaded})"
        for f in PBM_FILLS
        if f not in fills
    }
    if not fills:
        raise RuntimeError(f"no PBM fills fit loaded_ctx={loaded}")

    port = int(recipe.get("port") or 0)
    served = str(recipe.get("served_name") or "")
    engine = recipe.get("engine")

    if PBM_WARMUP:
        benchv2._bench_v2_session(
            port, served, fill_target_tokens=fills[0], engine=engine
        )

    fill_results: dict[str, Any] = {}
    for fill in fills:
        rates: list[float] = []
        tool_ok = True
        decode_tokens = 0
        decode_s = 0.0
        for _ in range(max(1, PBM_MEASURED_SESSIONS)):
            stats = benchv2._bench_v2_session(
                port, served, fill_target_tokens=fill, engine=engine
            )
            rates.append(float(stats["decode_tok_s"]))
            decode_tokens += int(stats["decode_completion_tokens"])
            decode_s += float(stats["decode_elapsed_s"])
            tool_ok = tool_ok and bool(stats["tool_roundtrip_ok"])
        tok_s = sum(rates) / len(rates)
        fill_results[str(fill)] = {
            "tok_s": round(tok_s, 1),
            "tok_s_min": round(min(rates), 1),
            "tok_s_max": round(max(rates), 1),
            "sessions": len(rates),
            "tool_roundtrip_ok": tool_ok,
            "completion_tokens": decode_tokens,
            "elapsed_s": round(decode_s, 2),
            "run_tok_s": [round(r, 1) for r in rates],
        }

    # Default primary: prefer 50k, else largest measured
    primary = 50000 if "50000" in fill_results else int(max(fill_results, key=int))
    note = (
        "PBM "
        + " / ".join(
            f"{k}={fill_results[k]['tok_s']}"
            for k in ("4096", "50000", "100000")
            if k in fill_results
        )
        + (f" skipped={list(skipped)}" if skipped else "")
    )
    result = {
        "profile": profile_id,
        "loaded_ctx": loaded,
        "fills": fill_results,
        "skipped": skipped,
        "primary_fill": primary,
        "note": note,
        "method": PBM_METHOD,
        "version": PBM_VERSION,
    }
    record_pbm(profile_id, recipe, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run perfbench-metrics on active profile")
    parser.add_argument("--profile", help="profile id (default: active)")
    args = parser.parse_args(argv)

    inf = _load_module("spark_inference", ROOT / "scripts" / "spark-inference.py")
    active = inf.detect_active_profile()
    if not active:
        raise SystemExit("no active profile")
    profile_id = args.profile or active["profile"]
    if profile_id != active["profile"]:
        raise SystemExit(
            f"active profile is {active['profile']}, not {profile_id} — up it first"
        )
    recipe = active["recipe"]
    result = run_pbm_on_active(
        profile_id=profile_id,
        recipe=recipe,
        engine_ready=inf.engine_ready,
    )
    fills = result.get("fills") or {}
    parts = [f"{k}:{v['tok_s']}" for k, v in fills.items()]
    print(
        f"PBM {profile_id}: "
        + " ".join(parts)
        + (f" skipped={list(result.get('skipped') or {})}" if result.get("skipped") else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
