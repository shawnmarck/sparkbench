#!/opt/spark/venv/bin/python3
"""Publish golden_cell bench results to site-visible YAML (verification + benchmarks)."""
from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
GOLDEN_FILE = ROOT / "data/golden-recipes.yaml"
CATALOG_FILE = ROOT / "data/model-catalog.yaml"
VERIFY_FILE = ROOT / "data/model-verification.yaml"
BENCH_FILE = ROOT / "data/inference-benchmarks.yaml"
RECIPES = ROOT / "recipes"

SKIP_INVENTORY: frozenset[str] = frozenset(
    {
        "0xsero/deepseek-v4-flash-spark",
    }
)

FAIL_STATUSES = frozenset({"load_fail", "bench_fail", "failed", "pending", "up_failed"})


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] site-publish: {msg}"
    print(line, flush=True)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text())
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def load_inference_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "spark_inference", ROOT / "scripts/spark-inference.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_golden_map() -> dict[str, str]:
    data = load_yaml(GOLDEN_FILE)
    return dict(data.get("golden") or {})


def load_leaderboard_exclude() -> frozenset[str]:
    data = load_yaml(GOLDEN_FILE)
    return frozenset(str(x) for x in (data.get("leaderboard_exclude") or []))


def site_publish_blocked(inventory_path: str | None) -> bool:
    if not inventory_path:
        return False
    return inventory_path in SKIP_INVENTORY or inventory_path in load_leaderboard_exclude()


def inventory_for_profile(profile_id: str, golden_map: dict[str, str] | None = None) -> str | None:
    gmap = golden_map if golden_map is not None else load_golden_map()
    for inv, prof in gmap.items():
        if prof == profile_id:
            return inv
    return None


def load_recipe(profile_id: str) -> dict[str, Any]:
    path = RECIPES / f"{profile_id}.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def fmt_ctx(ctx: int | None) -> str:
    if ctx is None:
        return "?"
    ctx = int(ctx)
    return f"{ctx // 1024}k" if ctx >= 1024 else str(ctx)


def golden_cell_publishable(cell: dict[str, Any]) -> tuple[bool, str]:
    if not cell:
        return False, "empty cell"
    status = str(cell.get("status") or "ok").lower()
    if status in FAIL_STATUSES:
        return False, f"status={status}"
    tok_s = cell.get("tok_s")
    if tok_s is None:
        return False, "missing tok_s"
    try:
        if float(tok_s) <= 0:
            return False, "tok_s <= 0"
    except (TypeError, ValueError):
        return False, "invalid tok_s"
    tool_ok = cell.get("tool_ok")
    if tool_ok is False:
        log(f"WARN golden_cell tool_ok=False — publishing tok_s anyway (audit does not gate)")
    return True, "ok"


def golden_cell_note(cell: dict[str, Any]) -> str:
    ctx = fmt_ctx(cell.get("ctx"))
    kv = cell.get("kv") or "?"
    tok_s = cell.get("tok_s")
    fill = cell.get("fill_target") or cell.get("context_fill_target_tokens")
    parts = [f"golden {ctx}/{kv} @ {tok_s} tok/s"]
    if fill:
        parts.append(f"fill~{int(fill)}")
    method = cell.get("method") or "bench-agent-v2"
    parts.append(method)
    if cell.get("tool_ok") is True:
        parts.append("tool_ok=True")
    elif cell.get("tool_ok") is False:
        parts.append("tool_ok=False")
    return " — ".join(parts)


def cell_benchmark_kwargs(cell: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    kw: dict[str, Any] = {
        "method": cell.get("method") or "bench-agent-v2",
        "note": golden_cell_note(cell),
    }
    for src, dst in (
        ("bench_standard", "bench_standard_version"),
        ("bench_standard_version", "bench_standard_version"),
        ("fill_target", "context_fill_target_tokens"),
        ("context_fill_target_tokens", "context_fill_target_tokens"),
        ("tool_ok", "tool_roundtrip_ok"),
        ("tool_roundtrip_ok", "tool_roundtrip_ok"),
        ("decode_tokens", "completion_tokens"),
        ("decode_elapsed_s", "elapsed_s"),
        ("prefill_prompt_tokens", "prompt_tokens"),
        ("run_tok_s", "run_tok_s"),
        ("sessions", "sessions"),
        ("turns_per_session", "turns_per_session"),
        ("tok_s_min", "tok_s_min"),
        ("tok_s_max", "tok_s_max"),
    ):
        val = cell.get(src)
        if val is not None and dst not in kw:
            kw[dst] = val
    if "bench_standard_version" not in kw and cell.get("bench_standard"):
        kw["bench_standard_version"] = str(cell["bench_standard"])
    return kw


def _parse_param_b(*names: str) -> int | None:
    for name in names:
        if not name:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*b", str(name).lower())
        if m:
            return int(float(m.group(1)))
    return None


def _catalog_models_list(cat: dict[str, Any]) -> list[dict[str, Any]]:
    models = cat.get("models")
    if isinstance(models, list):
        return models
    if isinstance(models, dict):
        out: list[dict[str, Any]] = []
        for key, entry in models.items():
            if isinstance(entry, dict):
                row = dict(entry)
                row.setdefault("id", key)
                out.append(row)
        return out
    cat["models"] = []
    return cat["models"]


def find_catalog_entry(cat: dict[str, Any], inventory_path: str) -> dict[str, Any] | None:
    for entry in _catalog_models_list(cat):
        if str(entry.get("id") or "") == inventory_path:
            return entry
    return None


def ensure_catalog_entry(
    inventory_path: str,
    recipe: dict[str, Any],
    *,
    dry_run: bool = False,
) -> bool:
    """Ensure model-catalog.yaml has a row for inventory_path; scaffold if missing."""
    if not inventory_path:
        return False
    cat = load_yaml(CATALOG_FILE)
    if find_catalog_entry(cat, inventory_path):
        return False

    lab, _, slug = inventory_path.partition("/")
    name = str(recipe.get("name") or slug.replace("-", " ").title())
    hf_repo = (
        recipe.get("catalog_id")
        or recipe.get("hf_repo")
        or inventory_path
    )
    param_b = _parse_param_b(name, slug, inventory_path)
    engine = str(recipe.get("engine") or "")
    tags = [str(t) for t in (recipe.get("tags") or [])]
    caps: list[str] = []
    for cap in tags + [engine, "golden"]:
        c = cap.lower()
        if c and c not in caps:
            caps.append(c)
    if engine == "llamacpp" and "gguf" not in caps:
        caps.append("gguf")
    if engine == "eugr" and "vllm" not in caps:
        caps.append("vllm")

    entry: dict[str, Any] = {
        "id": inventory_path,
        "lab": lab,
        "name": name,
        "slug": slug,
        "hf_repo": hf_repo,
        "capabilities": caps,
        "why_downloaded": f"Golden fleet target — auto-scaffolded from recipe {recipe.get('id', '')}.\n",
    }
    if param_b:
        entry["param_b"] = param_b
    arch = recipe.get("architecture")
    if arch:
        entry["architecture"] = arch
    for tag in tags:
        if tag.lower() in {"moe", "dense"} and tag.lower() not in caps:
            caps.append(tag.lower())

    log(f"WARN catalog missing {inventory_path} — {'DRY ' if dry_run else ''}scaffold: {name}")
    if dry_run:
        return True

    models = _catalog_models_list(cat)
    models.append(entry)
    cat["models"] = models
    save_yaml(CATALOG_FILE, cat)
    return True


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def verification_needs_publish(
    inventory_path: str,
    profile_id: str,
    cell: dict[str, Any],
    *,
    verify_entry: dict[str, Any] | None = None,
    bench_entry: dict[str, Any] | None = None,
    matrix_updated_at: str | None = None,
    force: bool = False,
) -> bool:
    if force:
        return True
    verify_entry = verify_entry or {}
    bench_entry = bench_entry or {}
    if verify_entry.get("spark_status") != "works":
        return True
    if verify_entry.get("tok_s_profile") != profile_id:
        return True
    if profile_id not in bench_entry or not bench_entry[profile_id].get("tok_s"):
        return True
    vt = verify_entry.get("tok_s")
    ct = cell.get("tok_s")
    if vt is None or ct is None:
        return True
    if abs(float(vt) - float(ct)) > 0.25:
        return True
    cell_ts = _parse_ts(matrix_updated_at) or _parse_ts(cell.get("measured_at"))
    verify_ts = _parse_ts(verify_entry.get("updated_at"))
    bench_ts = _parse_ts(bench_entry.get(profile_id, {}).get("measured_at"))
    if cell_ts and verify_ts and cell_ts > verify_ts:
        return True
    if cell_ts and bench_ts and cell_ts > bench_ts:
        return True
    return False


def publish_golden_cell_to_site(
    profile_id: str,
    cell: dict[str, Any],
    recipe: dict[str, Any],
    *,
    inventory_path: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """
    Publish golden_cell to inference-benchmarks + model-verification via record_benchmark().
  Returns {"published": bool, "reason": str, ...}.
    """
    inv = (
        inventory_path
        or recipe.get("inventory_path")
        or inventory_for_profile(profile_id)
    )
    result: dict[str, Any] = {
        "profile_id": profile_id,
        "inventory_path": inv,
        "published": False,
    }

    if site_publish_blocked(inv):
        result["reason"] = "leaderboard_exclude" if inv in load_leaderboard_exclude() else "skip_list"
        return result

    ok, reason = golden_cell_publishable(cell)
    if not ok:
        result["reason"] = reason
        return result

    if not inv:
        result["reason"] = "missing inventory_path"
        return result

    recipe = dict(recipe)
    recipe.setdefault("inventory_path", inv)

    verify_store = load_yaml(VERIFY_FILE)
    verify_models = verify_store.get("models") or {}
    bench_store = load_yaml(BENCH_FILE)
    bench_profiles = bench_store.get("profiles") or {}
    matrix_updated = ((recipe.get("context") or {}).get("bench_matrix") or {}).get(
        "updated_at"
    )

    if not verification_needs_publish(
        inv,
        profile_id,
        cell,
        verify_entry=verify_models.get(inv) or {},
        bench_entry=bench_profiles,
        matrix_updated_at=matrix_updated,
        force=force,
    ):
        result["reason"] = "already_current"
        result["tok_s"] = cell.get("tok_s")
        return result

    if dry_run:
        result["published"] = True
        result["reason"] = "dry_run"
        result["tok_s"] = cell.get("tok_s")
        result["note"] = golden_cell_note(cell)
        log(f"DRY publish {inv} -> {profile_id} @ {cell.get('tok_s')} tok/s")
        return result

    ensure_catalog_entry(inv, recipe, dry_run=False)

    inf = load_inference_module()
    extra = cell_benchmark_kwargs(cell, recipe)
    entry = inf.record_benchmark(
        profile_id,
        recipe,
        float(cell["tok_s"]),
        **extra,
    )
    result["published"] = True
    result["reason"] = "ok"
    result["tok_s"] = entry.get("tok_s")
    result["measured_at"] = entry.get("measured_at")
    log(f"published {inv} -> {profile_id} @ {entry.get('tok_s')} tok/s")
    return result


def sync_headline_from_bench_profile(
    inventory_path: str,
    profile_id: str,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Align verification headline when inference-benchmarks already has the golden profile."""
    if site_publish_blocked(inventory_path):
        return {"published": False, "reason": "leaderboard_exclude", "inventory_path": inventory_path}

    verify_store = load_yaml(VERIFY_FILE)
    verify_entry = (verify_store.get("models") or {}).get(inventory_path) or {}
    bench_profiles = (load_yaml(BENCH_FILE).get("profiles") or {})
    bench_entry = bench_profiles.get(profile_id)
    if not bench_entry or not bench_entry.get("tok_s"):
        return {"published": False, "reason": "no bench profile", "inventory_path": inventory_path}

    if (
        not force
        and verify_entry.get("spark_status") == "works"
        and verify_entry.get("tok_s_profile") == profile_id
        and verify_entry.get("tok_s") == bench_entry.get("tok_s")
    ):
        return {"published": False, "reason": "already_current", "inventory_path": inventory_path}

    recipe = load_recipe(profile_id)
    if not recipe:
        recipe = {"inventory_path": inventory_path, "engine": bench_entry.get("engine")}

    cell = {
        "tok_s": bench_entry["tok_s"],
        "method": bench_entry.get("method"),
        "bench_standard_version": bench_entry.get("bench_standard_version"),
        "context_fill_target_tokens": bench_entry.get("context_fill_target_tokens"),
        "tool_ok": bench_entry.get("tool_roundtrip_ok"),
        "run_tok_s": bench_entry.get("run_tok_s"),
        "sessions": bench_entry.get("sessions"),
        "turns_per_session": bench_entry.get("turns_per_session"),
        "tok_s_min": bench_entry.get("tok_s_min"),
        "tok_s_max": bench_entry.get("tok_s_max"),
        "measured_at": bench_entry.get("measured_at"),
    }
    return publish_golden_cell_to_site(
        profile_id,
        cell,
        recipe,
        inventory_path=inventory_path,
        dry_run=dry_run,
        force=True,
    )


def publish_from_profile(
    profile_id: str,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    recipe = load_recipe(profile_id)
    if not recipe:
        return {"profile_id": profile_id, "published": False, "reason": "no recipe"}
    cell = ((recipe.get("context") or {}).get("bench_matrix") or {}).get("golden_cell") or {}
    if not cell.get("tok_s"):
        return {
            "profile_id": profile_id,
            "published": False,
            "reason": "empty cell",
        }
    inv = recipe.get("inventory_path") or inventory_for_profile(profile_id)
    return publish_golden_cell_to_site(
        profile_id,
        cell,
        recipe,
        inventory_path=str(inv) if inv else None,
        dry_run=dry_run,
        force=force,
    )


def publish_all_golden(
    *,
    dry_run: bool = False,
    force: bool = False,
    only: set[str] | None = None,
) -> dict[str, Any]:
    golden_map = load_golden_map()
    results: list[dict[str, Any]] = []
    published = 0
    skipped = 0

    for inv, profile_id in sorted(golden_map.items()):
        if site_publish_blocked(inv):
            results.append(
                {
                    "inventory_path": inv,
                    "profile_id": profile_id,
                    "published": False,
                    "reason": "leaderboard_exclude",
                }
            )
            skipped += 1
            continue
        if only and inv not in only and profile_id not in only:
            continue
        row = publish_from_profile(profile_id, dry_run=dry_run, force=force)
        if not row.get("published") and row.get("reason") in {
            "empty cell",
            "missing tok_s",
            "no recipe",
        }:
            row = sync_headline_from_bench_profile(
                inv, profile_id, dry_run=dry_run, force=force
            )
            row.setdefault("profile_id", profile_id)
        row["inventory_path"] = inv
        results.append(row)
        if row.get("published"):
            published += 1
        else:
            skipped += 1

    return {
        "dry_run": dry_run,
        "force": force,
        "published": published,
        "skipped": skipped,
        "total": len(results),
        "results": results,
    }
