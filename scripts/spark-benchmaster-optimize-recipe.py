#!/opt/spark/venv/bin/python3
"""After perf_sweep, pick best ctx/kv from bench_matrix and write optimal preset."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
RECIPES = ROOT / "recipes" / "drafts"


def load_recipe(profile_id: str) -> tuple[Path, dict[str, Any]]:
    for base in (RECIPES, ROOT / "recipes"):
        path = base / f"{profile_id}.yaml"
        if path.is_file():
            return path, yaml.safe_load(path.read_text()) or {}
    raise SystemExit(f"recipe not found: {profile_id}")


def best_rung(recipe: dict[str, Any]) -> dict[str, Any] | None:
    bm = (recipe.get("context") or {}).get("bench_matrix") or {}
    ladder = bm.get("ctx_ladder") or {}
    rungs = ladder.get("rungs") or []
    ok = [r for r in rungs if r.get("status") == "ok" and r.get("tok_s")]
    if not ok:
        cell = bm.get("golden_cell")
        return cell if cell and cell.get("status") == "ok" else None
    return max(ok, key=lambda r: float(r["tok_s"]))


def apply_optimal(profile_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    path, recipe = load_recipe(profile_id)
    best = best_rung(recipe)
    if not best:
        raise SystemExit("no successful bench cells in bench_matrix")

    ctx = int(best["ctx"])
    kv = str(best.get("kv") or "q8_0")
    tok_s = float(best["tok_s"])

    block = recipe.setdefault("context", {})
    presets = block.setdefault("presets", {})
    presets["golden"] = {
        "label": f"Optimal from bench ({tok_s:.1f} tok/s @ {ctx})",
        "ctx": ctx,
        "kv": kv,
    }
    presets["optimal"] = dict(presets["golden"])
    block["default"] = ctx
    block["kv_default"] = kv

    notes = str(recipe.get("notes") or "")
    tag = f"Optimal preset: ctx={ctx} kv={kv} tok_s={tok_s:.1f} (bench v2)."
    if tag not in notes:
        recipe["notes"] = (notes.rstrip() + "\n" + tag).strip()

    out = {
        "profile_id": profile_id,
        "optimal_ctx": ctx,
        "optimal_kv": kv,
        "tok_s": tok_s,
        "source": "ctx_ladder" if (block.get("bench_matrix") or {}).get("ctx_ladder") else "golden_cell",
    }
    if dry_run:
        print(yaml.safe_dump(out, sort_keys=False))
        return out

    path.write_text(yaml.safe_dump(recipe, sort_keys=False, default_flow_style=False))
    print(yaml.safe_dump(out, sort_keys=False))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Set optimal golden preset from bench_matrix")
    p.add_argument("profile_id")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    apply_optimal(args.profile_id, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
