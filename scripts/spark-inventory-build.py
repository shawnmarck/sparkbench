#!/usr/bin/env python3
"""Build /opt/spark/portal/models.json from catalog + disk scan + HuggingFace metadata."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

MODELS_ROOT = Path("/models")
SHELF_ROOT = Path("/mnt/model-shelf/models")
CATALOG = Path("/opt/spark/data/model-catalog.yaml")
VERIFY_FILE = Path("/opt/spark/data/model-verification.yaml")
RECIPES_DIR = Path("/opt/spark/recipes")
INFERENCE_PROFILES = Path("/opt/spark/data/inference-profiles.yaml")
BENCHMARKS_FILE = Path("/opt/spark/data/inference-benchmarks.yaml")
OUT_JSON = Path("/opt/spark/portal/models.json")
HF_CACHE_FILE = Path("/opt/spark/run/hf-metadata-cache.json")
HF_CACHE_TTL_DAYS = 7
SPARK_VERIFY_VALID = frozenset({"unverified", "wip", "works", "failed"})
BENCH_METHODS = frozenset({"bench", "bench-agent"})
HF = Path("/opt/spark/venv/bin/python")


def shelf_mounted() -> bool:
    return os.path.ismount("/mnt/model-shelf")


def location_info(root: Path, lab: str, slug: str) -> dict:
    path = root / lab / slug
    if not path.is_dir():
        return {
            "present": False,
            "size_bytes": 0,
            "size_human": "—",
            "path": str(path),
        }
    size = dir_size(path)
    return {
        "present": size > 0,
        "size_bytes": size,
        "size_human": human_size(size),
        "path": str(path),
    }


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


def human_size(n: int) -> str:
    if n <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def read_local_config(path: Path) -> dict:
    cfg = path / "config.json"
    if not cfg.is_file():
        return {}
    try:
        return json.loads(cfg.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def max_context_from_config(cfg: dict) -> int | None:
    for key in (
        "max_position_embeddings",
        "model_max_length",
        "max_seq_len",
        "n_ctx",
        "seq_length",
    ):
        if key in cfg and cfg[key]:
            return int(cfg[key])
    rope = cfg.get("rope_scaling") or {}
    if isinstance(rope, dict) and rope.get("original_max_position_embeddings"):
        factor = rope.get("factor", 1)
        try:
            return int(rope["original_max_position_embeddings"] * factor)
        except (TypeError, ValueError):
            pass
    return None


def infer_hf_repo_from_path(model_dir: Path) -> str | None:
    for sub in ("hf", "nvfp4", "gguf", "."):
        base = model_dir if sub == "." else model_dir / sub
        cfg = read_local_config(base)
        for key in ("_name_or_path", "name_or_path"):
            val = cfg.get(key)
            if val and isinstance(val, str) and "/" in val and "://" not in val:
                return val.strip().strip("/")
    readme = model_dir / "README.md"
    if readme.is_file():
        try:
            text = readme.read_text(errors="ignore")[:8000]
        except OSError:
            text = ""
        match = re.search(r"huggingface\.co/([^\s)\]\"']+)", text)
        if match:
            return match.group(1).rstrip("/")
    return None


def fallback_release_date(path: Path) -> str | None:
    try:
        mtimes = [path.stat().st_mtime]
        for root, _dirs, files in os.walk(path):
            for fname in files[:300]:
                try:
                    mtimes.append((Path(root) / fname).stat().st_mtime)
                except OSError:
                    pass
        if mtimes:
            return datetime.fromtimestamp(min(mtimes), timezone.utc).isoformat()
    except OSError:
        pass
    return None


def collect_hf_repos(hf_repo: str | None, variants: list) -> list[str]:
    repos: list[str] = []
    if hf_repo:
        repos.append(hf_repo)
    for variant in variants or []:
        repo = variant.get("hf_repo")
        if repo and repo not in repos:
            repos.append(repo)
    return repos


def resolve_release_date(
    hf_repo: str | None,
    variants: list,
    model_path: Path,
    hf_cache: dict,
) -> tuple[str | None, str | None]:
    repos = collect_hf_repos(hf_repo, variants)
    for repo in repos:
        info = hf_enrich(repo, hf_cache)
        if info.get("release_date"):
            return info["release_date"], "huggingface"
    inferred = infer_hf_repo_from_path(model_path)
    if inferred and inferred not in repos:
        info = hf_enrich(inferred, hf_cache)
        if info.get("release_date"):
            return info["release_date"], "huggingface"
    local = fallback_release_date(model_path)
    if local:
        return local, "local_earliest"
    return None, None


def model_engines(variants: list) -> list[str]:
    seen: list[str] = []
    for variant in variants or []:
        engine = variant.get("engine")
        if engine and engine not in seen:
            seen.append(engine)
    return seen


def hf_cache_entry_fresh(entry: dict) -> bool:
    fetched = entry.get("_fetched_at")
    if not fetched:
        return False
    try:
        ts = datetime.fromisoformat(fetched)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        return age.days < HF_CACHE_TTL_DAYS
    except Exception:
        return False


def load_hf_disk_cache() -> dict:
    if not HF_CACHE_FILE.is_file():
        return {}
    try:
        data = json.loads(HF_CACHE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_hf_disk_cache(cache: dict) -> None:
    HF_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    HF_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def hf_enrich(repo: str, cache: dict) -> dict:
    if repo in cache:
        entry = cache[repo]
        if hf_cache_entry_fresh(entry):
            return entry
    info = {
        "description": None,
        "release_date": None,
        "max_context": None,
        "pipeline_tag": None,
        "tags": [],
    }
    try:
        from huggingface_hub import HfApi

        api = HfApi()
        meta = api.repo_info(repo)
        cd = getattr(meta, "card_data", None)
        if cd and isinstance(cd, dict):
            info["description"] = cd.get("text") or cd.get("description")
        created = getattr(meta, "created_at", None) or getattr(meta, "lastModified", None)
        if created:
            info["release_date"] = created.isoformat() if hasattr(created, "isoformat") else str(created)
        tags = list(getattr(meta, "tags", []) or [])
        info["tags"] = tags
        info["pipeline_tag"] = getattr(meta, "pipeline_tag", None)
        # try config from HF
        try:
            from huggingface_hub import hf_hub_download

            cfg_path = hf_hub_download(repo, "config.json")
            cfg = json.loads(Path(cfg_path).read_text())
            info["max_context"] = max_context_from_config(cfg)
        except Exception:
            pass
    except Exception as e:
        info["hf_error"] = str(e)[:120]
    info["_fetched_at"] = datetime.now(timezone.utc).isoformat()
    cache[repo] = info
    return info


def load_spark_verification() -> dict:
    if not VERIFY_FILE.is_file():
        return {}
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(VERIFY_FILE.read_text()) or {}
        models = data.get("models") or {}
        return models if isinstance(models, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def spark_verify_for(rel: str, store: dict) -> dict:
    entry = store.get(rel) or {}
    status = entry.get("spark_status") or "unverified"
    if status not in SPARK_VERIFY_VALID:
        status = "unverified"
    return {
        "spark_status": status,
        "engine": entry.get("engine"),
        "note": entry.get("note"),
        "tok_s": entry.get("tok_s"),
        "tok_s_engine": entry.get("tok_s_engine"),
        "tok_s_profile": entry.get("tok_s_profile"),
        "updated_at": entry.get("updated_at"),
        "removal_pending": bool(entry.get("removal_pending")),
        "removal_queued_at": entry.get("removal_queued_at"),
    }


def parse_param_b(name: str, slug: str, cfg: dict | None = None) -> float | None:
    cfg = cfg or {}
    for key in ("num_parameters", "total_params", "n_parameters"):
        if key in cfg and cfg[key]:
            try:
                n = float(cfg[key])
                return n / 1e9 if n > 1e6 else n
            except (TypeError, ValueError):
                pass
    text = f"{name} {slug}"
    m = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?[Bb](?:\b|[-/])", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def parse_active_param_b(name: str, slug: str) -> float | None:
    text = f"{name} {slug}"
    m = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?[Bb]\s*[-/]\s*[Aa]?\s*(\d+(?:\.\d+)?)\s*[Bb]", text, re.I)
    if m:
        try:
            return float(m.group(2))
        except ValueError:
            pass
    return None


def load_profile_benchmarks() -> dict[str, dict]:
    if yaml is None or not BENCHMARKS_FILE.is_file():
        return {}
    try:
        data = yaml.safe_load(BENCHMARKS_FILE.read_text()) or {}
        raw = data.get("profiles") or {}
        return raw if isinstance(raw, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def attach_spark_verify(entries: list, store: dict, benchmarks: dict[str, dict]) -> None:
    for entry in entries:
        rel = entry.get("rel_path") or entry.get("id")
        sv = spark_verify_for(rel, store)
        profile = sv.get("tok_s_profile")
        if profile:
            bench = benchmarks.get(profile) or {}
            if bench.get("method") not in BENCH_METHODS:
                sv["tok_s"] = None
                sv["tok_s_engine"] = None
                sv["tok_s_profile"] = None
        entry["spark_verify"] = sv


def attach_best_bench_tok(entries: list) -> None:
    for entry in entries:
        toks = [
            p["tok_s"]
            for p in (entry.get("inference_profiles") or [])
            if p.get("tok_s") is not None
        ]
        entry["best_bench_tok_s"] = max(toks) if toks else None


def load_inference_profile_map() -> dict[str, list[dict]]:
    """Map inventory_path -> enabled recipe profiles for portal bridge."""
    if yaml is None or not RECIPES_DIR.is_dir():
        return {}

    enabled: set[str] = set()
    if INFERENCE_PROFILES.is_file():
        try:
            data = yaml.safe_load(INFERENCE_PROFILES.read_text()) or {}
            enabled = {p for p in (data.get("profiles") or []) if isinstance(p, str) and p}
        except (OSError, yaml.YAMLError):
            enabled = set()

    benchmarks: dict = {}
    if BENCHMARKS_FILE.is_file():
        try:
            bench_data = yaml.safe_load(BENCHMARKS_FILE.read_text()) or {}
            raw = bench_data.get("profiles") or {}
            benchmarks = raw if isinstance(raw, dict) else {}
        except (OSError, yaml.YAMLError):
            benchmarks = {}

    by_path: dict[str, list[dict]] = {}
    for recipe_file in sorted(RECIPES_DIR.glob("*.yaml")):
        profile_id = recipe_file.stem
        try:
            recipe = yaml.safe_load(recipe_file.read_text()) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(recipe, dict):
            continue
        inv_path = recipe.get("inventory_path") or recipe.get("catalog_id")
        if not inv_path:
            continue
        bench = benchmarks.get(profile_id) or {}
        method = bench.get("method")
        measured = method in BENCH_METHODS
        notes = (recipe.get("notes") or "").strip()
        first_note = notes.split("\n", 1)[0].strip() if notes else None
        info = {
            "id": profile_id,
            "name": recipe.get("name"),
            "engine": recipe.get("engine"),
            "tier": recipe.get("tier"),
            "enabled": profile_id in enabled,
            "tok_s": bench.get("tok_s") if measured else None,
            "bench_method": method if measured else None,
            "bench_measured_at": bench.get("measured_at") if measured else None,
            "notes": first_note,
        }
        by_path.setdefault(str(inv_path), []).append(info)

    for profiles in by_path.values():
        profiles.sort(key=lambda p: (not p.get("enabled"), p.get("id") or ""))
    return by_path


def attach_inference_profiles(entries: list, by_path: dict[str, list[dict]]) -> None:
    for entry in entries:
        rel = entry.get("rel_path") or entry.get("id")
        profiles = by_path.get(rel)
        if profiles:
            entry["inference_profiles"] = profiles


def load_catalog() -> list:
    if not CATALOG.is_file():
        return []
    text = CATALOG.read_text()
    if yaml:
        data = yaml.safe_load(text) or {}
        return data.get("models", [])
    # minimal fallback without pyyaml
    raise SystemExit("PyYAML required: pip install pyyaml in /opt/spark/venv")


def variant_status(base: Path, subpath: str) -> tuple[str, int]:
    p = base / subpath
    if not p.exists():
        return "missing", 0
    size = dir_size(p)
    if size == 0:
        return "empty", 0
    # partial heuristic: nvfp4/hf expect config; gguf expects .gguf
    if subpath == "gguf":
        ggufs = list(p.glob("*.gguf"))
        if not ggufs:
            return "downloading", size
    elif subpath in ("nvfp4", "hf"):
        if not (p / "config.json").exists() and not list(p.glob("*.gguf")):
            # may still be downloading safetensors
            st = list(p.glob("*.safetensors")) + list(p.glob("model-*"))
            if not st and size < 1_000_000:
                return "downloading", size
            if not st and size > 0:
                return "downloading", size
    return "ready", size


def main() -> int:
    global yaml
    if yaml is None:
        import subprocess

        subprocess.run(
            ["/opt/spark/venv/bin/pip", "install", "-q", "pyyaml"],
            check=True,
        )
        import yaml as _yaml

        yaml = _yaml

    catalog = load_catalog()
    hf_cache: dict = load_hf_disk_cache()
    entries = []
    now = datetime.now(timezone.utc).isoformat()

    for m in catalog:
        lab = m["lab"]
        slug = m["slug"]
        base = MODELS_ROOT / lab / slug
        hf_repo = m.get("hf_repo", "")
        hf_info = hf_enrich(hf_repo, hf_cache) if hf_repo else {}

        variants = []
        total_size = 0
        statuses = []
        max_ctx = hf_info.get("max_context")

        for v in m.get("variants", []):
            sub = v["subpath"]
            status, size = variant_status(base, sub)
            total_size += size
            statuses.append(status)
            local_cfg = read_local_config(base / sub)
            local_ctx = max_context_from_config(local_cfg)
            if local_ctx:
                max_ctx = max_ctx or local_ctx
            variants.append(
                {
                    "format": v.get("format"),
                    "engine": v.get("engine"),
                    "subpath": sub,
                    "path": str(base / sub),
                    "hf_repo": v.get("hf_repo"),
                    "hf_url": f"https://huggingface.co/{v['hf_repo']}" if v.get("hf_repo") else None,
                    "status": status,
                    "size_bytes": size,
                    "size_human": human_size(size),
                    "note": v.get("note"),
                }
            )

        if all(s == "missing" for s in statuses):
            overall = "missing"
        elif any(s == "downloading" for s in statuses):
            overall = "downloading"
        elif any(s == "ready" for s in statuses):
            overall = "ready" if not any(s in ("downloading", "empty") for s in statuses) else "partial"
        else:
            overall = "partial"

        desc = hf_info.get("description") or ""
        if desc:
            desc = re.sub(r"\s+", " ", desc.strip())[:500]

        release_date, release_date_source = resolve_release_date(
            hf_repo or None,
            m.get("variants", []),
            base,
            hf_cache,
        )
        if not release_date:
            release_date = hf_info.get("release_date")
            release_date_source = "huggingface" if release_date else None

        shelf = location_info(SHELF_ROOT, lab, slug)
        shelf["mounted"] = shelf_mounted()

        best_cfg: dict = {}
        for v in m.get("variants", []):
            c = read_local_config(base / v["subpath"])
            if c:
                best_cfg = c
                break
        param_b = m.get("param_b") or parse_param_b(m["name"], slug, best_cfg)
        param_active_b = m.get("param_active_b") or parse_active_param_b(m["name"], slug)

        entries.append(
            {
                "id": m["id"],
                "lab": lab,
                "name": m["name"],
                "slug": slug,
                "rel_path": f"{lab}/{slug}",
                "path": str(base),
                "local": location_info(MODELS_ROOT, lab, slug),
                "shelf": shelf,
                "hf_repo": hf_repo,
                "hf_url": f"https://huggingface.co/{hf_repo}" if hf_repo else None,
                "capabilities": m.get("capabilities", []),
                "why_downloaded": (m.get("why_downloaded") or "").strip(),
                "description": desc or None,
                "release_date": release_date,
                "release_date_source": release_date_source,
                "max_context": max_ctx,
                "param_b": param_b,
                "param_active_b": param_active_b,
                "pipeline_tag": hf_info.get("pipeline_tag"),
                "tags": hf_info.get("tags", []),
                "status": overall,
                "size_bytes": total_size,
                "size_human": human_size(total_size),
                "engines": model_engines(variants),
                "variants": variants,
            }
        )

    # discover untracked dirs
    if MODELS_ROOT.is_dir():
        for lab_dir in MODELS_ROOT.iterdir():
            if not lab_dir.is_dir() or lab_dir.name.startswith("_"):
                continue
            for model_dir in lab_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                mid = f"{lab_dir.name}/{model_dir.name}"
                if any(e.get("rel_path") == mid or e["id"] == mid for e in entries):
                    continue
                size = dir_size(model_dir)
                shelf = location_info(SHELF_ROOT, lab_dir.name, model_dir.name)
                shelf["mounted"] = shelf_mounted()
                slug = model_dir.name
                inferred_repo = infer_hf_repo_from_path(model_dir)
                untracked_variants = []
                untracked_release, untracked_source = resolve_release_date(
                    inferred_repo,
                    untracked_variants,
                    model_dir,
                    hf_cache,
                )
                entries.append(
                    {
                        "id": mid,
                        "lab": lab_dir.name,
                        "name": model_dir.name,
                        "slug": slug,
                        "rel_path": mid,
                        "path": str(model_dir),
                        "local": location_info(MODELS_ROOT, lab_dir.name, model_dir.name),
                        "shelf": shelf,
                        "hf_repo": inferred_repo,
                        "hf_url": f"https://huggingface.co/{inferred_repo}" if inferred_repo else None,
                        "capabilities": ["untracked"],
                        "why_downloaded": "Not in catalog — add to model-catalog.yaml",
                        "description": None,
                        "release_date": untracked_release,
                        "release_date_source": untracked_source,
                        "max_context": max_context_from_config(read_local_config(model_dir)),
                        "param_b": parse_param_b(model_dir.name, slug, read_local_config(model_dir)),
                        "param_active_b": parse_active_param_b(model_dir.name, slug),
                        "status": "ready" if size else "empty",
                        "size_bytes": size,
                        "size_human": human_size(size),
                        "engines": model_engines(untracked_variants),
                        "variants": untracked_variants,
                    }
                )

    # Shelf-only models (on NAS, not already represented by catalog/untracked rel_path)
    seen_ids = {e["id"] for e in entries}
    seen_rel_paths = {e.get("rel_path") or e["id"] for e in entries}
    if shelf_mounted() and SHELF_ROOT.is_dir():
        for lab_dir in SHELF_ROOT.iterdir():
            if not lab_dir.is_dir() or lab_dir.name.startswith("_"):
                continue
            for model_dir in lab_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                mid = f"{lab_dir.name}/{model_dir.name}"
                if mid in seen_ids or mid in seen_rel_paths:
                    continue
                size = dir_size(model_dir)
                shelf = location_info(SHELF_ROOT, lab_dir.name, model_dir.name)
                shelf["mounted"] = True
                inferred_repo = infer_hf_repo_from_path(model_dir)
                shelf_variants = []
                shelf_release, shelf_source = resolve_release_date(
                    inferred_repo,
                    shelf_variants,
                    model_dir,
                    hf_cache,
                )
                entries.append(
                    {
                        "id": mid,
                        "lab": lab_dir.name,
                        "name": model_dir.name,
                        "slug": model_dir.name,
                        "rel_path": mid,
                        "path": str(MODELS_ROOT / lab_dir.name / model_dir.name),
                        "local": location_info(MODELS_ROOT, lab_dir.name, model_dir.name),
                        "shelf": shelf,
                        "hf_repo": inferred_repo,
                        "hf_url": f"https://huggingface.co/{inferred_repo}" if inferred_repo else None,
                        "capabilities": ["shelf-only"],
                        "why_downloaded": "On NAS shelf only — fetch to Spark to use locally",
                        "description": None,
                        "release_date": shelf_release,
                        "release_date_source": shelf_source,
                        "max_context": max_context_from_config(read_local_config(model_dir)),
                        "param_b": parse_param_b(model_dir.name, model_dir.name, {}),
                        "param_active_b": parse_active_param_b(model_dir.name, model_dir.name),
                        "status": "shelf-only",
                        "size_bytes": size,
                        "size_human": human_size(size),
                        "engines": model_engines(shelf_variants),
                        "variants": shelf_variants,
                    }
                )
                seen_ids.add(mid)

    profile_benchmarks = load_profile_benchmarks()
    attach_spark_verify(entries, load_spark_verification(), profile_benchmarks)
    attach_inference_profiles(entries, load_inference_profile_map())
    attach_best_bench_tok(entries)

    payload = {
        "generated_at": now,
        "local_root": str(MODELS_ROOT),
        "shelf_root": str(SHELF_ROOT),
        "shelf_mounted": shelf_mounted(),
        "count": len(entries),
        "models": sorted(entries, key=lambda x: (x["lab"], x["name"])),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2))
    save_hf_disk_cache(hf_cache)
    print(f"Wrote {OUT_JSON} ({len(entries)} models)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
