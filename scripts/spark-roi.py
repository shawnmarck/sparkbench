#!/usr/bin/env python3
"""ROI profiles: the cloud-SKU identity a recipe is tagged with.

Identity lives in data/roi-profiles.yaml (git, no prices).
Recipe tags live in run/roi-recipe-tags.json (host-local).
Prices stay in run/inference-pricing.json, keyed by ROI profile id.
Token counters stay keyed by recipe id.

A recipe file's roi_profile field wins over the tag map. The map covers
recipe ids whose file is gone. This module does not move token totals.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
REGISTRY_PATH = ROOT / "data" / "roi-profiles.yaml"
TAGS_PATH = ROOT / "run" / "roi-recipe-tags.json"
PRICING_PATH = ROOT / "run" / "inference-pricing.json"
RECIPES_DIR = ROOT / "recipes"
RECIPES_DRAFTS_DIR = RECIPES_DIR / "drafts"

# Longer tokens first. Packaging and engine, not the model.
_SUFFIXES = (
    "int4-autoround",
    "fp4-local",
    "nvfp4-fast",
    "dspark-nvfp4",
    "dflash-n10",
    "dflash-n15",
    "dflash2",
    "q4-k-m",
    "q4_k_m",
    "q5-k-m",
    "q5_k_m",
    "iq4-xs",
    "iq4_xs",
    "mtp-xs",
    "nvfp4",
    "q6-k",
    "tensorfold",
    "sparkinfer",
    "llamacpp",
    "dflash",
    "dspark",
    "sglang",
    "eugr",
    "llama",
    "vllm",
    "b12x",
    "gguf",
    "fp8",
    "mtp",
    "fast",
)
_VARIANTS = ("uncensored", "abliterated")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TAG_CACHE: dict[str, Any] = {"at": 0.0, "tags": {}}

# Recipe ids already on the usage card. These win over family_key.
EXPLICIT_TAGS: dict[str, str] = {
    "mia-ailab-qwen3.8-flash-next-vllm": "qwen3.8-flash-next",
    "nvidia-qwen3.8-flash-next-fp4-local-eugr": "qwen3.8-flash-next",
    "nvidia-qwen3.8-flash-next-fp4-local-tensorfold": "qwen3.8-flash-next",
    "radixark-qwen3-8-27b-mtp-eugr": "qwen3.8-27b",
    "radixark-qwen3-8-27b-dflash2-sglang": "qwen3.8-27b",
    "qwen36-35b-a3b-mtp-eugr": "qwen3.6-35b-a3b",
    "ornith-ai-ornith-1-5-35b-a3b-nvfp4-b12x-eugr": "ornith-1.5-35b-a3b",
    "0xsero-deepseek-v4-flash-0731-sparkinfer": "deepseek-v4-flash",
}


def _stamp(now: float | None = None) -> str:
    when = datetime.now(timezone.utc) if now is None else datetime.fromtimestamp(now, tz=timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def family_key(inventory_path: str) -> str:
    """Inventory slug minus lab and packaging/engine suffixes."""
    slug = str(inventory_path or "").strip().strip("/")
    slug = slug.split("/", 1)[-1].lower().replace("_", "-")
    slug = slug.replace("qwen3-6-", "qwen3.6-").replace("qwen36-", "qwen3.6-")
    slug = slug.replace("qwen3-8-", "qwen3.8-").replace("qwen38-", "qwen3.8-")
    while True:
        trimmed = False
        for sfx in _SUFFIXES:
            token = "-" + sfx
            if slug.endswith(token):
                slug = slug[: -len(token)]
                trimmed = True
                break
        if not trimmed:
            break
    return slug.rstrip("-")


def split_variant(slug: str) -> tuple[str, str]:
    for tok in _VARIANTS:
        suffix = "-" + tok
        if slug.endswith(suffix):
            return slug[: -len(suffix)].rstrip("-"), tok
    return slug, ""


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    cloud = raw.get("cloud") if isinstance(raw.get("cloud"), dict) else {}
    proxy = cloud.get("proxy")
    return {
        "id": _as_str(raw.get("id")),
        "name": _as_str(raw.get("name")) or _as_str(raw.get("id")),
        "family": _as_str(raw.get("family")),
        "version": _as_str(raw.get("version")),
        "params": _as_str(raw.get("params")),
        "variant": _as_str(raw.get("variant")),
        "cloud": {
            "provider": _as_str(cloud.get("provider")),
            "model": _as_str(cloud.get("model")),
            "proxy": bool(proxy) if proxy is not None else False,
        },
    }


def load_profiles() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.is_file():
        return []
    try:
        raw = yaml.safe_load(REGISTRY_PATH.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    items = raw.get("profiles") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        prof = _normalize_profile(item)
        if prof["id"]:
            out.append(prof)
    return out


def profile_ids() -> set[str]:
    return {p["id"] for p in load_profiles()}


def profile_exists(roi_id: str) -> bool:
    return roi_id in profile_ids()


def get_profile(roi_id: str) -> dict[str, Any] | None:
    for prof in load_profiles():
        if prof["id"] == roi_id:
            return prof
    return None


def save_profiles(profiles: list[dict[str, Any]]) -> None:
    payload = {"profiles": [_normalize_profile(p) for p in profiles if p.get("id")]}
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, sort_keys=False, default_flow_style=False, allow_unicode=True)
    tmp = REGISTRY_PATH.with_name(REGISTRY_PATH.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, REGISTRY_PATH)


def load_tags() -> dict[str, str]:
    if not TAGS_PATH.is_file():
        return {}
    try:
        raw = json.loads(TAGS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    recipes = raw.get("recipes") if isinstance(raw, dict) else None
    if not isinstance(recipes, dict):
        return {}
    out: dict[str, str] = {}
    for recipe_id, roi_id in recipes.items():
        rid = _as_str(recipe_id)
        roi = _as_str(roi_id)
        if rid and roi:
            out[rid] = roi
    return out


def save_tags(recipes: dict[str, str]) -> None:
    _TAG_CACHE["at"] = 0.0
    payload = {"updated_at": _stamp(), "recipes": dict(sorted(recipes.items()))}
    TAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TAGS_PATH.with_name(TAGS_PATH.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, TAGS_PATH)


def _recipe_files() -> list[Path]:
    files: list[Path] = []
    for folder in (RECIPES_DIR, RECIPES_DRAFTS_DIR):
        if not folder.is_dir():
            continue
        files.extend(sorted(p for p in folder.glob("*.yaml") if p.is_file()))
    return files


def _roi_field(path: Path) -> str:
    try:
        text = path.read_text()
    except OSError:
        return ""
    for line in text.splitlines():
        if line.startswith("roi_profile:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def _inventory_field(path: Path) -> str:
    try:
        text = path.read_text()
    except OSError:
        return ""
    for line in text.splitlines():
        if line.startswith("inventory_path:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def effective_tags() -> dict[str, str]:
    """Recipe id → ROI profile id. A roi_profile line in the recipe file wins."""
    now = time.time()
    if now - float(_TAG_CACHE.get("at") or 0) < 5:
        cached = _TAG_CACHE.get("tags")
        if isinstance(cached, dict):
            return dict(cached)
    tags = load_tags()
    for path in _recipe_files():
        roi = _roi_field(path)
        if roi:
            tags[path.stem] = roi
    _TAG_CACHE["at"] = now
    _TAG_CACHE["tags"] = dict(tags)
    return dict(tags)


def suggest(inventory_path: str) -> dict[str, str]:
    """Proposal only. Does not write a tag."""
    slug = family_key(inventory_path)
    base, variant = split_variant(slug)
    known = profile_ids()
    join = base if base in known else (slug if slug in known else "")
    create_id = slug if variant or slug not in known else ""
    return {
        "family_key": slug,
        "base": base,
        "variant": variant,
        "join": join,
        "create_id": create_id,
    }


def desired_tag(recipe_id: str, inventory_path: str) -> str:
    """Backfill tag. Explicit card rows win. Otherwise an exact registry id."""
    explicit = EXPLICIT_TAGS.get(recipe_id)
    if explicit:
        return explicit
    slug = family_key(inventory_path)
    if slug in profile_ids():
        return slug
    return ""


def stamp_recipe_yaml(path: Path, roi_id: str) -> bool:
    """Insert or replace roi_profile without rewriting the rest of the file."""
    try:
        text = path.read_text()
    except OSError:
        return False
    lines = text.splitlines(keepends=True)
    new_line = f"roi_profile: {roi_id}\n"
    for i, line in enumerate(lines):
        if line.startswith("roi_profile:"):
            if line.strip() == f"roi_profile: {roi_id}":
                return False
            lines[i] = new_line
            path.write_text("".join(lines))
            return True
    for i, line in enumerate(lines):
        if line.startswith("inventory_path:"):
            lines.insert(i + 1, new_line)
            path.write_text("".join(lines))
            return True
    for i, line in enumerate(lines):
        if line.startswith("id:"):
            lines.insert(i + 1, new_line)
            path.write_text("".join(lines))
            return True
    return False


def assign_recipe(recipe_id: str, roi_id: str, *, recipe_path: Path | None = None) -> None:
    if not profile_exists(roi_id):
        raise RuntimeError(f"unknown roi_profile: {roi_id}")
    if not _SLUG_RE.match(recipe_id):
        raise RuntimeError(f"bad recipe id: {recipe_id}")
    tags = load_tags()
    tags[recipe_id] = roi_id
    save_tags(tags)
    path = recipe_path
    if path is None:
        for folder in (RECIPES_DIR, RECIPES_DRAFTS_DIR):
            candidate = folder / f"{recipe_id}.yaml"
            if candidate.is_file():
                path = candidate
                break
    if path is not None and path.is_file():
        stamp_recipe_yaml(path, roi_id)


def validate_new_profile(fields: dict[str, str]) -> dict[str, Any]:
    roi_id = _as_str(fields.get("id"))
    if not _SLUG_RE.match(roi_id):
        raise RuntimeError("roi profile id must be a lowercase slug")
    if profile_exists(roi_id):
        raise RuntimeError(f"roi profile already exists: {roi_id}")
    required = ("name", "family", "version", "params", "provider", "model")
    missing = [key for key in required if not _as_str(fields.get(key))]
    if missing:
        raise RuntimeError("missing " + ", ".join(missing))
    try:
        inn = float(fields.get("in", ""))
        out = float(fields.get("out", ""))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("in and out must be numbers ($ per 1M tokens)") from exc
    if inn < 0 or out < 0:
        raise RuntimeError("in and out must be >= 0")
    proxy_raw = _as_str(fields.get("proxy")).lower()
    proxy = proxy_raw in {"1", "true", "yes", "y"}
    return {
        "id": roi_id,
        "name": _as_str(fields.get("name")),
        "family": _as_str(fields.get("family")),
        "version": _as_str(fields.get("version")),
        "params": _as_str(fields.get("params")),
        "variant": _as_str(fields.get("variant")),
        "cloud": {
            "provider": _as_str(fields.get("provider")),
            "model": _as_str(fields.get("model")),
            "proxy": proxy,
        },
        "in_per_m": round(inn, 6),
        "out_per_m": round(out, 6),
    }


def create_profile(fields: dict[str, str]) -> dict[str, Any]:
    prof = validate_new_profile(fields)
    profiles = load_profiles()
    profiles.append({k: prof[k] for k in ("id", "name", "family", "version", "params", "variant", "cloud")})
    save_profiles(profiles)
    _write_price(prof["id"], prof["in_per_m"], prof["out_per_m"])
    return prof


def _write_price(roi_id: str, inn: float, out: float) -> None:
    store: dict[str, Any] = {"updated_at": "", "profiles": {}}
    if PRICING_PATH.is_file():
        try:
            raw = json.loads(PRICING_PATH.read_text())
            if isinstance(raw, dict):
                store = raw
        except (OSError, json.JSONDecodeError):
            pass
    profiles = store.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        store["profiles"] = profiles
    current = profiles.get(roi_id)
    if not isinstance(current, dict):
        current = {"in_per_m": inn, "out_per_m": out, "overrides": [], "history": []}
    else:
        current["in_per_m"] = inn
        current["out_per_m"] = out
        current.setdefault("overrides", [])
        current.setdefault("history", [])
    profiles[roi_id] = current
    store["updated_at"] = _stamp()
    PRICING_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PRICING_PATH.with_name(PRICING_PATH.name + ".tmp")
    tmp.write_text(json.dumps(store, indent=2) + "\n")
    os.replace(tmp, PRICING_PATH)


def _pick_ledger(ledgers: list[dict[str, Any]]) -> dict[str, Any]:
    def rank(item: dict[str, Any]) -> tuple[int, int]:
        hist = item.get("history") or []
        return (len(hist) if isinstance(hist, list) else 0, len(item.get("overrides") or []))

    chosen = max(ledgers, key=rank)
    return {
        "in_per_m": chosen.get("in_per_m") or 0,
        "out_per_m": chosen.get("out_per_m") or 0,
        "overrides": list(chosen.get("overrides") or []),
        "history": list(chosen.get("history") or []),
    }


def copy_prices_from_recipes(tags: dict[str, str]) -> list[str]:
    """Copy recipe ledgers onto ROI profile ids. Leave the recipe keys in place."""
    if not PRICING_PATH.is_file():
        return []
    try:
        store = json.loads(PRICING_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    profiles = store.get("profiles")
    if not isinstance(profiles, dict):
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for recipe_id, roi_id in tags.items():
        raw = profiles.get(recipe_id)
        if isinstance(raw, dict):
            grouped.setdefault(roi_id, []).append(raw)
    notes: list[str] = []
    for roi_id, ledgers in sorted(grouped.items()):
        picked = _pick_ledger(ledgers)
        profiles[roi_id] = picked
        hist = len(picked.get("history") or [])
        notes.append(
            f"{roi_id}: in={picked['in_per_m']} out={picked['out_per_m']} history={hist} from {len(ledgers)} recipe ledger(s)"
        )
    store["profiles"] = profiles
    store["updated_at"] = _stamp()
    tmp = PRICING_PATH.with_name(PRICING_PATH.name + ".tmp")
    tmp.write_text(json.dumps(store, indent=2) + "\n")
    os.replace(tmp, PRICING_PATH)
    return notes


def backfill() -> dict[str, Any]:
    """Tag recipe files whose family key is a registry id, plus the explicit card rows."""
    tags = load_tags()
    stamped: list[str] = []
    skipped: list[str] = []
    for path in _recipe_files():
        recipe_id = path.stem
        inventory = _inventory_field(path)
        roi_id = desired_tag(recipe_id, inventory)
        if not roi_id:
            skipped.append(recipe_id)
            continue
        if not profile_exists(roi_id):
            skipped.append(recipe_id)
            continue
        tags[recipe_id] = roi_id
        if stamp_recipe_yaml(path, roi_id):
            stamped.append(recipe_id)
    save_tags(tags)
    price_notes = copy_prices_from_recipes(tags)
    return {"tagged": len(tags), "yaml_updated": stamped, "untagged_files": skipped, "prices": price_notes}


def suggestion_lines(recipe_id: str, inventory_path: str) -> list[str]:
    idea = suggest(inventory_path)
    lines = ["ROI profile required before testing."]
    if idea["join"]:
        lines.append(f"  join {idea['join']}")
        lines.append(f"    spark recipe roi {recipe_id} {idea['join']}")
    create_id = idea["create_id"] or idea["family_key"]
    if create_id and create_id != idea["join"]:
        variant = f" variant={idea['variant']}" if idea["variant"] else ""
        lines.append(
            f"  create {create_id}{variant}"
        )
        lines.append(
            "    spark recipe roi-new "
            f"{recipe_id} id={create_id} name= family= version= params= "
            "provider= model= in= out="
        )
    elif not idea["join"]:
        lines.append(
            "    spark recipe roi-new "
            f"{recipe_id} id={create_id} name= family= version= params= "
            "provider= model= in= out="
        )
    return lines


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "backfill":
        result = backfill()
        print(json.dumps(result, indent=2))
    elif cmd == "suggest" and len(sys.argv) >= 3:
        print(json.dumps(suggest(sys.argv[2]), indent=2))
    else:
        raise SystemExit("usage: spark-roi.py backfill | suggest <lab/slug>")
