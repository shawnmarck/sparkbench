#!/opt/spark/venv/bin/python3
"""KV sweep — bench golden ctx at each supported KV quant (75% fill, decode tok/s)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/spark")
LOG_FILE = ROOT / "logs" / "kv-sweep.log"
REPORT_FILE = ROOT / "run" / "kv-sweep-report.json"


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


def run_kv_sweep(
    profile_id: str,
    *,
    dry_run: bool = False,
    fill_ratio: float | None = None,
    force: bool = False,
) -> dict[str, Any]:
    gb = _load_golden_bench()
    fill_ratio = fill_ratio if fill_ratio is not None else gb.FILL_RATIO
    ctxmod = gb.load_ctxmod()
    benchv2 = gb.load_benchv2()
    recipe = gb.load_recipe(profile_id)
    golden_ctx, golden_kv = gb.golden_ctx_and_kv(recipe, ctxmod)
    kvs = gb.kv_sweep_options(recipe)

    report: dict[str, Any] = {
        "profile_id": profile_id,
        "inventory_path": recipe.get("inventory_path"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "golden_ctx": golden_ctx,
        "golden_kv": golden_kv,
        "fill_ratio": fill_ratio,
        "kvs_planned": kvs,
        "results": [],
    }

    block = recipe.get("context") or {}
    if not force and block.get("kv_sweep", {}).get("results"):
        prior = block["kv_sweep"]
        report["status"] = "skipped"
        report["reason"] = "kv_sweep already present (use --force)"
        report["results"] = prior.get("results") or []
        return report

    if not gb.kv_sweep_eligible(recipe, inventory_path=recipe.get("inventory_path")):
        reason = gb.kv_sweep_skip_reason(recipe, inventory_path=recipe.get("inventory_path"))
        report["status"] = "skipped"
        report["reason"] = reason
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        log(f"skip kv sweep {profile_id}: {reason}")
        return report

    log(f"=== kv sweep {profile_id} ctx={golden_ctx} kvs={kvs} ===")

    if dry_run:
        report["dry_run"] = True
        report["status"] = "dry_run"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report

    results: list[dict[str, Any]] = []
    for kv in kvs:
        log(f"--- kv={kv} ctx={golden_ctx} fill~{gb.fill_target_for_ctx(golden_ctx, fill_ratio=fill_ratio)} ---")
        row = gb.probe_cell(
            profile_id,
            recipe,
            ctx=golden_ctx,
            kv=kv,
            fill_ratio=fill_ratio,
            benchv2=benchv2,
        )
        results.append(row)
        log(f"kv={kv} status={row['status']} tok_s={row.get('tok_s')}")

    ok = sum(1 for r in results if r.get("status") == "ok")
    report["results"] = results
    report["status"] = "ok" if ok else "failed"
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    recipe = gb.load_recipe(profile_id)
    block = recipe.setdefault("context", {})
    block["kv_sweep"] = {
        "version": "1.0",
        "tested_at": report["finished_at"],
        "golden_ctx": golden_ctx,
        "fill_ratio": fill_ratio,
        "results": results,
    }
    gb.save_recipe(profile_id, recipe)
    gb.merge_bench_matrix(profile_id, kv_sweep=results, fill_ratio=fill_ratio)
    log(f"saved kv_sweep ({ok}/{len(results)} ok)")

    gb.run_cmd(["/usr/local/bin/spark", "models", "inventory"], timeout=300)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="KV cache sweep at golden ctx")
    parser.add_argument("profile_id", help="Golden recipe profile id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-run even if kv_sweep exists")
    parser.add_argument("--fill-ratio", type=float, default=None)
    args = parser.parse_args()

    report = run_kv_sweep(
        args.profile_id,
        dry_run=args.dry_run,
        fill_ratio=args.fill_ratio,
        force=args.force,
    )
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"ok": report.get("status") in ("ok", "skipped", "dry_run"), "report": str(REPORT_FILE)}, indent=2))
    return 0 if report.get("status") in ("ok", "skipped", "dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
