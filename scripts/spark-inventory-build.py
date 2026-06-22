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
BENCHMARK_HISTORY_FILE = Path("/opt/spark/run/inference-benchmark-history.yaml")
BENCHMARK_HISTORY_LEGACY = Path("/opt/spark/data/inference-benchmark-history.yaml")
OUT_JSON = Path("/opt/spark/portal/models.json")
HF_CACHE_FILE = Path("/opt/spark/run/hf-metadata-cache.json")
HF_CACHE_TTL_DAYS = 7
README_SUMMARY_VERSION = 6
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


def _normalize_hf_repo(repo: str | None) -> str | None:
    if not repo:
        return None
    repo = repo.strip().strip("/").strip("'\"")
    if "/" not in repo or "://" in repo:
        return None
    org, name = repo.split("/", 1)
    return f"{org}/{name.split('/')[0]}"


def _add_hf_repo(repos: list[str], seen: set[str], repo: str | None) -> None:
    repo = _normalize_hf_repo(repo)
    if not repo or repo in seen:
        return
    seen.add(repo)
    repos.append(repo)


def _repos_from_config(base: Path, repos: list[str], seen: set[str]) -> None:
    cfg = read_local_config(base)
    for key in ("_name_or_path", "name_or_path"):
        val = cfg.get(key)
        if val and isinstance(val, str):
            _add_hf_repo(repos, seen, val)


def _repos_from_readme(readme: Path, repos: list[str], seen: set[str]) -> None:
    try:
        text = readme.read_text(errors="ignore")[:12000]
    except OSError:
        return
    fm = re.match(r"---\s*\n(.*?)\n---", text, re.DOTALL)
    block = fm.group(1) if fm else text[:2000]
    for match in re.finditer(r"huggingface\.co/([^\s)\]\"']+)", block):
        _add_hf_repo(repos, seen, match.group(1).rstrip("/"))
    if not fm:
        return
    for match in re.finditer(r"base_model:\s*['\"]?([^'\"\n]+)['\"]?", block):
        _add_hf_repo(repos, seen, match.group(1).strip())
    in_base = False
    for line in block.splitlines():
        if re.match(r"base_model:\s*$", line.strip()):
            in_base = True
            continue
        if in_base:
            item = re.match(r"\s*-\s+['\"]?([^'\"\n]+)['\"]?", line)
            if item:
                _add_hf_repo(repos, seen, item.group(1).strip())
            elif line.strip() and not line.startswith(" "):
                in_base = False


def discover_hf_repos(model_dir: Path) -> list[str]:
    repos: list[str] = []
    seen: set[str] = set()
    if not model_dir.is_dir():
        return repos
    _repos_from_config(model_dir, repos, seen)
    readme = model_dir / "README.md"
    if readme.is_file():
        _repos_from_readme(readme, repos, seen)
    for sub in sorted(model_dir.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        _repos_from_config(sub, repos, seen)
        sub_readme = sub / "README.md"
        if sub_readme.is_file():
            _repos_from_readme(sub_readme, repos, seen)
    return repos


def infer_hf_repo_from_path(model_dir: Path) -> str | None:
    repos = discover_hf_repos(model_dir)
    return repos[0] if repos else None


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
    if not repos:
        repos = discover_hf_repos(model_path)
    best_date: str | None = None
    for repo in repos:
        info = hf_enrich(repo, hf_cache)
        release_date = info.get("release_date")
        if release_date and (best_date is None or release_date < best_date):
            best_date = release_date
    if best_date:
        return best_date, "huggingface"
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


def _strip_inline_html(line: str) -> str:
    return re.sub(r"<[^>]+>", " ", line).strip()


def _looks_like_code(line: str) -> bool:
    low = line.lower()
    if line.count("`") >= 4:
        return True
    if re.match(r"^(bash|sh|python|curl|git |cmake|apt-get|export |\./|pip )", low):
        return True
    if re.search(r"\b(cmake|llama-server|llama\.cpp/build|git clone|pip install)\b", low):
        return True
    return False


def extract_readme_summary(text: str, max_len: int = 700) -> str | None:
    body = text
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]
    lines: list[str] = []
    in_code = False
    for line in body.splitlines():
        stripped = _strip_inline_html(line.strip())
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if stripped.startswith(("![", "[!", "| ", "|-", "|:", ">")):
            continue
        if stripped.startswith("[") and "](" in stripped:
            continue
        if _looks_like_code(stripped):
            continue
        if re.match(r"^([^|]{1,40} \| ){2,}[^|]{1,60}$", stripped):
            continue
        if stripped.startswith("#"):
            heading = re.sub(r"^#+\s*", "", stripped)
            heading = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading)
            heading = re.sub(r"[*_`]", "", heading).strip()
            if len(heading) > 3 and not heading.startswith("http"):
                lines.append(heading + ".")
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        line = re.sub(r"[*_`]", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    paras: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line == "":
            if buf:
                paras.append(" ".join(buf))
                buf = []
        else:
            buf.append(line)
    if buf:
        paras.append(" ".join(buf))
    good: list[str] = []
    for para in paras:
        low = para.lower()
        if len(para) < 40:
            continue
        if low.startswith(("table of contents", "bibtex", "citation", "license")):
            continue
        if para.count("http") > 2:
            continue
        if _looks_like_code(para) or "src=" in para:
            continue
        good.append(para)
        if len(good) >= 3:
            break
    summary = " ".join(good)
    summary = re.sub(r"\s+", " ", summary).strip()
    summary = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        summary,
    )
    if not summary:
        return None
    if len(summary) > max_len:
        summary = summary[: max_len - 1].rsplit(" ", 1)[0] + "…"
    return summary


def hf_readme_summary(repo: str, cache: dict) -> str | None:
    entry = cache.get(repo) or {}
    if (
        entry.get("readme_summary")
        and entry.get("readme_summary_version") == README_SUMMARY_VERSION
        and hf_cache_entry_fresh(entry)
    ):
        return entry.get("readme_summary")
    summary = None
    try:
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(repo, "README.md")
        summary = extract_readme_summary(Path(path).read_text(errors="ignore"))
    except Exception:
        pass
    if repo not in cache or not isinstance(cache.get(repo), dict):
        cache[repo] = {}
    cache[repo]["readme_summary"] = summary
    cache[repo]["readme_summary_version"] = README_SUMMARY_VERSION
    cache[repo]["_fetched_at"] = datetime.now(timezone.utc).isoformat()
    return summary


def local_readme_summary(model_path: Path, subpath: str | None = None) -> str | None:
    bases: list[Path] = []
    if subpath:
        bases.append(model_path / subpath)
    bases.append(model_path)
    for base in bases:
        readme = base / "README.md"
        if readme.is_file():
            text = extract_readme_summary(readme.read_text(errors="ignore"))
            if text:
                return text
    return None


SPARK_WHY_SKIP_PREFIXES = (
    "not in catalog",
    "on nas shelf only",
)


def build_model_summary(
    hf_repo: str | None,
    variants: list,
    why_downloaded: str,
    model_path: Path | None,
    hf_cache: dict,
    catalog_summary: str | None = None,
) -> str | None:
    parts: list[str] = []
    seen: set[str] = set()

    def add_summary(label: str | None, text: str | None) -> None:
        if not text or text in seen:
            return
        seen.add(text)
        parts.append(f"{label}: {text}" if label else text)

    variant_entries = variants or []
    if variant_entries:
        for variant in variant_entries:
            repo = variant.get("hf_repo")
            subpath = variant.get("subpath")
            text = None
            if model_path and subpath:
                text = local_readme_summary(model_path, subpath)
            if not text and repo:
                text = hf_readme_summary(repo, hf_cache)
            if not text:
                continue
            label = None
            if len(variant_entries) > 1:
                label = (variant.get("subpath") or variant.get("format") or "").upper()
                if variant.get("note"):
                    label = f"{label} ({variant['note']})" if label else variant["note"]
            add_summary(label or None, text)
    else:
        text = local_readme_summary(model_path) if model_path else None
        if not text and hf_repo:
            text = hf_readme_summary(hf_repo, hf_cache)
        if not text and model_path:
            for repo in discover_hf_repos(model_path):
                if repo == hf_repo:
                    continue
                text = hf_readme_summary(repo, hf_cache)
                if text:
                    break
        add_summary(None, text)

    if not parts and catalog_summary:
        add_summary(None, re.sub(r"\s+", " ", catalog_summary.strip()))

    why = re.sub(r"\s+", " ", (why_downloaded or "").strip())
    if why and not any(why.lower().startswith(p) for p in SPARK_WHY_SKIP_PREFIXES):
        parts.append(f"On Spark: {why}")

    return "\n\n".join(parts) if parts else None


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


def infer_architecture(
    *,
    capabilities: list | None,
    param_b: float | None,
    param_active_b: float | None,
    name: str = "",
    slug: str = "",
) -> str | None:
    caps = {str(c).lower() for c in (capabilities or [])}
    if param_active_b or "moe" in caps:
        return "moe"
    if "dense" in caps:
        return "dense"
    text = f"{name} {slug}".lower()
    if re.search(r"a\d+b|moe", text):
        return "moe"
    if param_b is not None:
        return "dense"
    return None


def _bench_history_path() -> Path | None:
    if BENCHMARK_HISTORY_FILE.is_file():
        return BENCHMARK_HISTORY_FILE
    if BENCHMARK_HISTORY_LEGACY.is_file():
        return BENCHMARK_HISTORY_LEGACY
    return None


def load_bench_history_counts() -> dict[str, int]:
    path = _bench_history_path()
    if yaml is None or path is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        profiles = data.get("profiles") or {}
        if not isinstance(profiles, dict):
            return {}
        out: dict[str, int] = {}
        for profile_id, prof in profiles.items():
            if isinstance(prof, dict):
                runs = prof.get("runs") or []
                if isinstance(runs, list):
                    out[str(profile_id)] = len(runs)
        return out
    except (OSError, yaml.YAMLError):
        return {}


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
        entry["latest_bench_tok_s"] = entry["best_bench_tok_s"]


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
    history_counts = load_bench_history_counts()

    by_path: dict[str, list[dict]] = {}
    recipe_files = sorted(RECIPES_DIR.glob("*.yaml"))
    drafts_dir = RECIPES_DIR / "drafts"
    if drafts_dir.is_dir():
        recipe_files.extend(sorted(drafts_dir.glob("*.yaml")))
    for recipe_file in recipe_files:
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
        lifecycle = recipe.get("lifecycle")
        if not lifecycle:
            lifecycle = "works" if recipe_file.parent == RECIPES_DIR else "draft"
        spec = recipe.get("speculative") if isinstance(recipe.get("speculative"), dict) else None
        mtp = recipe.get("mtp") if isinstance(recipe.get("mtp"), dict) else None
        tags = recipe.get("tags") or []
        info = {
            "id": profile_id,
            "name": recipe.get("name"),
            "engine": recipe.get("engine"),
            "tier": recipe.get("tier"),
            "lifecycle": lifecycle,
            "enabled": profile_id in enabled or (lifecycle in ("production", "works")),
            "tok_s": bench.get("tok_s") if measured else None,
            "bench_method": method if measured else None,
            "bench_measured_at": bench.get("measured_at") if measured else None,
            "latest_run_id": bench.get("latest_run_id") if measured else None,
            "bench_run_count": history_counts.get(profile_id, 0),
            "notes": first_note,
            "tags": tags if isinstance(tags, list) else [],
            "speculative": spec,
            "mtp": mtp,
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

        summary = build_model_summary(
            hf_repo or None,
            m.get("variants", []),
            (m.get("why_downloaded") or "").strip(),
            base,
            hf_cache,
            catalog_summary=(m.get("summary") or "").strip() or None,
        )

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
        architecture = infer_architecture(
            capabilities=m.get("capabilities", []),
            param_b=param_b,
            param_active_b=param_active_b,
            name=m["name"],
            slug=slug,
        )

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
                "summary": summary,
                "release_date": release_date,
                "release_date_source": release_date_source,
                "max_context": max_ctx,
                "param_b": param_b,
                "param_active_b": param_active_b,
                "architecture": architecture,
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
                untracked_why = "Not in catalog — add to model-catalog.yaml"
                untracked_summary = build_model_summary(
                    inferred_repo,
                    untracked_variants,
                    untracked_why,
                    model_dir,
                    hf_cache,
                )
                untracked_param_b = parse_param_b(model_dir.name, slug, read_local_config(model_dir))
                untracked_param_active_b = parse_active_param_b(model_dir.name, slug)
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
                        "why_downloaded": untracked_why,
                        "summary": untracked_summary,
                        "release_date": untracked_release,
                        "release_date_source": untracked_source,
                        "max_context": max_context_from_config(read_local_config(model_dir)),
                        "param_b": untracked_param_b,
                        "param_active_b": untracked_param_active_b,
                        "architecture": infer_architecture(
                            capabilities=["untracked"],
                            param_b=untracked_param_b,
                            param_active_b=untracked_param_active_b,
                            name=model_dir.name,
                            slug=slug,
                        ),
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
                shelf_why = "On NAS shelf only — fetch to Spark to use locally"
                shelf_summary = build_model_summary(
                    inferred_repo,
                    shelf_variants,
                    shelf_why,
                    model_dir,
                    hf_cache,
                )
                shelf_param_b = parse_param_b(model_dir.name, model_dir.name, {})
                shelf_param_active_b = parse_active_param_b(model_dir.name, model_dir.name)
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
                        "why_downloaded": shelf_why,
                        "summary": shelf_summary,
                        "release_date": shelf_release,
                        "release_date_source": shelf_source,
                        "max_context": max_context_from_config(read_local_config(model_dir)),
                        "param_b": shelf_param_b,
                        "param_active_b": shelf_param_active_b,
                        "architecture": infer_architecture(
                            capabilities=["shelf-only"],
                            param_b=shelf_param_b,
                            param_active_b=shelf_param_active_b,
                            name=model_dir.name,
                            slug=model_dir.name,
                        ),
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
