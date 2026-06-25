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
EUGR_READY_SECS = int(os.environ.get("AUDIT_EUGR_READY_SECS", "2400"))
DEFAULT_READY_SECS = int(os.environ.get("AUDIT_READY_SECS", "300"))
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
    "qwen/qwen-agentworld-35b-a3b": "qwen-qwen-agentworld-35b-a3b-eugr",
    "empero-ai/qwythos-9b-claude-mythos-5-1m": "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr",
    "0xsero/deepseek-v4-flash-spark": "0xsero-deepseek-v4-flash-spark-llama",
}

SKIP_INVENTORY: set[str] = {
    # REAP GGUF fails llama load on current stack — revisit with ds4 routing
    "0xsero/deepseek-v4-flash-spark",
}

DEPRECATED_PROFILES = [
    "qwen36-nvfp4",
    "qwen-qwen3-6-27b-dflash-eugr",
    "qwen-qwen3-6-27b-eugr",
    "0xsero-deepseek-v4-flash-spark-llama-2",
    "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr-2",
    "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr-3",
    "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr-4",
]

ARCH_FIXES: dict[str, str] = {
    "microsoft/phi-4": "dense",
    "qwen/qwen3-coder-next": "dense",
    "saricles/qwen3-coder-next": "dense",
    "qwen/qwen-agentworld-35b-a3b": "moe",
    "empero-ai/qwythos-9b-claude-mythos-5-1m": "dense",
    "z-lab/qwen3.6-27b": "dense",
}


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def write_report(report: dict[str, Any]) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2))


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


def ready_timeout_secs(recipe: dict[str, Any]) -> int:
    engine = str(recipe.get("engine") or "")
    if engine == "eugr":
        ctx_block = recipe.get("context") or {}
        ctx = int(ctx_block.get("default") or ctx_block.get("effective") or 32768)
        # Large KV windows can take many minutes to compile/load on eugr.
        if ctx >= 200000:
            return max(EUGR_READY_SECS, 3600)
        if ctx >= 100000:
            return max(EUGR_READY_SECS, 3000)
        return EUGR_READY_SECS
    if engine == "ds4":
        return max(DEFAULT_READY_SECS, 600)
    return DEFAULT_READY_SECS


def wait_ready(port: int, timeout: int = DEFAULT_READY_SECS, *, engine: str | None = None) -> bool:
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


def ensure_testing_recipe(core: Any, profile_id: str, dry_run: bool) -> None:
    """Mark a draft recipe as testing — never promote before bench v2."""
    draft = ROOT / "recipes" / "drafts" / f"{profile_id}.yaml"
    prod = ROOT / "recipes" / f"{profile_id}.yaml"
    if prod.is_file():
        return
    if not draft.is_file():
        raise RuntimeError(f"no recipe for {profile_id}")
    if dry_run:
        log(f"DRY mark testing {profile_id}")
        return
    core.set_recipe_lifecycle(profile_id, "testing")


def promote_after_bench(core: Any, profile_id: str, dry_run: bool) -> None:
    """Promote draft → production works only after bench v2 succeeded."""
    if dry_run:
        log(f"DRY promote after bench {profile_id}")
        return
    draft = ROOT / "recipes" / "drafts" / f"{profile_id}.yaml"
    if draft.is_file():
        recipe = core.load_yaml(draft)
        if core.infer_lifecycle(recipe, draft) == core.LIFECYCLE_DRAFT:
            core.set_recipe_lifecycle(profile_id, "testing")
        core.promote_recipe(profile_id)
        return
    prod = ROOT / "recipes" / f"{profile_id}.yaml"
    if not prod.is_file():
        raise RuntimeError(f"no recipe to promote: {profile_id}")
    recipe = core.load_yaml(prod)
    recipe["lifecycle"] = core.LIFECYCLE_WORKS
    recipe["promoted_at"] = datetime.now(timezone.utc).isoformat()
    core.save_recipe_file(prod, recipe)
    profiles = core.enabled_profiles()
    if profile_id not in profiles:
        profiles.append(profile_id)
        core.save_profiles_index(profiles)
    core.sync_spark_status_for_works(recipe)
    core.trigger_inventory_rebuild()


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

        ensure_testing_recipe(core, profile_id, dry_run)
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
            result["error"] = (up.stderr or up.stdout)[-800:]
            run(["/usr/local/bin/spark", "models", "verify", "set", path, "failed"], timeout=120)
            return result

        recipe = core.load_recipe(profile_id)
        port = int(recipe.get("port") or 8000)
        ready_secs = ready_timeout_secs(recipe)
        if not wait_ready(port, timeout=ready_secs, engine=str(recipe.get("engine") or "")):
            result["status"] = "not_ready"
            result["error"] = f"/v1/models not ready on port {port} within {ready_secs}s"
            run(["/usr/local/bin/spark", "models", "verify", "set", path, "failed"], timeout=120)
            return result

        if skip_bench:
            result["status"] = "bench_skipped"
            return result

        bench = run(
            [str(ROOT / "venv/bin/python"), str(ROOT / "scripts/spark-inference.py"), "bench", "--write-result"],
            timeout=7200,
            env={"BENCH_STANDARD": "v2"},
        )
        if bench.returncode != 0:
            result["status"] = "bench_failed"
            result["error"] = bench.stderr[-800:]
            run(["/usr/local/bin/spark", "models", "verify", "set", path, "failed"], timeout=120)
            return result
        try:
            br = json.loads((ROOT / "run/inference-bench-result.json").read_text())
            if not br.get("ok"):
                result["status"] = "bench_failed"
                result["error"] = str(br.get("error") or "bench result not ok")
                run(["/usr/local/bin/spark", "models", "verify", "set", path, "failed"], timeout=120)
                return result
            result["bench"] = br
            result["bench_tok_s"] = br.get("tok_s")
        except Exception as exc:
            result["status"] = "bench_failed"
            result["error"] = f"bench result unreadable: {exc}"
            run(["/usr/local/bin/spark", "models", "verify", "set", path, "failed"], timeout=120)
            return result

        promote_after_bench(core, profile_id, dry_run=False)
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


def reset_verify_all(paths: set[str], dry_run: bool) -> None:
    """Clear works/failed flags so only a fresh bench v2 can set works."""
    for path in sorted(paths):
        if path in SKIP_INVENTORY:
            continue
        if dry_run:
            log(f"DRY reset verify {path} -> unverified")
            continue
        run(["/usr/local/bin/spark", "models", "verify", "set", path, "unverified"], timeout=60)
    if not dry_run and paths:
        run(["/usr/local/bin/spark", "models", "inventory"], timeout=300)
        log(f"reset verify -> unverified for {len(paths)} models")


def write_report_markdown(report: dict[str, Any]) -> Path:
    md_path = REPORT_FILE.with_suffix(".md")
    lines = [
        "# Golden inventory audit report",
        "",
        f"- **Started:** {report.get('started_at', '')}",
        f"- **Finished:** {report.get('finished_at', '')}",
        f"- **Bench standard:** v{report.get('bench_standard', '2.0')}",
        "",
        "| Model | Golden profile | Status | ctx | kv | tok/s (v2) |",
        "|-------|----------------|--------|-----|-----|-------------|",
    ]
    ok = 0
    for m in report.get("models") or []:
        if m.get("status") == "ok":
            ok += 1
        bench = m.get("bench") or {}
        tok = bench.get("tok_s") or m.get("bench_tok_s") or ""
        lines.append(
            f"| `{m.get('inventory_path', '')}` | `{m.get('golden_profile', '')}` | "
            f"{m.get('status', '')} | {m.get('ctx', '')} | {m.get('kv', '')} | {tok} |"
        )
    lines.extend(["", f"**Summary:** {ok}/{len(report.get('models') or [])} ok", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def audit_inventory(
    dry_run: bool = False,
    skip_bench: bool = False,
    skip_shelf: bool = False,
    only: set[str] | None = None,
    resume: bool = False,
    reset_verify: bool = False,
) -> dict[str, Any]:
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
    done_paths: set[str] = set()
    if resume and REPORT_FILE.is_file():
        prior = json.loads(REPORT_FILE.read_text())
        for entry in prior.get("models") or []:
            if entry.get("status") == "ok":
                path = str(entry.get("inventory_path") or "")
                if path:
                    done_paths.add(path)
                    report["models"].append(entry)
        if done_paths:
            log(f"resume: skipping {len(done_paths)} ok models")

    targets: list[tuple[str, str]] = []
    for m in inventory_models():
        path = inv_path(m)
        if not path:
            continue
        if is_auxiliary(path):
            mark_auxiliary_catalog(path, dry_run)
            report["auxiliary"].append(path)
            continue
        if only and path not in only:
            continue
        if path in done_paths:
            continue
        if path in SKIP_INVENTORY:
            report["models"].append(
                {"inventory_path": path, "status": "skipped", "reason": "load_blocked"}
            )
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

    if reset_verify and not dry_run and not resume:
        reset_verify_all({p for p, _ in targets}, dry_run)

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
        write_report(report)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_report(report)
    md = write_report_markdown(report)
    log(f"report markdown: {md}")
    run(["/usr/local/bin/spark", "models", "inventory"], timeout=300)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden inventory audit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-bench", action="store_true")
    parser.add_argument("--skip-shelf", action="store_true")
    parser.add_argument("--only", help="Comma-separated inventory paths to process")
    parser.add_argument("--resume", action="store_true", help="Skip models already ok in report")
    parser.add_argument(
        "--reset-verify",
        action="store_true",
        help="Reset targeted models to unverified before audit (works only set after bench)",
    )
    args = parser.parse_args()
    only = {x.strip() for x in args.only.split(",")} if args.only else None
    report = audit_inventory(
        dry_run=args.dry_run,
        skip_bench=args.skip_bench,
        skip_shelf=args.skip_shelf,
        only=only,
        resume=args.resume,
        reset_verify=args.reset_verify,
    )
    ok = sum(1 for m in report["models"] if m.get("status") == "ok")
    log(f"DONE ok={ok}/{len(report['models'])}")
    print(json.dumps({"ok": ok, "total": len(report["models"]), "report": str(REPORT_FILE)}, indent=2))
    return 0 if ok == len(report["models"]) else 1


if __name__ == "__main__":
    sys.exit(main())
