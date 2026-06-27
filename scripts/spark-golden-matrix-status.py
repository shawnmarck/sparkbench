#!/opt/spark/venv/bin/python3
"""Report golden-workflow bench matrix completeness per model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path("/opt/spark")
GOLDEN = ROOT / "data/golden-recipes.yaml"
RECIPES = ROOT / "recipes"
SKIP = {"0xsero/deepseek-v4-flash-spark"}


def load_golden() -> dict[str, str]:
    data = yaml.safe_load(GOLDEN.read_text()) or {}
    return dict(data.get("golden") or {})


def layer_status(recipe: dict) -> dict[str, str]:
    ctx = recipe.get("context") or {}
    matrix = ctx.get("bench_matrix") or {}
    golden_cell = matrix.get("golden_cell") or {}
    kv = ctx.get("kv_sweep") or matrix.get("kv_sweep")
    ladder = ctx.get("ctx_ladder") or matrix.get("ctx_ladder")

    g = "ok" if golden_cell.get("tok_s") or recipe.get("lifecycle") == "works" else "missing"
    if isinstance(kv, dict) and kv.get("results"):
        kv_s = "ok" if any(r.get("status") == "ok" for r in kv["results"]) else "partial"
    elif isinstance(kv, list) and kv:
        kv_s = "ok"
    else:
        kv_s = "missing"

    if isinstance(ladder, dict) and ladder.get("rungs"):
        ladder_s = "ok" if ladder.get("max_viable_ctx") else "partial"
    else:
        presets = (ctx.get("presets") or {}).get("golden") or {}
        native = ctx.get("native") or 0
        gctx = presets.get("ctx") or ctx.get("default") or 0
        ladder_s = "skip" if native and gctx and int(native) <= int(gctx) * 1.1 else "missing"

    return {"golden": g, "kv_sweep": kv_s, "ctx_ladder": ladder_s}


def main() -> int:
    as_json = "--json" in sys.argv
    rows = []
    for inv, prof in sorted(load_golden().items()):
        if inv in SKIP:
            continue
        path = RECIPES / f"{prof}.yaml"
        if not path.is_file():
            rows.append({"inventory": inv, "profile": prof, "status": "no_recipe"})
            continue
        recipe = yaml.safe_load(path.read_text()) or {}
        layers = layer_status(recipe)
        complete = layers["golden"] == "ok" and layers["kv_sweep"] in ("ok", "skip") and layers["ctx_ladder"] in ("ok", "skip")
        rows.append(
            {
                "inventory": inv,
                "profile": prof,
                "layers": layers,
                "complete": complete,
            }
        )

    if as_json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"{'Model':<45} {'Profile':<40} {'Golden':<8} {'KV':<8} {'Ladder':<8} {'OK'}")
    print("-" * 120)
    ok = 0
    for r in rows:
        if "layers" not in r:
            print(f"{r['inventory']:<45} {r.get('profile',''):<40} {'—':<8} {'—':<8} {'—':<8} no_recipe")
            continue
        L = r["layers"]
        mark = "✓" if r["complete"] else ""
        if r["complete"]:
            ok += 1
        print(
            f"{r['inventory']:<45} {r['profile']:<40} {L['golden']:<8} {L['kv_sweep']:<8} {L['ctx_ladder']:<8} {mark}"
        )
    print(f"\n{ok}/{len(rows)} complete")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
