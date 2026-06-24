#!/opt/spark/venv/bin/python3
"""Golden inventory audit — one optimized recipe + bench v2 + shelf per model."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/spark")
GOLDEN_FILE = ROOT / "data" / "golden-recipes.yaml"
REPORT_FILE = ROOT / "run" / "golden-audit-report.json"
LOG_FILE = ROOT / "logs" / "golden-audit.log"
MODELS_JSON = ROOT / "portal" / "models.json"
CATALOG_FILE = ROOT / "data" / "model-catalog.yaml"
PROFILES_FILE = ROOT / "data" / "inference-profiles.yaml"

AUXILIARY_PREFIXES = ("z-lab/",)

# inventory_path -> golden profile id (explicit overrides)
DEFAULT_GOLDEN: dict[str, str] = {
    "nvidia/qwen3.6-35b-a3b": "opencode-qwen36-250k",
    "qwen/qwen3.6-27b": "opencode-qwen27-dflash-262k",
    "antirez/deepseek-v4-flash": "antirez-deepseek-v4-flash-ds4",
    "deepseek-ai/deepseek-r1-distill-qwen-32b": "deepseek-ai-deepseek-r1-distill-qwen-32b-eugr",
    "google/diffusiongemma-26b-a4b-it": "google-diffusiongemma-26b-a4b-it-eugr",
    "google/gemma-4-12b-it": "google-gemma-4-12b-it-llama",
    "google/gemma-4-26b-a4b-it": "google-gemma-4-26b-a4b-it-eugr",
    "kaitchup/qwen3.6-27b": "kaitchup-qwen3-6-27b-llama",
    "microsoft/phi-4": "microsoft-phi-4-eugr",
    "nousresearch/hermes-4-14b": "nousresearch-hermes-4-14b-eugr",
    "nvidia/qwen3-30b-a3b": "nvidia-qwen3-30b-a3b-eugr",
    "qwen/qwen3-coder-next": "qwen-qwen3-coder-next-eugr",
    "rdtand/qwen3.6-27b": "rdtand-qwen3-6-27b-eugr",
    "saricles/qwen3-coder-next": "saricles-qwen3-coder-next-eugr",
    "stepfun-ai/step-3.7-flash": "stepfun-ai-step-3-7-flash-llama",
    "unsloth/qwen3-coder-30b-a3b-instruct": "unsloth-qwen3-coder-30b-a3b-instruct-llama",
    "unsloth/qwen3.6-27b": "unsloth-qwen3-6-27b-eugr",
    "unsloth/qwen3.6-35b-a3b": "qwen36-q4-llama",
    "yuxinlu1/gemma-4-12b-coder-fable5-composer2.5-v1": "gemma4-12b-coder-q4",
    "0xsero/deepseek-v4-flash-spark": "0xsero-deepseek-v4-flash-spark-llama",
}

DEPRECATED_PROFILES = [
    "qwen36-nvfp4",
    "qwen-qwen3-6-27b-dflash-eugr",
    "qwen-qwen3-6-27b-eugr",
    "0xsero-deepseek-v4-flash-spark-llama-2",
]

ARCH_FIXES: dict[str, str] = {
    "microsoft/phi-4": "dense",
    "qwen/qwen3-coder-next": "dense",
    "saricles/qwen3-coder-next": "dense",
    "z-lab/qwen3.6-27b": "dense",
    "z-lab/qwen3.6-35b-a3b": "moe",
}


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(
    cmd: list[str],
    *,
    timeout: int = 7200,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    log(f"RUN: {' '.join(cmd)}")
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
        env=merged,
    )


def load_core():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "inference_core", ROOT / "scripts" / "spark-inference.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def inventory_models() -> list[dict[str, Any]]:
    data = json.loads(MODELS_JSON.read_text())
    return data.get("models") or []


def inv_path(m: dict[str, Any]) -> str:
    return m.get("path", "").replace("/models/", "").strip("/")


def is_auxiliary(path: str) -> bool:
    return path.startswith(AUXILIARY_PREFIXES) or path.split("/")[0] == "z-lab"


def wait_ready(port: int, timeout: int = 900) -> bool:
    url = f"http://127.0.0.1:{port}/v1/models"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def _catalog_entries() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cat = load_yaml(CATALOG_FILE)
    models = cat.get("models")
    if isinstance(models, list):
        by_id: dict[str, dict[str, Any]] = {}
        for entry in models:
            if isinstance(entry, dict):
                key = str(entry.get("id") or entry.get("inventory_path") or "")
                if key:
                    by_id[key] = entry
        return cat, models
    if isinstance(models, dict):
        return cat, []
    cat["models"] = []
    return cat, cat["models"]


def _find_catalog_entry(path: str) -> dict[str, Any] | None:
    cat, models = _catalog_entries()
    if isinstance(cat.get("models"), list):
        for entry in models:
            if isinstance(entry, dict) and str(entry.get("id") or "") == path:
                return entry
        new_entry = {"id": path}
        models.append(new_entry)
        return new_entry
    models_dict = cat.setdefault("models", {})
    if isinstance(models_dict, dict):
        return models_dict.setdefault(path, {})
    return None


def fix_catalog_architecture(path: str, arch: str, dry_run: bool) -> bool:
    entry = _find_catalog_entry(path)
    if entry is None:
        return False
    old = entry.get("architecture")
    if old == arch:
        return False
    if dry_run:
        log(f"DRY catalog arch {path}: {old} -> {arch}")
        return True
    entry["architecture"] = arch
    caps = entry.setdefault("capabilities", [])
    if arch == "moe" and "moe" not in [str(c).lower() for c in caps]:
        caps.append("moe")
    if arch == "dense" and "dense" not in [str(c).lower() for c in caps]:
        caps.append("dense")
    cat, _ = _catalog_entries()
    save_yaml(CATALOG_FILE, cat)
    log(f"catalog arch {path}: {old} -> {arch}")
    return True


def mark_auxiliary_catalog(path: str, dry_run: bool) -> None:
    entry = _find_catalog_entry(path)
    if entry is None:
        return
    tags = entry.setdefault("tags", [])
    if "sidecar" in [str(t).lower() for t in tags]:
        return
    if dry_run:
        log(f"DRY mark auxiliary {path}")
        return
    tags.append("sidecar")
    entry["model_kind"] = "sidecar"
    cat, _ = _catalog_entries()
    save_yaml(CATALOG_FILE, cat)


def consolidate_profiles(
    golden_ids: set[str],
    deprecated: list[str],
    dry_run: bool,
) -> list[str]:
    data = load_yaml(PROFILES_FILE)
    profiles = list(data.get("profiles") or [])
    removed: list[str] = []
    new_profiles: list[str] = []
    dep_set = set(deprecated)
    for pid in profiles:
        if pid in dep_set:
            removed.append(pid)
            continue
        new_profiles.append(pid)
    for gid in sorted(golden_ids):
        if gid not in new_profiles:
            new_profiles.append(gid)
    if dry_run:
        log(f"DRY profiles remove={removed} add={[g for g in golden_ids if g not in profiles]}")
        return removed
    data["profiles"] = new_profiles
    save_yaml(PROFILES_FILE, data)
    log(f"profiles updated; removed {removed}")
    return removed


def optimize_recipe_context(core: Any, profile_id: str, dry_run: bool) -> tuple[int, str]:
    import yaml

    recipe = core.load_recipe(profile_id)
    ctxmod = core.ctxmod
    existing = ctxmod.default_context(recipe) or 32768
    native = ctxmod.native_context(recipe) or existing
    max_ctx = ctxmod.estimate_max_ctx(recipe, kv="fp8") or native
    if existing >= 131072:
        target = min(existing, native, max_ctx)
    else:
        target = min(native, max(max_ctx, existing))
    target = max(8192, int(target // 1024) * 1024)
    kv = "fp8" if recipe.get("engine") == "eugr" else "q8_0"
    if dry_run:
        log(f"DRY optimize {profile_id} ctx={target} kv={kv}")
        return target, kv

    block = recipe.setdefault("context", {})
    block["default"] = target
    block["native"] = native
    block["kv_default"] = kv
    block.setdefault("presets", {})
    block["presets"]["golden"] = {"label": "Golden max fit", "ctx": target, "kv": kv}
    recipe["lifecycle"] = "works"
    recipe["tags"] = list(dict.fromkeys((recipe.get("tags") or []) + ["golden"]))
    path = core.recipe_path(profile_id)
    path.write_text(yaml.safe_dump(recipe, sort_keys=False, default_flow_style=False))

    engine = recipe.get("engine")
    if engine == "eugr" and recipe.get("eugr_recipe"):
        eugr_path = Path(recipe["eugr_recipe"])
        if eugr_path.is_file():
            eugr = yaml.safe_load(eugr_path.read_text()) or {}
            eugr.setdefault("defaults", {})["max_model_len"] = target
            cmd = str(eugr.get("command") or "")
            if "--kv-cache-dtype" not in cmd and kv == "fp8":
                cmd = cmd.replace("--kv-cache-dtype auto", "--kv-cache-dtype fp8")
            eugr["command"] = cmd
            eugr_path.write_text(yaml.safe_dump(eugr, sort_keys=False, default_flow_style=False))
    elif engine == "llamacpp":
        args = [str(a) for a in (recipe.get("llamacpp_args") or [])]
        out: list[str] = []
        i = 0
        replaced = False
        while i < len(args):
            if args[i] in ("-c", "--ctx") and i + 1 < len(args):
                out.extend(["-c", str(target)])
                i += 2
                replaced = True
                continue
            out.append(args[i])
            i += 1
        if not replaced:
            out.extend(["-c", str(target)])
        recipe["llamacpp_args"] = out
        path.write_text(yaml.safe_dump(recipe, sort_keys=False, default_flow_style=False))
    elif engine == "ds4":
        args = [str(a) for a in (recipe.get("ds4_args") or [])]
        out = []
        i = 0
        replaced = False
        while i < len(args):
            if args[i] == "-c" and i + 1 < len(args):
                out.extend(["-c", str(min(target, 131072))])
                i += 2
                replaced = True
                continue
            out.append(args[i])
            i += 1
        if not replaced:
            out.extend(["-c", str(min(target, 131072))])
        recipe["ds4_args"] = out
        path.write_text(yaml.safe_dump(recipe, sort_keys=False, default_flow_style=False))

    log(f"optimized {profile_id} ctx={target} kv={kv}")
    return target, kv


def ensure_local(path: str, dry_run: bool) -> bool:
    local = Path(f"/models/{path}")
    if local.exists() and any(local.rglob("*")):
        return True
    if dry_run:
        log(f"DRY would shelf pull {path}")
        return False
    r = run(["/usr/local/bin/spark", "shelf", "pull", path], timeout=86400)
    if r.returncode != 0:
        log(f"shelf pull failed {path}: {r.stderr[-500:]}")
        return False
    return True


def promote_draft_if_needed(core: Any, profile_id: str, dry_run: bool) -> None:
    draft = ROOT / "recipes" / "drafts" / f"{profile_id}.yaml"
    prod = ROOT / "recipes" / f"{profile_id}.yaml"
    if prod.is_file():
        return
    if not draft.is_file():
        raise RuntimeError(f"no recipe for {profile_id}")
    if dry_run:
        log(f"DRY promote draft {profile_id}")
        return
    core.set_recipe_lifecycle(profile_id, "testing")
    core.promote_recipe(profile_id)


def process_model(
    core: Any,
    path: str,
    profile_id: str,
    *,
    dry_run: bool,
    skip_bench: bool,
    skip_shelf: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "inventory_path": path,
        "golden_profile": profile_id,
        "status": "pending",
    }
    try:
        if path in ARCH_FIXES:
            fix_catalog_architecture(path, ARCH_FIXES[path], dry_run)

        if not ensure_local(path, dry_run):
            result["status"] = "needs_shelf_pull"
            return result

        promote_draft_if_needed(core, profile_id, dry_run)
        if not dry_run:
            run(["/usr/local/bin/spark", "inference", "down"], timeout=120)
        ctx, kv = optimize_recipe_context(core, profile_id, dry_run)

        if dry_run:
            result["status"] = "dry_run_ok"
            result["ctx"] = ctx
            return result

        run(["/usr/local/bin/spark", "inference", "down"], timeout=120)
        up = run(
            [
                "/usr/local/bin/spark",
                "inference",
                "up",
                profile_id,
                "--ctx",
                str(ctx),
                "--kv",
                kv,
                "--preset",
                "golden",
            ],
            timeout=3600,
        )
        if up.returncode != 0:
            result["status"] = "up_failed"
            result["error"] = up.stderr[-800:]
            return result

        recipe = core.load_recipe(profile_id)
        port = int(recipe.get("port") or 8000)
        if not wait_ready(port):
            result["status"] = "not_ready"
            return result

        if not skip_bench:
            bench = run(
                [str(ROOT / "venv/bin/python"), str(ROOT / "scripts/spark-inference.py"), "bench", "--write-result"],
                timeout=7200,
                env={"BENCH_STANDARD": "v2"},
            )
            if bench.returncode != 0:
                result["status"] = "bench_failed"
                result["error"] = bench.stderr[-800:]
                return result
            try:
                br = json.loads((ROOT / "run/inference-bench-result.json").read_text())
                result["bench"] = br
            except Exception:
                pass

        run(["/usr/local/bin/spark", "models", "verify", "set", path, "works"], timeout=120)
        run(["/usr/local/bin/spark", "models", "inventory"], timeout=300)

        m = next((x for x in inventory_models() if inv_path(x) == path), {})
        if not skip_shelf and not (m.get("shelf") or {}).get("present"):
            push = run(["/usr/local/bin/spark", "shelf", "push", path], timeout=86400)
            result["shelf_push"] = push.returncode == 0
            if push.returncode != 0:
                result["shelf_error"] = push.stderr[-500:]

        result["status"] = "ok"
        result["ctx"] = ctx
        result["kv"] = kv
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        log(f"ERROR {path}: {exc}")
    return result


def audit_inventory(dry_run: bool = False, skip_bench: bool = False, skip_shelf: bool = False) -> dict[str, Any]:
    core = load_core()
    golden_data = load_yaml(GOLDEN_FILE)
    golden_map = dict(DEFAULT_GOLDEN)
    golden_map.update(golden_data.get("golden") or {})
    deprecated = list(dict.fromkeys(
        list(DEPRECATED_PROFILES) + list(golden_data.get("deprecated_profiles") or [])
    ))

    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "bench_standard": "2.0",
        "models": [],
        "auxiliary": [],
    }

    targets: list[tuple[str, str]] = []
    for m in inventory_models():
        path = inv_path(m)
        if not path:
            continue
        if is_auxiliary(path):
            mark_auxiliary_catalog(path, dry_run)
            report["auxiliary"].append(path)
            continue
        profile = golden_map.get(path)
        if not profile:
            # auto-pick sole recipe for inventory
            profiles = [
                pid
                for pid in core.list_recipe_ids()
                if (core.load_recipe(pid).get("inventory_path") or "") == path
            ]
            if len(profiles) == 1:
                profile = profiles[0]
            elif profiles:
                profile = sorted(profiles)[0]
                log(f"WARN multiple recipes for {path}, picked {profile}")
            else:
                report["models"].append({"inventory_path": path, "status": "no_recipe"})
                continue
        targets.append((path, profile))

    consolidate_profiles({p for _, p in targets}, deprecated, dry_run)

    for path, profile in targets:
        log(f"=== processing {path} -> {profile} ===")
        res = process_model(
            core,
            path,
            profile,
            dry_run=dry_run,
            skip_bench=skip_bench,
            skip_shelf=skip_shelf,
        )
        report["models"].append(res)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    run(["/usr/local/bin/spark", "models", "inventory"], timeout=300)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden inventory audit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-bench", action="store_true")
    parser.add_argument("--skip-shelf", action="store_true")
    args = parser.parse_args()
    report = audit_inventory(
        dry_run=args.dry_run,
        skip_bench=args.skip_bench,
        skip_shelf=args.skip_shelf,
    )
    ok = sum(1 for m in report["models"] if m.get("status") == "ok")
    log(f"DONE ok={ok}/{len(report['models'])}")
    print(json.dumps({"ok": ok, "total": len(report["models"]), "report": str(REPORT_FILE)}, indent=2))
    return 0 if ok == len(report["models"]) else 1


if __name__ == "__main__":
    sys.exit(main())
