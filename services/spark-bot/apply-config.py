#!/usr/bin/env python3
"""Preservation-safe deep merge for the host-local Hermes config."""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def load_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SystemExit(f"{path} must contain a YAML mapping")
    return value


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    args = parser.parse_args()

    current = load_mapping(args.config)
    overlay = load_mapping(args.overlay)
    merged = deep_merge(current, overlay)
    args.config.parent.mkdir(parents=True, exist_ok=True)
    if args.config.is_file():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(args.config, args.config.with_name(f"{args.config.name}.bak.{stamp}"))
    temporary = args.config.with_suffix(".tmp")
    temporary.write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(args.config)
    print(f"merged operator config into {args.config}")


if __name__ == "__main__":
    main()
