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
EXPLORE_WARNINGS_FILE = DATA_DIR / "spark-explore-warnings.yaml"
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

DOWNLOAD_QUEUE_PRUNE_STATES = frozenset({STATE_DONE, STATE_SKIPPED})

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


def _pid_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _is_queue_worker_pid(pid: int) -> bool:
    cmd = _pid_cmdline(pid)
    return "spark-hf.py" in cmd and re.search(r"\bworker\b", cmd) is not None


def _clear_stale_download_pid() -> None:
    pid = read_pid_file(DOWNLOAD_PID_FILE)
    if pid is None:
        DOWNLOAD_PID_FILE.unlink(missing_ok=True)
        return
    if not _is_queue_worker_pid(pid):
        DOWNLOAD_PID_FILE.unlink(missing_ok=True)


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
    if not pid or not _is_queue_worker_pid(pid):
        _clear_stale_download_pid()
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


ACTIVE_DOWNLOAD_STATES = frozenset({STATE_DOWNLOADING, STATE_CHECKING})


def active_download_item() -> dict[str, Any] | None:
    for item in load_download_queue().get("items", []):
        if item.get("state") in ACTIVE_DOWNLOAD_STATES:
            return item
    return None


def download_item_public(item: dict[str, Any]) -> dict[str, Any]:
    plan = item.get("plan") if isinstance(item.get("plan"), dict) else {}
    files = plan.get("files") if isinstance(plan.get("files"), list) else []
    return {
        "id": item.get("id"),
        "repo": item.get("repo"),
        "state": item.get("state"),
        "started_at": item.get("started_at"),
        "intent": plan.get("intent") or item.get("intent"),
        "dest": plan.get("dest"),
        "size_human": plan.get("size_human"),
        "file_count": len(files) or plan.get("file_count"),
        "inventory_path": plan.get("inventory_path"),
    }


def parse_download_log_progress(log_tail: list[str]) -> dict[str, Any]:
    """Best-effort hints from hf download log tail."""
    out: dict[str, Any] = {}
    for line in reversed(log_tail):
        text = line.strip()
        if not text:
            continue
        m = re.search(
            r"==> HF queue download (\S+) -> (\S+) \((\d+) files\)",
            text,
        )
        if m and "repo" not in out:
            out["repo"] = m.group(1)
            out["dest"] = m.group(2)
            out["file_count"] = int(m.group(3))
        if text.startswith("==> started "):
            out["log_started_at"] = text.replace("==> started ", "")
        if text.startswith("==> finished "):
            out["finished"] = True
            break
        if "Downloading" in text or "Downloaded" in text or "%" in text:
            out["last_activity"] = text[:160]
    return out


def _parse_legacy_repo(line: str) -> str | None:
    m = re.search(r"(?:/venv/bin/hf|/bin/hf|\bhf)\s+download\s+([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)", line)
    return m.group(1) if m else None


def enrich_active_download(active: dict[str, Any]) -> dict[str, Any]:
    if not active.get("running"):
        return active
    log_tail = list(active.get("log_tail") or tail_log(DOWNLOAD_LOG_FILE))
    active["log_tail"] = log_tail
    progress = parse_download_log_progress(log_tail)
    if progress:
        active["progress"] = progress

    item = active_download_item()
    if item:
        active["item"] = download_item_public(item)
    elif progress.get("repo"):
        active["item"] = {
            "repo": progress["repo"],
            "state": STATE_DOWNLOADING,
            "dest": progress.get("dest"),
            "file_count": progress.get("file_count"),
        }

    if active.get("source") == "legacy":
        matches = active.get("matches") or []
        if matches and not active.get("item"):
            repo = _parse_legacy_repo(str(matches[0].get("line", "")))
            if repo:
                active["item"] = {"repo": repo, "state": STATE_DOWNLOADING}

    dq = load_download_queue()
    items = dq.get("items", [])
    if isinstance(items, list):
        active["queued_count"] = sum(
            1 for i in items if i.get("state") == STATE_QUEUED
        )
        active["awaiting_count"] = sum(
            1 for i in items if i.get("state") == STATE_AWAITING
        )
    return active


def active_hf_download() -> dict[str, Any]:
    legacy = active_legacy_download()
    if legacy.get("running"):
        return enrich_active_download(legacy)
    worker = active_queue_worker()
    if worker.get("running"):
        return enrich_active_download(worker)
    return {"running": False}


def can_start_download(*, defer_bench: bool = True) -> tuple[bool, str]:
    active = active_hf_download()
    if active.get("running"):
        src = active.get("source", "unknown")
        return False, f"download already running ({src})"
    if defer_bench and active_bench_running():
        return False, "benchmark running — queue deferred"
    return True, "ok"


def worker_can_start(self_pid: int) -> tuple[bool, str]:
    """Queue worker guard — must not treat our own PID file as a blocking download."""
    legacy = active_legacy_download()
    if legacy.get("running"):
        return False, "legacy download in progress"
    if active_bench_running():
        return False, "benchmark running — queue deferred"
    pid = read_pid_file(DOWNLOAD_PID_FILE)
    if pid and pid != self_pid and _is_queue_worker_pid(pid):
        return False, "another queue worker is running"
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


def repo_file_sizes(repo_id: str) -> dict[str, int]:
    """Path → bytes from HF repo tree (model_info siblings often omit size)."""
    sizes: dict[str, int] = {}
    try:
        api = _hf_api()
        for entry in api.list_repo_tree(repo_id, recursive=True, expand=True):
            path = getattr(entry, "path", None)
            raw = getattr(entry, "size", None)
            if path and raw:
                sizes[str(path)] = int(raw)
    except Exception:
        pass
    return sizes


def _sibling_size(name: str, sibling: Any, sizes: dict[str, int]) -> int:
    raw = getattr(sibling, "size", None)
    if raw:
        return int(raw)
    return sizes.get(name, 0)


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


GGUF_SHARD_RE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)


def _is_auxiliary_gguf(filename: str) -> bool:
    base = filename.split("/")[-1].lower()
    return base.startswith("mmproj") or base.startswith("mmp_")


def _gguf_shard_sort_key(fname: str) -> tuple[int, int, str]:
    m = GGUF_SHARD_RE.search(fname)
    if m:
        return (0, int(m.group(1)), fname)
    return (1, 0, fname)


def _gguf_group_key(filename: str) -> str:
    if GGUF_SHARD_RE.search(filename):
        return GGUF_SHARD_RE.sub("", filename)
    return filename


def _expand_gguf_shards(names: list[str], pick: str) -> list[str]:
    """Return every shard in the set when pick is a multi-part GGUF."""
    if not GGUF_SHARD_RE.search(pick):
        return [pick]
    key = _gguf_group_key(pick)
    siblings = [n for n in names if n.endswith(".gguf") and _gguf_group_key(n) == key]
    return sorted(siblings, key=_gguf_shard_sort_key)


def _pick_gguf(names: list[str], preference: tuple[str, ...]) -> list[str]:
    ggufs = [
        n for n in names if n.endswith(".gguf") and not _is_auxiliary_gguf(n)
    ]
    if not ggufs:
        return []
    for pref in preference:
        matches = [g for g in ggufs if pref in g]
        if matches:
            pick = sorted(matches, key=lambda x: (len(x), x))[0]
            return _expand_gguf_shards(ggufs, pick)
    pick = sorted(ggufs, key=lambda x: (len(x), x))[0]
    return _expand_gguf_shards(ggufs, pick)


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

    repo_low = repo_id.lower()
    scaffold_kind: str | None = None
    scaffold_engine: str | None = "llamacpp" if engine == "llamacpp" else "eugr"

    if str(engine).lower() == "ds4":
        scaffold_kind = "ds4"
        scaffold_engine = None
    elif "dflash" in repo_low:
        fmt = "dflash"
        subpath = "dflash"
        scaffold_kind = "dflash"
        scaffold_engine = None
        dest = MODELS_ROOT / inv / subpath
    elif "mtp" in repo_low:
        if "gguf" in repo_low or fmt == "gguf":
            fmt = "gguf"
            subpath = "mtp-gguf"
            scaffold_kind = "mtp_llama"
            scaffold_engine = "llamacpp"
            dest = MODELS_ROOT / inv / subpath

    plan: dict[str, Any] = {
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
    if scaffold_kind:
        plan["scaffold_kind"] = scaffold_kind
    return plan


def _human_size(n: int) -> str:
    if n <= 0:
        return "—"
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024
    return f"{val:.1f} TB"


GGUF_QUANT_PATTERNS = (
    "UD-Q4_K_M",
    "UD-Q4_K_XL",
    "UD-Q3_K_M",
    "UD-Q3_K_XL",
    "UD-Q2_K_XL",
    "UD-Q8_K_XL",
    "UD-IQ4_XS",
    "UD-IQ3_S",
    "UD-IQ2_XXS",
    "UD-IQ2_M",
    "UD-IQ1_M",
    "Q4_K_XL",
    "Q4_K_M",
    "Q4_K_S",
    "Q5_K_XL",
    "Q5_K_M",
    "Q5_K_S",
    "Q6_K",
    "Q6_K_XL",
    "Q8_0",
    "MXFP4_MOE",
    "MXFP4",
    "Q4_0",
    "Q5_0",
    "Q3_K",
    "Q2_K",
)

GGUF_QUANT_NOTES: dict[str, str] = {
    "UD-Q4_K_M": "Unsloth dynamic Q4 — strong default for llama.cpp on Spark",
    "UD-Q4_K_XL": "Unsloth dynamic Q4 XL — more quality, still practical",
    "Q4_K_M": "Balanced everyday quant — best general GGUF pick on Spark",
    "Q4_K_XL": "Larger Q4 — sharper than Q4_K_M, heavier download",
    "Q4_K_S": "Compact Q4 — smaller file, slightly lower quality",
    "Q5_K_M": "Higher fidelity — good when you want sharper output",
    "Q5_K_XL": "Premium Q5 — near-best GGUF quality, more disk",
    "Q6_K": "High quality — large; use if you have headroom",
    "Q8_0": "Near-FP16 size — rarely worth it for big models on Spark",
    "MXFP4_MOE": "MoE MXFP4 — GB10-friendly experimental quant",
    "MXFP4": "MXFP4 quant — tuned for MoE on Blackwell-class hardware",
    "Q3_K": "Small quant — fast, noticeable quality loss",
    "Q2_K": "Very small — experiments only",
}

SPARK_FIT_ORDER = {
    "recommended": 0,
    "ok": 1,
    "tight": 2,
    "too_large": 3,
    "not_recommended": 4,
}


def _gguf_quant_label(filename: str) -> str:
    base = filename.replace(".gguf", "")
    base = GGUF_SHARD_RE.sub("", base)
    for pat in GGUF_QUANT_PATTERNS:
        if pat in base:
            return pat
    return base.split("/")[-1][-48:]


def _infer_weights_format(repo_id: str) -> str:
    repo_low = repo_id.lower()
    if "nvfp4" in repo_low:
        return "nvfp4"
    if "fp8" in repo_low:
        return "fp8"
    if "prismaquant" in repo_low:
        return "prismaquant"
    return "hf"


def _spark_fit(
    size_bytes: int, fmt: str, label: str, repo_id: str
) -> tuple[str, str, str]:
    """Return (spark_fit, spark_fit_label, explanation)."""
    size_gb = (size_bytes or 0) / (1024**3)
    repo_low = repo_id.lower()
    label_u = label.upper()

    if any(x in repo_low for x in ("70b", "72b", "405b", "671b")) and fmt != "gguf":
        return (
            "not_recommended",
            "Skip",
            "Dense 70B+ HF weights — poor fit for a single 128GB Spark",
        )

    if size_gb > 95:
        return (
            "too_large",
            "Too large",
            f"~{size_gb:.0f} GB — unlikely to leave room for KV cache on Spark",
        )
    if size_gb > 72:
        return (
            "tight",
            "Tight",
            f"~{size_gb:.0f} GB — may load but little headroom for long context",
        )

    if fmt == "gguf":
        note = GGUF_QUANT_NOTES.get(label, "GGUF file for llama.cpp")
        if any(x in label_u for x in ("Q4_K_M", "Q4_K_XL", "UD-Q4")):
            return "recommended", "Spark pick", note
        if "MXFP4" in label_u:
            return "recommended", "Spark pick", note
        if any(x in label_u for x in ("Q5_K_M", "Q5_K_XL")) and size_gb < 52:
            return "recommended", "Spark pick", note
        if any(x in label_u for x in ("Q2", "Q3")):
            return "ok", "OK", note
        if "Q8" in label_u and size_gb > 35:
            return "not_recommended", "Skip", note + " — very heavy on Spark"
        if "BF16" in label_u or "F16" in label_u:
            return "not_recommended", "Skip", "BF16 / full-precision GGUF — too heavy for daily Spark use"
        if size_gb < 55:
            return "ok", "OK", note
        return "tight", "Tight", note

    if fmt == "nvfp4":
        return (
            "recommended",
            "Spark pick",
            "NVFP4 weights — native Blackwell vLLM path (eugr)",
        )

    if fmt == "fp8":
        if size_gb < 70:
            return "recommended", "Spark pick", "FP8 checkpoint — reference vLLM path"
        return "tight", "Tight", "FP8 weights — verify headroom before switching"

    if fmt in {"hf", "prismaquant"}:
        if size_gb < 68:
            return "recommended", "Spark pick", "HF safetensors — eugr vLLM serve path"
        if size_gb < 78:
            return "ok", "OK", "HF weights — fits many Spark profiles; heavy for 24/7"
        return "tight", "Tight", "Large HF tree — benchmark before promoting"

    return "ok", "OK", "May work — check disk and VRAM headroom"


def discover_model_variants(repo_id: str) -> list[dict[str, Any]]:
    """List downloadable file/quant options with Spark fit hints."""
    repo_id = validate_repo_id(repo_id)
    if not repo_id:
        raise ValueError("invalid repo id")

    siblings = repo_siblings(repo_id)
    by_name = {s.rfilename: s for s in siblings}
    sizes = repo_file_sizes(repo_id)
    inv = inventory_path_for_repo(repo_id)
    meta = repo_meta(repo_id)
    variants: list[dict[str, Any]] = []

    ggufs = [
        s
        for s in siblings
        if s.rfilename.endswith(".gguf") and not _is_auxiliary_gguf(s.rfilename)
    ]
    groups: dict[str, list[Any]] = {}
    for s in ggufs:
        key = _gguf_group_key(s.rfilename)
        groups.setdefault(key, []).append(s)

    for group_key, group in groups.items():
        files = sorted(
            [s.rfilename for s in group],
            key=_gguf_shard_sort_key,
        )
        total_size = sum(
            _sibling_size(fname, by_name[fname], sizes)
            for fname in files
            if fname in by_name
        )
        label = _gguf_quant_label(files[0])
        shard_count = len(files)
        display_label = f"{label} ({shard_count} shards)" if shard_count > 1 else label
        fit, fit_label, explanation = _spark_fit(total_size, "gguf", label, repo_id)
        if shard_count > 1:
            explanation = f"{shard_count} shard files — " + explanation
        dest = MODELS_ROOT / inv / "gguf"
        variants.append(
            {
                "id": f"gguf:{group_key}",
                "label": display_label,
                "format": "gguf",
                "engine": "llamacpp",
                "intent": "files",
                "files": files,
                "inventory_path": inv,
                "subpath": "gguf",
                "dest": str(dest),
                "size_bytes": total_size,
                "size_human": _human_size(total_size),
                "shard_count": shard_count if shard_count > 1 else None,
                "explanation": explanation,
                "spark_fit": fit,
                "spark_fit_label": fit_label,
            }
        )

    weight_files = _weights_files(siblings)
    if weight_files and not ggufs:
        fmt = _infer_weights_format(repo_id)
        engine = "vllm"
        total = sum(
            _sibling_size(f, by_name[f], sizes) for f in weight_files if f in by_name
        )
        label = fmt.upper() if fmt != "hf" else "HF weights"
        fit, fit_label, explanation = _spark_fit(total, fmt, label, repo_id)
        if len(weight_files) > 12:
            explanation = (
                f"{len(weight_files)} essential files (config, tokenizer, shards) — "
                + explanation
            )
        dest = MODELS_ROOT / inv / fmt
        variants.append(
            {
                "id": f"{fmt}:bundle",
                "label": label,
                "format": fmt,
                "engine": engine,
                "intent": "files",
                "files": weight_files,
                "inventory_path": inv,
                "subpath": fmt,
                "dest": str(dest),
                "size_bytes": total,
                "size_human": _human_size(total),
                "file_count": len(weight_files),
                "explanation": explanation,
                "spark_fit": fit,
                "spark_fit_label": fit_label,
            }
        )

    variants.sort(
        key=lambda v: (
            SPARK_FIT_ORDER.get(str(v.get("spark_fit")), 9),
            v.get("size_bytes") or 0,
        )
    )
    return variants


TEXT_GEN_PIPES = frozenset(
    {"text-generation", "text2text-generation", "conversational", "feature-extraction"}
)
VISION_PIPES = frozenset(
    {
        "image-text-to-text",
        "image-to-text",
        "visual-question-answering",
        "document-question-answering",
    }
)
DIFFUSION_PIPES = frozenset({"text-to-image", "image-to-image"})


def _model_traits(
    repo: str, tags: list[str], pipeline_tag: str | None
) -> dict[str, bool]:
    repo_low = repo.lower()
    tag_blob = " ".join(tags).lower()
    pipe = (pipeline_tag or "").lower()

    has_gguf = "gguf" in repo_low or "gguf" in tag_blob or "llama.cpp" in tag_blob
    has_nvfp4 = "nvfp4" in repo_low or "nvfp4" in tag_blob
    has_mtp = "mtp" in repo_low or "-mtp" in repo_low or "mtp" in tag_blob
    has_moe = bool(
        "moe" in tag_blob
        or re.search(r"\ba3b\b", repo_low)
        or "-a3b" in repo_low
        or re.search(r"-\d+b-a\d+b", repo_low)
    )
    has_diffusion = (
        pipe in DIFFUSION_PIPES
        or "diffusion" in repo_low
        or "diffusion" in tag_blob
        or "diffusers" in tag_blob
    )
    has_vision = (
        pipe in VISION_PIPES
        or "vision" in tag_blob
        or "multimodal" in tag_blob
        or "image-text" in pipe
        or "visual" in tag_blob
    )
    is_text_llm = pipe in TEXT_GEN_PIPES or (
        not has_diffusion
        and not has_vision
        and (not pipe or "gguf" in tag_blob or "transformers" in tag_blob)
    )
    has_dense = is_text_llm and not has_moe

    return {
        "has_gguf": has_gguf,
        "has_nvfp4": has_nvfp4,
        "has_moe": has_moe,
        "has_dense": has_dense,
        "has_mtp": has_mtp,
        "has_vision": has_vision,
        "has_diffusion": has_diffusion,
    }


def _model_card(m: Any) -> dict[str, Any]:
    repo = getattr(m, "id", None) or getattr(m, "modelId", None) or ""
    tags = list(getattr(m, "tags", []) or [])
    pipeline_tag = getattr(m, "pipeline_tag", None)
    created = getattr(m, "created_at", None)
    modified = getattr(m, "lastModified", None)
    traits = _model_traits(repo, tags, pipeline_tag)
    card = {
        "repo": repo,
        "author": getattr(m, "author", None),
        "downloads": getattr(m, "downloads", None),
        "likes": getattr(m, "likes", None),
        "pipeline_tag": pipeline_tag,
        "tags": tags[:20],
        "release_date": _iso(created) or _iso(modified),
        "last_modified": _iso(modified),
        **traits,
        "hf_url": f"https://huggingface.co/{repo}" if repo else None,
    }
    warning = explore_warning_for_repo(repo)
    if warning:
        card["spark_warning"] = warning
    return card


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


def load_explore_warnings() -> dict[str, dict[str, Any]]:
    data = load_yaml(EXPLORE_WARNINGS_FILE)
    repos = data.get("repos")
    if not isinstance(repos, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for repo_id, entry in repos.items():
        if not isinstance(entry, dict):
            continue
        key = str(repo_id).strip()
        if key:
            out[key] = entry
    return out


def explore_warning_for_repo(repo_id: str) -> dict[str, Any] | None:
    repo_id = (repo_id or "").strip()
    if not repo_id:
        return None
    entry = load_explore_warnings().get(repo_id)
    if not entry:
        return None
    return {
        "status": str(entry.get("status") or "incompatible"),
        "title": str(entry.get("title") or "Not compatible with Spark"),
        "message": str(entry.get("message") or "").strip(),
    }


def _ensure_explore_download_allowed(repo: str) -> None:
    warning = explore_warning_for_repo(repo)
    if warning:
        msg = warning.get("message") or warning.get("title") or "incompatible with Spark"
        raise ValueError(f"blocked: {msg}")


def load_explore_queue() -> dict[str, Any]:
    data = load_yaml(EXPLORE_QUEUE_FILE)
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def save_explore_queue(data: dict[str, Any]) -> None:
    save_yaml(EXPLORE_QUEUE_FILE, data)


def prune_download_queue(*, persist: bool = True) -> int:
    """Drop finished download queue rows (done/skipped)."""
    data = load_download_queue()
    items = data.get("items", [])
    if not isinstance(items, list):
        return 0
    kept = [i for i in items if i.get("state") not in DOWNLOAD_QUEUE_PRUNE_STATES]
    removed = len(items) - len(kept)
    if removed and persist:
        data["items"] = kept
        save_download_queue(data)
    return removed


def _explore_item_status(item: dict[str, Any], dl_items: list[dict[str, Any]]) -> str:
    """Derive shortlist status for an explore item from download queue + disk state."""
    repo = item.get("repo", "")
    inv_path = item.get("inventory_path", "")
    # Check download queue for this item's repo+inventory_path
    for dl in dl_items:
        dl_plan = dl.get("plan") or {}
        if dl.get("repo") != repo:
            continue
        if inv_path and dl_plan.get("inventory_path") and dl_plan["inventory_path"] != inv_path:
            continue
        state = dl.get("state", "")
        if state == STATE_DOWNLOADING or state == STATE_CHECKING:
            return "downloading"
        if state == STATE_QUEUED:
            return "download_queued"
        if state == STATE_AWAITING:
            return "gated"
    # Check disk: if item has a snapshot with dest or can resolve via inventory_path
    snap = item.get("snapshot") or {}
    dest_str = snap.get("dest") or (
        str(MODELS_ROOT / inv_path) if inv_path else None
    )
    if dest_str and Path(dest_str).is_dir() and any(Path(dest_str).iterdir()):
        return "on_disk"
    return "saved"


def queue_list() -> dict[str, Any]:
    prune_download_queue()
    dq = load_download_queue()
    eq = load_explore_queue()
    dl_items = dq.get("items", [])
    explore_items = eq.get("items", [])
    enriched = []
    for item in explore_items:
        it = dict(item)
        it["status"] = _explore_item_status(item, dl_items)
        enriched.append(it)
    return {
        "download": dl_items,
        "explore": enriched,
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
    _ensure_explore_download_allowed(repo)
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


def queue_add_explore(
    *,
    repo: str,
    intent: str = "gguf_best",
    files: list[str] | None = None,
    inventory_path: str | None = None,
    variant_label: str | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo = validate_repo_id(repo)
    if not repo:
        raise ValueError("invalid repo")
    _ensure_explore_download_allowed(repo)
    inv = str(inventory_path or "").strip().strip("/") or None
    item: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "repo": repo,
        "intent": intent,
        "added_at": utc_now(),
    }
    if files:
        item["files"] = [str(f) for f in files if str(f).strip()]
    if inv:
        item["inventory_path"] = inv
    if variant_label:
        item["variant_label"] = str(variant_label).strip()
    if snapshot and isinstance(snapshot, dict):
        item["snapshot"] = {
            k: v for k, v in snapshot.items()
            if k in ("format", "engine", "size_bytes", "size_human", "spark_fit",
                      "spark_fit_label", "badges", "dest", "downloads")
        }
    data = load_explore_queue()
    items = data.setdefault("items", [])
    # Dedupe: replace existing item with same repo + intent + inventory_path
    dedup_key = (repo, intent, inv or "")
    kept = []
    replaced_id = None
    for existing in items:
        ex_inv = str(existing.get("inventory_path") or "").strip("/")
        ex_key = (existing.get("repo", ""), existing.get("intent", ""), ex_inv)
        if ex_key == dedup_key:
            replaced_id = existing.get("id")
        else:
            kept.append(existing)
    if replaced_id:
        item["id"] = replaced_id  # keep stable id so UI selections survive
        item["added_at"] = utc_now()
    data["items"] = kept + [item]
    save_explore_queue(data)
    return item


def queue_remove_explore(item_id: str) -> None:
    data = load_explore_queue()
    items = data.get("items", [])
    kept = [i for i in items if i.get("id") != item_id]
    if len(kept) == len(items):
        raise ValueError("unknown explore item")
    data["items"] = kept
    save_explore_queue(data)


def queue_remove_download(item_id: str) -> None:
    data = load_download_queue()
    items = data.get("items", [])
    item = _find_item(items, item_id)
    if not item:
        raise ValueError("unknown download item")
    state = item.get("state")
    if state in {STATE_DOWNLOADING, STATE_CHECKING}:
        raise ValueError("cannot remove active download")
    data["items"] = [i for i in items if i.get("id") != item_id]
    save_download_queue(data)


def queue_download_explore_item(item_id: str) -> dict[str, Any]:
    data = load_explore_queue()
    item = _find_item(data.get("items", []), item_id)
    if not item:
        raise ValueError("unknown explore item")
    repo = str(item.get("repo", ""))
    intent = str(item.get("intent") or "gguf_best")
    files = item.get("files") if isinstance(item.get("files"), list) else None
    inventory_path = item.get("inventory_path")
    if intent == "files" and not files:
        intent = "gguf_best"
    return queue_add_download(
        repo=repo,
        intent=intent,
        files=files,
        inventory_path=str(inventory_path) if inventory_path else None,
    )


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
    try:
        core = _load_inference_core()
        core.scaffold_auto(str(inv), plan if isinstance(plan, dict) else None)
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
        prune_download_queue()
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
    prune_download_queue()


def worker_main() -> int:
    DOWNLOAD_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_PID_FILE.write_text(str(os.getpid()))

    self_pid = os.getpid()
    try:
        while True:
            ok, reason = worker_can_start(self_pid)
            if not ok:
                with DOWNLOAD_LOG_FILE.open("a", encoding="utf-8") as logfh:
                    logfh.write(f"==> worker idle exit: {reason} {utc_now()}\n")
                return 0

            item = _next_actionable_item()
            if not item:
                return 0

            process_queue_item(item)

            ok, reason = worker_can_start(self_pid)
            if not ok:
                return 0
    finally:
        DOWNLOAD_PID_FILE.unlink(missing_ok=True)


def maybe_start_worker() -> bool:
    _clear_stale_download_pid()
    pid = read_pid_file(DOWNLOAD_PID_FILE)
    if pid and _is_queue_worker_pid(pid):
        return False
    ok, _reason = can_start_download()
    if not ok:
        return False
    if _next_actionable_item() is None:
        return False
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "spark-hf.py"), "worker"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
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
            try:
                variants = discover_model_variants(repo)
            except ValueError:
                variants = []
            default_plan = variants[0] if variants else None
            warning = explore_warning_for_repo(repo)
            payload: dict[str, Any] = {
                "ok": True,
                "model": meta,
                "variants": variants,
                "default_plan": default_plan,
            }
            if warning:
                payload["spark_warning"] = warning
            return 200, payload
        return None

    if method != "POST":
        return None

    if route == "/api/hf/queue":
        action = str(body.get("action", "download")).strip().lower()
        if action == "explore":
            try:
                files = body.get("files") if isinstance(body.get("files"), list) else None
                snap = body.get("snapshot")
                item = queue_add_explore(
                    repo=str(body.get("repo", "")),
                    intent=str(body.get("intent", "gguf_best")),
                    files=files,
                    inventory_path=body.get("inventory_path"),
                    variant_label=body.get("variant_label"),
                    snapshot=snap if isinstance(snap, dict) else None,
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

    remove_match = re.match(r"^/api/hf/queue/([^/]+)/remove$", route)
    if remove_match:
        item_id = remove_match.group(1)
        which = str(body.get("queue", "explore")).strip().lower()
        try:
            if which == "download":
                queue_remove_download(item_id)
            else:
                queue_remove_explore(item_id)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 200, {"ok": True, "removed": item_id, "queue": which}

    download_match = re.match(r"^/api/hf/queue/([^/]+)/download$", route)
    if download_match:
        try:
            item = queue_download_explore_item(download_match.group(1))
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}
        return 202, {"ok": True, "item": item, "active": active_hf_download()}

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