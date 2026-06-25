#!/usr/bin/env python3
"""Deep-merge spark-bot config overlay into Hermes config.yaml."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def deep_merge(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--base", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.overlay.exists():
        print(f"overlay not found: {args.overlay}", file=sys.stderr)
        return 1

    if args.config.exists():
        with args.config.open() as f:
            config = yaml.safe_load(f) or {}
    elif args.base and args.base.exists():
        with args.base.open() as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    with args.overlay.open() as f:
        overlay = yaml.safe_load(f) or {}

    merged = deep_merge(config, overlay)

    if args.dry_run:
        print(yaml.dump(merged, default_flow_style=False, sort_keys=False))
        return 0

    args.config.parent.mkdir(parents=True, exist_ok=True)
    if args.config.exists():
        backup = args.config.with_suffix(".yaml.bak")
        backup.write_text(args.config.read_text())
        print(f"backup: {backup}")

    with args.config.open("w") as f:
        yaml.dump(merged, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    print(f"merged overlay into {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())