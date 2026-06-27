#!/opt/spark/venv/bin/python3
"""Context ladder — load + bench probe at increasing ctx rungs above golden preset.

Stores results in recipe.context.ctx_ladder and bench_matrix.ctx_ladder.
Each rung loads at target ctx, fills to FILL_RATIO of usable window, runs one
measured v2-style session, records decode tok/s.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/spark")
REPORT_FILE = ROOT / "run" / "ctx-ladder-report.json"
LOG_FILE = ROOT / "logs" / "ctx-ladder.log"


def _load_golden_bench():
    spec = importlib.util.spec_from_file_location(
        "golden_bench", ROOT / "scripts" / "spark-golden-bench.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def resolve_native_ctx(recipe: dict[str, Any], ctxmod: Any) -> int:
    native = ctxmod.native_context(recipe)
    if native and native > 0:
        return int(native)
    block = recipe.get("context") or {}
    return int(block.get("native") or ctxmod.default_context(recipe) or 32768)


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


def run_ladder(
    profile_id: str,
    *,
    dry_run: bool = False,
    include_golden: bool = False,
    stop_on_fail: bool = True,
    fill_ratio: float | None = None,
    force: bool = False,
) -> dict[str, Any]:
    gb = _load_golden_bench()
    fill_ratio = fill_ratio if fill_ratio is not None else gb.FILL_RATIO
    ctxmod = gb.load_ctxmod()
    benchv2 = gb.load_benchv2()
    recipe = gb.load_recipe(profile_id)

    block = recipe.get("context") or {}
    if not force and block.get("ctx_ladder", {}).get("rungs"):
        return {
            "profile_id": profile_id,
            "status": "skipped",
            "reason": "ctx_ladder already present (use --force)",
            "ctx_ladder": block["ctx_ladder"],
        }

    golden, kv = gb.golden_ctx_and_kv(recipe, ctxmod)
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
        log(f"--- rung ctx={ctx} fill~{gb.fill_target_for_ctx(ctx, fill_ratio=fill_ratio)} ---")
        row = gb.probe_cell(
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

    recipe = gb.load_recipe(profile_id)
    block = recipe.setdefault("context", {})
    block["native"] = native
    ladder_doc = {
        "version": "1.0",
        "tested_at": report["finished_at"],
        "golden_ctx": golden,
        "native_ctx": native,
        "fill_ratio": fill_ratio,
        "kv": kv,
        "max_viable_ctx": max_viable,
        "rungs": report["results"],
    }
    block["ctx_ladder"] = ladder_doc
    gb.save_recipe(profile_id, recipe)
    gb.merge_bench_matrix(profile_id, ctx_ladder=ladder_doc, fill_ratio=fill_ratio)
    log(f"saved ctx_ladder; max_viable_ctx={max_viable}")

    gb.run_cmd(["/usr/local/bin/spark", "models", "inventory"], timeout=300)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Context ladder viability + tok/s probe")
    parser.add_argument("profile_id", help="Golden recipe profile id")
    parser.add_argument("--dry-run", action="store_true", help="Plan rungs only")
    parser.add_argument("--include-golden", action="store_true", help="Re-test golden ctx rung")
    parser.add_argument("--continue-on-fail", action="store_true", help="Keep climbing after failure")
    parser.add_argument("--force", action="store_true", help="Re-run even if ctx_ladder exists")
    parser.add_argument("--fill-ratio", type=float, default=None, help="Usable ctx fill fraction (default 0.75)")
    args = parser.parse_args()

    gb = _load_golden_bench()
    fill_ratio = args.fill_ratio if args.fill_ratio is not None else gb.FILL_RATIO

    report = run_ladder(
        args.profile_id,
        dry_run=args.dry_run,
        include_golden=args.include_golden,
        stop_on_fail=not args.continue_on_fail,
        fill_ratio=fill_ratio,
        force=args.force,
    )
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"ok": True, "max_viable_ctx": report.get("max_viable_ctx"), "report": str(REPORT_FILE)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
