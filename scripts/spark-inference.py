#!/opt/spark/venv/bin/python3
"""Phase 5 inference control plane — recipe-driven profile switch."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml

ROOT = Path("/opt/spark")
RECIPES_DIR = ROOT / "recipes"
RECIPES_DRAFTS_DIR = RECIPES_DIR / "drafts"
MODELS_ROOT = Path("/models")
SERVICES_DIR = ROOT / "services"
PROFILES_INDEX = ROOT / "data" / "inference-profiles.yaml"
STATE_FILE = ROOT / "run" / "inference-active.json"
SWITCH_PID_FILE = ROOT / "run" / "inference-switch.pid"
SWITCH_META_FILE = ROOT / "run" / "inference-switch.meta.json"
SWITCH_LOG_FILE = ROOT / "logs" / "inference-switch-latest.log"
SWITCH_LOG_PROFILE_RE = re.compile(r"^==>\s+switch\s+to\s+(\S+)")
BENCH_PID_FILE = ROOT / "run" / "inference-bench.pid"
BENCH_RESULT_FILE = ROOT / "run" / "inference-bench-result.json"
LOG_DIR = ROOT / "logs"
BENCHMARKS_FILE = ROOT / "data" / "inference-benchmarks.yaml"
BENCHMARK_HISTORY_LEGACY = ROOT / "data" / "inference-benchmark-history.yaml"
BENCHMARK_HISTORY_FILE = ROOT / "run" / "inference-benchmark-history.yaml"
BENCHMARK_HISTORY_OWNER = "techno"
BENCH_HISTORY_RUN_RE = re.compile(
    r"^/api/inference/benchmarks/([^/]+)/runs/([^/]+)$"
)
BENCH_HISTORY_LIST_RE = re.compile(
    r"^/api/inference/benchmarks/([^/]+)/history$"
)
_history_migrated = False
VERIFY_FILE = ROOT / "data" / "model-verification.yaml"
SPARK_EUGR = ROOT / "scripts" / "spark-eugr"
SPARK_LLAMA = ROOT / "scripts" / "spark-llama"
VERIFY_SCRIPT = ROOT / "scripts" / "spark-model-verify"
INVENTORY_BUILD = ROOT / "scripts" / "spark-inventory-build"
PROFILE_ID_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]*$")
BENCH_METHODS = frozenset({"bench", "bench-agent"})
LIFECYCLE_DRAFT = "draft"
LIFECYCLE_TESTING = "testing"
LIFECYCLE_PRODUCTION = "production"
LIFECYCLE_VALID = frozenset({LIFECYCLE_DRAFT, LIFECYCLE_TESTING, LIFECYCLE_PRODUCTION})


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"invalid yaml root in {path}")
    return data


def enabled_profiles() -> list[str]:
    data = load_yaml(PROFILES_INDEX)
    profiles = data.get("profiles") or []
    return [p for p in profiles if isinstance(p, str) and p]


def save_profiles_index(profiles: list[str]) -> None:
    PROFILES_INDEX.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_INDEX.write_text(
        yaml.safe_dump({"profiles": profiles}, sort_keys=False, default_flow_style=False)
    )


def trigger_inventory_rebuild() -> None:
    if not INVENTORY_BUILD.is_file():
        return
    subprocess.Popen(
        [str(INVENTORY_BUILD)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def sync_spark_status_for_testing(recipe: dict[str, Any]) -> None:
    """Align model Spark row with recipe testing (skip if already wip/works/failed)."""
    inv_path = recipe.get("inventory_path") or recipe.get("catalog_id")
    if not inv_path or not VERIFY_SCRIPT.is_file():
        return
    try:
        proc = subprocess.run(
            [sys.executable, str(VERIFY_SCRIPT), "get", str(inv_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        current = json.loads(proc.stdout).get("spark_status", "unverified")
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        current = "unverified"
    if current in ("wip", "works", "failed"):
        return
    engine = str(recipe.get("engine") or "").strip()
    note = f"Model Lab: {recipe.get('id', 'recipe')} testing"
    args = [sys.executable, str(VERIFY_SCRIPT), "set", str(inv_path), "wip"]
    if engine:
        args.append(engine)
    args.append(note)
    subprocess.run(args, capture_output=True, check=False)


def production_recipe_path(profile_id: str) -> Path:
    return RECIPES_DIR / f"{profile_id}.yaml"


def draft_recipe_path(profile_id: str) -> Path:
    return RECIPES_DRAFTS_DIR / f"{profile_id}.yaml"


def resolve_recipe_path(profile_id: str) -> Path | None:
    prod = production_recipe_path(profile_id)
    if prod.is_file():
        return prod
    draft = draft_recipe_path(profile_id)
    if draft.is_file():
        return draft
    return None


def infer_lifecycle(recipe: dict[str, Any], path: Path) -> str:
    lifecycle = recipe.get("lifecycle")
    if lifecycle in LIFECYCLE_VALID:
        return lifecycle
    if path.parent == RECIPES_DRAFTS_DIR:
        return LIFECYCLE_DRAFT
    return LIFECYCLE_PRODUCTION


def load_recipe(profile_id: str) -> dict[str, Any]:
    path = resolve_recipe_path(profile_id)
    if path is None:
        raise SystemExit(f"unknown profile: {profile_id}")
    recipe = load_yaml(path)
    if recipe.get("id") and recipe["id"] != profile_id:
        print(f"warning: recipe id {recipe['id']!r} != filename {profile_id!r}", file=sys.stderr)
    recipe.setdefault("id", profile_id)
    recipe["lifecycle"] = infer_lifecycle(recipe, path)
    recipe["_path"] = str(path)
    return recipe


def recipe_path(profile_id: str) -> Path:
    path = resolve_recipe_path(profile_id)
    if path is None:
        raise SystemExit(f"unknown profile: {profile_id}")
    return path


def list_recipe_ids() -> list[str]:
    ids: set[str] = set()
    if RECIPES_DIR.is_dir():
        for path in RECIPES_DIR.glob("*.yaml"):
            if path.is_file():
                ids.add(path.stem)
    if RECIPES_DRAFTS_DIR.is_dir():
        for path in RECIPES_DRAFTS_DIR.glob("*.yaml"):
            if path.is_file():
                ids.add(path.stem)
    return sorted(ids)


def switchable_profile_ids() -> list[str]:
    out: list[str] = []
    for profile_id in list_recipe_ids():
        try:
            recipe = load_recipe(profile_id)
        except SystemExit:
            continue
        lifecycle = recipe.get("lifecycle")
        if lifecycle == LIFECYCLE_PRODUCTION and profile_id in enabled_profiles():
            out.append(profile_id)
        elif lifecycle == LIFECYCLE_TESTING:
            out.append(profile_id)
    return out


def save_recipe_file(path: Path, recipe: dict[str, Any]) -> None:
    payload = {k: v for k, v in recipe.items() if not str(k).startswith("_")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, default_flow_style=False))


def discover_gguf(model_root: Path) -> Path | None:
    def pick(candidates: list[Path]) -> Path | None:
        if not candidates:
            return None
        for pref in ("Q4_K_M", "Q4_K_XL", "Q4"):
            for p in candidates:
                if pref in p.name:
                    return p
        return sorted(candidates, key=lambda p: p.stat().st_size)[0]

    gguf_dir = model_root / "gguf"
    if gguf_dir.is_dir():
        picked = pick(list(gguf_dir.glob("*.gguf")))
        if picked:
            return picked
    return pick(list(model_root.rglob("*.gguf")))


def discover_nvfp4_dir(model_root: Path) -> Path | None:
    nvfp4 = model_root / "nvfp4"
    if nvfp4.is_dir() and any(nvfp4.iterdir()):
        return nvfp4
    return None


def discover_hf_dir(model_root: Path) -> Path | None:
    hf = model_root / "hf"
    if not hf.is_dir() or not any(hf.iterdir()):
        return None
    if (hf / "config.json").is_file() or any(hf.glob("*.safetensors")):
        return hf
    return None


VLLM_WEIGHT_SUBDIRS = ("nvfp4", "fp8", "hf", "prismaquant")


def discover_vllm_weights_dir(model_root: Path) -> tuple[Path, str] | None:
    for name in VLLM_WEIGHT_SUBDIRS:
        sub = model_root / name
        if sub.is_dir() and (sub / "config.json").is_file():
            return sub, name
    for sub in sorted(model_root.iterdir()):
        if sub.is_dir() and (sub / "config.json").is_file():
            return sub, sub.name
    return None


def is_multimodal_model(model_dir: Path) -> bool:
    cfg_path = model_dir / "config.json"
    if not cfg_path.is_file():
        return False
    try:
        cfg = json.loads(cfg_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    archs = cfg.get("architectures") or []
    if any("ConditionalGeneration" in str(a) for a in archs):
        return True
    if cfg.get("vision_config") or cfg.get("audio_config"):
        return True
    return False


def infer_max_model_len(model_dir: Path, weight_format: str) -> int:
    default = 65536 if weight_format == "nvfp4" else 16384
    cfg_path = model_dir / "config.json"
    if not cfg_path.is_file():
        return default
    try:
        cfg = json.loads(cfg_path.read_text())
    except (json.JSONDecodeError, OSError):
        return default
    for key in ("max_position_embeddings", "max_seq_len", "seq_length"):
        val = cfg.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    rope = cfg.get("rope_scaling") or {}
    factor = rope.get("factor")
    base = cfg.get("max_position_embeddings")
    if isinstance(factor, (int, float)) and isinstance(base, (int, float)):
        return int(base * factor)
    return default


def make_profile_id(inventory_path: str, engine: str) -> str:
    lab, slug = inventory_path.split("/", 1)
    suffix = "llama" if engine == "llamacpp" else "eugr"
    raw = f"{lab}-{slug.replace('.', '-')}-{suffix}".lower()
    raw = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-")
    base = raw[:56].strip("-") or "profile"
    candidate = base
    n = 2
    while resolve_recipe_path(candidate):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def write_eugr_service(profile_id: str, inventory_path: str, served_name: str) -> Path:
    found = discover_vllm_weights_dir(MODELS_ROOT / inventory_path)
    if found is None:
        raise RuntimeError(
            f"no vLLM weights (nvfp4/ or hf/) under /models/{inventory_path}"
        )
    model_dir, weight_format = found
    moe_line = "    --moe-backend marlin \\\n" if weight_format == "nvfp4" else ""
    attn_line = ""
    if not is_multimodal_model(model_dir):
        attn_line = "    --attention-backend flashinfer \\\n"
    load_fmt = "auto" if is_multimodal_model(model_dir) else "fastsafetensors"
    max_len = infer_max_model_len(model_dir, weight_format)
    path = SERVICES_DIR / f"eugr-{profile_id}.yaml"
    content = f"""# Generated by spark-inference recipe scaffold ({profile_id})
recipe_version: "1"
name: {profile_id}
description: eugr vLLM serve for {inventory_path}

model: {served_name}
container: vllm-node

defaults:
  port: 8000
  host: 0.0.0.0
  tensor_parallel: 1
  gpu_memory_utilization: 0.85
  max_model_len: {max_len}
  max_num_seqs: 4
  max_num_batched_tokens: 8192

command: |
  vllm serve {model_dir} \\
    --host {{host}} \\
    --port {{port}} \\
    --served-model-name {served_name} \\
    --tensor-parallel-size {{tensor_parallel}} \\
    --trust-remote-code \\
    --kv-cache-dtype auto \\
{attn_line}{moe_line}    --gpu-memory-utilization {{gpu_memory_utilization}} \\
    --max-model-len {{max_model_len}} \\
    --max-num-seqs {{max_num_seqs}} \\
    --max-num-batched-tokens {{max_num_batched_tokens}} \\
    --enable-chunked-prefill \\
    --enable-prefix-caching \\
    --load-format {load_fmt}
"""
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def scaffold_recipe(
    inventory_path: str,
    engine: str,
    *,
    name: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    inventory_path = inventory_path.strip().strip("/")
    if "/" not in inventory_path:
        raise RuntimeError("inventory_path must be lab/slug")
    if engine not in {"llamacpp", "eugr"}:
        raise RuntimeError("engine must be llamacpp or eugr")

    model_root = MODELS_ROOT / inventory_path
    if not model_root.is_dir():
        raise RuntimeError(f"model not on disk: /models/{inventory_path}")

    profile_id = make_profile_id(inventory_path, engine)
    slug = inventory_path.split("/", 1)[1]
    served_name = re.sub(r"[^a-z0-9._-]+", "-", slug.lower()).strip("-")[:48]
    display = name or f"{slug} ({engine})"

    recipe: dict[str, Any] = {
        "id": profile_id,
        "name": display,
        "inventory_path": inventory_path,
        "engine": engine,
        "tier": tier or ("heavy" if engine == "eugr" else "fast"),
        "lifecycle": LIFECYCLE_DRAFT,
        "served_name": served_name,
        "port": 8000 if engine == "eugr" else 8081,
        "tags": ["lab", engine],
        "notes": (
            f"Scaffolded {datetime.now(timezone.utc).date().isoformat()} from "
            f"/models/{inventory_path}. Mark testing, switch, bench, then promote."
        ),
    }

    if engine == "llamacpp":
        gguf = discover_gguf(model_root)
        if gguf is None:
            raise RuntimeError(f"no .gguf under /models/{inventory_path}")
        recipe["model"] = str(gguf)
        recipe["llamacpp_args"] = ["-ngl", "999", "-fa", "1", "--no-mmap", "-c", "32768"]
    else:
        eugr_path = write_eugr_service(profile_id, inventory_path, served_name)
        recipe["eugr_recipe"] = str(eugr_path)

    path = draft_recipe_path(profile_id)
    save_recipe_file(path, recipe)
    trigger_inventory_rebuild()
    return recipe


def set_recipe_lifecycle(profile_id: str, lifecycle: str) -> dict[str, Any]:
    if lifecycle not in LIFECYCLE_VALID:
        raise RuntimeError(f"invalid lifecycle: {lifecycle}")
    path = resolve_recipe_path(profile_id)
    if path is None:
        raise RuntimeError(f"unknown profile: {profile_id}")
    if path.parent == RECIPES_DIR and lifecycle != LIFECYCLE_PRODUCTION:
        raise RuntimeError("production recipes live in recipes/ — use discard to remove")
    recipe = load_yaml(path)
    recipe["lifecycle"] = lifecycle
    recipe["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_recipe_file(path, recipe)
    recipe["id"] = profile_id
    if lifecycle == LIFECYCLE_TESTING:
        sync_spark_status_for_testing(recipe)
    trigger_inventory_rebuild()
    return recipe


def promote_recipe(profile_id: str) -> dict[str, Any]:
    draft_path = draft_recipe_path(profile_id)
    if not draft_path.is_file():
        raise RuntimeError(f"no draft recipe: {profile_id}")
    recipe = load_yaml(draft_path)
    lifecycle = infer_lifecycle(recipe, draft_path)
    if lifecycle == LIFECYCLE_DRAFT:
        raise RuntimeError("mark recipe as testing before promote (bench first)")

    recipe["lifecycle"] = LIFECYCLE_PRODUCTION
    recipe["promoted_at"] = datetime.now(timezone.utc).isoformat()
    prod_path = production_recipe_path(profile_id)
    save_recipe_file(prod_path, recipe)
    draft_path.unlink()

    profiles = enabled_profiles()
    if profile_id not in profiles:
        profiles.append(profile_id)
        save_profiles_index(profiles)

    trigger_inventory_rebuild()
    recipe["id"] = profile_id
    return recipe


def discard_recipe(profile_id: str) -> None:
    if profile_id in enabled_profiles():
        raise RuntimeError("cannot discard production profile — remove from inference-profiles.yaml first")
    draft_path = draft_recipe_path(profile_id)
    if draft_path.is_file():
        draft_path.unlink()
        trigger_inventory_rebuild()
        return
    prod_path = production_recipe_path(profile_id)
    if prod_path.is_file():
        raise RuntimeError("production recipes must be demoted manually")
    raise RuntimeError(f"no recipe: {profile_id}")


def api_recipe_list() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    production = set(enabled_profiles())
    for profile_id in list_recipe_ids():
        try:
            recipe = load_recipe(profile_id)
        except SystemExit:
            continue
        item = recipe_public(recipe)
        item["lifecycle"] = recipe.get("lifecycle")
        item["enabled"] = profile_id in production
        item["switchable"] = profile_id in switchable_profile_ids()
        items.append(item)
    return items


def curl_json(url: str, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def eugr_running() -> bool:
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return any(name in {"vllm_node", "spark-vllm-qwen36"} for name in out.splitlines())


def llama_running() -> bool:
    pid_file = ROOT / "run" / "llama-server.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def served_name_from_port(port: int) -> str | None:
    payload = curl_json(f"http://127.0.0.1:{port}/v1/models")
    if not payload:
        return None
    models = payload.get("data") or payload.get("models") or []
    if not models:
        return None
    first = models[0]
    return first.get("id") or first.get("name")


def detect_active_profile() -> dict[str, Any] | None:
    if STATE_FILE.is_file():
        try:
            state = json.loads(STATE_FILE.read_text())
            profile_id = state.get("profile")
            if profile_id:
                recipe = load_recipe(profile_id)
                engine = recipe.get("engine")
                if engine == "eugr" and eugr_running():
                    return {"profile": profile_id, "recipe": recipe, "state": state}
                if engine == "llamacpp" and llama_running():
                    return {"profile": profile_id, "recipe": recipe, "state": state}
                if engine == "eugr" and not eugr_running() and not llama_running():
                    clear_state()
                elif engine == "llamacpp" and not llama_running() and not eugr_running():
                    clear_state()
        except (json.JSONDecodeError, OSError, SystemExit):
            pass

    for profile_id in enabled_profiles():
        recipe = load_recipe(profile_id)
        engine = recipe.get("engine")
        port = int(recipe.get("port") or 0)
        if engine == "eugr" and eugr_running():
            return {"profile": profile_id, "recipe": recipe, "state": None}
        if engine == "llamacpp" and llama_running():
            served = served_name_from_port(port) if port else None
            if served == recipe.get("served_name"):
                return {"profile": profile_id, "recipe": recipe, "state": None}
    return None


def write_state(profile_id: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {
                "profile": profile_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n"
    )


def clear_state() -> None:
    STATE_FILE.unlink(missing_ok=True)


def run_script(script: Path, *args: str, env: dict[str, str] | None = None) -> None:
    if not script.is_file():
        raise SystemExit(f"missing script: {script}")
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run([str(script), *args], check=True, env=merged)


def cmd_list() -> int:
    active = detect_active_profile()
    active_id = active["profile"] if active else None
    print(
        f"{'PROFILE':<24} {'ENGINE':<10} {'TIER':<8} {'LIFE':<10} "
        f"{'PORT':<6} {'TOK/S':<8} ACTIVE"
    )
    print("-" * 78)
    for profile_id in list_recipe_ids():
        recipe = load_recipe(profile_id)
        mark = "*" if profile_id == active_id else ""
        bench = benchmark_for_profile(profile_id) or {}
        tok = bench.get("tok_s")
        tok_s = f"{tok:.0f}" if isinstance(tok, (int, float)) else "—"
        print(
            f"{profile_id:<24} "
            f"{recipe.get('engine', '?'):<10} "
            f"{recipe.get('tier', '?'):<8} "
            f"{recipe.get('lifecycle', '?'):<10} "
            f"{recipe.get('port', '?'):<6} "
            f"{tok_s:<8} {mark}"
        )
    return 0


def cmd_status() -> int:
    active = detect_active_profile()
    if not active:
        print("Active profile: none")
        print("Engines: eugr down, llama.cpp down")
        return 0

    recipe = active["recipe"]
    profile_id = active["profile"]
    lines = [
        f"Active profile: {profile_id}",
        f"  name:   {recipe.get('name', '')}",
        f"  engine: {recipe.get('engine', '')}",
        f"  tier:   {recipe.get('tier', '')}",
        f"  port:   {recipe.get('port', '')}",
        f"  model:  {recipe.get('served_name', '')}",
    ]
    if active.get("state") and active["state"].get("started_at"):
        lines.append(f"  since:  {active['state']['started_at']}")
    lines.append("---")
    print("\n".join(lines), flush=True)
    if recipe.get("engine") == "eugr":
        run_script(SPARK_EUGR, "status")
    else:
        run_script(SPARK_LLAMA, "status")
    return 0


def cmd_down() -> int:
    errors = 0
    for script, args in ((SPARK_EUGR, ("down",)), (SPARK_LLAMA, ("down",))):
        try:
            run_script(script, *args)
        except subprocess.CalledProcessError:
            errors += 1
    clear_state()
    return errors


def cmd_up(profile_id: str) -> int:
    if profile_id not in switchable_profile_ids():
        raise SystemExit(
            f"profile {profile_id!r} is not switchable — production index or testing draft required"
        )

    recipe = load_recipe(profile_id)
    active = detect_active_profile()
    if active and active["profile"] == profile_id:
        print(f"Already active: {profile_id}")
        return cmd_status()

    print("Stopping current engines (if any)...")
    cmd_down()

    path = str(recipe_path(profile_id))
    engine = recipe.get("engine")
    print(f"Starting {profile_id} ({engine})...")

    if engine == "eugr":
        run_script(
            SPARK_EUGR,
            "up",
            env={"SPARK_EUGR_RECIPE": recipe.get("eugr_recipe", "")},
        )
    elif engine == "llamacpp":
        run_script(SPARK_LLAMA, "up", env={"SPARK_LLAMA_RECIPE": path})
    else:
        raise SystemExit(f"unsupported engine: {engine!r}")

    write_state(profile_id)
    print(f"Profile {profile_id} started — run: spark-inference status")
    return 0


def validate_profile_id(profile_id: str) -> str | None:
    profile_id = profile_id.strip()
    if not profile_id or not PROFILE_ID_RE.match(profile_id):
        return None
    if profile_id not in switchable_profile_ids():
        return None
    if resolve_recipe_path(profile_id) is None:
        return None
    return profile_id


def load_benchmarks() -> dict[str, Any]:
    if not BENCHMARKS_FILE.is_file():
        return {}
    data = load_yaml(BENCHMARKS_FILE)
    profiles = data.get("profiles") or {}
    return profiles if isinstance(profiles, dict) else {}


def save_benchmarks(profiles: dict[str, Any]) -> None:
    BENCHMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BENCHMARKS_FILE.write_text(
        yaml.safe_dump({"profiles": profiles}, sort_keys=False, default_flow_style=False)
    )


def benchmark_for_profile(profile_id: str) -> dict[str, Any] | None:
    entry = load_benchmarks().get(profile_id)
    return entry if isinstance(entry, dict) else None


def make_bench_run_id(measured_at: str) -> str:
    slug = re.sub(r"[^0-9TZ]", "", measured_at.replace("+00:00", "Z"))[:17]
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def _chown_benchmark_history_if_root(path: Path) -> None:
    if os.geteuid() != 0:
        return
    try:
        import pwd

        pw = pwd.getpwnam(BENCHMARK_HISTORY_OWNER)
        os.chown(path, pw.pw_uid, pw.pw_gid)
    except (KeyError, OSError):
        pass


def _ensure_benchmark_history_file() -> None:
    if BENCHMARK_HISTORY_FILE.is_file():
        _chown_benchmark_history_if_root(BENCHMARK_HISTORY_FILE)
        return
    BENCHMARK_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if BENCHMARK_HISTORY_LEGACY.is_file():
        BENCHMARK_HISTORY_FILE.write_text(BENCHMARK_HISTORY_LEGACY.read_text())
        _chown_benchmark_history_if_root(BENCHMARK_HISTORY_FILE)


def load_benchmark_history_store() -> dict[str, Any]:
    _ensure_benchmark_history_file()
    ensure_benchmark_history_migrated()
    if not BENCHMARK_HISTORY_FILE.is_file():
        return {"profiles": {}}
    data = load_yaml(BENCHMARK_HISTORY_FILE)
    profiles = data.get("profiles") or {}
    if not isinstance(profiles, dict):
        profiles = {}
    return {"profiles": profiles, "_meta": data.get("_meta") or {}}


def save_benchmark_history_store(store: dict[str, Any]) -> None:
    BENCHMARK_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"_meta": store.get("_meta") or {}, "profiles": store.get("profiles") or {}}
    BENCHMARK_HISTORY_FILE.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    )
    _chown_benchmark_history_if_root(BENCHMARK_HISTORY_FILE)


def ensure_benchmark_history_migrated() -> None:
    global _history_migrated
    if _history_migrated:
        return
    _history_migrated = True
    store = {"profiles": {}, "_meta": {}}
    if BENCHMARK_HISTORY_FILE.is_file():
        try:
            data = load_yaml(BENCHMARK_HISTORY_FILE)
            store["profiles"] = data.get("profiles") or {}
            store["_meta"] = data.get("_meta") or {}
            if not isinstance(store["profiles"], dict):
                store["profiles"] = {}
        except SystemExit:
            store["profiles"] = {}
    if store["_meta"].get("migrated_from_latest"):
        return
    latest = load_benchmarks()
    for profile_id, entry in latest.items():
        if not isinstance(entry, dict) or entry.get("tok_s") is None:
            continue
        prof = store["profiles"].setdefault(profile_id, {"runs": []})
        runs = prof.setdefault("runs", [])
        if runs:
            continue
        measured_at = str(entry.get("measured_at") or datetime.now(timezone.utc).isoformat())
        run = {
            "id": make_bench_run_id(measured_at),
            "measured_at": measured_at,
            "method": entry.get("method"),
            "engine": entry.get("engine"),
            "tok_s": entry.get("tok_s"),
            "source": "import",
            "note": "",
            "tags": [],
        }
        for key in (
            "completion_tokens",
            "prompt_tokens",
            "elapsed_s",
            "tok_s_min",
            "tok_s_max",
            "sessions",
            "turns_per_session",
            "run_tok_s",
        ):
            if entry.get(key) is not None:
                run[key] = entry[key]
        if entry.get("note"):
            run["system_note"] = entry["note"]
        runs.append(run)
        entry_copy = dict(entry)
        entry_copy["latest_run_id"] = run["id"]
        latest[profile_id] = entry_copy
    store["_meta"]["migrated_from_latest"] = datetime.now(timezone.utc).isoformat()
    save_benchmark_history_store(store)
    if latest:
        save_benchmarks(latest)


def bench_history_runs(profile_id: str) -> list[dict[str, Any]]:
    store = load_benchmark_history_store()
    prof = store["profiles"].get(profile_id) or {}
    runs = prof.get("runs") or []
    return [r for r in runs if isinstance(r, dict)]


def bench_history_count(profile_id: str) -> int:
    return len(bench_history_runs(profile_id))


def append_benchmark_history_run(
    profile_id: str,
    entry: dict[str, Any],
    *,
    system_note: str | None = None,
    source: str = "auto",
) -> dict[str, Any]:
    store = load_benchmark_history_store()
    prof = store["profiles"].setdefault(profile_id, {"runs": []})
    runs = prof.setdefault("runs", [])
    measured_at = str(entry.get("measured_at") or datetime.now(timezone.utc).isoformat())
    run: dict[str, Any] = {
        "id": make_bench_run_id(measured_at),
        "measured_at": measured_at,
        "method": entry.get("method"),
        "engine": entry.get("engine"),
        "tok_s": entry.get("tok_s"),
        "source": source,
        "note": "",
        "tags": [],
    }
    for key in (
        "completion_tokens",
        "prompt_tokens",
        "elapsed_s",
        "tok_s_min",
        "tok_s_max",
        "sessions",
        "turns_per_session",
        "run_tok_s",
    ):
        if entry.get(key) is not None:
            run[key] = entry[key]
    if system_note:
        run["system_note"] = system_note
    runs.append(run)
    save_benchmark_history_store(store)
    return run


def list_bench_history(
    profile_id: str, *, limit: int = 50
) -> list[dict[str, Any]]:
    runs = bench_history_runs(profile_id)
    runs_sorted = sorted(
        runs,
        key=lambda r: str(r.get("measured_at") or ""),
        reverse=True,
    )
    return runs_sorted[: max(1, min(limit, 200))]


def get_bench_history_run(profile_id: str, run_id: str) -> dict[str, Any] | None:
    for run in bench_history_runs(profile_id):
        if run.get("id") == run_id:
            return run
    return None


def update_bench_history_run(
    profile_id: str,
    run_id: str,
    *,
    note: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    store = load_benchmark_history_store()
    prof = store["profiles"].get(profile_id)
    if not prof:
        raise RuntimeError(f"no benchmark history for profile {profile_id}")
    runs = prof.get("runs") or []
    for run in runs:
        if run.get("id") != run_id:
            continue
        if note is not None:
            run["note"] = note
        if tags is not None:
            run["tags"] = tags
        run["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_benchmark_history_store(store)
        return run
    raise RuntimeError(f"benchmark run not found: {run_id}")


def validate_history_profile(profile_id: str) -> str | None:
    profile_id = profile_id.strip()
    if not profile_id or not PROFILE_ID_RE.match(profile_id):
        return None
    if resolve_recipe_path(profile_id) is None:
        return None
    return profile_id


_MODEL_FAMILY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"qwen3[\.\-_]?coder[\.\-_]?next|qwen[\.\-_]?coder[\.\-_]?next", re.I), "Qwen3 Coder Next"),
    (re.compile(r"qwen3[\.\-_]?coder|qwen[\.\-_]?coder", re.I), "Qwen3 Coder"),
    (re.compile(r"qwen3[\.\-_]?6|qwen36|qwen3-6", re.I), "Qwen3.6"),
    (re.compile(r"qwen3[\.\-_]?5|qwen35", re.I), "Qwen3.5"),
    (re.compile(r"qwen3[\.\-_]?30|qwen3-30", re.I), "Qwen3 30B"),
    (re.compile(r"gemma[\.\-_]?4", re.I), "Gemma 4"),
    (re.compile(r"hermes[\.\-_]?4", re.I), "Hermes 4"),
    (re.compile(r"deepseek[\.\-_]?r1", re.I), "DeepSeek R1"),
    (re.compile(r"deepseek[\.\-_]?v4", re.I), "DeepSeek V4"),
    (re.compile(r"phi[\.\-_]?4", re.I), "Phi-4"),
    (re.compile(r"step[\.\-_]?3[\.\-_]?7", re.I), "Step 3.7"),
    (re.compile(r"nemotron[\.\-_]?3", re.I), "Nemotron 3"),
    (re.compile(r"minimax[\.\-_]?m2", re.I), "MiniMax M2"),
    (re.compile(r"gpt[\.\-_]?oss", re.I), "GPT-OSS"),
    (re.compile(r"glm[\.\-_]?4", re.I), "GLM 4"),
]


def _family_haystack(recipe: dict[str, Any]) -> str:
    parts = [
        recipe.get("name"),
        recipe.get("id"),
        recipe.get("inventory_path"),
        recipe.get("catalog_id"),
        recipe.get("served_name"),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def infer_model_family(recipe: dict[str, Any]) -> str:
    explicit = str(recipe.get("model_family") or "").strip()
    if explicit:
        return explicit
    hay = _family_haystack(recipe)
    for pattern, label in _MODEL_FAMILY_RULES:
        if pattern.search(hay):
            return label
    inv = str(recipe.get("inventory_path") or recipe.get("catalog_id") or "").strip()
    slug = inv.split("/", 1)[1] if "/" in inv else (inv or str(recipe.get("id") or "Other"))
    return slug.replace("-", " ").replace("_", " ").title()


def recipe_public(recipe: dict[str, Any]) -> dict[str, Any]:
    profile_id = recipe.get("id")
    bench = benchmark_for_profile(profile_id) if profile_id else None
    out = {
        "id": profile_id,
        "name": recipe.get("name"),
        "engine": recipe.get("engine"),
        "tier": recipe.get("tier"),
        "port": recipe.get("port"),
        "served_name": recipe.get("served_name"),
        "inventory_path": recipe.get("inventory_path") or recipe.get("catalog_id"),
        "model_family": infer_model_family(recipe),
        "tags": recipe.get("tags") or [],
        "notes": (recipe.get("notes") or "").strip(),
    }
    if bench and bench.get("tok_s") is not None and bench.get("method") in BENCH_METHODS:
        out["tok_s"] = bench.get("tok_s")
        out["tok_s_method"] = bench.get("method")
        out["tok_s_measured_at"] = bench.get("measured_at")
        if bench.get("latest_run_id"):
            out["latest_run_id"] = bench.get("latest_run_id")
        out["bench_run_count"] = bench_history_count(profile_id) if profile_id else 0
    return out


def record_benchmark(
    profile_id: str,
    recipe: dict[str, Any],
    tok_s: float,
    *,
    method: str,
    completion_tokens: int | None = None,
    prompt_tokens: int | None = None,
    elapsed_s: float | None = None,
    note: str | None = None,
    tok_s_min: float | None = None,
    tok_s_max: float | None = None,
    sessions: int | None = None,
    turns_per_session: int | None = None,
    run_tok_s: list[float] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    engine = recipe.get("engine")
    profiles = load_benchmarks()
    entry = {
        "tok_s": round(float(tok_s), 1),
        "engine": engine,
        "method": method,
        "measured_at": now,
    }
    if completion_tokens is not None:
        entry["completion_tokens"] = completion_tokens
    if prompt_tokens is not None:
        entry["prompt_tokens"] = prompt_tokens
    if elapsed_s is not None:
        entry["elapsed_s"] = round(elapsed_s, 2)
    if tok_s_min is not None:
        entry["tok_s_min"] = round(float(tok_s_min), 1)
    if tok_s_max is not None:
        entry["tok_s_max"] = round(float(tok_s_max), 1)
    if sessions is not None:
        entry["sessions"] = sessions
    if turns_per_session is not None:
        entry["turns_per_session"] = turns_per_session
    if run_tok_s:
        entry["run_tok_s"] = [round(float(v), 1) for v in run_tok_s]
    if note:
        entry["note"] = note
    run = append_benchmark_history_run(
        profile_id, entry, system_note=note, source="auto"
    )
    entry["latest_run_id"] = run["id"]
    profiles[profile_id] = entry
    save_benchmarks(profiles)

    inv_path = recipe.get("inventory_path") or recipe.get("catalog_id")
    if inv_path:
        if VERIFY_FILE.is_file():
            store = load_yaml(VERIFY_FILE)
        else:
            store = {"models": {}}
        models = store.setdefault("models", {})
        model_entry = models.setdefault(str(inv_path), {})
        model_entry["tok_s"] = entry["tok_s"]
        model_entry["tok_s_engine"] = engine
        model_entry["tok_s_profile"] = profile_id
        model_entry["updated_at"] = now
        if note:
            model_entry["note"] = note
        VERIFY_FILE.write_text(
            yaml.safe_dump(store, sort_keys=False, default_flow_style=False)
        )

    trigger_inventory_rebuild()
    return entry


BENCH_WARMUP_SESSIONS = 1
BENCH_MEASURED_SESSIONS = 3
BENCH_TURNS_PER_SESSION = 3
BENCH_MAX_TOKENS = 256
BENCH_MIN_COMPLETION_TOKENS = 48
BENCH_TEMPERATURE = 0.0
BENCH_SYSTEM = (
    "You are a helpful assistant running a throughput benchmark. "
    "Follow instructions precisely and write substantive responses."
)
BENCH_USER_TURNS = [
    (
        "Task: design a small REST API for a model inventory service. "
        "Reply with exactly 8 numbered bullets; each bullet must be one full sentence."
    ),
    (
        "Expand bullets 3 and 4 into Python pseudocode with comments. "
        "Include at least 20 lines of code total."
    ),
    (
        "List 6 edge cases this API must handle and one pytest idea for each. "
        "Use a numbered list with two sentences per item."
    ),
]


def _chat_completion(
    port: int,
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    min_tokens: int,
    timeout: float = 180.0,
) -> tuple[dict[str, Any], float]:
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "min_tokens": min_tokens,
            "temperature": BENCH_TEMPERATURE,
        }
    ).encode()
    req = Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    elapsed = time.perf_counter() - start
    return payload, elapsed


def _completion_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    if completion_tokens is not None:
        return int(completion_tokens)
    choice = (payload.get("choices") or [{}])[0]
    text = choice.get("message", {}).get("content") or choice.get("text") or ""
    return max(1, len(text.split()))


def _assistant_text(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    return (choice.get("message", {}).get("content") or choice.get("text") or "").strip()


def _bench_agent_session(
    port: int,
    model: str,
    turn_prompts: list[str],
) -> tuple[int, int, float]:
    messages: list[dict[str, str]] = [{"role": "system", "content": BENCH_SYSTEM}]
    total_completion = 0
    total_prompt = 0
    total_elapsed = 0.0

    for user_text in turn_prompts:
        messages.append({"role": "user", "content": user_text})
        payload, elapsed = _chat_completion(
            port,
            model,
            messages,
            max_tokens=BENCH_MAX_TOKENS,
            min_tokens=BENCH_MIN_COMPLETION_TOKENS,
        )
        completion_tokens = _completion_tokens(payload)
        if completion_tokens < BENCH_MIN_COMPLETION_TOKENS:
            retry_text = user_text + " Write a longer, more detailed response."
            payload, retry_elapsed = _chat_completion(
                port,
                model,
                messages[:-1] + [{"role": "user", "content": retry_text}],
                max_tokens=BENCH_MAX_TOKENS,
                min_tokens=BENCH_MIN_COMPLETION_TOKENS,
            )
            elapsed += retry_elapsed
            completion_tokens = _completion_tokens(payload)
        if completion_tokens < BENCH_MIN_COMPLETION_TOKENS:
            raise RuntimeError(
                f"benchmark turn too short ({completion_tokens} tok) — model stopped early"
            )

        usage = payload.get("usage") or {}
        total_completion += completion_tokens
        total_prompt += int(usage.get("prompt_tokens") or 0)
        total_elapsed += elapsed
        messages.append({"role": "assistant", "content": _assistant_text(payload)})

    return total_completion, total_prompt, total_elapsed


def run_benchmark(
    *,
    warmup_sessions: int = BENCH_WARMUP_SESSIONS,
    measured_sessions: int = BENCH_MEASURED_SESSIONS,
    turns_per_session: int = BENCH_TURNS_PER_SESSION,
) -> dict[str, Any]:
    active = detect_active_profile()
    if not active:
        raise RuntimeError("no active profile")
    recipe = active["recipe"]
    profile_id = active["profile"]
    if not engine_ready(recipe):
        raise RuntimeError("active profile not ready — wait for /v1/models")

    port = int(recipe.get("port") or 0)
    served = recipe.get("served_name")
    turn_prompts = BENCH_USER_TURNS[:turns_per_session]
    if len(turn_prompts) < turns_per_session:
        raise RuntimeError("benchmark turn prompts misconfigured")

    for _ in range(warmup_sessions):
        _bench_agent_session(port, served, turn_prompts)

    run_rates: list[float] = []
    total_completion = 0
    total_prompt = 0
    total_elapsed = 0.0
    for _ in range(measured_sessions):
        completion_tokens, prompt_tokens, elapsed = _bench_agent_session(
            port, served, turn_prompts
        )
        if elapsed <= 0:
            raise RuntimeError("benchmark elapsed time was zero")
        run_rates.append(completion_tokens / elapsed)
        total_completion += completion_tokens
        total_prompt += prompt_tokens
        total_elapsed += elapsed

    tok_s = sum(run_rates) / len(run_rates)
    bench = record_benchmark(
        profile_id,
        recipe,
        tok_s,
        method="bench-agent",
        completion_tokens=total_completion,
        prompt_tokens=total_prompt,
        elapsed_s=total_elapsed,
        tok_s_min=min(run_rates),
        tok_s_max=max(run_rates),
        sessions=measured_sessions,
        turns_per_session=turns_per_session,
        run_tok_s=run_rates,
        note=(
            f"agent bench avg {tok_s:.1f} tok/s over {measured_sessions} sessions "
            f"× {turns_per_session} turns ({total_completion} tok in {total_elapsed:.1f}s)"
        ),
    )
    return {
        "profile": profile_id,
        "served_name": served,
        "tok_s": bench["tok_s"],
        "tok_s_min": bench.get("tok_s_min"),
        "tok_s_max": bench.get("tok_s_max"),
        "run_tok_s": run_rates,
        "sessions": measured_sessions,
        "turns_per_session": turns_per_session,
        "completion_tokens": total_completion,
        "prompt_tokens": total_prompt,
        "elapsed_s": round(total_elapsed, 2),
        "benchmark": bench,
    }


def engine_ready(recipe: dict[str, Any]) -> bool:
    port = int(recipe.get("port") or 0)
    if not port:
        return False
    served = served_name_from_port(port)
    return served == recipe.get("served_name")


def read_pid_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        path.unlink(missing_ok=True)
        return None
    return pid


def tail_log(path: Path, lines: int = 12) -> list[str]:
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-lines:]


def _read_switch_meta() -> dict[str, Any]:
    if not SWITCH_META_FILE.is_file():
        return {}
    try:
        data = json.loads(SWITCH_META_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_switch_meta(profile_id: str) -> None:
    SWITCH_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    SWITCH_META_FILE.write_text(
        json.dumps(
            {
                "profile": profile_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )


def _clear_switch_meta() -> None:
    SWITCH_META_FILE.unlink(missing_ok=True)


def _switch_target_profile() -> str | None:
    profile_id = _read_switch_meta().get("profile")
    if isinstance(profile_id, str) and profile_id.strip():
        return profile_id.strip()
    if not SWITCH_LOG_FILE.is_file():
        return None
    try:
        for line in SWITCH_LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[:5]:
            match = SWITCH_LOG_PROFILE_RE.match(line.strip())
            if match:
                return match.group(1)
    except OSError:
        return None
    return None


def active_switch_job() -> dict[str, Any]:
    pid = read_pid_file(SWITCH_PID_FILE)
    if not pid:
        SWITCH_PID_FILE.unlink(missing_ok=True)
        _clear_switch_meta()
        return {"running": False}
    job: dict[str, Any] = {
        "running": True,
        "pid": pid,
        "log": SWITCH_LOG_FILE.name,
        "log_tail": tail_log(SWITCH_LOG_FILE),
    }
    meta = _read_switch_meta()
    profile_id = meta.get("profile") or _switch_target_profile()
    if isinstance(profile_id, str) and profile_id.strip():
        job["profile"] = profile_id.strip()
    if isinstance(meta.get("started_at"), str):
        job["started_at"] = meta["started_at"]
    return job


def _read_bench_result() -> dict[str, Any] | None:
    if not BENCH_RESULT_FILE.is_file():
        return None
    try:
        data = json.loads(BENCH_RESULT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_bench_result(payload: dict[str, Any]) -> None:
    BENCH_RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    BENCH_RESULT_FILE.write_text(json.dumps(payload), encoding="utf-8")


def active_bench_job() -> dict[str, Any]:
    pid = read_pid_file(BENCH_PID_FILE)
    if pid:
        return {"running": True, "pid": pid}
    BENCH_PID_FILE.unlink(missing_ok=True)
    result = _read_bench_result()
    if not result:
        return {"running": False}
    out: dict[str, Any] = {"running": False, "result": result}
    if not result.get("ok", True):
        out["error"] = result.get("error") or "benchmark failed"
    return out


def start_bench_job() -> tuple[bool, str, dict[str, Any]]:
    if active_switch_job().get("running"):
        return False, "profile switch in progress", active_switch_job()

    job = active_bench_job()
    if job.get("running"):
        return False, "benchmark already running", job

    active = detect_active_profile()
    if not active:
        return False, "no active profile", {}
    if not engine_ready(active["recipe"]):
        return False, "active profile not ready — wait for /v1/models", {}

    BENCH_RESULT_FILE.unlink(missing_ok=True)
    BENCH_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "spark-inference.py"), "bench", "--write-result"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    BENCH_PID_FILE.write_text(str(proc.pid))
    return True, "started", {"running": True, "pid": proc.pid}


def engine_log_file(recipe: dict[str, Any] | None) -> Path:
    if not recipe:
        return LOG_DIR / "llama-server.log"
    if recipe.get("engine") == "eugr":
        return SWITCH_LOG_FILE
    return LOG_DIR / "llama-server.log"


def api_profiles(active_id: str | None = None) -> list[dict[str, Any]]:
    profiles = []
    production = set(enabled_profiles())
    for profile_id in list_recipe_ids():
        recipe = load_recipe(profile_id)
        item = recipe_public(recipe)
        item["lifecycle"] = recipe.get("lifecycle")
        item["enabled"] = profile_id in production
        item["switchable"] = profile_id in switchable_profile_ids()
        item["active"] = profile_id == active_id
        if active_id == profile_id:
            item["ready"] = engine_ready(recipe)
            item["starting"] = not item["ready"] and (
                (recipe.get("engine") == "llamacpp" and llama_running())
                or (recipe.get("engine") == "eugr" and eugr_running())
            )
        else:
            item["ready"] = False
            item["starting"] = False
        profiles.append(item)
    return profiles


def api_loading_state(
    *,
    switch_job: dict[str, Any] | None = None,
    active_id: str | None = None,
    recipe: dict[str, Any] | None = None,
    ready: bool = False,
    starting: bool = False,
    active_started_at: str | None = None,
) -> dict[str, Any] | None:
    switch_job = switch_job if switch_job is not None else active_switch_job()
    if switch_job.get("running"):
        started_at = switch_job.get("started_at")
        profile_id = switch_job.get("profile")
        if not profile_id:
            return {"phase": "switch", "profile": None, "name": None, "started_at": started_at}
        try:
            target = load_recipe(profile_id)
            name = target.get("name") or profile_id
        except SystemExit:
            name = profile_id
        return {
            "phase": "switch",
            "profile": profile_id,
            "name": name,
            "started_at": started_at,
        }

    if active_id and recipe and not ready:
        phase = "model" if starting else "waiting"
        return {
            "phase": phase,
            "profile": active_id,
            "name": recipe.get("name") or active_id,
            "started_at": active_started_at,
        }
    return None


def api_status() -> dict[str, Any]:
    active = detect_active_profile()
    active_id = active["profile"] if active else None
    recipe = active["recipe"] if active else None
    ready = engine_ready(recipe) if recipe else False
    port = int(recipe.get("port") or 0) if recipe else None
    switch_job = active_switch_job()

    payload: dict[str, Any] = {
        "active": None,
        "loading": None,
        "profiles": api_profiles(active_id),
        "engines": {"eugr": eugr_running(), "llamacpp": llama_running()},
        "switch": switch_job,
        "bench": active_bench_job(),
        "urls": {
            "openwebui": "http://sparky:3000",
            "portal": "http://sparky/",
        },
    }

    if active and recipe:
        starting = not ready and (
            (recipe.get("engine") == "llamacpp" and llama_running())
            or (recipe.get("engine") == "eugr" and eugr_running())
        )
        payload["active"] = {
            **recipe_public(recipe),
            "started_at": (active.get("state") or {}).get("started_at"),
            "ready": ready,
            "starting": starting,
            "api_url": f"http://sparky:{port}/v1" if port else None,
            "log_file": engine_log_file(recipe).name,
        }
        payload["urls"]["api"] = payload["active"]["api_url"]
        bench = benchmark_for_profile(active_id)
        if bench:
            payload["active"]["benchmark"] = bench
    active_started_at = (active.get("state") or {}).get("started_at") if active else None
    payload["loading"] = api_loading_state(
        switch_job=switch_job,
        active_id=active_id,
        recipe=recipe,
        ready=ready,
        starting=bool(payload.get("active") and payload["active"].get("starting")),
        active_started_at=active_started_at,
    )

    payload["benchmarks"] = load_benchmarks()
    return payload


def start_switch_job(profile_id: str) -> tuple[bool, str, dict[str, Any]]:
    profile_id = validate_profile_id(profile_id)
    if not profile_id:
        return False, "unknown or disabled profile", {}

    if active_switch_job().get("running"):
        return False, "profile switch already running", active_switch_job()

    if active_bench_job().get("running"):
        return False, "benchmark running", active_bench_job()

    active = detect_active_profile()
    if active and active["profile"] == profile_id and engine_ready(active["recipe"]):
        return False, "profile already active", api_status()

    SWITCH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    SWITCH_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _write_switch_meta(profile_id)
    with SWITCH_LOG_FILE.open("w", encoding="utf-8") as log:
        log.write(f"==> switch to {profile_id} {datetime.now(timezone.utc).isoformat()}\n")
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "spark-inference.py"), "up", profile_id],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    SWITCH_PID_FILE.write_text(str(proc.pid))
    job = active_switch_job()
    job["profile"] = profile_id
    job["started_at"] = datetime.now(timezone.utc).isoformat()
    return True, "started", job


def api_down() -> dict[str, Any]:
    if active_switch_job().get("running"):
        raise RuntimeError("profile switch in progress")
    if active_bench_job().get("running"):
        raise RuntimeError("benchmark in progress")
    cmd_down()
    return api_status()


def api_route_path(path: str) -> str:
    return path.split("?", 1)[0].rstrip("/") or "/"


def api_dispatch(
    method: str, path: str, body: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]] | None:
    """HTTP route table for spark-inference-api (hot-reloaded with this module)."""
    body = body or {}
    route = api_route_path(path)

    if method == "GET":
        if route == "/api/inference/status":
            return 200, {"ok": True, **api_status()}
        if route == "/api/inference/recipes":
            return 200, {"ok": True, "recipes": api_recipe_list()}
        hist_match = BENCH_HISTORY_LIST_RE.match(route)
        if hist_match:
            profile = validate_history_profile(hist_match.group(1))
            if not profile:
                return 404, {"ok": False, "error": "unknown profile"}
            limit = 50
            if "?" in path:
                for part in path.split("?", 1)[1].split("&"):
                    if part.startswith("limit="):
                        try:
                            limit = max(1, min(200, int(part.split("=", 1)[1])))
                        except ValueError:
                            pass
            runs = list_bench_history(profile, limit=limit)
            latest = benchmark_for_profile(profile)
            return 200, {
                "ok": True,
                "profile": profile,
                "latest": latest,
                "runs": runs,
                "count": bench_history_count(profile),
            }
        run_match = BENCH_HISTORY_RUN_RE.match(route)
        if run_match:
            profile = validate_history_profile(run_match.group(1))
            if not profile:
                return 404, {"ok": False, "error": "unknown profile"}
            run = get_bench_history_run(profile, run_match.group(2))
            if not run:
                return 404, {"ok": False, "error": "run not found"}
            return 200, {"ok": True, "profile": profile, "run": run}
        if path.startswith("/api/inference/logs"):
            lines = 30
            if "?" in path:
                for part in path.split("?", 1)[1].split("&"):
                    if part.startswith("lines="):
                        try:
                            lines = max(5, min(200, int(part.split("=", 1)[1])))
                        except ValueError:
                            pass
            active = detect_active_profile()
            recipe = active["recipe"] if active else None
            log_path = engine_log_file(recipe)
            return 200, {
                "ok": True,
                "file": log_path.name,
                "lines": tail_log(log_path, lines),
                "switch": active_switch_job(),
            }
        return None

    if method == "PATCH":
        run_match = BENCH_HISTORY_RUN_RE.match(route)
        if not run_match:
            return None
        profile = validate_history_profile(run_match.group(1))
        if not profile:
            return 404, {"ok": False, "error": "unknown profile"}
        note = body.get("note")
        tags = body.get("tags")
        if note is None and tags is None:
            return 400, {"ok": False, "error": "note or tags required"}
        if tags is not None and not isinstance(tags, list):
            return 400, {"ok": False, "error": "tags must be a list"}
        try:
            run = update_bench_history_run(
                profile,
                run_match.group(2),
                note=str(note) if note is not None else None,
                tags=[str(t) for t in tags] if tags is not None else None,
            )
        except RuntimeError as exc:
            return 404, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "profile": profile, "run": run}

    if method != "POST":
        return None

    if route == "/api/inference/switch":
        if not body.get("confirm"):
            return 400, {"ok": False, "error": "confirmation required"}
        profile = str(body.get("profile", "")).strip()
        if not validate_profile_id(profile):
            return 400, {"ok": False, "error": "unknown or disabled profile"}
        recipe = load_recipe(profile)
        if recipe.get("tier") == "heavy" and not body.get("confirm_heavy"):
            return 400, {
                "ok": False,
                "error": "heavy tier requires confirm_heavy",
                "profile": profile,
                "notes": (recipe.get("notes") or "").strip(),
            }
        ok, message, job = start_switch_job(profile)
        if not ok:
            code = 409 if "already" in message else 400
            return code, {"ok": False, "error": message, "job": job}
        return 202, {"ok": True, "message": message, "profile": profile, "job": job}

    if route == "/api/inference/bench":
        ok, message, job = start_bench_job()
        if not ok:
            code = 409 if "already" in message or "progress" in message else 400
            return code, {"ok": False, "error": message, "bench": job}
        return 202, {"ok": True, "message": message, "bench": job}

    if route == "/api/inference/recipes/scaffold":
        if not body.get("confirm"):
            return 400, {"ok": False, "error": "confirmation required"}
        inv = str(body.get("inventory_path", "")).strip()
        engine = str(body.get("engine", "")).strip().lower()
        try:
            recipe = scaffold_recipe(
                inv,
                engine,
                name=str(body.get("name", "")).strip() or None,
                tier=str(body.get("tier", "")).strip() or None,
            )
        except RuntimeError as exc:
            return 400, {"ok": False, "error": str(exc)}
        pub = recipe_public(recipe)
        pub["lifecycle"] = recipe.get("lifecycle")
        return 201, {"ok": True, "recipe": pub}

    if route == "/api/inference/recipes/testing":
        if not body.get("confirm"):
            return 400, {"ok": False, "error": "confirmation required"}
        profile = str(body.get("profile", "")).strip()
        try:
            recipe = set_recipe_lifecycle(profile, LIFECYCLE_TESTING)
        except RuntimeError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "recipe": recipe_public(recipe)}

    if route == "/api/inference/recipes/promote":
        if not body.get("confirm"):
            return 400, {"ok": False, "error": "confirmation required"}
        profile = str(body.get("profile", "")).strip()
        try:
            recipe = promote_recipe(profile)
        except RuntimeError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "recipe": recipe_public(recipe)}

    if route == "/api/inference/recipes/discard":
        if not body.get("confirm"):
            return 400, {"ok": False, "error": "confirmation required"}
        profile = str(body.get("profile", "")).strip()
        try:
            discard_recipe(profile)
        except RuntimeError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "profile": profile}

    if route == "/api/inference/down":
        if not body.get("confirm"):
            return 400, {"ok": False, "error": "confirmation required"}
        try:
            status = api_down()
        except RuntimeError as exc:
            return 409, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "message": "stopped", **status}

    return None


def cmd_logs(profile_id: str | None) -> int:
    active = detect_active_profile()
    target = profile_id or (active["profile"] if active else None)
    if not target:
        raise SystemExit("no active profile — pass: spark-inference logs <profile>")

    recipe = load_recipe(target)
    if recipe.get("engine") == "eugr":
        run_script(SPARK_EUGR, "logs")
    else:
        run_script(SPARK_LLAMA, "logs")
    return 0


def cmd_bench_history_cli(argv: list[str]) -> int:
    if len(argv) < 3:
        raise SystemExit(
            "usage: spark-inference bench {history|show|note|latest} ..."
        )
    sub = argv[2]
    as_json = "--json" in argv

    if sub == "history":
        if len(argv) < 4:
            raise SystemExit("usage: spark-inference bench history <profile> [--json]")
        profile = validate_history_profile(argv[3])
        if not profile:
            raise SystemExit(f"unknown profile: {argv[3]}")
        limit = 50
        for i, arg in enumerate(argv):
            if arg == "--limit" and i + 1 < len(argv):
                try:
                    limit = max(1, min(200, int(argv[i + 1])))
                except ValueError:
                    pass
        runs = list_bench_history(profile, limit=limit)
        if as_json:
            print(
                json.dumps(
                    {
                        "profile": profile,
                        "latest": benchmark_for_profile(profile),
                        "runs": runs,
                        "count": bench_history_count(profile),
                    },
                    indent=2,
                )
            )
            return 0
        if not runs:
            print(f"No benchmark history for {profile}")
            return 0
        print(f"Benchmark history: {profile} ({bench_history_count(profile)} runs)")
        for run in runs:
            tok = run.get("tok_s")
            when = (run.get("measured_at") or "")[:19].replace("T", " ")
            note = (run.get("note") or "").strip()
            tag = f"  {note}" if note else ""
            print(f"  {when}  {tok} tok/s  {run.get('id')}{tag}")
        return 0

    if sub == "show":
        if len(argv) < 5:
            raise SystemExit("usage: spark-inference bench show <profile> <run_id> [--json]")
        profile = validate_history_profile(argv[3])
        if not profile:
            raise SystemExit(f"unknown profile: {argv[3]}")
        run = get_bench_history_run(profile, argv[4])
        if not run:
            raise SystemExit(f"run not found: {argv[4]}")
        if as_json:
            print(json.dumps({"profile": profile, "run": run}, indent=2))
        else:
            print(yaml.safe_dump(run, sort_keys=False, default_flow_style=False))
        return 0

    if sub == "latest":
        if len(argv) < 4:
            raise SystemExit("usage: spark-inference bench latest <profile> [--json]")
        profile = validate_history_profile(argv[3])
        if not profile:
            raise SystemExit(f"unknown profile: {argv[3]}")
        latest = benchmark_for_profile(profile)
        if not latest:
            raise SystemExit(f"no benchmark for {profile}")
        if as_json:
            print(json.dumps({"profile": profile, "latest": latest}, indent=2))
        else:
            print(yaml.safe_dump(latest, sort_keys=False, default_flow_style=False))
        return 0

    if sub == "note":
        if len(argv) < 5:
            raise SystemExit(
                "usage: spark-inference bench note <profile> <run_id> <text>"
            )
        profile = validate_history_profile(argv[3])
        if not profile:
            raise SystemExit(f"unknown profile: {argv[3]}")
        run_id = argv[4]
        text = " ".join(a for a in argv[5:] if a != "--json").strip()
        if not text:
            raise SystemExit("note text required")
        try:
            run = update_bench_history_run(profile, run_id, note=text)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        if as_json:
            print(json.dumps({"profile": profile, "run": run}, indent=2))
        else:
            print(f"Updated note on {run_id}")
        return 0

    raise SystemExit(f"unknown bench subcommand: {sub}")


def cmd_bench(write_result: bool = False) -> int:
    try:
        result = run_benchmark()
    except (RuntimeError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        if write_result:
            _write_bench_result({"ok": False, "error": str(exc)})
            BENCH_PID_FILE.unlink(missing_ok=True)
        raise SystemExit(str(exc)) from exc
    if write_result:
        _write_bench_result({"ok": True, **result})
        BENCH_PID_FILE.unlink(missing_ok=True)
    runs = ", ".join(f"{v:.1f}" for v in result.get("run_tok_s") or [])
    print(
        f"Benchmark {result['profile']}: {result['tok_s']:.1f} tok/s avg "
        f"({result['sessions']} sessions × {result['turns_per_session']} turns, "
        f"{result['completion_tokens']} tokens in {result['elapsed_s']:.1f}s)"
    )
    if runs:
        print(f"  session tok/s: {runs}")
    if result.get("tok_s_min") is not None and result.get("tok_s_max") is not None:
        print(
            f"  range: {result['tok_s_min']:.1f}–{result['tok_s_max']:.1f} tok/s"
        )
    return 0


def cmd_recipe(argv: list[str]) -> int:
    if len(argv) < 3:
        raise SystemExit(
            "usage: spark-inference recipe {list|scaffold|testing|promote|discard} ..."
        )
    sub = argv[2]
    if sub == "list":
        for item in api_recipe_list():
            print(
                f"{item['id']:<24} {item.get('lifecycle', '?'):<10} "
                f"{item.get('engine', '?'):<10} "
                f"{'on' if item.get('enabled') else 'off':<4} "
                f"{item.get('inventory_path') or '—'}"
            )
        return 0
    if sub == "scaffold":
        if len(argv) < 5:
            raise SystemExit(
                "usage: spark-inference recipe scaffold <lab/slug> <llamacpp|eugr>"
            )
        recipe = scaffold_recipe(argv[3], argv[4])
        print(f"Scaffolded draft {recipe['id']} -> {draft_recipe_path(recipe['id'])}")
        return 0
    if sub == "testing":
        if len(argv) < 4:
            raise SystemExit("usage: spark-inference recipe testing <profile>")
        recipe = set_recipe_lifecycle(argv[3], LIFECYCLE_TESTING)
        print(f"Marked testing: {recipe['id']}")
        return 0
    if sub == "promote":
        if len(argv) < 4:
            raise SystemExit("usage: spark-inference recipe promote <profile>")
        recipe = promote_recipe(argv[3])
        print(f"Promoted to production: {recipe['id']}")
        return 0
    if sub == "discard":
        if len(argv) < 4:
            raise SystemExit("usage: spark-inference recipe discard <profile>")
        discard_recipe(argv[3])
        print(f"Discarded draft: {argv[3]}")
        return 0
    raise SystemExit(f"unknown recipe subcommand: {sub}")


def usage() -> None:
    print(
        """Usage: spark-inference {list|status|up <profile>|down|logs [profile]|bench|recipe ...}

Recipe-driven inference control (Phase 5). One GPU workload at a time.
bench — multi-turn agent-style timing on the active profile (avg of 3 sessions).
recipe scaffold <lab/slug> <llamacpp|eugr> — Model Lab draft recipe
recipe testing|promote|discard <profile> — lifecycle (draft → testing → production)"""
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        usage()
        return 1

    cmd = argv[1]
    if cmd == "list":
        return cmd_list()
    if cmd == "status":
        return cmd_status()
    if cmd == "down":
        return cmd_down()
    if cmd == "up":
        if len(argv) < 3:
            raise SystemExit("usage: spark-inference up <profile>")
        return cmd_up(argv[2])
    if cmd == "logs":
        return cmd_logs(argv[2] if len(argv) > 2 else None)
    if cmd == "bench":
        if len(argv) > 2 and argv[2] in ("history", "show", "note", "latest"):
            return cmd_bench_history_cli(argv)
        return cmd_bench(write_result="--write-result" in argv)
    if cmd == "recipe":
        return cmd_recipe(argv)

    usage()
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc