#!/opt/spark/venv/bin/python3
"""Roll up recipe bench_matrix + benchmaster intel into data/benchmaster-results.yaml."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
RECIPES = ROOT / "recipes"
DRAFTS = RECIPES / "drafts"
OUT = ROOT / "data" / "benchmaster-results.yaml"
RUNS = ROOT / "run" / "benchmaster" / "runs"


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def infer_quant(profile_id: str, recipe: dict[str, Any]) -> str:
    if recipe.get("quant"):
        return str(recipe["quant"])
    tags = [str(t).lower() for t in (recipe.get("tags") or [])]
    for tag in ("nvfp4", "fp8", "q8", "q4", "gguf", "llama"):
        if tag in tags or tag in profile_id.lower():
            return tag
    if "llama" in profile_id or recipe.get("engine") == "llamacpp":
        return "q8_0"
    return ""


def perf_from_recipe(recipe: dict[str, Any]) -> dict[str, Any] | None:
    block = (recipe.get("context") or {}).get("bench_matrix")
    if not block:
        return None
    perf: dict[str, Any] = {
        "fill_ratio": block.get("fill_ratio"),
        "updated_at": block.get("updated_at"),
    }
    if block.get("golden_cell"):
        perf["golden_cell"] = block["golden_cell"]
    if block.get("kv_sweep"):
        perf["kv_sweep"] = block["kv_sweep"]
    if block.get("ctx_ladder"):
        perf["ctx_ladder"] = block["ctx_ladder"]
    return perf


def intel_from_runs(profile_id: str) -> dict[str, Any] | None:
    if not RUNS.is_dir():
        return None
    best_by_harness: dict[str, dict[str, Any]] = {}
    for run_dir in sorted(RUNS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        result_path = run_dir / "intel-result.json"
        if not result_path.is_file():
            continue
        row = json.loads(result_path.read_text())
        if str(row.get("profile_id") or "") != profile_id:
            continue
        harness = str(row.get("harness") or "terminal-bench@2.1")
        key = harness.split("@")[0]
        total = int(row.get("total") or 0)
        prev = best_by_harness.get(key)
        if prev is None or total >= int(prev.get("total") or 0):
            best_by_harness[key] = row
    if not best_by_harness:
        return None
    intel: dict[str, Any] = {}
    for key, best in best_by_harness.items():
        harness = str(best.get("harness") or "terminal-bench@2.1")
        version = harness.split("@")[-1] if "@" in harness else harness
        intel[key] = {
            "version": version,
            "harness": harness,
            "agent": best.get("agent"),
            "worker_id": best.get("worker_id"),
            "pass_rate": best.get("pass_rate"),
            "passed": best.get("passed"),
            "total": best.get("total"),
            "reward_mean": best.get("reward_mean"),
            "task_ok": best.get("task_ok"),
            "measured_at": best.get("measured_at"),
            "job_id": best.get("job_id"),
        }
    return intel


def collect_recipes() -> list[tuple[Path, dict[str, Any]]]:
    rows: list[tuple[Path, dict[str, Any]]] = []
    for base in (DRAFTS, RECIPES):
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.yaml")):
            if path.is_file():
                rows.append((path, load_yaml(path)))
    return rows


def rollup(*, merge_existing: bool = True) -> dict[str, Any]:
    existing = load_yaml(OUT) if merge_existing and OUT.is_file() else {}
    data: dict[str, Any] = {
        "version": "1.0",
        "updated_at": existing.get("updated_at"),
        "models": dict(existing.get("models") or {}),
    }
    models = data["models"]

    for path, recipe in collect_recipes():
        profile_id = str(recipe.get("id") or path.stem)
        inventory = str(recipe.get("inventory_path") or profile_id)
        perf = perf_from_recipe(recipe)
        intel = intel_from_runs(profile_id)
        if not perf and not intel:
            continue

        block = models.setdefault(inventory, {"inventory_path": inventory, "quants": []})
        quants: list[dict[str, Any]] = block.setdefault("quants", [])

        entry: dict[str, Any] = {
            "quant": infer_quant(profile_id, recipe),
            "profile_id": profile_id,
            "engine": recipe.get("engine"),
            "lifecycle": recipe.get("lifecycle"),
        }
        if perf:
            entry["perf"] = perf
        if intel:
            entry["intel"] = intel

        replaced = False
        for idx, row in enumerate(quants):
            if str(row.get("profile_id")) == profile_id:
                merged = dict(row)
                if perf:
                    merged["perf"] = perf
                if intel:
                    merged["intel"] = {**(row.get("intel") or {}), **intel}
                merged.update({k: v for k, v in entry.items() if k not in ("perf", "intel")})
                quants[idx] = merged
                replaced = True
                break
        if not replaced:
            quants.append(entry)

        quants.sort(key=lambda r: str(r.get("profile_id") or ""))

    from datetime import datetime, timezone

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Roll up benchmaster perf/intel results")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    data = rollup()
    save_yaml(args.out, data)
    if args.json:
        import json as json_mod

        print(json_mod.dumps(data, indent=2))
    else:
        print(f"wrote {args.out} ({len(data.get('models') or {})} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
