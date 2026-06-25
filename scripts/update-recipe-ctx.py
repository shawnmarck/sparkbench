#!/usr/bin/env python3
"""Update recipe + eugr service after ctx viability test."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path("/opt/spark")
RECIPES = ROOT / "recipes"


def update(profile_id: str, ctx: int, *, preset_label: str, note: str) -> None:
    recipe_path = RECIPES / f"{profile_id}.yaml"
    if not recipe_path.is_file():
        raise SystemExit(f"missing recipe: {recipe_path}")

    recipe = yaml.safe_load(recipe_path.read_text()) or {}
    native = int((recipe.get("context") or {}).get("native") or ctx)
    # refresh native from HF if still stale at 16k
    if native <= 16384:
        inv = str(recipe.get("inventory_path") or "")
        cfg_path = Path(f"/models/{inv}/hf/config.json")
        if cfg_path.is_file():
            import json

            cfg = json.loads(cfg_path.read_text())
            for src in (cfg, cfg.get("text_config") or {}):
                if isinstance(src, dict):
                    for key in ("max_position_embeddings", "max_seq_len"):
                        val = src.get(key)
                        if isinstance(val, (int, float)) and val > native:
                            native = int(val)

    block = recipe.setdefault("context", {})
    block["default"] = ctx
    block["native"] = native
    block["kv_default"] = "fp8"
    block.setdefault("presets", {})
    block["presets"]["golden"] = {
        "label": preset_label,
        "ctx": ctx,
        "kv": "fp8",
    }
    block["presets"]["long"] = {
        "label": f"Long ctx (viability {ctx // 1024}k)",
        "ctx": ctx,
        "kv": "fp8",
    }
    stamp = datetime.now(timezone.utc).isoformat()
    notes = str(recipe.get("notes") or "")
    recipe["notes"] = f"{notes.rstrip()} Viability ctx {ctx} verified {stamp[:10]}. {note}".strip()
    recipe_path.write_text(yaml.safe_dump(recipe, sort_keys=False, default_flow_style=False))

    eugr_path = recipe.get("eugr_recipe")
    if eugr_path:
        ep = Path(str(eugr_path))
        if ep.is_file():
            eugr = yaml.safe_load(ep.read_text()) or {}
            eugr.setdefault("defaults", {})["max_model_len"] = ctx
            cmd = str(eugr.get("command") or "")
            if "--kv-cache-dtype auto" in cmd:
                cmd = cmd.replace("--kv-cache-dtype auto", "--kv-cache-dtype fp8")
            elif "--kv-cache-dtype fp8" not in cmd and "kv-cache-dtype" not in cmd:
                cmd = cmd.replace(
                    "--trust-remote-code \\",
                    "--trust-remote-code \\\n    --kv-cache-dtype fp8 \\",
                )
            eugr["command"] = cmd
            ep.write_text(yaml.safe_dump(eugr, sort_keys=False, default_flow_style=False))
            print(f"updated eugr defaults max_model_len={ctx}: {ep}")

    print(f"updated recipe ctx default/golden={ctx} native={native}: {recipe_path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("profile_id")
    p.add_argument("ctx", type=int)
    p.add_argument("--label", default="Golden max fit")
    p.add_argument("--note", default="")
    args = p.parse_args()
    update(args.profile_id, args.ctx, preset_label=args.label, note=args.note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
