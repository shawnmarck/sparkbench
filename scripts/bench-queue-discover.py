#!/usr/bin/env python3
"""Discover models that need benchmarking on sparky.

Reads portal/models.json, recipe YAML, and inference-benchmark-history.yaml.
Emits one job per line:  <inventory_path> <eugr|llamacpp|eugr-dflash>

Modes (--mode):
  unbenched     — no best_bench_tok_s yet (default), plus unbenched DFlash profiles
  refire-import — already benched but history is import-only (pre-feature runs)
  sidecar       — DFlash sidecar profiles missing a benchmark only
  all           — unbenched first, then refire-import (deduped)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

MODELS_JSON = Path("/opt/spark/portal/models.json")
MODELS_ROOT = Path("/models")
RECIPES = Path("/opt/spark/recipes")
DRAFTS = RECIPES / "drafts"
HISTORY_FILE = Path("/opt/spark/run/inference-benchmark-history.yaml")
BENCHMARKS_FILE = Path("/opt/spark/data/inference-benchmarks.yaml")
CATALOG_FILE = Path("/opt/spark/data/model-catalog.yaml")
DS4_PIN_FILE = Path("/opt/spark/data/ds4-dwarfstar.yaml")
LLAMACPP_VARIANTS = Path("/opt/spark/config/llamacpp-variants.yaml")

VLLM_SUBDIRS = ("nvfp4", "fp8", "hf", "prismaquant")
VLLM_DFLASH_WEIGHT_ORDER = ("fp8", "hf", "prismaquant", "nvfp4")
AUX_ONLY = frozenset({"dflash"})
MIN_AUX_BYTES = 5 * 1024**3
# GGUF architectures not loadable by the default (stable) llama.cpp build.
# When llamacpp-variants.yaml adds a variant that lists an arch, discover can emit it.
STABLE_LLAMACPP_ARCHS = frozenset(
    {
        "llama",
        "llama4",
        "qwen2",
        "qwen3",
        "qwen3moe",
        "qwen35",
        "step35",
        "gemma",
        "gemma2",
        "gemma3",
        "phi3",
        "phi4",
        "deepseek2",
        "mistral",
        "mixtral",
        "command-r",
    }
)

_RUN = Path(__file__).resolve().parent
if str(_RUN) not in sys.path:
    sys.path.insert(0, str(_RUN))
from gguf_pick import GGUF_WEIGHT_SUBDIRS, pick_main_gguf_dir  # noqa: E402


def model_downloading(inv: str) -> bool:
    needles = (f"/models/{inv}", inv.replace("/", " "), inv.split("/", 1)[-1])
    try:
        out = subprocess.check_output(
            ["pgrep", "-af", "download"], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return False
    for line in out.splitlines():
        if "bench-queue" in line or "pgrep" in line:
            continue
        if not any(n in line for n in needles):
            continue
        if "hf download" in line or "spark-download" in line:
            return True
    return False


def pick_main_gguf(sub: Path) -> Path | None:
    return pick_main_gguf_dir(sub)


def gguf_architecture(path: Path) -> str | None:
    """Read general.architecture from GGUF metadata (stdlib only)."""
    import struct

    try:
        with path.open("rb") as f:
            if f.read(4) != b"GGUF":
                return None
            _version = struct.unpack("<I", f.read(4))[0]
            n_tensors = struct.unpack("<Q", f.read(8))[0]
            n_kv = struct.unpack("<Q", f.read(8))[0]
            for _ in range(n_kv):
                key_len = struct.unpack("<Q", f.read(8))[0]
                key = f.read(key_len).decode("utf-8", errors="replace")
                vtype = struct.unpack("<I", f.read(4))[0]
                if vtype == 8:  # string
                    vlen = struct.unpack("<Q", f.read(8))[0]
                    val = f.read(vlen).decode("utf-8", errors="replace")
                    if key == "general.architecture":
                        return val
                elif vtype in (0, 1, 2, 3, 4, 5, 6, 7, 10, 11):
                    _ = struct.unpack("<Q", f.read(8))[0]
                elif vtype == 9:  # array — skip
                    etype = struct.unpack("<I", f.read(4))[0]
                    alen = struct.unpack("<Q", f.read(8))[0]
                    for _ in range(alen):
                        if etype == 8:
                            slen = struct.unpack("<Q", f.read(8))[0]
                            f.read(slen)
                        else:
                            f.read(8 if etype not in (4, 5, 6) else (4 if etype == 4 else 8))
                else:
                    return None
            _ = n_tensors
    except (OSError, struct.error, UnicodeDecodeError, MemoryError):
        return None
    return None


def load_llamacpp_variant_archs() -> dict[str, frozenset[str]]:
    """variant_id -> supported GGUF architectures (from config when present)."""
    out: dict[str, frozenset[str]] = {"stable": STABLE_LLAMACPP_ARCHS}
    if not yaml or not LLAMACPP_VARIANTS.is_file():
        return out
    try:
        data = yaml.safe_load(LLAMACPP_VARIANTS.read_text()) or {}
    except OSError:
        return out
    for vid, spec in (data.get("variants") or {}).items():
        if not isinstance(spec, dict):
            continue
        archs = spec.get("architectures") or []
        if archs:
            out[str(vid)] = frozenset(str(a) for a in archs)
    return out


def llamacpp_variant_for_gguf(gguf: Path) -> str | None:
    arch = gguf_architecture(gguf)
    if not arch:
        return "stable"  # unknown — try default build
    variants = load_llamacpp_variant_archs()
    for vid, archs in variants.items():
        if arch in archs:
            return vid
    return None


def gguf_ready(sub: Path) -> bool:
    gguf = pick_main_gguf(sub)
    if gguf is None:
        return False
    return llamacpp_variant_for_gguf(gguf) is not None


def subdir_ready(root: Path, name: str) -> bool:
    sub = root / name
    if not sub.is_dir():
        return False
    if name in GGUF_WEIGHT_SUBDIRS:
        return gguf_ready(sub)
    if (sub / "config.json").is_file():
        return True
    return any(sub.glob("*.safetensors")) or any(sub.glob("*.gguf"))


def is_auxiliary_only(root: Path) -> bool:
    if not root.is_dir():
        return True
    subs = [p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not subs:
        return True
    if set(subs) <= AUX_ONLY:
        try:
            total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
        except OSError:
            total = 0
        return total < MIN_AUX_BYTES
    return False




def load_ds4_pin_inventory() -> str | None:
    if not yaml or not DS4_PIN_FILE.is_file():
        return None
    try:
        data = yaml.safe_load(DS4_PIN_FILE.read_text()) or {}
    except OSError:
        return None
    return (data.get("model") or {}).get("inventory_path")


def catalog_engine_for(inventory_path: str) -> str | None:
    if not yaml or not CATALOG_FILE.is_file():
        return None
    try:
        data = yaml.safe_load(CATALOG_FILE.read_text()) or {}
    except OSError:
        return None
    for entry in data.get("models") or []:
        if entry.get("id") != inventory_path:
            continue
        caps = set(entry.get("capabilities") or [])
        variants = entry.get("variants") or []
        var_engines = {v.get("engine") for v in variants if isinstance(v, dict)}
        if "ds4" in caps or "ds4" in var_engines:
            return "ds4"
        if "llamacpp" in caps or "gguf" in caps:
            return "llamacpp"
        for eng in ("eugr", "vllm", "explorer"):
            if eng in caps or eng in var_engines:
                return "eugr"
    return None


def pick_engine(root: Path, inventory_path: str | None = None) -> str | None:
    if inventory_path:
        pinned = load_ds4_pin_inventory()
        if pinned and inventory_path == pinned:
            gguf = root / "gguf"
            if gguf.is_dir() and any(gguf.glob("*.gguf")):
                return "ds4"
        cat_eng = catalog_engine_for(inventory_path)
        if cat_eng == "ds4":
            gguf = root / "gguf"
            if gguf.is_dir() and any(gguf.glob("*.gguf")):
                return "ds4"
    for sub in VLLM_SUBDIRS:
        if subdir_ready(root, sub):
            return "eugr"
    for sub in GGUF_WEIGHT_SUBDIRS:
        if subdir_ready(root, sub):
            return "llamacpp"
    return None


def load_recipe_profiles() -> dict[tuple[str, str], str]:
    """Map (inventory_path, engine) -> profile_id."""
    out: dict[tuple[str, str], str] = {}
    for path in sorted(DRAFTS.glob("*.yaml")) + sorted(RECIPES.glob("*.yaml")):
        if not yaml:
            break
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except OSError:
            continue
        pid = data.get("id")
        inv = data.get("inventory_path") or data.get("catalog_id")
        engine = data.get("engine")
        if not pid or not inv:
            continue
        if data.get("speculative"):
            out[(str(inv), "eugr-dflash")] = str(pid)
        elif engine:
            out.setdefault((str(inv), str(engine)), str(pid))
    return out


def sidecar_ready(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / "config.json").is_file() or any(path.glob("*.safetensors"))


def find_dflash_target(slug: str) -> str | None:
    best: str | None = None
    best_key = (99, 99)
    for lab_dir in sorted(MODELS_ROOT.iterdir()):
        if not lab_dir.is_dir() or lab_dir.name in ("z-lab", ".cache"):
            continue
        inv = f"{lab_dir.name}/{slug}"
        root = MODELS_ROOT / inv
        for fmt_idx, sub in enumerate(VLLM_DFLASH_WEIGHT_ORDER):
            if subdir_ready(root, sub):
                lab_pref = 0 if lab_dir.name == "qwen" else 1
                key = (lab_pref, fmt_idx)
                if key < best_key:
                    best_key = key
                    best = inv
                break
    return best


def dflash_target_weight_dir(inv: str) -> tuple[Path, str] | None:
    root = MODELS_ROOT / inv
    for sub in VLLM_DFLASH_WEIGHT_ORDER:
        model_dir = root / sub
        if subdir_ready(root, sub):
            return model_dir, sub
    return None


def dflash_pair_compatible(inv: str) -> bool:
    found = dflash_target_weight_dir(inv)
    if not found:
        return False
    model_dir, weight_format = found
    if weight_format != "nvfp4":
        return True
    cfg_path = model_dir / "config.json"
    if not cfg_path.is_file():
        return True
    try:
        cfg = json.loads(cfg_path.read_text())
    except (json.JSONDecodeError, OSError):
        return True
    model_type = str(cfg.get("model_type", "")).lower()
    if "moe" in model_type:
        return False
    archs = cfg.get("architectures") or []
    return not any("Moe" in str(a) for a in archs)


def recipe_speculative_blocked(profile_id: str) -> bool:
    if not yaml:
        return False
    for base in (DRAFTS, RECIPES):
        path = base / f"{profile_id}.yaml"
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except OSError:
            continue
        spec = data.get("speculative") or {}
        return bool(spec.get("blocked"))
    return False


def discover_dflash_sidecars() -> list[tuple[str, str]]:
    """Return (target_inventory, eugr-dflash) jobs for installed sidecars."""
    jobs: list[tuple[str, str]] = []
    zlab = MODELS_ROOT / "z-lab"
    if not zlab.is_dir():
        return jobs
    for sidecar in sorted(zlab.glob("*/dflash")):
        if not sidecar_ready(sidecar):
            continue
        slug = sidecar.parent.name
        target = find_dflash_target(slug)
        if not target or not dflash_pair_compatible(target):
            continue
        if model_downloading(target) or model_downloading(f"z-lab/{slug}"):
            continue
        jobs.append((target, "eugr-dflash"))
    return jobs


def load_benchmark_profiles() -> dict[str, dict]:
    if not yaml or not BENCHMARKS_FILE.is_file():
        return {}
    try:
        data = yaml.safe_load(BENCHMARKS_FILE.read_text()) or {}
    except OSError:
        return {}
    profiles = data.get("profiles") or {}
    return profiles if isinstance(profiles, dict) else {}


def sidecar_profile_benched(
    target_inv: str, recipe_map: dict[tuple[str, str], str], benchmarks: dict[str, dict]
) -> bool:
    profile_id = recipe_map.get((target_inv, "eugr-dflash"))
    if profile_id and recipe_speculative_blocked(profile_id):
        return True
    if not profile_id:
        return False
    prof = benchmarks.get(profile_id) or {}
    return prof.get("tok_s") is not None


def discover_sidecar_unbenched(
    recipe_map: dict[tuple[str, str], str], benchmarks: dict[str, dict]
) -> list[tuple[str, str]]:
    jobs: list[tuple[str, str]] = []
    for target, engine in discover_dflash_sidecars():
        if sidecar_profile_benched(target, recipe_map, benchmarks):
            continue
        jobs.append((target, engine))
    return jobs


def load_history_runs(profile_id: str) -> list[dict]:
    if not yaml or not HISTORY_FILE.is_file():
        return []
    try:
        data = yaml.safe_load(HISTORY_FILE.read_text()) or {}
    except OSError:
        return []
    prof = (data.get("profiles") or {}).get(profile_id) or {}
    runs = prof.get("runs") or []
    return [r for r in runs if isinstance(r, dict)]


def needs_refire(profile_id: str) -> bool:
    runs = load_history_runs(profile_id)
    if not runs:
        return True
    return all(r.get("source") == "import" for r in runs)


def discover_unbenched(models: list[dict]) -> list[tuple[str, str]]:
    jobs: list[tuple[str, str]] = []
    for m in sorted(models, key=lambda x: x.get("id", "")):
        inv = m.get("id") or ""
        if not inv or m.get("best_bench_tok_s"):
            continue
        root = MODELS_ROOT / inv
        if is_auxiliary_only(root):
            continue
        if model_downloading(inv):
            continue
        engine = pick_engine(root, inv)
        if engine:
            jobs.append((inv, engine))
    return jobs


def discover_refire(
    models: list[dict], recipe_map: dict[tuple[str, str], str]
) -> list[tuple[str, str]]:
    jobs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in sorted(models, key=lambda x: x.get("id", "")):
        inv = m.get("id") or ""
        if not inv or not m.get("best_bench_tok_s"):
            continue
        root = MODELS_ROOT / inv
        if is_auxiliary_only(root):
            continue
        if model_downloading(inv):
            continue
        engine = pick_engine(root, inv)
        if not engine:
            continue
        key = (inv, engine)
        if key in seen:
            continue
        profile_id = recipe_map.get(key)
        if not profile_id:
            continue
        if not needs_refire(profile_id):
            continue
        jobs.append(key)
        seen.add(key)
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover benchmark queue jobs")
    parser.add_argument(
        "--mode",
        choices=("unbenched", "refire-import", "sidecar", "all"),
        default="unbenched",
        help="unbenched=new models + DFlash profiles; refire-import=re-bench migrated pre-history runs",
    )
    args = parser.parse_args()

    if not MODELS_JSON.is_file():
        print("models.json missing", file=sys.stderr)
        return 1

    data = json.loads(MODELS_JSON.read_text())
    models = data.get("models") or []
    recipe_map = load_recipe_profiles()
    bench_profiles = load_benchmark_profiles()

    jobs: list[tuple[str, str]] = []
    if args.mode in ("unbenched", "all"):
        jobs.extend(discover_unbenched(models))
        sidecar = discover_sidecar_unbenched(recipe_map, bench_profiles)
        seen = set(jobs)
        for job in sidecar:
            if job not in seen:
                jobs.append(job)
                seen.add(job)
    if args.mode == "sidecar":
        jobs = discover_sidecar_unbenched(recipe_map, bench_profiles)
    if args.mode in ("refire-import", "all"):
        refire = discover_refire(models, recipe_map)
        if args.mode == "all":
            seen = set(jobs)
            for job in refire:
                if job not in seen:
                    jobs.append(job)
        else:
            jobs = refire

    for inv, engine in jobs:
        print(f"{inv} {engine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
