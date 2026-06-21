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
CATALOG = Path("/opt/spark/data/model-catalog.yaml")
OUT_JSON = Path("/opt/spark/portal/models.json")
HF = Path("/opt/spark/venv/bin/python")


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


def hf_enrich(repo: str, cache: dict) -> dict:
    if repo in cache:
        return cache[repo]
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
    cache[repo] = info
    return info


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
    hf_cache: dict = {}
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

        entries.append(
            {
                "id": m["id"],
                "lab": lab,
                "name": m["name"],
                "slug": slug,
                "path": str(base),
                "hf_repo": hf_repo,
                "hf_url": f"https://huggingface.co/{hf_repo}" if hf_repo else None,
                "capabilities": m.get("capabilities", []),
                "why_downloaded": (m.get("why_downloaded") or "").strip(),
                "description": desc or None,
                "release_date": hf_info.get("release_date"),
                "max_context": max_ctx,
                "pipeline_tag": hf_info.get("pipeline_tag"),
                "tags": hf_info.get("tags", [])[:12],
                "status": overall,
                "size_bytes": total_size,
                "size_human": human_size(total_size),
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
                if any(e["id"] == mid for e in entries):
                    continue
                size = dir_size(model_dir)
                entries.append(
                    {
                        "id": mid,
                        "lab": lab_dir.name,
                        "name": model_dir.name,
                        "slug": model_dir.name,
                        "path": str(model_dir),
                        "hf_repo": None,
                        "hf_url": None,
                        "capabilities": ["untracked"],
                        "why_downloaded": "Not in catalog — add to model-catalog.yaml",
                        "description": None,
                        "release_date": None,
                        "max_context": None,
                        "status": "ready" if size else "empty",
                        "size_bytes": size,
                        "size_human": human_size(size),
                        "variants": [],
                    }
                )

    payload = {
        "generated_at": now,
        "spark_root": str(MODELS_ROOT),
        "count": len(entries),
        "models": sorted(entries, key=lambda x: (x["lab"], x["name"])),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUT_JSON} ({len(entries)} models)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
