#!/opt/spark/venv/bin/python3
"""Download golden-variant model weights from Hugging Face to /models."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
MODELS = Path("/models")
HF = ROOT / "venv/bin/hf"
GOLDEN_FILE = ROOT / "data/golden-recipes.yaml"
CATALOG_FILE = ROOT / "data/model-catalog.yaml"
RECIPES = ROOT / "recipes"
LOG_FILE = ROOT / "logs/models-fetch-latest.log"
PID_FILE = ROOT / "run/models-fetch.pid"


def log(msg: str) -> None:
    line = f"[{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_yaml(path: Path) -> Any:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def load_golden_map() -> dict[str, str]:
    data = load_yaml(GOLDEN_FILE)
    return {str(k): str(v) for k, v in (data.get("golden") or {}).items()}


def catalog_by_rel() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entry in load_yaml(CATALOG_FILE).get("models") or []:
        if not isinstance(entry, dict):
            continue
        lab = entry.get("lab")
        slug = entry.get("slug")
        if lab and slug:
            out[f"{lab}/{slug}"] = entry
    return out


def load_recipe(profile_id: str) -> dict[str, Any]:
    path = RECIPES / f"{profile_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no recipe: {profile_id}")
    return yaml.safe_load(path.read_text()) or {}


def normalize_inv(path: str) -> str:
    return path.strip().strip("/")


def parse_model_path(model_path: str, inventory_path: str) -> tuple[str, str | None]:
    """Return (subpath under inventory, optional single filename)."""
    prefix = f"/models/{inventory_path}/"
    p = model_path.replace("\\", "/")
    if not p.startswith(prefix):
        raise ValueError(f"recipe model path not under {prefix}: {model_path}")
    rel = p[len(prefix) :]
    parts = Path(rel).parts
    if not parts:
        raise ValueError("empty model path")
    if rel.endswith(".gguf") or rel.endswith(".safetensors"):
        return str(Path(*parts[:-1])) if len(parts) > 1 else ".", parts[-1]
    return rel.rstrip("/"), None


def match_variant(catalog: dict, subpath: str, engine: str, filename: str | None) -> dict | None:
    variants = catalog.get("variants") or []
    subpath = subpath.strip("/") or "."
    best = None
    for v in variants:
        if not isinstance(v, dict):
            continue
        vsub = (v.get("subpath") or "").strip("/")
        if vsub != subpath.strip("/"):
            continue
        if engine and v.get("engine") and v.get("engine") != engine:
            continue
        note = str(v.get("note") or "")
        if filename and note and filename not in note and not note.endswith(filename):
            continue
        best = v
        if filename and filename in note:
            return v
    if best:
        return best
    # fallback: engine match only
    for v in variants:
        if isinstance(v, dict) and v.get("engine") == engine:
            return v
    return variants[0] if variants else None


def resolve_plan(inventory_path: str, *, variant_subpath: str | None = None) -> dict[str, Any]:
    inventory_path = normalize_inv(inventory_path)
    golden = load_golden_map()
    profile_id = golden.get(inventory_path)
    if not profile_id:
        raise SystemExit(f"no golden profile for {inventory_path} (see data/golden-recipes.yaml)")

    recipe = load_recipe(profile_id)
    catalog = catalog_by_rel().get(inventory_path)
    if not catalog:
        raise SystemExit(f"no catalog entry for {inventory_path}")

    engine = str(recipe.get("engine") or "")
    model_path = str(recipe.get("model") or "")
    if not model_path:
        raise SystemExit(f"recipe {profile_id} has no model path")

    if variant_subpath:
        subpath = variant_subpath.strip("/")
        filename = None
    else:
        subpath, filename = parse_model_path(model_path, inventory_path)

    variant = match_variant(catalog, subpath, engine, filename)
    hf_repo = (variant or {}).get("hf_repo") or catalog.get("hf_repo")
    if not hf_repo:
        raise SystemExit(f"no hf_repo for {inventory_path}")

    dest = MODELS / inventory_path / subpath if subpath != "." else MODELS / inventory_path
    plan: dict[str, Any] = {
        "inventory_path": inventory_path,
        "golden_profile": profile_id,
        "engine": engine,
        "hf_repo": hf_repo,
        "dest": str(dest),
        "subpath": subpath,
    }

    if filename:
        plan["mode"] = "files"
        plan["files"] = [filename]
    elif engine == "llamacpp" and subpath.endswith(".gguf"):
        plan["mode"] = "files"
        plan["files"] = [Path(subpath).name]
        plan["dest"] = str(MODELS / inventory_path / Path(subpath).parent)
    else:
        plan["mode"] = "repo"

    return plan


def run_plan(plan: dict[str, Any], *, dry_run: bool = False) -> int:
    if not HF.is_file():
        raise SystemExit(f"hf CLI not found: {HF}")

    if plan["mode"] == "files":
        cmd = [str(HF), "download", plan["hf_repo"], *plan["files"], "--local-dir", plan["dest"]]
    else:
        cmd = [str(HF), "download", plan["hf_repo"], "--local-dir", plan["dest"]]

    log(f"PLAN {json.dumps(plan)}")
    if dry_run:
        print("DRY-RUN:", " ".join(cmd))
        return 0

    Path(plan["dest"]).mkdir(parents=True, exist_ok=True)
    log(f"RUN {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode == 0:
        subprocess.run(["/usr/local/bin/spark", "models", "inventory"], cwd=str(ROOT), check=False)
    return proc.returncode


def run_background(inventory_path: str, extra_argv: list[str]) -> int:
    if PID_FILE.is_file():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid > 0 and Path(f"/proc/{pid}").exists():
                print(f"fetch already running pid={pid}", file=sys.stderr)
                return 1
        except ValueError:
            pass

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("w", encoding="utf-8") as fh:
        fh.write(f"=== models fetch {inventory_path} ===\n")

    cmd = [str(ROOT / "scripts/spark-models-fetch.py"), inventory_path, *extra_argv]
    proc = subprocess.Popen(
        cmd,
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))
    print(f"Started background fetch pid={proc.pid}")
    print(f"Log: {LOG_FILE}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch golden model weights from Hugging Face")
    parser.add_argument("inventory_path", nargs="?", help="lab/slug")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--variant", help="Catalog variant subpath override (e.g. gguf)")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.status:
        if PID_FILE.is_file():
            pid = PID_FILE.read_text().strip()
            print(f"pid={pid}")
            if LOG_FILE.is_file():
                print(LOG_FILE.read_text()[-2000:])
        else:
            print("no fetch running")
        return 0

    if not args.inventory_path:
        parser.error("inventory_path required")

    inv = normalize_inv(args.inventory_path)
    if args.background:
        extra = []
        if args.dry_run:
            extra.append("--dry-run")
        if args.variant:
            extra.extend(["--variant", args.variant])
        return run_background(inv, extra)

    plan = resolve_plan(inv, variant_subpath=args.variant)
    print(json.dumps(plan, indent=2))
    rc = run_plan(plan, dry_run=args.dry_run)
    if PID_FILE.is_file():
        PID_FILE.unlink(missing_ok=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
