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
GOLDEN_RECIPES = Path("/opt/spark/data/golden-recipes.yaml")
OUT_JSON = Path("/opt/spark/portal/models.json")
HF_CACHE_FILE = Path("/opt/spark/run/hf-metadata-cache.json")
HF_CACHE_TTL_DAYS = 7
README_SUMMARY_VERSION = 6
SPARK_VERIFY_VALID = frozenset({"unverified", "wip", "works", "failed"})
BENCH_METHODS = frozenset({"bench", "bench-agent", "bench-agent-v2"})
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


def max_context_from_config(cfg: dict, _depth: int = 0) -> int | None:
    if not isinstance(cfg, dict) or _depth > 4:
        return None
    for key in (
        "max_position_embeddings",
        "model_max_length",
        "max_seq_len",
        "n_ctx",
        "seq_length",
    ):
        if key in cfg and cfg[key]:
            try:
                return int(cfg[key])
            except (TypeError, ValueError):
                pass
    rope = cfg.get("rope_scaling") or {}
    if isinstance(rope, dict) and rope.get("original_max_position_embeddings"):
        factor = rope.get("factor", 1)
        try:
            return int(rope["original_max_position_embeddings"] * factor)
        except (TypeError, ValueError):
            pass
    for nest in ("text_config", "llm_config", "language_config", "vision_config"):
        sub = cfg.get(nest)
        if isinstance(sub, dict):
            ctx = max_context_from_config(sub, _depth + 1)
            if ctx:
                return ctx
    return None


def _normalize_hf_repo(repo: str | None) -> str | None:
    if not repo:
        return None
    repo = repo.strip().strip("/").strip("'\"")
    repo = re.sub(r"^[-–—*•]\s*", "", repo)
    if "/" not in repo or "://" in repo:
        return None
    org, name = repo.split("/", 1)
    return f"{org}/{name.split('/')[0]}"


def _base_model_from_tags(tags: list | None) -> str | None:
    for tag in tags or []:
        if not isinstance(tag, str) or not tag.startswith("base_model:"):
            continue
        raw = tag.split(":", 1)[1].strip()
        if raw.startswith("quantized:"):
            raw = raw.split(":", 1)[1].strip()
        repo = _normalize_hf_repo(raw)
        if repo:
            return repo
    return None


def _iter_local_config_paths(model_path: Path, variants: list | None = None) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()

    def add(base: Path) -> None:
        cfg = base / "config.json"
        key = str(cfg)
        if cfg.is_file() and key not in seen:
            seen.add(key)
            paths.append(cfg)

    if model_path.is_dir():
        add(model_path)
        for sub in sorted(model_path.iterdir()):
            if sub.is_dir() and not sub.name.startswith("."):
                add(sub)
    for variant in variants or []:
        subpath = variant.get("subpath")
        if subpath:
            add(model_path / subpath)
    return paths


def _max_context_from_local(model_path: Path, variants: list | None = None) -> int | None:
    best: int | None = None
    for cfg_path in _iter_local_config_paths(model_path, variants):
        ctx = max_context_from_config(read_local_config(cfg_path.parent))
        if ctx and (best is None or ctx > best):
            best = ctx
    return best


def _best_local_config(model_path: Path, variants: list | None = None) -> dict:
    best: dict = {}
    best_ctx = -1
    for cfg_path in _iter_local_config_paths(model_path, variants):
        cfg = read_local_config(cfg_path.parent)
        if not cfg:
            continue
        ctx = max_context_from_config(cfg) or 0
        if ctx > best_ctx or not best:
            best = cfg
            best_ctx = ctx
    return best


def resolve_max_context(
    *,
    catalog_max: int | None,
    hf_repo: str | None,
    variants: list | None,
    model_path: Path,
    hf_cache: dict,
) -> int | None:
    if catalog_max:
        return int(catalog_max)
    local_ctx = _max_context_from_local(model_path, variants)
    repos = collect_hf_repos(hf_repo, variants or [])
    if not repos:
        repos = discover_hf_repos(model_path)
    seen: set[str] = set()
    for repo in repos:
        if not repo or repo in seen:
            continue
        seen.add(repo)
        info = hf_enrich(repo, hf_cache)
        if info.get("max_context"):
            return int(info["max_context"])
        base = _base_model_from_tags(info.get("tags"))
        if base and base not in seen:
            seen.add(base)
            base_info = hf_enrich(base, hf_cache)
            if base_info.get("max_context"):
                return int(base_info["max_context"])
    return local_ctx


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
    _repos_from_manifest(model_dir, repos, seen)
    _repos_from_config(model_dir, repos, seen)
    readme = model_dir / "README.md"
    if readme.is_file():
        _repos_from_readme(readme, repos, seen)
    for sub in sorted(model_dir.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        _repos_from_manifest(sub, repos, seen)
        _repos_from_config(sub, repos, seen)
        sub_readme = sub / "README.md"
        if sub_readme.is_file():
            _repos_from_readme(sub_readme, repos, seen)
    return repos


def _repos_from_manifest(model_dir: Path, repos: list[str], seen: set[str]) -> None:
    path = model_dir / "manifest.yaml"
    if not path.is_file() or yaml is None:
        return
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return
    if not isinstance(data, dict):
        return
    _add_hf_repo(repos, seen, data.get("hf_repo"))
    for variant in data.get("variants") or []:
        if isinstance(variant, dict):
            _add_hf_repo(repos, seen, variant.get("hf_repo"))


def local_earliest_mtime(model_path: Path) -> str | None:
    """ISO timestamp of oldest non-cache file under model_path (fallback release date)."""
    if not model_path.is_dir():
        return None
    earliest: float | None = None
    for root, dirs, files in os.walk(model_path):
        dirs[:] = [d for d in dirs if d not in (".cache", ".git")]
        for name in files:
            fp = Path(root) / name
            try:
                mtime = fp.stat().st_mtime
            except OSError:
                continue
            if earliest is None or mtime < earliest:
                earliest = mtime
    if earliest is None:
        return None
    return datetime.fromtimestamp(earliest, tz=timezone.utc).isoformat()


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
    for repo in discover_hf_repos(model_path):
        if repo not in repos:
            repos.append(repo)
    best_date: str | None = None
    for repo in repos:
        info = hf_enrich(repo, hf_cache)
        release_date = info.get("release_date")
        if release_date and (best_date is None or release_date < best_date):
            best_date = release_date
    if best_date:
        return best_date, "huggingface"
    local = local_earliest_mtime(model_path)
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
    cached = cache.get(repo)
    if cached and hf_cache_entry_fresh(cached) and cached.get("max_context") is not None:
        return cached
    info = {
        "description": (cached or {}).get("description"),
        "release_date": (cached or {}).get("release_date"),
        "max_context": (cached or {}).get("max_context"),
        "pipeline_tag": (cached or {}).get("pipeline_tag"),
        "tags": list((cached or {}).get("tags") or []),
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
        "removal_shelf": bool(entry.get("removal_shelf")),
        "removal_queued_at": entry.get("removal_queued_at"),
    }


def parse_param_b(name: str, slug: str, cfg: dict | None = None) -> float | None:
    cfg = cfg or {}
    blocks = [cfg]
    for nest in ("text_config", "llm_config", "language_config"):
        sub = cfg.get(nest)
        if isinstance(sub, dict):
            blocks.append(sub)
    for block in blocks:
        for key in ("num_parameters", "total_params", "n_parameters"):
            if key in block and block[key]:
                try:
                    n = float(block[key])
                    return n / 1e9 if n > 1e6 else n
                except (TypeError, ValueError):
                    pass
    text = f"{name} {slug}"
    if re.search(r"coder-next", text, re.I):
        return 80.0
    if re.search(r"\bphi-4\b", text, re.I):
        return 14.0
    if re.search(r"laguna-xs", text, re.I) and "dflash" not in text.lower():
        return 33.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?[Bb](?:\b|[-/])", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def parse_active_param_b(
    name: str,
    slug: str,
    cfg: dict | None = None,
    *,
    hf_repo: str | None = None,
) -> float | None:
    text = f"{name} {slug} {hf_repo or ''}"
    # 35B-A3B / 12B-A2.5B / 30b/a3b
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*[- ]?[Bb]\s*[-/]\s*[Aa]?(\d+(?:\.\d+)?)\s*[Bb]",
        text,
        re.I,
    )
    if m:
        try:
            return float(m.group(2))
        except ValueError:
            pass
    # Standalone A3B / A2.5B token (common in HF repo ids)
    m = re.search(r"(?:^|[^a-z0-9])[Aa](\d+(?:\.\d+)?)\s*[Bb](?:\b|[-_/])", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    if re.search(r"coder-next", text, re.I):
        return 3.0
    if re.search(r"deepseek-v4-flash|deepseek-v4", text, re.I):
        return 13.0
    if re.search(r"laguna-xs", text, re.I) and "dflash" not in text.lower():
        return 3.0
    # Ornith-1.0-35B is Qwen3.5-35B-A3B MoE (~3B active)
    if re.search(r"ornith", text, re.I) and re.search(r"35", text):
        return 3.0
    # JetBrains Mellum2 is 12B-A2.5B
    if re.search(r"mellum", text, re.I):
        return 2.5
    return None


def _config_blocks(cfg: dict | None) -> list[dict]:
    cfg = cfg or {}
    blocks = [cfg]
    for nest in ("text_config", "llm_config", "language_config"):
        sub = cfg.get(nest)
        if isinstance(sub, dict):
            blocks.append(sub)
    return blocks


def config_looks_moe(cfg: dict | None) -> bool:
    """True when local config.json exposes MoE expert routing."""
    for block in _config_blocks(cfg):
        try:
            n_experts = int(block.get("num_experts") or block.get("n_routed_experts") or 0)
        except (TypeError, ValueError):
            n_experts = 0
        if n_experts > 1:
            return True
    return False


def normalize_param_active_b(
    architecture: str | None,
    param_b: float | None,
    param_active_b: float | None,
) -> float | None:
    """Dense models: active = total so the Active column sorts usefully."""
    if param_active_b is not None and param_active_b > 0:
        return param_active_b
    if architecture == "dense" and param_b is not None:
        return param_b
    return param_active_b


def infer_architecture(
    *,
    capabilities: list | None,
    param_b: float | None,
    param_active_b: float | None,
    name: str = "",
    slug: str = "",
    cfg: dict | None = None,
) -> str | None:
    caps = {str(c).lower() for c in (capabilities or [])}
    if param_active_b or "moe" in caps or config_looks_moe(cfg):
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
            method = bench.get("method")
            # Only strip when the profile is present with a non-v2/legacy method.
            # Missing benchmark rows must not erase a recorded verify tok_s.
            if method and method not in BENCH_METHODS:
                sv["tok_s"] = None
                sv["tok_s_engine"] = None
                sv["tok_s_profile"] = None
        entry["spark_verify"] = sv


def is_speculative_profile(profile: dict) -> bool:
    """External sidecar specs (DFlash) — not built-in MTP on the same target weights."""
    spec = profile.get("speculative") if isinstance(profile.get("speculative"), dict) else None
    if spec:
        method = str(spec.get("method") or "").lower()
        if method == "mtp":
            return False
        if spec.get("sidecar_inventory") or spec.get("sidecar_path"):
            return True
        if method:
            return True
    tags = {str(t).lower() for t in (profile.get("tags") or [])}
    return "dflash" in tags or "sidecar" in tags


def baseline_profiles(profiles: list[dict]) -> list[dict]:
    return [p for p in profiles if not is_speculative_profile(p)]


def target_weight_bytes(target_entry: dict, weight_format: str | None) -> int:
    if weight_format:
        for variant in target_entry.get("variants") or []:
            if variant.get("format") == weight_format and variant.get("size_bytes"):
                return int(variant["size_bytes"])
    local = target_entry.get("local") or {}
    if local.get("size_bytes"):
        return int(local["size_bytes"])
    if target_entry.get("size_bytes"):
        return int(target_entry["size_bytes"])
    return 0


def attach_speculative_sidecars(
    entries: list, by_path: dict[str, list[dict]]
) -> None:
    """Attribute speculative/DFlash profiles to sidecar rows; keep baseline-only on targets."""
    sidecar_links: dict[str, list[dict]] = {}
    for target_inv, profiles in by_path.items():
        for profile in profiles:
            if not is_speculative_profile(profile):
                continue
            spec = profile.get("speculative") if isinstance(profile.get("speculative"), dict) else {}
            sidecar_inv = spec.get("sidecar_inventory")
            if not sidecar_inv:
                continue
            sidecar_links.setdefault(str(sidecar_inv), []).append(
                {
                    "profile": profile,
                    "target_inventory": str(target_inv),
                    "weight_format": spec.get("target_weight_format"),
                    "blocked": bool(spec.get("blocked")),
                    "blocked_reason": spec.get("blocked_reason"),
                }
            )

    entry_by_id = {str(e.get("id") or e.get("rel_path")): e for e in entries}

    for entry in entries:
        rel = str(entry.get("rel_path") or entry.get("id"))
        profiles = list(by_path.get(rel) or [])
        if not profiles:
            continue
        entry["inference_profiles"] = baseline_profiles(profiles)
        spec_on_target = speculative_profiles(profiles)
        if spec_on_target:
            entry["has_speculative_addon"] = True

    for sidecar_inv, links in sidecar_links.items():
        entry = entry_by_id.get(sidecar_inv)
        if not entry:
            continue
        entry["model_kind"] = entry.get("model_kind") or "speculative_sidecar"
        profiles = [link["profile"] for link in links]
        entry["inference_profiles"] = profiles
        primary = links[0]
        target_inv = primary["target_inventory"]
        target_entry = entry_by_id.get(target_inv)
        entry["requires_target"] = target_inv
        if target_entry:
            entry["requires_target_name"] = target_entry.get("name")
        sidecar_bytes = int((entry.get("local") or {}).get("size_bytes") or entry.get("size_bytes") or 0)
        target_bytes = target_weight_bytes(target_entry or {}, primary.get("weight_format"))
        combined = sidecar_bytes + target_bytes
        entry["sidecar_size_bytes"] = sidecar_bytes
        entry["sidecar_size_human"] = human_size(sidecar_bytes) if sidecar_bytes else None
        entry["requires_target_size_bytes"] = target_bytes or None
        entry["requires_target_size_human"] = human_size(target_bytes) if target_bytes else None
        entry["combined_size_bytes"] = combined or None
        entry["combined_size_human"] = human_size(combined) if combined else None
        if primary.get("blocked"):
            entry["speculative_blocked"] = True
            entry["speculative_blocked_reason"] = primary.get("blocked_reason")


def speculative_profiles(profiles: list[dict]) -> list[dict]:
    return [p for p in profiles if is_speculative_profile(p)]


def attach_unlinked_sidecar_metadata(entries: list) -> None:
    """Fill requires_target + combined size for z-lab sidecars without recipe links."""
    entry_by_id = {str(e.get("id") or e.get("rel_path")): e for e in entries}

    def sidecar_has_dflash(entry: dict) -> bool:
        caps = {str(c).lower() for c in (entry.get("capabilities") or [])}
        if "dflash" in caps or "speculative" in caps:
            return True
        path = Path(entry.get("path") or "")
        if (path / "dflash").is_dir():
            return True
        return any(v.get("format") == "dflash" for v in (entry.get("variants") or []))

    def infer_target(sidecar: dict) -> dict | None:
        slug = sidecar.get("slug") or ""
        if not slug:
            return None
        exact = [
            e for eid, e in entry_by_id.items()
            if eid != sidecar.get("id") and (e.get("slug") or "") == slug
        ]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            exact.sort(key=lambda e: int((e.get("local") or {}).get("present") or 0), reverse=True)
            return exact[0]
        prefix = [
            e for eid, e in entry_by_id.items()
            if eid != sidecar.get("id")
            and ((e.get("slug") or "").startswith(slug + "-") or slug.startswith((e.get("slug") or "") + "-"))
        ]
        if prefix:
            prefix.sort(
                key=lambda e: (
                    int((e.get("local") or {}).get("present") or 0),
                    int((e.get("local") or {}).get("size_bytes") or 0),
                ),
                reverse=True,
            )
            return prefix[0]
        return None

    for entry in entries:
        if entry.get("lab") != "z-lab" or not sidecar_has_dflash(entry):
            continue
        entry["model_kind"] = entry.get("model_kind") or "speculative_sidecar"
        if entry.get("requires_target"):
            continue
        target = infer_target(entry)
        if not target:
            continue
        target_inv = str(target.get("rel_path") or target.get("id"))
        entry["requires_target"] = target_inv
        entry["requires_target_name"] = target.get("name")
        sidecar_bytes = int((entry.get("local") or {}).get("size_bytes") or entry.get("size_bytes") or 0)
        target_bytes = int((target.get("local") or {}).get("size_bytes") or target.get("size_bytes") or 0)
        combined = sidecar_bytes + target_bytes
        entry["sidecar_size_bytes"] = sidecar_bytes or None
        entry["sidecar_size_human"] = human_size(sidecar_bytes) if sidecar_bytes else None
        entry["requires_target_size_bytes"] = target_bytes or None
        entry["requires_target_size_human"] = human_size(target_bytes) if target_bytes else None
        entry["combined_size_bytes"] = combined or None
        entry["combined_size_human"] = human_size(combined) if combined else None


def load_golden_recipe_maps() -> tuple[dict[str, str], set[str]]:
    """Return (inventory_path -> golden profile id, deprecated profile ids)."""
    if yaml is None or not GOLDEN_RECIPES.is_file():
        return {}, set()
    try:
        data = yaml.safe_load(GOLDEN_RECIPES.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}, set()
    golden = data.get("golden") or {}
    inv_to_profile = {
        str(k): str(v)
        for k, v in golden.items()
        if isinstance(k, str) and isinstance(v, str) and k and v
    }
    deprecated = {
        str(p)
        for p in (data.get("deprecated_profiles") or [])
        if isinstance(p, str) and p
    }
    return inv_to_profile, deprecated


def _bench_profile_for_entry(entry: dict, profiles: list[dict], golden_by_inv: dict[str, str]) -> dict | None:
    """Pick the headline bench profile — golden production recipe, not experimental max."""
    rated = [p for p in profiles if p.get("tok_s") is not None]
    if not rated:
        return None
    rel = str(entry.get("rel_path") or entry.get("id") or "")
    golden_id = entry.get("golden_profile") or golden_by_inv.get(rel)
    if golden_id:
        for p in rated:
            if p.get("id") == golden_id:
                return p
    if entry.get("model_kind") == "speculative_sidecar":
        target_inv = str(entry.get("requires_target") or "")
        golden_id = golden_by_inv.get(target_inv)
        if golden_id:
            for p in rated:
                if p.get("id") == golden_id:
                    return p
        v2 = [p for p in rated if p.get("bench_method") == "bench-agent-v2"]
        if v2:
            return max(v2, key=lambda p: float(p["tok_s"]))
    return max(rated, key=lambda p: float(p["tok_s"]))


def attach_best_bench_tok(entries: list, golden_by_inv: dict[str, str] | None = None) -> None:
    golden_by_inv = golden_by_inv or {}
    for entry in entries:
        profiles = entry.get("inference_profiles") or []
        best = _bench_profile_for_entry(entry, profiles, golden_by_inv)
        entry["best_bench_tok_s"] = best.get("tok_s") if best else None
        entry["latest_bench_tok_s"] = entry["best_bench_tok_s"]
        entry.pop("best_speculative_tok_s", None)


def propagate_sidecar_bench_to_targets(entries: list) -> None:
    """Surface DFlash/sidecar tok/s on the base model row users actually click."""
    by_id = {str(e.get("id") or e.get("rel_path")): e for e in entries}
    for entry in entries:
        if entry.get("model_kind") != "speculative_sidecar":
            continue
        tok = entry.get("best_bench_tok_s")
        if tok is None:
            continue
        target = by_id.get(str(entry.get("requires_target") or ""))
        if not target:
            continue
        target["has_speculative_addon"] = True
        if target.get("best_bench_tok_s") is None:
            target["best_bench_tok_s"] = tok
            target["latest_bench_tok_s"] = tok


def fill_best_bench_from_verify(entries: list) -> None:
    """Last resort: verification tok_s when profiles/benchmarks didn't attach a score."""
    for entry in entries:
        if entry.get("best_bench_tok_s") is not None:
            continue
        sv = entry.get("spark_verify") or {}
        tok = sv.get("tok_s")
        if tok is None:
            continue
        try:
            entry["best_bench_tok_s"] = float(tok)
            entry["latest_bench_tok_s"] = entry["best_bench_tok_s"]
        except (TypeError, ValueError):
            continue


def reconcile_spark_verify_with_profiles(
    entry: dict, golden_by_inv: dict[str, str] | None = None
) -> None:
    """Align portal spark_verify headline with attributed inference profiles."""
    sv = dict(entry.get("spark_verify") or {})
    profiles = entry.get("inference_profiles") or []
    rated = [p for p in profiles if p.get("tok_s") is not None]
    kind = entry.get("model_kind")
    golden_by_inv = golden_by_inv or {}

    if kind == "speculative_sidecar":
        if entry.get("speculative_blocked") and not rated:
            sv["spark_status"] = "failed"
            if entry.get("speculative_blocked_reason"):
                sv["note"] = str(entry["speculative_blocked_reason"])
        elif rated:
            best = _bench_profile_for_entry(entry, profiles, golden_by_inv) or max(
                rated, key=lambda p: float(p["tok_s"])
            )
            spec = best.get("speculative") if isinstance(best.get("speculative"), dict) else {}
            sv["spark_status"] = "failed" if spec.get("blocked") else "works"
            sv["tok_s"] = best.get("tok_s")
            sv["tok_s_engine"] = best.get("engine")
            sv["tok_s_profile"] = best.get("id")
            if best.get("notes"):
                sv["note"] = best["notes"]
        elif sv.get("spark_status") == "failed" and sv.get("note"):
            pass
        entry["spark_verify"] = sv
        return

    if rated:
        best = _bench_profile_for_entry(entry, profiles, golden_by_inv) or max(
            rated, key=lambda p: float(p["tok_s"])
        )
        # Never auto-promote to works — only explicit verify set (post successful bench) does that.
        sv["tok_s"] = best.get("tok_s")
        sv["tok_s_engine"] = best.get("engine")
        sv["tok_s_profile"] = best.get("id")
        if best.get("notes") and not sv.get("note"):
            sv["note"] = best["notes"]
    elif entry.get("has_speculative_addon"):
        entry.pop("has_speculative_addon", None)
    entry["spark_verify"] = sv


def load_inference_profile_map() -> dict[str, list[dict]]:
    """Map inventory_path -> enabled recipe profiles for portal bridge."""
    if yaml is None or not RECIPES_DIR.is_dir():
        return {}

    _, deprecated_profiles = load_golden_recipe_maps()

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
        if profile_id in deprecated_profiles:
            continue
        try:
            recipe = yaml.safe_load(recipe_file.read_text()) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(recipe, dict):
            continue
        if str(recipe.get("lifecycle") or "").lower() == "deprecated":
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
        ctx_block = recipe.get("context") if isinstance(recipe.get("context"), dict) else {}
        ctx_ladder = ctx_block.get("ctx_ladder") if isinstance(ctx_block.get("ctx_ladder"), dict) else None
        kv_sweep = ctx_block.get("kv_sweep") if isinstance(ctx_block.get("kv_sweep"), dict) else None
        bench_matrix = ctx_block.get("bench_matrix") if isinstance(ctx_block.get("bench_matrix"), dict) else None
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
            "ctx_ladder": ctx_ladder,
            "kv_sweep": kv_sweep,
            "bench_matrix": bench_matrix,
            "model": recipe.get("model"),
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


WEIGHT_SUBDIR_NAMES = frozenset(
    {
        "hf",
        "fp8",
        "nvfp4",
        "gguf",
        "mtp-gguf",
        "awq",
        "gptq",
        "int4",
        "int8",
        "bnb",
        "exl2",
        "dflash",
        "compressed-tensors",
    }
)
SKIP_WEIGHT_DIR_NAMES = frozenset({"assets", ".cache", "__pycache__"})
ENGINE_BY_SUBPATH = {
    "gguf": "llamacpp",
    "mtp-gguf": "llamacpp",
    "fp8": "vllm",
    "nvfp4": "vllm",
    "hf": "vllm",
    "dflash": "vllm",
    "awq": "vllm",
    "gptq": "vllm",
}
LABEL_BY_SUBPATH = {
    "hf": "HF weights",
    "fp8": "FP8",
    "nvfp4": "NVFP4",
    "gguf": "GGUF",
    "mtp-gguf": "MTP GGUF",
    "dflash": "DFlash",
    "awq": "AWQ",
    "gptq": "GPTQ",
}


def variant_status(base: Path, subpath: str) -> tuple[str, int]:
    p = base / subpath
    if not p.exists():
        return "missing", 0
    size = dir_size(p)
    if size == 0:
        return "empty", 0
    # partial heuristic: nvfp4/hf expect config; gguf expects .gguf
    if subpath in ("gguf", "mtp-gguf"):
        ggufs = list(p.glob("*.gguf"))
        if not ggufs:
            return "downloading", size
    elif subpath in ("nvfp4", "hf", "fp8"):
        if not (p / "config.json").exists() and not list(p.glob("*.gguf")):
            # may still be downloading safetensors
            st = list(p.glob("*.safetensors")) + list(p.glob("model-*"))
            if not st and size < 1_000_000:
                return "downloading", size
            if not st and size > 0:
                return "downloading", size
    return "ready", size


def _looks_like_weight_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "config.json").exists():
        return True
    if any(path.glob("*.safetensors")):
        return True
    if any(path.glob("*.gguf")):
        return True
    return False


def _gguf_label(filename: str, subpath: str | None = None) -> str:
    stem = Path(filename).stem
    # Prefer trailing quant token: Q4_K_M, Q8_0, IQ4_XS, NVFP4-MTP, etc.
    m = re.search(
        r"(?:^|[-_.])((?:IQ|Q|UQ)\d[\w.]*|NVFP4(?:-MTP)?|FP\d+|BF16|F16|F32|MXFP\d+(?:_MOE)?)(?:$|[-_.])",
        stem,
        re.I,
    )
    if m:
        label = f"{m.group(1).upper()} GGUF"
    else:
        label = f"{stem} GGUF"
    if subpath == "mtp-gguf" and "MTP" not in label.upper():
        label = label.replace(" GGUF", " MTP GGUF")
    return label


def _variant_label(subpath: str, format_: str | None, file: str | None = None) -> str:
    if file:
        return _gguf_label(file, subpath)
    if subpath in LABEL_BY_SUBPATH:
        return LABEL_BY_SUBPATH[subpath]
    if format_ in LABEL_BY_SUBPATH:
        return LABEL_BY_SUBPATH[format_]
    return (format_ or subpath or "weights").upper()


def _variant_key(subpath: str, file: str | None = None) -> str:
    return f"{subpath}/{file}" if file else subpath


def build_weight_variants(base: Path, catalog_variants: list | None) -> list[dict]:
    """Build deduped on-disk weight units (subdir and/or per-GGUF file).

    Catalog variants are hints (engine/hf_repo). Disk wins for what exists and sizes.
    Mixed dirs (safetensors + GGUFs in the same folder) emit separate units so the
    Models page can show one row per servable artifact.
    """
    catalog_by_sub: dict[str, dict] = {}
    for v in catalog_variants or []:
        sub = (v or {}).get("subpath")
        if not sub or sub in catalog_by_sub:
            continue
        catalog_by_sub[sub] = v

    found_subs: set[str] = set(catalog_by_sub.keys())
    if base.is_dir():
        for child in base.iterdir():
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_WEIGHT_DIR_NAMES:
                continue
            if child.name in WEIGHT_SUBDIR_NAMES or _looks_like_weight_dir(child):
                found_subs.add(child.name)

    variants: list[dict] = []
    for sub in sorted(found_subs):
        meta = catalog_by_sub.get(sub) or {}
        p = base / sub
        hf_repo = meta.get("hf_repo")
        hf_url = f"https://huggingface.co/{hf_repo}" if hf_repo else None
        note = meta.get("note")

        if not p.exists():
            variants.append(
                {
                    "format": meta.get("format") or sub,
                    "engine": meta.get("engine") or ENGINE_BY_SUBPATH.get(sub),
                    "subpath": sub,
                    "path": str(p),
                    "label": _variant_label(sub, meta.get("format")),
                    "key": _variant_key(sub),
                    "hf_repo": hf_repo,
                    "hf_url": hf_url,
                    "status": "missing",
                    "size_bytes": 0,
                    "size_human": human_size(0),
                    "note": note,
                }
            )
            continue

        ggufs = sorted(p.glob("*.gguf"))
        has_tensors = bool(
            (p / "config.json").exists()
            or list(p.glob("*.safetensors"))
            or list(p.glob("model-*.safetensors"))
        )
        gguf_bytes = 0
        for g in ggufs:
            try:
                sz = int(g.stat().st_size)
            except OSError:
                sz = 0
            gguf_bytes += sz
            variants.append(
                {
                    "format": "gguf",
                    "engine": "llamacpp",
                    "subpath": sub,
                    "file": g.name,
                    "path": str(g),
                    "label": _gguf_label(g.name, sub),
                    "key": _variant_key(sub, g.name),
                    "hf_repo": hf_repo,
                    "hf_url": hf_url,
                    "status": "ready" if sz > 0 else "empty",
                    "size_bytes": sz,
                    "size_human": human_size(sz),
                    "note": note,
                }
            )

        if has_tensors or not ggufs:
            status, full_size = variant_status(base, sub)
            if ggufs and has_tensors:
                size = max(0, full_size - gguf_bytes)
                status = "ready" if size > 0 else status
            else:
                size = full_size
            # Skip empty leftover after splitting GGUFs out of a GGUF-only dir
            if size <= 0 and ggufs:
                continue
            fmt = meta.get("format") or (sub if sub in WEIGHT_SUBDIR_NAMES else "hf")
            if fmt == "gguf" and has_tensors:
                fmt = sub if sub in ("fp8", "nvfp4") else "hf"
            engine = meta.get("engine") or ENGINE_BY_SUBPATH.get(sub) or ENGINE_BY_SUBPATH.get(fmt)
            if fmt == "gguf":
                engine = "llamacpp"
            variants.append(
                {
                    "format": fmt,
                    "engine": engine,
                    "subpath": sub,
                    "path": str(p),
                    "label": _variant_label(sub, fmt),
                    "key": _variant_key(sub),
                    "hf_repo": hf_repo,
                    "hf_url": hf_url,
                    "status": status,
                    "size_bytes": size,
                    "size_human": human_size(size),
                    "note": note,
                }
            )

    return variants


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
        hf_repo = _normalize_hf_repo(m.get("hf_repo", "")) or (m.get("hf_repo") or "").strip()
        hf_info = hf_enrich(hf_repo, hf_cache) if hf_repo else {}

        max_ctx = resolve_max_context(
            catalog_max=m.get("max_context"),
            hf_repo=hf_repo or None,
            variants=m.get("variants", []),
            model_path=base,
            hf_cache=hf_cache,
        )

        variants = build_weight_variants(base, m.get("variants", []))
        statuses = [v.get("status") or "missing" for v in variants]
        # Prefer real on-disk tree size so list totals match `du` (no double-count).
        local = location_info(MODELS_ROOT, lab, slug)
        total_size = int(local.get("size_bytes") or 0)
        if not total_size:
            total_size = sum(int(v.get("size_bytes") or 0) for v in variants)

        if not statuses:
            overall = "ready" if total_size > 0 else "missing"
        elif all(s == "missing" for s in statuses):
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
        if m.get("release_date"):
            release_date = str(m.get("release_date"))
            release_date_source = "catalog"
        if not release_date:
            release_date = hf_info.get("release_date")
            release_date_source = "huggingface" if release_date else None

        shelf = location_info(SHELF_ROOT, lab, slug)
        shelf["mounted"] = shelf_mounted()

        best_cfg = _best_local_config(base, m.get("variants", []))
        param_b = m.get("param_b") or parse_param_b(m["name"], slug, best_cfg)
        param_active_b = m.get("param_active_b") or parse_active_param_b(
            m["name"], slug, best_cfg, hf_repo=hf_repo
        )
        catalog_arch = m.get("architecture")
        if catalog_arch in ("moe", "dense"):
            architecture = catalog_arch
        else:
            architecture = infer_architecture(
                capabilities=m.get("capabilities", []),
                param_b=param_b,
                param_active_b=param_active_b,
                name=m["name"],
                slug=slug,
                cfg=best_cfg,
            )
        param_active_b = normalize_param_active_b(architecture, param_b, param_active_b)

        entries.append(
            {
                "id": m["id"],
                "lab": lab,
                "name": m["name"],
                "slug": slug,
                "rel_path": f"{lab}/{slug}",
                "path": str(base),
                "local": local,
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
                "model_kind": m.get("model_kind"),
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
                inferred_repo = _normalize_hf_repo(infer_hf_repo_from_path(model_dir)) or infer_hf_repo_from_path(model_dir)
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
                untracked_cfg = _best_local_config(model_dir, untracked_variants)
                untracked_param_b = parse_param_b(model_dir.name, slug, untracked_cfg)
                untracked_param_active_b = parse_active_param_b(model_dir.name, slug, untracked_cfg)
                untracked_arch = infer_architecture(
                    capabilities=["untracked"],
                    param_b=untracked_param_b,
                    param_active_b=untracked_param_active_b,
                    name=model_dir.name,
                    slug=slug,
                    cfg=untracked_cfg,
                )
                untracked_param_active_b = normalize_param_active_b(
                    untracked_arch, untracked_param_b, untracked_param_active_b
                )
                untracked_ctx = resolve_max_context(
                    catalog_max=None,
                    hf_repo=inferred_repo,
                    variants=untracked_variants,
                    model_path=model_dir,
                    hf_cache=hf_cache,
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
                        "why_downloaded": untracked_why,
                        "summary": untracked_summary,
                        "release_date": untracked_release,
                        "release_date_source": untracked_source,
                        "max_context": untracked_ctx,
                        "param_b": untracked_param_b,
                        "param_active_b": untracked_param_active_b,
                        "architecture": untracked_arch,
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
                inferred_repo = _normalize_hf_repo(infer_hf_repo_from_path(model_dir)) or infer_hf_repo_from_path(model_dir)
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
                shelf_cfg = _best_local_config(model_dir, shelf_variants)
                shelf_param_b = parse_param_b(model_dir.name, model_dir.name, shelf_cfg)
                shelf_param_active_b = parse_active_param_b(model_dir.name, model_dir.name, shelf_cfg)
                shelf_arch = infer_architecture(
                    capabilities=["shelf-only"],
                    param_b=shelf_param_b,
                    param_active_b=shelf_param_active_b,
                    name=model_dir.name,
                    slug=model_dir.name,
                    cfg=shelf_cfg,
                )
                shelf_param_active_b = normalize_param_active_b(
                    shelf_arch, shelf_param_b, shelf_param_active_b
                )
                shelf_ctx = resolve_max_context(
                    catalog_max=None,
                    hf_repo=inferred_repo,
                    variants=shelf_variants,
                    model_path=model_dir,
                    hf_cache=hf_cache,
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
                        "why_downloaded": shelf_why,
                        "summary": shelf_summary,
                        "release_date": shelf_release,
                        "release_date_source": shelf_source,
                        "max_context": shelf_ctx,
                        "param_b": shelf_param_b,
                        "param_active_b": shelf_param_active_b,
                        "architecture": shelf_arch,
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
    golden_by_inv, _ = load_golden_recipe_maps()
    for entry in entries:
        rel = entry.get("rel_path") or ""
        entry["is_golden"] = rel in golden_by_inv
        entry["golden_profile"] = golden_by_inv.get(rel)
    profile_map = load_inference_profile_map()
    attach_inference_profiles(entries, profile_map)
    attach_speculative_sidecars(entries, profile_map)
    attach_unlinked_sidecar_metadata(entries)
    for entry in entries:
        caps = {str(c).lower() for c in (entry.get("capabilities") or [])}
        if entry.get("lab") == "z-lab" and ("dflash" in caps or "speculative" in caps):
            entry.setdefault("model_kind", "speculative_sidecar")
    attach_best_bench_tok(entries, golden_by_inv)
    propagate_sidecar_bench_to_targets(entries)
    for entry in entries:
        reconcile_spark_verify_with_profiles(entry, golden_by_inv)
    fill_best_bench_from_verify(entries)

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
