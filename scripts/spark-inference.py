#!/opt/spark/venv/bin/python3
"""Phase 5 inference control plane — recipe-driven profile switch."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
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
SWITCH_LOG_FILE = ROOT / "logs" / "inference-switch-latest.log"
BENCH_PID_FILE = ROOT / "run" / "inference-bench.pid"
BENCH_RESULT_FILE = ROOT / "run" / "inference-bench-result.json"
LOG_DIR = ROOT / "logs"
BENCHMARKS_FILE = ROOT / "data" / "inference-benchmarks.yaml"
VERIFY_FILE = ROOT / "data" / "model-verification.yaml"
SPARK_EUGR = ROOT / "scripts" / "spark-eugr"
SPARK_LLAMA = ROOT / "scripts" / "spark-llama"
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
    gguf_dir = model_root / "gguf"
    if gguf_dir.is_dir():
        ggufs = sorted(gguf_dir.glob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True)
        if ggufs:
            return ggufs[0]
    candidates = sorted(model_root.rglob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True)
    return candidates[0] if candidates else None


def discover_nvfp4_dir(model_root: Path) -> Path | None:
    nvfp4 = model_root / "nvfp4"
    if nvfp4.is_dir() and any(nvfp4.iterdir()):
        return nvfp4
    return None


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
    model_dir = discover_nvfp4_dir(MODELS_ROOT / inventory_path)
    if model_dir is None:
        raise RuntimeError(f"no nvfp4 weights under /models/{inventory_path}")
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
  max_model_len: 65536
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
    --attention-backend flashinfer \\
    --moe-backend marlin \\
    --gpu-memory-utilization {{gpu_memory_utilization}} \\
    --max-model-len {{max_model_len}} \\
    --max-num-seqs {{max_num_seqs}} \\
    --max-num-batched-tokens {{max_num_batched_tokens}} \\
    --enable-chunked-prefill \\
    --enable-prefix-caching \\
    --load-format fastsafetensors
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

    subprocess.Popen(
        [str(ROOT / "scripts" / "spark-inventory-build")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    recipe["id"] = profile_id
    return recipe


def discard_recipe(profile_id: str) -> None:
    if profile_id in enabled_profiles():
        raise RuntimeError("cannot discard production profile — remove from inference-profiles.yaml first")
    draft_path = draft_recipe_path(profile_id)
    if draft_path.is_file():
        draft_path.unlink()
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
        "tags": recipe.get("tags") or [],
        "notes": (recipe.get("notes") or "").strip(),
    }
    if bench and bench.get("tok_s") is not None and bench.get("method") in BENCH_METHODS:
        out["tok_s"] = bench.get("tok_s")
        out["tok_s_method"] = bench.get("method")
        out["tok_s_measured_at"] = bench.get("measured_at")
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

    subprocess.Popen(
        [str(ROOT / "scripts" / "spark-inventory-build")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
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


def active_switch_job() -> dict[str, Any]:
    pid = read_pid_file(SWITCH_PID_FILE)
    if not pid:
        SWITCH_PID_FILE.unlink(missing_ok=True)
        return {"running": False}
    return {
        "running": True,
        "pid": pid,
        "log": SWITCH_LOG_FILE.name,
        "log_tail": tail_log(SWITCH_LOG_FILE),
    }


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


def api_status() -> dict[str, Any]:
    active = detect_active_profile()
    active_id = active["profile"] if active else None
    recipe = active["recipe"] if active else None
    ready = engine_ready(recipe) if recipe else False
    port = int(recipe.get("port") or 0) if recipe else None

    payload: dict[str, Any] = {
        "active": None,
        "profiles": api_profiles(active_id),
        "engines": {"eugr": eugr_running(), "llamacpp": llama_running()},
        "switch": active_switch_job(),
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