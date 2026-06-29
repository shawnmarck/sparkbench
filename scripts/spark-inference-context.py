"""Context window resolution, launch overrides, and fit recommendations."""
from __future__ import annotations

import copy
import json
import re
import shlex
from pathlib import Path
from typing import Any

ROOT = Path("/opt/spark")
MODELS_ROOT = Path("/models")
LAUNCH_OVERRIDES_FILE = ROOT / "run" / "inference-launch-overrides.json"
EUgr_LAUNCH_DIR = ROOT / "run" / "eugr-launch"
LLAMA_LAUNCH_DIR = ROOT / "run" / "llama-launch"

KV_BYTES_PER_TOKEN: dict[str, int] = {
    "auto": 192,
    "fp8": 96,
    "q8_0": 96,
    "q4_0": 48,
    "f16": 192,
}

LLAMA_KV_MAP = {
    "auto": None,
    "fp8": "q8_0",
    "q8_0": "q8_0",
    "q4_0": "q4_0",
    "f16": "f16",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_launch_overrides() -> dict[str, Any]:
    return _read_json(LAUNCH_OVERRIDES_FILE)


def write_launch_overrides(profile_id: str, ctx: int, kv: str, *, preset: str | None = None) -> dict[str, Any]:
    payload = {
        "profile": profile_id,
        "ctx": int(ctx),
        "kv": str(kv or "auto"),
    }
    if preset:
        payload["preset"] = preset
    LAUNCH_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_OVERRIDES_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def clear_launch_overrides() -> None:
    LAUNCH_OVERRIDES_FILE.unlink(missing_ok=True)


def _ctx_from_arg_list(args: list[Any]) -> int | None:
    flat = [str(a) for a in args]
    for i, a in enumerate(flat):
        if a in ("-c", "--ctx") and i + 1 < len(flat):
            try:
                return int(flat[i + 1])
            except ValueError:
                return None
    return None


def _load_hf_config(recipe: dict[str, Any]) -> dict[str, Any]:
    inv = str(recipe.get("inventory_path") or "").strip().strip("/")
    if not inv:
        return {}
    base = MODELS_ROOT / inv
    for rel in ("config.json", "hf/config.json", "nvfp4/config.json", "fp8/config.json"):
        path = base / rel
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return {}


def _inventory_native_ctx(inventory_path: str) -> int | None:
    path = ROOT / "portal" / "models.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for entry in data.get("models") or []:
        rel = str(entry.get("rel_path") or entry.get("id") or "")
        if rel == inventory_path or rel.startswith(inventory_path + "/"):
            mc = entry.get("max_context")
            if isinstance(mc, (int, float)) and mc > 0:
                return int(mc)
    return None


def native_context(recipe: dict[str, Any]) -> int | None:
    block = recipe.get("context") or {}
    if isinstance(block, dict) and block.get("native"):
        try:
            native = int(block["native"])
            if native > 32768:
                return native
        except (TypeError, ValueError):
            pass
    cfg = _load_hf_config(recipe)
    for src in (cfg, cfg.get("text_config") or {}):
        if not isinstance(src, dict):
            continue
        for key in ("max_position_embeddings", "max_seq_len", "model_max_length"):
            val = src.get(key)
            if isinstance(val, (int, float)) and val > 0:
                return int(val)
    inv = str(recipe.get("inventory_path") or "").strip().strip("/")
    if inv:
        inv_native = _inventory_native_ctx(inv)
        if inv_native:
            return inv_native
    if isinstance(block, dict) and block.get("native"):
        try:
            return int(block["native"])
        except (TypeError, ValueError):
            pass
    return None


def _parse_eugr_defaults(path: str | None) -> tuple[int | None, str | None]:
    if not path:
        return None, None
    p = Path(path)
    if not p.is_file():
        return None, None
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None, None
    defaults = data.get("defaults") or {}
    ctx = defaults.get("max_model_len")
    kv = None
    cmd = str(data.get("command") or "")
    m = re.search(r"--kv-cache-dtype\s+(\S+)", cmd)
    if m:
        kv = m.group(1)
    try:
        ctx_i = int(ctx) if ctx else None
    except (TypeError, ValueError):
        ctx_i = None
    return ctx_i, kv


def default_context(recipe: dict[str, Any]) -> int | None:
    block = recipe.get("context") or {}
    if isinstance(block, dict) and block.get("default"):
        try:
            return int(block["default"])
        except (TypeError, ValueError):
            pass
    engine = recipe.get("engine")
    if engine == "llamacpp":
        return _ctx_from_arg_list(recipe.get("llamacpp_args") or []) or 32768
    if engine == "ds4":
        c = _ctx_from_arg_list(recipe.get("ds4_args") or [])
        if c:
            return c
        return 32768
    if engine == "eugr":
        ctx, _ = _parse_eugr_defaults(recipe.get("eugr_recipe"))
        return ctx or 16384
    return None


def default_kv(recipe: dict[str, Any]) -> str:
    block = recipe.get("context") or {}
    if isinstance(block, dict) and block.get("kv_default"):
        return str(block["kv_default"])
    engine = recipe.get("engine")
    if engine == "eugr":
        _, kv = _parse_eugr_defaults(recipe.get("eugr_recipe"))
        return kv or "auto"
    if engine == "llamacpp":
        args = [str(a) for a in (recipe.get("llamacpp_args") or [])]
        for i, a in enumerate(args):
            if a == "--cache-type-k" and i + 1 < len(args):
                return args[i + 1]
        return "auto"
    return "auto"


def estimate_weight_gb(recipe: dict[str, Any]) -> float | None:
    engine = recipe.get("engine")
    if engine == "llamacpp":
        model = Path(str(recipe.get("model") or ""))
        if model.is_file():
            return model.stat().st_size / (1024**3)
    inv = str(recipe.get("inventory_path") or "").strip("/")
    if not inv:
        return None
    base = MODELS_ROOT / inv
    if not base.is_dir():
        return None
    if engine == "eugr":
        for sub in ("nvfp4", "fp8", ""):
            d = base / sub if sub else base
            if d.is_dir():
                total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                if total > 0:
                    return total / (1024**3)
    total = sum(f.stat().st_size for f in base.rglob("*") if f.is_file())
    return total / (1024**3) if total else None


def system_mem_avail_gb() -> float:
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return 96.0
    avail = None
    for line in meminfo.splitlines():
        if line.startswith("MemAvailable:"):
            avail = int(line.split()[1]) * 1024
            break
    if avail is None:
        return 96.0
    return avail / (1024**3)


def estimate_max_ctx(
    recipe: dict[str, Any],
    *,
    kv: str = "fp8",
    overhead_gb: float = 14.0,
) -> int | None:
    weight = estimate_weight_gb(recipe)
    if weight is None:
        return None
    mem = system_mem_avail_gb()
    usable = mem - weight - overhead_gb
    if usable <= 0:
        return 4096
    bpt = KV_BYTES_PER_TOKEN.get(kv, KV_BYTES_PER_TOKEN["auto"])
    est = int((usable * (1024**3)) / bpt)
    native = native_context(recipe)
    if native:
        est = min(est, native)
    return max(4096, est)


def _fmt_ctx_label(ctx: int) -> str:
    if ctx >= 1024 and ctx % 1024 == 0:
        return f"{ctx // 1024}k"
    if ctx >= 1024:
        return f"{ctx / 1024:.1f}k"
    return str(ctx)


def tested_kv_options(recipe: dict[str, Any]) -> list[str]:
    """KV dtypes with successful bench (kv_sweep ok cells, else golden bench)."""
    block = recipe.get("context") or {}
    ks = block.get("kv_sweep") or {}
    results = ks.get("results") if isinstance(ks, dict) else []
    ok: list[str] = []
    for row in results or []:
        if row.get("status") == "ok" and row.get("kv"):
            kv = str(row["kv"])
            if kv not in ok:
                ok.append(kv)
    if ok:
        return ok
    cell = (block.get("bench_matrix") or {}).get("golden_cell") or {}
    presets = block.get("presets") or {}
    golden = presets.get("golden") if isinstance(presets, dict) else None
    if not isinstance(golden, dict):
        golden = {}
    gkv = str(golden.get("kv") or block.get("kv_default") or "")
    if cell.get("tok_s") and gkv:
        return [gkv]
    dk = default_kv(recipe)
    return [dk] if dk else ["auto"]


def enriched_context_presets(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """Recipe presets plus one button per successful ctx_ladder rung."""
    by_id: dict[str, dict[str, Any]] = {}
    for p in context_presets(recipe):
        by_id[p["id"]] = dict(p)

    block = recipe.get("context") or {}
    lad = block.get("ctx_ladder") or {}
    for row in lad.get("rungs") or []:
        if row.get("status") != "ok":
            continue
        ctx = int(row["ctx"])
        pid = f"tested_{ctx}"
        if pid in by_id:
            continue
        tok = row.get("tok_s")
        label = f"Tested {_fmt_ctx_label(ctx)}"
        if tok:
            label += f" ({tok}t/s)"
        by_id[pid] = {
            "id": pid,
            "label": label,
            "ctx": ctx,
            "kv": str(row.get("kv") or default_kv(recipe)),
            "source": "ctx_ladder",
        }

    return sorted(by_id.values(), key=lambda p: int(p["ctx"]))


def context_presets(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    block = recipe.get("context") or {}
    if isinstance(block, dict) and isinstance(block.get("presets"), dict):
        out = []
        for pid, cfg in block["presets"].items():
            if not isinstance(cfg, dict):
                continue
            out.append(
                {
                    "id": pid,
                    "label": str(cfg.get("label") or pid),
                    "ctx": int(cfg["ctx"]),
                    "kv": str(cfg.get("kv") or "auto"),
                }
            )
        if out:
            return out
    default = default_context(recipe) or 32768
    native = native_context(recipe) or default
    long_ctx = min(max(default * 2, 65536), native)
    max_ctx = min(native, estimate_max_ctx(recipe, kv="fp8") or native)
    return [
        {"id": "default", "label": "Default", "ctx": default, "kv": default_kv(recipe)},
        {"id": "long", "label": "Long", "ctx": long_ctx, "kv": "fp8" if recipe.get("engine") == "eugr" else "q8_0"},
        {"id": "max", "label": "Max fit", "ctx": max_ctx, "kv": "fp8" if recipe.get("engine") == "eugr" else "q8_0"},
    ]


def context_recommendations(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    default = default_context(recipe) or 32768
    native = native_context(recipe)
    weight = estimate_weight_gb(recipe)
    mem = system_mem_avail_gb()
    recs: list[dict[str, Any]] = [
        {
            "label": "safe",
            "ctx": default,
            "kv": default_kv(recipe),
            "reason": "Recipe default — always the safest starting point.",
        }
    ]
    fit_fp8 = estimate_max_ctx(recipe, kv="fp8")
    if fit_fp8 and fit_fp8 > default:
        mid = min(fit_fp8, max(default * 2, 65536))
        if native:
            mid = min(mid, native)
        recs.append(
            {
                "label": "balanced",
                "ctx": mid,
                "kv": "fp8" if recipe.get("engine") == "eugr" else "q8_0",
                "reason": f"Est. fit ~{mid // 1024}k ctx with compressed KV ({mem:.0f} GB free, ~{weight or 0:.0f} GB weights).",
            }
        )
    if fit_fp8 and native and fit_fp8 >= min(native, 131072):
        long_ctx = min(fit_fp8, native, 131072)
        if long_ctx > default:
            recs.append(
                {
                    "label": "long",
                    "ctx": long_ctx,
                    "kv": "fp8" if recipe.get("engine") == "eugr" else "q8_0",
                    "reason": "100k+ territory — requires KV compression; bench before production.",
                }
            )
    return recs


def effective_launch(recipe: dict[str, Any], active_profile_id: str | None = None) -> dict[str, Any]:
    overrides = read_launch_overrides()
    default = default_context(recipe) or 32768
    default_k = default_kv(recipe)
    if active_profile_id and overrides.get("profile") == active_profile_id:
        return {
            "ctx": int(overrides.get("ctx") or default),
            "kv": str(overrides.get("kv") or default_k),
            "preset": overrides.get("preset"),
        }
    return {"ctx": default, "kv": default_k, "preset": None}


def context_public(recipe: dict[str, Any], *, active_profile_id: str | None = None) -> dict[str, Any]:
    eff = effective_launch(recipe, active_profile_id)
    native = native_context(recipe)
    default = default_context(recipe)
    return {
        "native": native,
        "default": default,
        "effective": eff.get("ctx"),
        "kv_default": default_kv(recipe),
        "kv_effective": eff.get("kv"),
        "kv_tested": tested_kv_options(recipe),
        "preset": eff.get("preset"),
        "presets": enriched_context_presets(recipe),
        "recommendations": context_recommendations(recipe),
        "weight_gb": estimate_weight_gb(recipe),
        "mem_avail_gb": round(system_mem_avail_gb(), 1),
    }


def resolve_launch_ctx_kv(
    recipe: dict[str, Any],
    *,
    ctx: int | None = None,
    kv: str | None = None,
    preset: str | None = None,
) -> tuple[int, str]:
    presets = {p["id"]: p for p in enriched_context_presets(recipe)}
    if preset and preset in presets:
        p = presets[preset]
        ctx = int(p["ctx"])
        kv = str(p.get("kv") or "auto")
    if ctx is None:
        ctx = default_context(recipe) or 32768
    if not kv:
        kv = default_kv(recipe)
    native = native_context(recipe)
    if native:
        ctx = min(int(ctx), int(native))
    ctx = max(4096, int(ctx))
    return ctx, str(kv)


def _set_arg(args: list[str], flag: str, value: str) -> list[str]:
    out: list[str] = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a == flag:
            skip = True
            continue
        out.append(a)
    out.extend([flag, value])
    return out


def materialize_llama_recipe(recipe: dict[str, Any], ctx: int, kv: str) -> Path:
    LLAMA_LAUNCH_DIR.mkdir(parents=True, exist_ok=True)
    out = copy.deepcopy(recipe)
    args = [str(a) for a in (out.get("llamacpp_args") or ["-ngl", "999", "-fa", "1", "--no-mmap", "-c", "32768"])]
    args = _set_arg(args, "-c", str(ctx))
    llama_kv = LLAMA_KV_MAP.get(kv) or LLAMA_KV_MAP.get(kv.replace("-", "_"))
    if llama_kv:
        args = _set_arg(args, "--cache-type-k", llama_kv)
        args = _set_arg(args, "--cache-type-v", llama_kv)
    out["llamacpp_args"] = args
    path = LLAMA_LAUNCH_DIR / f"{out.get('id', 'launch')}.yaml"
    import yaml

    path.write_text(yaml.safe_dump(out, sort_keys=False, default_flow_style=False), encoding="utf-8")
    return path


def materialize_eugr_recipe(recipe: dict[str, Any], ctx: int, kv: str) -> Path:
    import yaml

    base_path = Path(str(recipe.get("eugr_recipe") or ""))
    if not base_path.is_file():
        raise RuntimeError(f"missing eugr recipe: {base_path}")
    data = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    defaults = dict(data.get("defaults") or {})
    defaults["max_model_len"] = int(ctx)
    data["defaults"] = defaults
    cmd = str(data.get("command") or "")
    if kv and kv != "auto":
        if "--kv-cache-dtype" in cmd:
            cmd = re.sub(r"--kv-cache-dtype\s+\S+", f"--kv-cache-dtype {kv}", cmd)
        else:
            cmd = cmd.replace("--trust-remote-code \\", f"--trust-remote-code \\\n    --kv-cache-dtype {kv} \\")
    data["command"] = cmd
    EUgr_LAUNCH_DIR.mkdir(parents=True, exist_ok=True)
    path = EUgr_LAUNCH_DIR / f"{recipe.get('id', 'launch')}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False), encoding="utf-8")
    return path


def materialize_ds4_recipe(recipe: dict[str, Any], ctx: int, kv: str) -> Path:
    import yaml

    out = copy.deepcopy(recipe)
    args = [str(a) for a in (out.get("ds4_args") or [])]
    args = _set_arg(args, "-c", str(ctx))
    out["ds4_args"] = args
    path = LLAMA_LAUNCH_DIR / f"ds4-{out.get('id', 'launch')}.yaml"
    path.write_text(yaml.safe_dump(out, sort_keys=False, default_flow_style=False), encoding="utf-8")
    return path


def prepare_launch(recipe: dict[str, Any], profile_id: str, *, ctx: int | None = None, kv: str | None = None, preset: str | None = None) -> dict[str, str]:
    ctx_i, kv_s = resolve_launch_ctx_kv(recipe, ctx=ctx, kv=kv, preset=preset)
    write_launch_overrides(profile_id, ctx_i, kv_s, preset=preset)
    engine = recipe.get("engine")
    env: dict[str, str] = {}
    if engine == "llamacpp":
        path = materialize_llama_recipe(recipe, ctx_i, kv_s)
        env["SPARK_LLAMA_RECIPE"] = str(path)
    elif engine == "eugr":
        path = materialize_eugr_recipe(recipe, ctx_i, kv_s)
        env["SPARK_EUGR_RECIPE"] = str(path)
    elif engine == "ds4":
        path = materialize_ds4_recipe(recipe, ctx_i, kv_s)
        env["SPARK_DS4_RECIPE"] = str(path)
    else:
        raise RuntimeError(f"unsupported engine: {engine!r}")
    return env


def fmt_ctx(n: int | None) -> str:
    if not n:
        return "—"
    if n >= 1024 and n % 1024 == 0:
        return f"{n // 1024}k"
    if n >= 1024:
        return f"{round(n / 1024, 1)}k"
    return str(n)
