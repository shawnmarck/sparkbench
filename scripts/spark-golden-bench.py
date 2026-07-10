#!/opt/spark/venv/bin/python3
"""Shared golden-workflow bench probes — 75% ctx fill, decode tok/s per (ctx, kv) cell."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path("/opt/spark")
RECIPES = ROOT / "recipes"
RECIPES_DRAFTS = RECIPES / "drafts"

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

LIVE_PROBE_FILE = "live-probe.json"


def benchmaster_run_dir() -> Path | None:
    raw = os.environ.get("BENCHMASTER_RUN_DIR", "").strip()
    return Path(raw) if raw else None


def live_probe_path(run_dir: Path | None = None) -> Path | None:
    base = run_dir or benchmaster_run_dir()
    return (base / LIVE_PROBE_FILE) if base else None


def default_probe_substeps() -> list[dict[str, Any]]:
    return [
        {"id": "down", "label": "Stop prior inference", "state": "pending"},
        {"id": "up", "label": "Load model (inference up)", "state": "pending"},
        {"id": "ready", "label": "Wait for engine ready", "state": "pending"},
        {"id": "bench", "label": "Run benchmark", "state": "pending"},
    ]


def _set_substep(
    substeps: list[dict[str, Any]],
    step_id: str,
    state: str,
    *,
    detail: str | None = None,
) -> None:
    for row in substeps:
        if row.get("id") == step_id:
            row["state"] = state
            if detail is not None:
                row["detail"] = detail
            elif state == "pending":
                row.pop("detail", None)
            return


def write_live_probe(
    path: Path | None,
    substeps: list[dict[str, Any]],
    *,
    phase: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if path is None:
        return
    payload: dict[str, Any] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "substeps": substeps,
    }
    if extra:
        payload.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, path)


def read_live_probe(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


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


def resolve_recipe_path(profile_id: str) -> Path | None:
    """Production recipe wins over draft (matches spark-inference.py)."""
    prod = RECIPES / f"{profile_id}.yaml"
    if prod.is_file():
        return prod
    draft = RECIPES_DRAFTS / f"{profile_id}.yaml"
    if draft.is_file():
        return draft
    return None


def load_recipe(profile_id: str) -> dict[str, Any]:
    path = resolve_recipe_path(profile_id)
    if path is None:
        raise FileNotFoundError(
            f"missing recipe: {profile_id} (checked recipes/ and recipes/drafts/)"
        )
    return yaml.safe_load(path.read_text()) or {}


def save_recipe(profile_id: str, recipe: dict[str, Any]) -> None:
    path = resolve_recipe_path(profile_id) or (RECIPES / f"{profile_id}.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
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
    progress_path: Path | None = None,
    phase: str = "probe",
    preset: str | None = None,
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

    probe_path = progress_path or live_probe_path()
    substeps = default_probe_substeps()
    write_live_probe(
        probe_path,
        substeps,
        phase=phase,
        extra={"profile_id": profile_id, "ctx": ctx, "kv": kv},
    )

    def tick(step_id: str, state: str, detail: str | None = None) -> None:
        _set_substep(substeps, step_id, state, detail=detail)
        write_live_probe(
            probe_path,
            substeps,
            phase=phase,
            extra={"profile_id": profile_id, "ctx": ctx, "kv": kv},
        )

    tick("down", "running")
    run_cmd(["/usr/local/bin/spark", "inference", "down"], timeout=120)
    tick("down", "done")
    tick("up", "running", f"ctx={ctx} kv={kv}" + (f" preset={preset}" if preset else ""))
    up_cmd = [
        "/usr/local/bin/spark",
        "inference",
        "up",
        profile_id,
        "--ctx",
        str(ctx),
        "--kv",
        kv,
    ]
    if preset:
        up_cmd.extend(["--preset", preset])
    up = run_cmd(up_cmd, timeout=3600)
    try:
        if up.returncode != 0:
            tick("up", "failed", (up.stderr or up.stdout or "inference up failed")[-120:])
            row["status"] = "load_fail"
            row["error"] = (up.stderr or up.stdout or "inference up failed")[-500:]
            return row
        tick("up", "done")

        timeout = ready_timeout
        if timeout is None:
            timeout = 1200 if ctx >= 1_048_576 else 900 if ctx >= 524_288 else READY_SECS
        tick("ready", "running", f"/v1/models @ ctx={ctx} (up to {timeout}s)")
        if not wait_ready(port, expected_ctx=ctx, timeout=timeout):
            tick("ready", "failed", f"not ready within {timeout}s")
            row["status"] = "load_fail"
            row["error"] = f"/v1/models not ready at ctx={ctx} kv={kv} within {timeout}s"
            return row

        loaded = loaded_ctx(port)
        row["loaded_ctx"] = loaded
        if loaded is not None and abs(loaded - ctx) > 1024:
            tick("ready", "failed", f"loaded ctx={loaded}")
            row["status"] = "load_fail"
            row["error"] = f"requested ctx={ctx} but loaded={loaded}"
            return row
        tick("ready", "done", f"loaded ctx={loaded}")

        tick("bench", "running", f"fill ~{fill} tokens")
        try:
            stats = benchv2._bench_v2_session(
                port,
                served,
                fill_target_tokens=fill,
                engine=engine,
                use_tools=True,
            )
        except Exception as exc:
            tick("bench", "failed", str(exc)[:120])
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
        tick("bench", "done", f"{row['tok_s']} tok/s")
        return row
    finally:
        run_cmd(["/usr/local/bin/spark", "inference", "down"], timeout=120)


def probe_peak_cell(
    profile_id: str,
    recipe: dict[str, Any],
    *,
    preset: str = "batman_spark",
    fill_ratio: float = FILL_RATIO,
    benchv2: Any | None = None,
    ready_timeout: int | None = None,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    """Bench at extended multi-slot preset (e.g. batman -c 600000 -np 3 → ~200k/slot)."""
    if benchv2 is None:
        benchv2 = load_benchv2()
    port = int(recipe.get("port") or 8081)
    served = str(recipe.get("served_name") or profile_id)
    engine = recipe.get("engine")
    presets = {p["id"]: p for p in load_ctxmod().context_presets(recipe)}
    pcfg = presets.get(preset)
    if not pcfg or not pcfg.get("extended"):
        return {"status": "config_fail", "error": f"preset {preset!r} missing or not extended"}

    row: dict[str, Any] = {
        "preset": preset,
        "pool_ctx": int(pcfg["ctx"]),
        "np": int(pcfg.get("np") or 1),
        "kv": str(pcfg.get("kv") or "q8_0"),
        "fill_ratio": fill_ratio,
        "status": "pending",
    }

    probe_path = progress_path or live_probe_path()
    substeps = default_probe_substeps()
    write_live_probe(
        probe_path,
        substeps,
        phase="peak_cell",
        extra={"profile_id": profile_id, "preset": preset},
    )

    def tick(step_id: str, state: str, detail: str | None = None) -> None:
        _set_substep(substeps, step_id, state, detail=detail)
        write_live_probe(
            probe_path,
            substeps,
            phase="peak_cell",
            extra={"profile_id": profile_id, "preset": preset},
        )

    tick("down", "running")
    run_cmd(["/usr/local/bin/spark", "inference", "down"], timeout=120)
    tick("down", "done")
    tick("up", "running", f"preset={preset}")
    up = run_cmd(
        [
            "/usr/local/bin/spark",
            "inference",
            "up",
            profile_id,
            "--preset",
            preset,
        ],
        timeout=3600,
    )
    ok = False
    try:
        if up.returncode != 0:
            tick("up", "failed", (up.stderr or up.stdout or "inference up failed")[-120:])
            row["status"] = "load_fail"
            row["error"] = (up.stderr or up.stdout or "inference up failed")[-500:]
            return row
        tick("up", "done")

        timeout = ready_timeout or 1800
        tick("ready", "running", f"up to {timeout}s")
        if not wait_ready(port, expected_ctx=None, timeout=timeout):
            tick("ready", "failed", f"not ready within {timeout}s")
            row["status"] = "load_fail"
            row["error"] = f"/v1/models not ready within {timeout}s"
            return row

        loaded = loaded_ctx(port)
        row["loaded_ctx"] = loaded
        if loaded is None or loaded < 131072:
            tick("ready", "failed", f"loaded ctx={loaded}")
            row["status"] = "load_fail"
            row["error"] = f"expected per-slot ctx >= 131072, loaded={loaded}"
            return row
        tick("ready", "done", f"per-slot ctx={loaded}")

        fill = fill_target_for_ctx(int(loaded), fill_ratio=fill_ratio)
        row["fill_target"] = fill
        tick("bench", "running", f"fill ~{fill} tokens")
        try:
            stats = benchv2._bench_v2_session(
                port,
                served,
                fill_target_tokens=fill,
                engine=engine,
                use_tools=True,
            )
        except Exception as exc:
            tick("bench", "failed", str(exc)[:120])
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
        tick("bench", "done", f"{row['tok_s']} tok/s per slot")
        ok = True
        return row
    finally:
        if not ok:
            run_cmd(["/usr/local/bin/spark", "inference", "down"], timeout=120)


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
    peak_cell: dict[str, Any] | None = None,
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
    if peak_cell is not None:
        matrix["peak_cell"] = peak_cell
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
