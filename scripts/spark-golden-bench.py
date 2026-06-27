#!/opt/spark/venv/bin/python3
"""Shared golden-workflow bench probes — 75% ctx fill, decode tok/s per (ctx, kv) cell."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
RECIPES = ROOT / "recipes"

FILL_RATIO = 0.75
HEADROOM_MIN = 8192
HEADROOM_FRAC = 0.10
READY_SECS = 600
BENCH_TIMEOUT = 900

# KV options to sweep at golden ctx (engine-specific; auto skipped)
KV_SWEEP_BY_ENGINE: dict[str, list[str]] = {
    "eugr": ["fp8", "auto"],
    "llamacpp": ["q8_0", "q4_0", "f16"],
    "ds4": ["q8_0"],
}

# Engines / families where KV dtype is not meaningfully swappable at runtime.
KV_SWEEP_ENGINES: frozenset[str] = frozenset({"llamacpp", "eugr"})


def kv_sweep_eligible(recipe: dict[str, Any], *, inventory_path: str | None = None) -> bool:
    """True when golden workflow should run kv_sweep for this model."""
    path = str(inventory_path or recipe.get("inventory_path") or "").lower()
    if "deepseek" in path:
        return False
    engine = str(recipe.get("engine") or "llamacpp")
    if engine not in KV_SWEEP_ENGINES:
        return False
    return len(kv_sweep_options(recipe)) > 0


def kv_sweep_skip_reason(recipe: dict[str, Any], *, inventory_path: str | None = None) -> str:
    path = str(inventory_path or recipe.get("inventory_path") or "").lower()
    if "deepseek" in path:
        return "deepseek architecture — KV sweep not applicable"
    engine = str(recipe.get("engine") or "llamacpp")
    if engine not in KV_SWEEP_ENGINES:
        return f"engine={engine} does not support KV cache dtype sweep"
    return "no KV sweep options"


def load_ctxmod():
    spec = importlib.util.spec_from_file_location(
        "ctx", ROOT / "scripts" / "spark-inference-context.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_benchv2():
    spec = importlib.util.spec_from_file_location(
        "benchv2", ROOT / "scripts" / "spark-inference-bench-v2.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_recipe(profile_id: str) -> dict[str, Any]:
    path = RECIPES / f"{profile_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"missing recipe: {path}")
    return yaml.safe_load(path.read_text()) or {}


def save_recipe(profile_id: str, recipe: dict[str, Any]) -> None:
    path = RECIPES / f"{profile_id}.yaml"
    path.write_text(yaml.safe_dump(recipe, sort_keys=False, default_flow_style=False))


def headroom(ctx: int) -> int:
    return max(HEADROOM_MIN, int(ctx * HEADROOM_FRAC))


def fill_target_for_ctx(ctx: int, *, fill_ratio: float = FILL_RATIO) -> int:
    usable = max(4096, ctx - headroom(ctx))
    return max(2048, int(usable * fill_ratio))


def golden_ctx_and_kv(recipe: dict[str, Any], ctxmod: Any) -> tuple[int, str]:
    block = recipe.get("context") or {}
    presets = block.get("presets") or {}
    golden = presets.get("golden") if isinstance(presets, dict) else None
    if isinstance(golden, dict) and golden.get("ctx"):
        return int(golden["ctx"]), str(golden.get("kv") or block.get("kv_default") or "q8_0")
    default = ctxmod.default_context(recipe) or 32768
    kv = str(block.get("kv_default") or ctxmod.default_kv(recipe))
    return int(default), kv


def kv_sweep_options(recipe: dict[str, Any]) -> list[str]:
    engine = str(recipe.get("engine") or "llamacpp")
    golden_kv = golden_ctx_and_kv(recipe, load_ctxmod())[1]
    opts = [kv for kv in KV_SWEEP_BY_ENGINE.get(engine, ["q8_0"]) if kv != "auto"]
    ordered: list[str] = []
    for kv in [golden_kv] + opts:
        if kv not in ordered:
            ordered.append(kv)
    return ordered


def run_cmd(cmd: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))


def loaded_ctx(port: int, data: dict[str, Any] | None = None) -> int | None:
    try:
        if data is None:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as resp:
                data = json.loads(resp.read().decode())
        row = (data.get("data") or [{}])[0]
        meta = row.get("meta") or {}
        if isinstance(meta, dict) and meta.get("n_ctx") is not None:
            return int(meta["n_ctx"])
        val = row.get("max_model_len") or row.get("n_ctx")
        return int(val) if val is not None else None
    except Exception:
        return None


def wait_ready(
    port: int,
    *,
    expected_ctx: int | None = None,
    timeout: int = READY_SECS,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as resp:
                if resp.status != 200:
                    time.sleep(5)
                    continue
                if expected_ctx is None:
                    return True
                loaded = loaded_ctx(port, data=json.loads(resp.read().decode()))
                if loaded is not None and abs(loaded - expected_ctx) <= 1024:
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def probe_cell(
    profile_id: str,
    recipe: dict[str, Any],
    *,
    ctx: int,
    kv: str,
    fill_ratio: float = FILL_RATIO,
    benchv2: Any | None = None,
    ready_timeout: int | None = None,
) -> dict[str, Any]:
    """Load at (ctx, kv), bench once at fill_ratio of usable window."""
    if benchv2 is None:
        benchv2 = load_benchv2()
    port = int(recipe.get("port") or 8081)
    served = str(recipe.get("served_name") or profile_id)
    engine = recipe.get("engine")
    fill = fill_target_for_ctx(ctx, fill_ratio=fill_ratio)
    row: dict[str, Any] = {
        "ctx": ctx,
        "kv": kv,
        "fill_target": fill,
        "fill_ratio": fill_ratio,
        "status": "pending",
    }

    run_cmd(["/usr/local/bin/spark", "inference", "down"], timeout=120)
    up = run_cmd(
        [
            "/usr/local/bin/spark",
            "inference",
            "up",
            profile_id,
            "--ctx",
            str(ctx),
            "--kv",
            kv,
        ],
        timeout=3600,
    )
    if up.returncode != 0:
        row["status"] = "load_fail"
        row["error"] = (up.stderr or up.stdout or "inference up failed")[-500:]
        return row

    timeout = ready_timeout
    if timeout is None:
        timeout = 1200 if ctx >= 1_048_576 else 900 if ctx >= 524_288 else READY_SECS
    if not wait_ready(port, expected_ctx=ctx, timeout=timeout):
        row["status"] = "load_fail"
        row["error"] = f"/v1/models not ready at ctx={ctx} kv={kv} within {timeout}s"
        return row

    loaded = loaded_ctx(port)
    row["loaded_ctx"] = loaded
    if loaded is not None and abs(loaded - ctx) > 1024:
        row["status"] = "load_fail"
        row["error"] = f"requested ctx={ctx} but loaded={loaded}"
        return row

    try:
        # Match spark inference bench: retries on 400/413/500, eugr tool fallback.
        stats = benchv2._bench_v2_session(
            port,
            served,
            fill_target_tokens=fill,
            engine=engine,
            use_tools=True,
        )
    except Exception as exc:
        row["status"] = "bench_fail"
        row["error"] = str(exc)[:500]
        return row

    row.update(
        {
            "status": "ok",
            "tok_s": round(stats["decode_tok_s"], 1),
            "fill_estimated": stats.get("context_fill_estimated_tokens"),
            "prefill_prompt_tokens": stats.get("prefill_prompt_tokens"),
            "decode_tokens": stats.get("decode_completion_tokens"),
            "decode_elapsed_s": round(stats.get("decode_elapsed_s") or 0, 2),
            "tool_ok": stats.get("tool_roundtrip_ok"),
            "method": "bench-agent-v2",
        }
    )
    return row


def _load_site_publish():
    spec = importlib.util.spec_from_file_location(
        "site_publish", ROOT / "scripts" / "spark-site-publish.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def merge_bench_matrix(
    profile_id: str,
    *,
    golden_cell: dict[str, Any] | None = None,
    kv_sweep: list[dict[str, Any]] | None = None,
    ctx_ladder: dict[str, Any] | None = None,
    fill_ratio: float = FILL_RATIO,
    publish_site: bool = True,
    skip_site_publish: bool = False,
) -> dict[str, Any] | None:
    """Persist unified bench_matrix on recipe.context."""
    recipe = load_recipe(profile_id)
    block = recipe.setdefault("context", {})
    matrix = block.setdefault("bench_matrix", {})
    matrix["version"] = "1.0"
    matrix["fill_ratio"] = fill_ratio
    matrix["updated_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    if golden_cell is not None:
        matrix["golden_cell"] = golden_cell
    if kv_sweep is not None:
        matrix["kv_sweep"] = kv_sweep
    if ctx_ladder is not None:
        matrix["ctx_ladder"] = ctx_ladder
    elif block.get("ctx_ladder"):
        matrix["ctx_ladder"] = block["ctx_ladder"]
    save_recipe(profile_id, recipe)

    publish_result = None
    if golden_cell is not None and publish_site and not skip_site_publish:
        try:
            sp = _load_site_publish()
            publish_result = sp.publish_golden_cell_to_site(
                profile_id, golden_cell, recipe
            )
        except Exception as exc:
            print(f"WARN site publish {profile_id}: {exc}", flush=True)
    return publish_result
