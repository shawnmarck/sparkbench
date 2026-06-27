#!/opt/spark/venv/bin/python3
"""Context ladder — load + bench probe at increasing ctx rungs above golden preset.

Stores results in recipe.context.ctx_ladder for portal display and recipe tuning.
Each rung loads at target ctx, fills to FILL_RATIO of usable window, runs one
measured v2-style session, records decode tok/s.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
RECIPES = ROOT / "recipes"
MODELS_JSON = ROOT / "portal" / "models.json"
LOG_FILE = ROOT / "logs" / "ctx-ladder.log"
REPORT_FILE = ROOT / "run" / "ctx-ladder-report.json"

FILL_RATIO = 0.75
HEADROOM_MIN = 8192
HEADROOM_FRAC = 0.10
READY_SECS = 600
BENCH_TIMEOUT = 900


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _load_ctxmod():
    spec = importlib.util.spec_from_file_location(
        "ctx", ROOT / "scripts" / "spark-inference-context.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_benchv2():
    spec = importlib.util.spec_from_file_location(
        "benchv2", ROOT / "scripts" / "spark-inference-bench-v2.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_recipe(profile_id: str) -> dict[str, Any]:
    path = RECIPES / f"{profile_id}.yaml"
    if not path.is_file():
        raise SystemExit(f"missing recipe: {path}")
    return yaml.safe_load(path.read_text()) or {}


def save_recipe(profile_id: str, recipe: dict[str, Any]) -> None:
    path = RECIPES / f"{profile_id}.yaml"
    path.write_text(yaml.safe_dump(recipe, sort_keys=False, default_flow_style=False))


def resolve_native_ctx(recipe: dict[str, Any], ctxmod: Any) -> int:
    native = ctxmod.native_context(recipe)
    if native and native > 0:
        return int(native)
    block = recipe.get("context") or {}
    return int(block.get("native") or ctxmod.default_context(recipe) or 32768)


def golden_ctx_and_kv(recipe: dict[str, Any], ctxmod: Any) -> tuple[int, str]:
    block = recipe.get("context") or {}
    presets = block.get("presets") or {}
    golden = presets.get("golden") if isinstance(presets, dict) else None
    if isinstance(golden, dict) and golden.get("ctx"):
        return int(golden["ctx"]), str(golden.get("kv") or block.get("kv_default") or "q8_0")
    default = ctxmod.default_context(recipe) or 32768
    kv = str(block.get("kv_default") or ctxmod.default_kv(recipe))
    return int(default), kv


def headroom(ctx: int) -> int:
    return max(HEADROOM_MIN, int(ctx * HEADROOM_FRAC))


def fill_target_for_ctx(ctx: int, *, fill_ratio: float = FILL_RATIO) -> int:
    usable = max(4096, ctx - headroom(ctx))
    return max(2048, int(usable * fill_ratio))


def build_rungs(golden_ctx: int, native_ctx: int) -> list[int]:
    """Rungs strictly above golden, up to native, 1024-aligned."""
    if native_ctx <= golden_ctx:
        return []

    milestones = [
        4096 * n for n in (16, 24, 32, 48, 64, 80, 96, 112, 128, 147, 160, 192, 256, 320)
    ]
    candidates: set[int] = set()
    step = max(16384, golden_ctx)
    c = ((golden_ctx + step) // 1024) * 1024
    while c < native_ctx:
        candidates.add(c)
        if c < 65536:
            c = ((c + 16384) // 1024) * 1024
        elif c < 131072:
            c = ((c + 32768) // 1024) * 1024
        else:
            c = ((c + 65536) // 1024) * 1024
    for m in milestones:
        if golden_ctx < m <= native_ctx:
            candidates.add(m)
    candidates.add((native_ctx // 1024) * 1024)
    return sorted(x for x in candidates if x > golden_ctx)


def run(cmd: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    log(f"RUN: {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def wait_ready(port: int, *, expected_ctx: int | None = None, timeout: int = READY_SECS) -> bool:
    url = f"http://127.0.0.1:{port}/v1/models"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status != 200:
                    time.sleep(5)
                    continue
                if expected_ctx is None:
                    return True
                loaded = loaded_ctx(port, data=json.loads(resp.read().decode()))
                if loaded is not None and abs(loaded - expected_ctx) <= 1024:
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def loaded_ctx(port: int, data: dict[str, Any] | None = None) -> int | None:
    try:
        if data is None:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as resp:
                data = json.loads(resp.read().decode())
        row = (data.get("data") or [{}])[0]
        meta = row.get("meta") or {}
        if isinstance(meta, dict) and meta.get("n_ctx") is not None:
            return int(meta["n_ctx"])
        val = row.get("max_model_len") or row.get("n_ctx")
        return int(val) if val is not None else None
    except Exception:
        return None


def probe_rung(
    profile_id: str,
    recipe: dict[str, Any],
    *,
    ctx: int,
    kv: str,
    fill_ratio: float,
    benchv2: Any,
) -> dict[str, Any]:
    port = int(recipe.get("port") or 8081)
    served = str(recipe.get("served_name") or profile_id)
    engine = recipe.get("engine")
    fill = fill_target_for_ctx(ctx, fill_ratio=fill_ratio)
    row: dict[str, Any] = {
        "ctx": ctx,
        "kv": kv,
        "fill_target": fill,
        "fill_ratio": fill_ratio,
        "status": "pending",
    }

    run(["/usr/local/bin/spark", "inference", "down"], timeout=120)
    up = run(
        [
            "/usr/local/bin/spark",
            "inference",
            "up",
            profile_id,
            "--ctx",
            str(ctx),
            "--kv",
            kv,
        ],
        timeout=3600,
    )
    if up.returncode != 0:
        row["status"] = "load_fail"
        row["error"] = (up.stderr or up.stdout or "inference up failed")[-500:]
        return row

    if not wait_ready(port, expected_ctx=ctx, timeout=READY_SECS):
        row["status"] = "load_fail"
        row["error"] = f"/v1/models not ready at ctx={ctx} within {READY_SECS}s"
        return row

    loaded = loaded_ctx(port)
    row["loaded_ctx"] = loaded
    if loaded is not None and abs(loaded - ctx) > 1024:
        row["status"] = "load_fail"
        row["error"] = f"requested ctx={ctx} but loaded={loaded}"
        return row

    try:
        stats = benchv2._bench_v2_session_once(
            port,
            served,
            fill_target_tokens=fill,
            engine=engine,
            use_tools=True,
        )
    except Exception as exc:
        row["status"] = "bench_fail"
        row["error"] = str(exc)[:500]
        return row

    row.update(
        {
            "status": "ok",
            "tok_s": round(stats["decode_tok_s"], 1),
            "fill_estimated": stats.get("context_fill_estimated_tokens"),
            "prefill_prompt_tokens": stats.get("prefill_prompt_tokens"),
            "decode_tokens": stats.get("decode_completion_tokens"),
            "decode_elapsed_s": round(stats.get("decode_elapsed_s") or 0, 2),
            "tool_ok": stats.get("tool_roundtrip_ok"),
        }
    )
    return row


def run_ladder(
    profile_id: str,
    *,
    dry_run: bool = False,
    include_golden: bool = False,
    stop_on_fail: bool = True,
    fill_ratio: float = FILL_RATIO,
) -> dict[str, Any]:
    ctxmod = _load_ctxmod()
    benchv2 = _load_benchv2()
    recipe = load_recipe(profile_id)
    golden, kv = golden_ctx_and_kv(recipe, ctxmod)
    native = resolve_native_ctx(recipe, ctxmod)

    rungs = build_rungs(golden, native)
    if include_golden:
        rungs = [golden] + rungs

    report: dict[str, Any] = {
        "profile_id": profile_id,
        "inventory_path": recipe.get("inventory_path"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "golden_ctx": golden,
        "native_ctx": native,
        "kv": kv,
        "fill_ratio": fill_ratio,
        "rungs_planned": rungs,
        "results": [],
    }

    log(f"=== ctx ladder {profile_id} golden={golden} native={native} rungs={rungs} ===")

    if dry_run:
        report["dry_run"] = True
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report

    max_viable = golden if include_golden else None
    for ctx in rungs:
        log(f"--- rung ctx={ctx} fill~{fill_target_for_ctx(ctx, fill_ratio=fill_ratio)} ---")
        row = probe_rung(
            profile_id,
            recipe,
            ctx=ctx,
            kv=kv,
            fill_ratio=fill_ratio,
            benchv2=benchv2,
        )
        report["results"].append(row)
        log(f"rung ctx={ctx} status={row['status']} tok_s={row.get('tok_s')}")

        if row["status"] == "ok":
            max_viable = ctx
        elif stop_on_fail:
            log(f"stopping ladder after {row['status']} at ctx={ctx}")
            break

    report["max_viable_ctx"] = max_viable
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    # Persist on recipe (refresh recipe in case modified elsewhere)
    recipe = load_recipe(profile_id)
    block = recipe.setdefault("context", {})
    block["native"] = native
    block["ctx_ladder"] = {
        "version": "1.0",
        "tested_at": report["finished_at"],
        "golden_ctx": golden,
        "native_ctx": native,
        "fill_ratio": fill_ratio,
        "kv": kv,
        "max_viable_ctx": max_viable,
        "rungs": report["results"],
    }
    save_recipe(profile_id, recipe)
    log(f"saved ctx_ladder to recipe; max_viable_ctx={max_viable}")

    run(["/usr/local/bin/spark", "models", "inventory"], timeout=300)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Context ladder viability + tok/s probe")
    parser.add_argument("profile_id", help="Golden recipe profile id")
    parser.add_argument("--dry-run", action="store_true", help="Plan rungs only")
    parser.add_argument("--include-golden", action="store_true", help="Re-test golden ctx rung")
    parser.add_argument("--continue-on-fail", action="store_true", help="Keep climbing after failure")
    parser.add_argument(
        "--fill-ratio",
        type=float,
        default=FILL_RATIO,
        help=f"Fraction of usable ctx to fill (default {FILL_RATIO})",
    )
    args = parser.parse_args()

    report = run_ladder(
        args.profile_id,
        dry_run=args.dry_run,
        include_golden=args.include_golden,
        stop_on_fail=not args.continue_on_fail,
        fill_ratio=args.fill_ratio,
    )
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"ok": True, "max_viable_ctx": report.get("max_viable_ctx"), "report": str(REPORT_FILE)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
