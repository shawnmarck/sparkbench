#!/opt/spark/venv/bin/python3
"""Backfill site headlines from recipes/*/bench_matrix.golden_cell."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path("/opt/spark")

# Import sibling module without package layout.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "site_publish", ROOT / "scripts" / "spark-site-publish.py"
)
_sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sp)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish golden_cell metrics to model-verification + inference-benchmarks"
    )
    parser.add_argument("--all", action="store_true", help="All golden-recipes.yaml entries")
    parser.add_argument("--only", help="Comma-separated inventory paths or profile ids")
    parser.add_argument("--profile", help="Single golden profile id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Republish even if headline looks current")
    args = parser.parse_args()

    if args.profile:
        report = _sp.publish_from_profile(
            args.profile, dry_run=args.dry_run, force=args.force
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("published") or report.get("reason") == "already_current" else 1

    only: set[str] | None = None
    if args.only:
        only = {x.strip() for x in args.only.split(",") if x.strip()}

    if not args.all and not only:
        parser.error("use --all, --only, or --profile")

    report = _sp.publish_all_golden(dry_run=args.dry_run, force=args.force, only=only)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    if report.get("results"):
        for row in report["results"]:
            status = "PUB" if row.get("published") else row.get("reason", "?")
            print(f"  {row.get('inventory_path') or row.get('profile_id')}: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
