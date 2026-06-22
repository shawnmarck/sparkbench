#!/opt/spark/venv/bin/python3
"""Phase 5c HF Explorer — discovery, download planner, queue worker."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from urllib.parse import unquote, unquote_plus
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
MODELS_ROOT = Path("/models")
DATA_DIR = ROOT / "data"
RUN_DIR = ROOT / "run"
LOG_DIR = ROOT / "logs"
HF_BIN = ROOT / "venv" / "bin" / "hf"
CATALOG_FILE = DATA_DIR / "model-catalog.yaml"
DOWNLOAD_QUEUE_FILE = DATA_DIR / "hf-download-queue.yaml"
EXPLORE_QUEUE_FILE = DATA_DIR / "hf-explore-queue.yaml"
HF_CACHE_FILE = RUN_DIR / "hf-explore-cache.json"
DOWNLOAD_PID_FILE = RUN_DIR / "hf-download.pid"
DOWNLOAD_LOG_FILE = LOG_DIR / "hf-download-latest.log"
BENCH_PID_FILE = RUN_DIR / "inference-bench.pid"
INVENTORY_BUILD = ROOT / "scripts" / "spark-inventory-build"
INFERENCE_SCRIPT = ROOT / "scripts" / "spark-inference.py"

REPO_ID_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
INTENT_VALID = frozenset(
    {
        "gguf_q4",
        "gguf_q5",
        "gguf_best",
        "nvfp4",
        "fp8",
        "hf_weights",
        "files",
    }
)
STATE_QUEUED = "queued"
STATE_CHECKING = "checking_access"
STATE_AWAITING = "awaiting_license"
STATE_DOWNLOADING = "downloading"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_SKIPPED = "skipped"

REPO_SUFFIXES = (
    "-MTP-GGUF",
    "-Instruct-GGUF",
    "-GGUF",
    "-gguf",
    "-NVFP4",
    "-nvfp4",
    "-FP8",
    "-fp8",
    "-AWQ",
    "-GPTQ",
    "-PrismaQuant-5.5bit-vllm",
)

SKIP_EXTENSIONS = (".md", ".ipynb", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".txt")
SKIP_NAMES = frozenset({"README.md", ".gitattributes", "LICENSE", "USE_POLICY.md"})

GGUF_PREFERENCES = {
    "gguf_q4": ("Q4_K_M", "Q4_K_XL", "Q4_K_S", "Q4_0", "Q4"),
    "gguf_q5": ("Q5_K_M", "Q5_K_XL", "Q5_K_S", "Q5_0", "Q5"),
    "gguf_best": ("Q4_K_M", "Q4_K_XL", "Q5_K_M", "Q4_K_S", "Q4"),
}

FORMAT_MAP = {
    "gguf_q4": ("gguf", "llamacpp"),
    "gguf_q5": ("gguf", "llamacpp"),
    "gguf_best": ("gguf", "llamacpp"),
    "nvfp4": ("nvfp4", "vllm"),
    "fp8": ("fp8", "vllm"),
    "hf_weights": ("hf", "vllm"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def read_pid_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    if pid > 0 and os.path.exists(f"/proc/{pid}"):
        return pid
    return None


def tail_log(path: Path, lines: int = 12) -> list[str]:
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return content[-lines:]
    except OSError:
        return []


def _pgrep_lines(pattern: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["pgrep", "-af", pattern],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    return [line for line in out.splitlines() if line.strip()]


def _is_self_or_hf_api(line: str) -> bool:
    low = line.lower()
    if "spark-hf.py" in low:
        return True
    if "spark-hf-api" in low:
        return True
    if "pgrep -af" in low:
        return True
    return False


def _legacy_hf_download_line(line: str) -> bool:
    if _is_self_or_hf_api(line):
        return False
    if "bench-queue" in line:
        return False
    return bool(
        re.search(r"(?:/venv/bin/hf|/bin/hf)\s+download\b", line)
        or re.search(r"\bhf\s+download\s+[A-Za-z0-9._-]+/", line)
    )


def _legacy_spark_download_line(line: str) -> bool:
    if _is_self_or_hf_api(line):
        return False
    if "bench-queue" in line:
        return False
    return bool(
        re.search(r"/opt/spark/scripts/spark-download-[^/\s]+\.sh\b", line)
        or re.search(r"\bspark-download-[^/\s]+\.sh\b", line)
    )


def active_legacy_download() -> dict[str, Any]:
    """Detect ad-hoc hf download / spark-download-*.sh — never preempt these."""
    hits: list[dict[str, Any]] = []
    for line in _pgrep_lines("download"):
        if _legacy_hf_download_line(line):
            hits.append({"pattern": "hf download", "line": line.strip()})
            continue
        if _legacy_spark_download_line(line):
            hits.append({"pattern": "spark-download", "line": line.strip()})
    if not hits:
        return {"running": False}
    return {
        "running": True,
        "source": "legacy",
        "matches": hits[:5],
        "pid": _extract_pid(hits[0]["line"]),
    }


def _extract_pid(line: str) -> int | None:
    parts = line.strip().split(None, 1)
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None


def active_queue_worker() -> dict[str, Any]:
    pid = read_pid_file(DOWNLOAD_PID_FILE)
    if not pid:
        DOWNLOAD_PID_FILE.unlink(missing_ok=True)
        return {"running": False}
    return {
        "running": True,
        "source": "queue",
        "pid": pid,
        "log": DOWNLOAD_LOG_FILE.name,
        "log_tail": tail_log(DOWNLOAD_LOG_FILE),
    }


def active_bench_running() -> bool:
    return read_pid_file(BENCH_PID_FILE) is not None


def active_hf_download() -> dict[str, Any]:
    legacy = active_legacy_download()
    if legacy.get("running"):
        return legacy
    worker = active_queue_worker()
    if worker.get("running"):
        return worker
    return {"running": False}


def can_start_download(*, defer_bench: bool = True) -> tuple[bool, str]:
    active = active_hf_download()
    if active.get("running"):
        src = active.get("source", "unknown")
        return False, f"download already running ({src})"
    if defer_bench and active_bench_running():
        return False, "benchmark running — queue deferred"
    return True, "ok"


def load_hf_disk_cache() -> dict[str, Any]:
    if not HF_CACHE_FILE.is_file():
        return {}
    try:
        data = json.loads(HF_CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_hf_disk_cache(cache: dict[str, Any]) -> None:
    HF_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    HF_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _hf_api():
    from huggingface_hub import HfApi

    return HfApi()


def validate_repo_id(repo: str) -> str | None:
    repo = repo.strip()
    if REPO_ID_RE.match(repo):
        return repo
    return None


def repo_to_lab(repo_id: str) -> str:
    return repo_id.split("/", 1)[0].lower()


def repo_to_slug(repo_id: str) -> str:
    name = repo_id.split("/", 1)[1]
    for suf in REPO_SUFFIXES:
        if name.endswith(suf):
            name = name[: -len(suf)]
            break
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", slug).strip("-")
    return slug or "model"


def inventory_path_for_repo(repo_id: str) -> str:
    return f"{repo_to_lab(repo_id)}/{repo_to_slug(repo_id)}"


def repo_siblings(repo_id: str) -> list[Any]:
    api = _hf_api()
    info = api.model_info(repo_id)
    return list(getattr(info, "siblings", []) or [])


def repo_meta(repo_id: str, cache: dict[str, Any] | None = None) -> dict[str, Any]:
    cache = cache if cache is not None else load_hf_disk_cache()
    key = f"model:{repo_id}"
    entry = cache.get(key)
    if isinstance(entry, dict) and entry.get("_fetched_at"):
        return entry
    out: dict[str, Any] = {"repo": repo_id, "hf_url": f"https://huggingface.co/{repo_id}"}
    try:
        api = _hf_api()
        info = api.model_info(repo_id)
        out["id"] = getattr(info, "id", repo_id) or repo_id
        out["author"] = getattr(info, "author", None) or repo_to_lab(repo_id)
        out["pipeline_tag"] = getattr(info, "pipeline_tag", None)
        out["tags"] = list(getattr(info, "tags", []) or [])
        out["downloads"] = getattr(info, "downloads", None)
        out["likes"] = getattr(info, "likes", None)
        gated = getattr(info, "gated", None)
        out["gated"] = bool(gated)
        out["private"] = bool(getattr(info, "private", False))
        created = getattr(info, "created_at", None) or getattr(info, "lastModified", None)
        if created:
            out["last_modified"] = (
                created.isoformat() if hasattr(created, "isoformat") else str(created)
            )
        siblings = list(getattr(info, "siblings", []) or [])
        out["sibling_count"] = len(siblings)
        out["has_gguf"] = any(s.rfilename.endswith(".gguf") for s in siblings)
        out["has_nvfp4"] = any(
            "nvfp4" in s.rfilename.lower() or "nvfp4" in (out.get("tags") or [])
            for s in siblings
        )
        out["has_safetensors"] = any(s.rfilename.endswith(".safetensors") for s in siblings)
        names = " ".join(s.rfilename.lower() for s in siblings)
        out["has_moe"] = "a3b" in names or "moe" in names or "mixture" in " ".join(
            out.get("tags", [])
        ).lower()
        out["accessible"] = True
    except Exception as exc:
        err = str(exc)
        out["accessible"] = False
        out["error"] = err[:240]
        low = err.lower()
        if "gated" in low or "403" in low or "authorized" in low:
            out["gated"] = True
            out["accept_url"] = f"https://huggingface.co/{repo_id}"
    out["_fetched_at"] = utc_now()
    cache[key] = out
    save_hf_disk_cache(cache)
    return out


def check_repo_access(repo_id: str) -> dict[str, Any]:
    meta = repo_meta(repo_id)
    if meta.get("accessible"):
        return {"ok": True, "gated": bool(meta.get("gated")), "repo": repo_id}
    return {
        "ok": False,
        "gated": bool(meta.get("gated")),
        "repo": repo_id,
        "accept_url": meta.get("accept_url") or f"https://huggingface.co/{repo_id}",
        "error": meta.get("error"),
    }


def _pick_gguf(names: list[str], preference: tuple[str, ...]) -> list[str]:
    ggufs = [n for n in names if n.endswith(".gguf")]
    if not ggufs:
        return []
    for pref in preference:
        matches = [g for g in ggufs if pref in g]
        if matches:
            return [sorted(matches, key=lambda x: (len(x), x))[0]]
    return [sorted(ggufs, key=lambda x: (len(x), x))[0]]


def _weights_files(siblings: list[Any]) -> list[str]:
    picked: list[str] = []
    for s in siblings:
        name = s.rfilename
        if name in SKIP_NAMES:
            continue
        if any(name.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue
        if (
            name.endswith(".safetensors")
            or name.endswith(".json")
            or name.endswith(".model")
            or name.endswith(".txt")
            or name.startswith("tokenizer")
            or name.startswith("chat_template")
            or name.startswith("generation_config")
            or name == "config.json"
        ):
            picked.append(name)
    return sorted(set(picked))


def plan_download(
    repo_id: str,
    intent: str,
    *,
    files: list[str] | None = None,
    inventory_path: str | None = None,
) -> dict[str, Any]:
    repo_id = validate_repo_id(repo_id)
    if not repo_id:
        raise ValueError("invalid repo id")
    if intent not in INTENT_VALID:
        raise ValueError(f"invalid intent: {intent}")

    inv = (inventory_path or inventory_path_for_repo(repo_id)).strip().strip("/")
    if "/" not in inv:
        raise ValueError("inventory_path must be lab/slug")

    fmt, engine = FORMAT_MAP.get(intent, ("hf", "vllm"))
    subpath = fmt
    siblings = repo_siblings(repo_id)
    names = [s.rfilename for s in siblings]

    if intent == "files":
        if not files:
            raise ValueError("files required for intent=files")
        selected = [f.strip() for f in files if f.strip()]
    elif intent in GGUF_PREFERENCES:
        selected = _pick_gguf(names, GGUF_PREFERENCES[intent])
        if not selected:
            raise ValueError("no .gguf files found in repo")
    else:
        selected = _weights_files(siblings)
        if not selected:
            raise ValueError("no weight files found in repo")

    dest = MODELS_ROOT / inv / subpath
    total_bytes = 0
    by_name = {s.rfilename: s for s in siblings}
    for name in selected:
        sib = by_name.get(name)
        if sib is not None and getattr(sib, "size", None):
            total_bytes += int(sib.size or 0)

    scaffold_engine = "llamacpp" if engine == "llamacpp" else "eugr"
    return {
        "repo": repo_id,
        "intent": intent,
        "mode": "files",
        "files": selected,
        "inventory_path": inv,
        "subpath": subpath,
        "format": fmt,
        "engine": engine,
        "scaffold_engine": scaffold_engine,
        "dest": str(dest),
        "size_bytes": total_bytes,
        "size_human": _human_size(total_bytes),
        "file_count": len(selected),
    }


def _human_size(n: int) -> str:
    if n <= 0:
        return "—"
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024
    return f"{val:.1f} TB"


def _model_card(m: Any) -> dict[str, Any]:
    repo = getattr(m, "id", None) or getattr(m, "modelId", None) or ""
    tags = list(getattr(m, "tags", []) or [])
    repo_low = repo.lower()
    tag_blob = " ".join(tags).lower()
    return {
        "repo": repo,
        "author": getattr(m, "author", None),
        "downloads": getattr(m, "downloads", None),
        "likes": getattr(m, "likes", None),
        "pipeline_tag": getattr(m, "pipeline_tag", None),
        "tags": tags[:20],
        "last_modified": _iso(getattr(m, "lastModified", None)),
        "has_gguf": "gguf" in repo_low or "gguf" in tag_blob or "llama.cpp" in tag_blob,
        "has_nvfp4": "nvfp4" in repo_low or "nvfp4" in tag_blob,
        "has_moe": "a3b" in repo_low or "moe" in tag_blob,
        "hf_url": f"https://huggingface.co/{repo}" if repo else None,
    }


def _iso(val: Any) -> str | None:
    if val is None:
        return None
    return val.isoformat() if hasattr(val, "isoformat") else str(val)


def _apply_spark_filters(items: list[dict[str, Any]], filters: list[str]) -> list[dict[str, Any]]:
    if not filters:
        return items
    out = items
    norm = {f.strip().lower() for f in filters if f.strip()}
    if "gguf" in norm:
        out = [m for m in out if m.get("has_gguf") or any("gguf" in t.lower() for t in m.get("tags", []))]
    if "nvfp4" in norm:
        out = [
            m
            for m in out
            if m.get("has_nvfp4") or any("nvfp4" in t.lower() for t in m.get("tags", []))
        ]
    if "moe" in norm:
        out = [m for m in out if m.get("has_moe") or "a3b" in (m.get("repo") or "").lower()]
    if "fits_spark" in norm:
        kept = []
        for m in out:
            repo = (m.get("repo") or "").lower()
            if any(x in repo for x in ("70b", "72b", "405b", "671b")):
                continue
            kept.append(m)
        out = kept
    return out


def hf_search(query: str, *, limit: int = 30, filters: list[str] | None = None) -> dict[str, Any]:
    api = _hf_api()
    models = api.list_models(search=query, limit=limit, full=True)
    items = [_model_card(m) for m in models]
    items = _apply_spark_filters(items, filters or [])
    return {"query": query, "count": len(items), "models": items}


def hf_trending(*, limit: int = 30, filters: list[str] | None = None) -> dict[str, Any]:
    """HF Hub trending (recent momentum), not all-time download leaders."""
    api = _hf_api()
    models = api.list_models(sort="trending_score", limit=limit, full=True)
    items = [_model_card(m) for m in models]
    items = _apply_spark_filters(items, filters or [])
    return {"sort": "trending_score", "count": len(items), "models": items}


def hf_new(*, limit: int = 30, filters: list[str] | None = None) -> dict[str, Any]:
    api = _hf_api()
    models = api.list_models(sort="lastModified", limit=limit, full=True)
    items = [_model_card(m) for m in models]
    items = _apply_spark_filters(items, filters or [])
    return {"sort": "lastModified", "count": len(items), "models": items}


def load_download_queue() -> dict[str, Any]:
    data = load_yaml(DOWNLOAD_QUEUE_FILE)
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def save_download_queue(data: dict[str, Any]) -> None:
    save_yaml(DOWNLOAD_QUEUE_FILE, data)


def load_explore_queue() -> dict[str, Any]:
    data = load_yaml(EXPLORE_QUEUE_FILE)
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def save_explore_queue(data: dict[str, Any]) -> None:
    save_yaml(EXPLORE_QUEUE_FILE, data)


def queue_list() -> dict[str, Any]:
    dq = load_download_queue()
    eq = load_explore_queue()
    return {
        "download": dq.get("items", []),
        "explore": eq.get("items", []),
        "active": active_hf_download(),
        "can_start": can_start_download(),
    }


def _find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("id") == item_id:
            return item
    return None


def queue_add_download(
    *,
    repo: str,
    intent: str,
    files: list[str] | None = None,
    inventory_path: str | None = None,
) -> dict[str, Any]:
    repo = validate_repo_id(repo)
    if not repo:
        raise ValueError("invalid repo")
    plan = plan_download(repo, intent, files=files, inventory_path=inventory_path)
    dest = Path(plan["dest"])
    missing = [f for f in plan["files"] if not (dest / f).is_file()]
    if not missing and dest.is_dir():
        item = {
            "id": str(uuid.uuid4()),
            "repo": repo,
            "intent": intent,
            "state": STATE_SKIPPED,
            "created_at": utc_now(),
            "finished_at": utc_now(),
            "plan": plan,
            "note": "files already present",
        }
        data = load_download_queue()
        data.setdefault("items", []).append(item)
        save_download_queue(data)
        _post_download_complete(item)
        return item

    item = {
        "id": str(uuid.uuid4()),
        "repo": repo,
        "intent": intent,
        "state": STATE_QUEUED,
        "created_at": utc_now(),
        "plan": plan,
    }
    data = load_download_queue()
    data.setdefault("items", []).append(item)
    save_download_queue(data)
    maybe_start_worker()
    return item


def queue_add_explore(*, repo: str, intent: str = "gguf_best") -> dict[str, Any]:
    repo = validate_repo_id(repo)
    if not repo:
        raise ValueError("invalid repo")
    item = {
        "id": str(uuid.uuid4()),
        "repo": repo,
        "intent": intent,
        "added_at": utc_now(),
    }
    data = load_explore_queue()
    data.setdefault("items", []).append(item)
    save_explore_queue(data)
    return item


def queue_recheck(item_id: str) -> dict[str, Any]:
    data = load_download_queue()
    items = data.get("items", [])
    item = _find_item(items, item_id)
    if not item:
        raise ValueError("unknown queue item")
    access = check_repo_access(str(item.get("repo", "")))
    if access.get("ok"):
        item["state"] = STATE_QUEUED
        item["rechecked_at"] = utc_now()
        item.pop("accept_url", None)
    else:
        item["state"] = STATE_AWAITING
        item["accept_url"] = access.get("accept_url")
        item["rechecked_at"] = utc_now()
    save_download_queue(data)
    maybe_start_worker()
    return item


def _next_actionable_item() -> dict[str, Any] | None:
    data = load_download_queue()
    for item in data.get("items", []):
        state = item.get("state")
        if state in {STATE_QUEUED, STATE_CHECKING}:
            return item
        if state == STATE_AWAITING:
            continue
    return None


def _update_item(item_id: str, **fields: Any) -> None:
    data = load_download_queue()
    item = _find_item(data.get("items", []), item_id)
    if not item:
        return
    item.update(fields)
    save_download_queue(data)


def _files_already_present(plan: dict[str, Any]) -> bool:
    dest = Path(plan["dest"])
    return all((dest / f).is_file() for f in plan.get("files", []))


def _run_hf_download(repo: str, files: list[str], dest: Path, log_path: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [str(HF_BIN), "download", repo, *files, "--local-dir", str(dest)]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as logfh:
        logfh.write(f"\n==> HF queue download {repo} -> {dest} ({len(files)} files)\n")
        logfh.write(f"==> started {utc_now()}\n")
        logfh.flush()
        proc = subprocess.run(cmd, stdout=logfh, stderr=subprocess.STDOUT, check=False)
        logfh.write(f"==> finished {utc_now()} exit={proc.returncode}\n")
        return proc.returncode


def _load_inference_core() -> Any:
    spec = importlib.util.spec_from_file_location("inference_core", INFERENCE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load spark-inference.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_manifest(inventory_path: str, plan: dict[str, Any]) -> None:
    root = MODELS_ROOT / inventory_path
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": inventory_path,
        "hf_repo": plan.get("repo"),
        "variants": [
            {
                "format": plan.get("format"),
                "subpath": plan.get("subpath"),
                "engine": plan.get("engine"),
                "hf_repo": plan.get("repo"),
                "files": plan.get("files"),
            }
        ],
        "default_variant": f"{plan.get('format')}/{plan.get('subpath')}",
        "downloaded_at": utc_now(),
    }
    path = root / "manifest.yaml"
    if path.is_file():
        existing = load_yaml(path)
        variants = existing.get("variants")
        if isinstance(variants, list):
            variants.append(manifest["variants"][0])
            manifest["variants"] = variants
    save_yaml(path, manifest)


def _merge_catalog(inventory_path: str, plan: dict[str, Any]) -> None:
    lab, slug = inventory_path.split("/", 1)
    catalog = load_yaml(CATALOG_FILE)
    models = catalog.get("models")
    if not isinstance(models, list):
        models = []
    model_id = inventory_path
    entry = None
    for m in models:
        if m.get("id") == model_id or (m.get("lab") == lab and m.get("slug") == slug):
            entry = m
            break
    variant = {
        "format": plan.get("format"),
        "subpath": plan.get("subpath"),
        "engine": plan.get("engine"),
        "hf_repo": plan.get("repo"),
    }
    if entry is None:
        entry = {
            "id": model_id,
            "lab": lab,
            "name": slug.replace("-", " ").replace(".", " ").title(),
            "slug": slug,
            "hf_repo": plan.get("repo"),
            "capabilities": _infer_capabilities(plan),
            "why_downloaded": f"HF Explorer download {utc_now()[:10]}",
            "variants": [variant],
        }
        models.append(entry)
    else:
        variants = entry.get("variants")
        if not isinstance(variants, list):
            variants = []
        if not any(
            v.get("subpath") == variant["subpath"] and v.get("hf_repo") == variant["hf_repo"]
            for v in variants
        ):
            variants.append(variant)
        entry["variants"] = variants
    catalog["models"] = models
    save_yaml(CATALOG_FILE, catalog)


def _infer_capabilities(plan: dict[str, Any]) -> list[str]:
    caps = ["explorer"]
    fmt = plan.get("format")
    if fmt == "gguf":
        caps.extend(["gguf", "llamacpp"])
    elif fmt == "nvfp4":
        caps.extend(["nvfp4", "vllm"])
    elif fmt == "fp8":
        caps.extend(["fp8", "vllm"])
    else:
        caps.extend(["vllm"])
    return caps


def _post_download_complete(item: dict[str, Any]) -> None:
    plan = item.get("plan") or {}
    inv = plan.get("inventory_path")
    if not inv:
        return
    _write_manifest(str(inv), plan)
    _merge_catalog(str(inv), plan)
    engine = plan.get("scaffold_engine") or "eugr"
    try:
        core = _load_inference_core()
        core.scaffold_recipe(str(inv), str(engine))
    except Exception as exc:
        _update_item(str(item.get("id", "")), scaffold_error=str(exc)[:200])
    if INVENTORY_BUILD.is_file():
        subprocess.Popen(
            [str(INVENTORY_BUILD)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def process_queue_item(item: dict[str, Any]) -> None:
    item_id = str(item["id"])
    plan = item.get("plan") or {}
    repo = str(item.get("repo", ""))

    _update_item(item_id, state=STATE_CHECKING, started_at=utc_now())
    access = check_repo_access(repo)
    if not access.get("ok"):
        _update_item(
            item_id,
            state=STATE_AWAITING,
            accept_url=access.get("accept_url"),
            error=access.get("error"),
        )
        return

    if _files_already_present(plan):
        _update_item(item_id, state=STATE_DONE, finished_at=utc_now(), note="already present")
        _post_download_complete(item)
        return

    _update_item(item_id, state=STATE_DOWNLOADING)
    rc = _run_hf_download(
        repo,
        list(plan.get("files") or []),
        Path(plan["dest"]),
        DOWNLOAD_LOG_FILE,
    )
    if rc != 0:
        _update_item(item_id, state=STATE_FAILED, finished_at=utc_now(), exit_code=rc)
        return

    _update_item(item_id, state=STATE_DONE, finished_at=utc_now())
    refreshed = _find_item(load_download_queue().get("items", []), item_id) or item
    _post_download_complete(refreshed)


def worker_main() -> int:
    DOWNLOAD_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_PID_FILE.write_text(str(os.getpid()))

    try:
        while True:
            ok, reason = can_start_download()
            if not ok and "already running" in reason:
                return 0
            if not ok:
                return 0

            legacy = active_legacy_download()
            if legacy.get("running"):
                with DOWNLOAD_LOG_FILE.open("a", encoding="utf-8") as logfh:
                    logfh.write(f"==> yielding to legacy download {utc_now()}\n")
                return 0

            item = _next_actionable_item()
            if not item:
                return 0

            process_queue_item(item)

            ok, reason = can_start_download()
            if not ok:
                return 0
    finally:
        DOWNLOAD_PID_FILE.unlink(missing_ok=True)


def maybe_start_worker() -> bool:
    if read_pid_file(DOWNLOAD_PID_FILE):
        return False
    ok, _reason = can_start_download()
    if not ok:
        return False
    if _next_actionable_item() is None:
        return False
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "spark-hf.py"), "worker"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    DOWNLOAD_PID_FILE.write_text(str(proc.pid))
    return True


def api_status() -> dict[str, Any]:
    ok, reason = can_start_download()
    return {
        "active": active_hf_download(),
        "legacy": active_legacy_download(),
        "queue_worker": active_queue_worker(),
        "bench_running": active_bench_running(),
        "can_start": ok,
        "defer_reason": None if ok else reason,
        "queue": queue_list(),
    }


def api_route_path(path: str) -> str:
    return path.split("?", 1)[0].rstrip("/") or "/"


def _parse_query(path: str) -> dict[str, str]:
    if "?" not in path:
        return {}
    out: dict[str, str] = {}
    for part in path.split("?", 1)[1].split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[unquote(k)] = unquote_plus(v)
    return out


def api_dispatch(
    method: str, path: str, body: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]] | None:
    body = body or {}
    route = api_route_path(path)
    q = _parse_query(path)

    if method == "GET":
        if route == "/api/hf/status":
            maybe_start_worker()
            return 200, {"ok": True, **api_status()}
        if route == "/api/hf/queue":
            return 200, {"ok": True, **queue_list()}
        if route == "/api/hf/trending":
            limit = max(1, min(50, int(q.get("limit", "30"))))
            filters = [f for f in q.get("filter", "").split(",") if f]
            return 200, {"ok": True, **hf_trending(limit=limit, filters=filters)}
        if route == "/api/hf/new":
            limit = max(1, min(50, int(q.get("limit", "30"))))
            filters = [f for f in q.get("filter", "").split(",") if f]
            return 200, {"ok": True, **hf_new(limit=limit, filters=filters)}
        if route == "/api/hf/search":
            query = q.get("q", "").strip()
            if not query:
                return 400, {"ok": False, "error": "q required"}
            limit = max(1, min(50, int(q.get("limit", "30"))))
            filters = [f for f in q.get("filter", "").split(",") if f]
            return 200, {"ok": True, **hf_search(query, limit=limit, filters=filters)}
        if route.startswith("/api/hf/model/"):
            repo = unquote(route[len("/api/hf/model/") :])
            repo = validate_repo_id(repo)
            if not repo:
                return 400, {"ok": False, "error": "invalid repo"}
            meta = repo_meta(repo)
            intent = q.get("intent", "gguf_best")
            try:
                plan = plan_download(repo, intent)
            except ValueError:
                plan = None
            return 200, {"ok": True, "model": meta, "default_plan": plan}
        return None

    if method != "POST":
        return None

    if route == "/api/hf/queue":
        action = str(body.get("action", "download")).strip().lower()
        if action == "explore":
            try:
                item = queue_add_explore(
                    repo=str(body.get("repo", "")),
                    intent=str(body.get("intent", "gguf_best")),
                )
            except ValueError as exc:
                return 400, {"ok": False, "error": str(exc)}
            return 202, {"ok": True, "item": item}
        try:
            item = queue_add_download(
                repo=str(body.get("repo", "")),
                intent=str(body.get("intent", "gguf_best")),
                files=body.get("files") if isinstance(body.get("files"), list) else None,
                inventory_path=body.get("inventory_path"),
            )
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 202, {"ok": True, "item": item, "active": active_hf_download()}

    recheck_match = re.match(r"^/api/hf/queue/([^/]+)/recheck$", route)
    if recheck_match:
        try:
            item = queue_recheck(recheck_match.group(1))
        except ValueError as exc:
            return 404, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "item": item}

    plan_match = re.match(r"^/api/hf/plan$", route)
    if plan_match or route == "/api/hf/plan":
        try:
            plan = plan_download(
                str(body.get("repo", "")),
                str(body.get("intent", "gguf_best")),
                files=body.get("files") if isinstance(body.get("files"), list) else None,
                inventory_path=body.get("inventory_path"),
            )
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "plan": plan}

    return None


def cmd_status() -> int:
    maybe_start_worker()
    print(json.dumps({"ok": True, **api_status()}, indent=2))
    return 0


def cmd_queue_list() -> int:
    print(json.dumps({"ok": True, **queue_list()}, indent=2))
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        return cmd_status()

    cmd = sys.argv[1]
    if cmd == "status":
        return cmd_status()
    if cmd == "queue":
        sub = sys.argv[2] if len(sys.argv) > 2 else "list"
        if sub == "list":
            return cmd_queue_list()
        if sub == "add" and len(sys.argv) >= 5:
            item = queue_add_download(
                repo=sys.argv[3],
                intent=sys.argv[4],
            )
            print(json.dumps({"ok": True, "item": item}, indent=2))
            return 0
        print("usage: spark-hf.py queue list|add <repo> <intent>", file=sys.stderr)
        return 2
    if cmd == "worker":
        return worker_main()
    if cmd == "plan" and len(sys.argv) >= 4:
        plan = plan_download(sys.argv[2], sys.argv[3])
        print(json.dumps({"ok": True, "plan": plan}, indent=2))
        return 0

    print(
        "usage: spark-hf.py status|queue|worker|plan <repo> <intent>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())