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


def _load_golden_bench():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "golden_bench", ROOT / "scripts" / "spark-golden-bench.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def layer_status(recipe: dict, *, inventory_path: str) -> dict[str, str]:
    ctx = recipe.get("context") or {}
    matrix = ctx.get("bench_matrix") or {}
    golden_cell = matrix.get("golden_cell") or {}
    kv = ctx.get("kv_sweep") or matrix.get("kv_sweep")
    ladder = ctx.get("ctx_ladder") or matrix.get("ctx_ladder")

    g = "ok" if golden_cell.get("tok_s") or recipe.get("lifecycle") == "works" else "missing"
    gb = _load_golden_bench()
    if not gb.kv_sweep_eligible(recipe, inventory_path=inventory_path):
        kv_s = "skip"
    elif isinstance(kv, dict) and kv.get("results"):
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


def fmt_ctx(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1_048_576:
        return f"{n // 1024}k" if n % 1024 == 0 else str(n)
    if n >= 1024:
        return f"{n // 1024}k"
    return str(n)


def fmt_golden(recipe: dict) -> str:
    ctx = recipe.get("context") or {}
    g = (ctx.get("presets") or {}).get("golden") or {}
    cell = (ctx.get("bench_matrix") or {}).get("golden_cell") or {}
    c = g.get("ctx") or cell.get("ctx")
    k = g.get("kv") or cell.get("kv")
    t = cell.get("tok_s")
    if not c:
        return "—"
    out = f"{fmt_ctx(int(c))}/{k}"
    if t:
        out += f" {t}t/s"
    return out


def fmt_ladder_detail(recipe: dict) -> str:
    ctx = recipe.get("context") or {}
    lad = ctx.get("ctx_ladder") or (ctx.get("bench_matrix") or {}).get("ctx_ladder")
    nat = ctx.get("native")
    gctx = (ctx.get("presets") or {}).get("golden", {}).get("ctx") or ctx.get("default")
    if not isinstance(lad, dict) or not lad.get("rungs"):
        if nat and gctx and int(nat) <= int(gctx) * 1.1:
            return f"skip (native {fmt_ctx(int(nat))} ≤ golden {fmt_ctx(int(gctx))})"
        return "not run"
    parts = []
    maxv = lad.get("max_viable_ctx")
    if maxv:
        parts.append(f"max={fmt_ctx(int(maxv))}")
    for r in lad.get("rungs") or []:
        bit = f"{fmt_ctx(int(r['ctx']))}:{r.get('status', '?')}"
        if r.get("tok_s"):
            bit += f"@{r['tok_s']}t/s"
        parts.append(bit)
    return " | ".join(parts)


def fmt_kv_detail(recipe: dict, *, inventory_path: str) -> str:
    gb = _load_golden_bench()
    if not gb.kv_sweep_eligible(recipe, inventory_path=inventory_path):
        return "n/a"
    ctx = recipe.get("context") or {}
    ks = ctx.get("kv_sweep") or {}
    res = ks.get("results") if isinstance(ks, dict) else None
    if not res:
        return "—"
    parts = []
    for r in res:
        bit = f"{r.get('kv')}@{fmt_ctx(int(r.get('ctx') or 0))}:{r.get('status', '?')[:4]}"
        if r.get("tok_s"):
            bit += f" {r['tok_s']}t/s"
        parts.append(bit)
    return " | ".join(parts)


def load_golden() -> dict[str, str]:
    data = yaml.safe_load(GOLDEN.read_text()) or {}
    return dict(data.get("golden") or {})


def main() -> int:
    as_json = "--json" in sys.argv
    wide = "--wide" in sys.argv
    report_path = ROOT / "run/golden-workflow-report.json"
    fleet: dict[str, dict] = {}
    if report_path.is_file():
        data = json.loads(report_path.read_text())
        fleet = {m["inventory_path"]: m for m in data.get("models") or []}

    rows = []
    for inv, prof in sorted(load_golden().items()):
        if inv in SKIP:
            continue
        path = RECIPES / f"{prof}.yaml"
        if not path.is_file():
            rows.append({"inventory": inv, "profile": prof, "status": "no_recipe"})
            continue
        recipe = yaml.safe_load(path.read_text()) or {}
        layers = layer_status(recipe, inventory_path=inv)
        complete = layers["golden"] == "ok" and layers["kv_sweep"] in ("ok", "skip") and layers["ctx_ladder"] in ("ok", "skip")
        ctx = recipe.get("context") or {}
        row = {
            "inventory": inv,
            "profile": prof,
            "layers": layers,
            "complete": complete,
            "golden": fmt_golden(recipe),
            "native": fmt_ctx(ctx.get("native")),
            "ladder_detail": fmt_ladder_detail(recipe),
            "kv_detail": fmt_kv_detail(recipe, inventory_path=inv),
            "fleet": fleet.get(inv, {}).get("status", "pending"),
        }
        rows.append(row)

    if as_json:
        print(json.dumps(rows, indent=2))
        return 0

    if wide:
        print(
            f"{'Model':<38} {'Fleet':<8} {'Golden':<16} {'Native':<8} "
            f"{'Ctx ladder (each rung)':<52} {'KV sweep'}"
        )
        print("=" * 180)
        ok = 0
        for r in rows:
            if "layers" not in r:
                print(f"{r['inventory']:<38} no_recipe")
                continue
            mark = "✓" if r["complete"] else ""
            if r["complete"]:
                ok += 1
            print(
                f"{r['inventory']:<38} {r['fleet']:<8} {r['golden']:<16} {r['native']:<8} "
                f"{r['ladder_detail']:<52} {r['kv_detail']} {mark}"
            )
        print(f"\n{ok}/{len(rows)} matrix-complete")
        if fleet:
            s = json.loads(report_path.read_text()).get("summary") or {}
            print(f"Fleet report: {s.get('complete', 0)} complete, {s.get('partial', 0)} partial, {s.get('failed', 0)} failed")
        return 0 if ok == len(rows) else 1

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
