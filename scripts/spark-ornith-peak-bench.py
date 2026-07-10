#!/opt/spark/venv/bin/python3
"""Run batman_spark peak bench (~200k/slot, 3 parallel) and persist peak_cell."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path("/opt/spark")


def _load_golden_bench():
    spec = importlib.util.spec_from_file_location(
        "golden_bench", ROOT / "scripts" / "spark-golden-bench.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    parser = argparse.ArgumentParser(description="Batman DGX Spark peak bench")
    parser.add_argument("profile_id")
    parser.add_argument("--preset", default="batman_spark")
    parser.add_argument("--leave-up", action="store_true", help="Keep inference running after bench")
    args = parser.parse_args()

    gb = _load_golden_bench()
    recipe = gb.load_recipe(args.profile_id)
    row = gb.probe_peak_cell(args.profile_id, recipe, preset=args.preset)
    print(json.dumps(row, indent=2))
    if row.get("status") == "ok":
        gb.merge_bench_matrix(args.profile_id, peak_cell=row, skip_site_publish=True)
    if row.get("status") != "ok" and not args.leave_up:
        gb.run_cmd(["/usr/local/bin/spark", "inference", "down"], timeout=120)
    return 0 if row.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
