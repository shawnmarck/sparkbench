#!/usr/bin/env python3
"""Sweep Laguna S 2.1 DFlash num_speculative_tokens for single-slot PBM @ 4k.

Patches the golden eugr service + recipe, restarts inference, runs PBM --fills 4096,
and scrapes SpecDecoding metrics from the vLLM container log.

Usage (on Sparky):
  /opt/spark/venv/bin/python3 /opt/spark/scripts/laguna-s-dflash-nspec-sweep.py
  /opt/spark/venv/bin/python3 /opt/spark/scripts/laguna-s-dflash-nspec-sweep.py --moe flashinfer_cutlass --ns 7
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SPARK_ROOT", "/opt/spark"))
PROFILE = "poolside-laguna-s-2-1-dflash-eugr"
RECIPE_PATH = ROOT / "recipes" / f"{PROFILE}.yaml"
EUGR_PATH = ROOT / "services" / f"eugr-{PROFILE}.yaml"
OUT_DIR = ROOT / "run"
RESULTS_PATH = OUT_DIR / "laguna-s-dflash-nspec-sweep.json"
FULL_LADDER_PATH = OUT_DIR / "laguna-s-dflash-nspec-full-ladder.json"
TARGET_WEIGHTS = "/models/poolside/laguna-s-2.1/nvfp4"
DRAFT_WEIGHTS = "/models/poolside/laguna-s-2.1-dflash/dflash"

SPEC_ACCEPT_RE = re.compile(
    r"SpecDecoding metrics:\s*Mean acceptance length:\s*([\d.]+).*?"
    r"Accepted throughput:\s*([\d.]+).*?"
    r"Drafted throughput:\s*([\d.]+).*?"
    r"Avg Draft acceptance rate:\s*([\d.]+)%",
    re.I | re.S,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text()) or {}


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def write_eugr(*, n_spec: int, max_num_seqs: int, moe: str) -> None:
    """Rewrite eugr service as a clean block scalar (avoids escaped one-liner YAML).

    Brace-doubling: spark-inference formats the command with defaults, so JSON
    objects in the command must use {{ / }} in the on-disk recipe.
    """
    content = f"""recipe_version: "1"
name: {PROFILE}
description: eugr vLLM DFlash speculative serve for poolside/laguna-s-2.1 (NVFP4)
model: laguna-s-2.1-dflash
container: vllm-node
defaults:
  port: 8000
  host: 0.0.0.0
  tensor_parallel: 1
  gpu_memory_utilization: 0.85
  max_model_len: 262144
  max_num_seqs: {max_num_seqs}
  max_num_batched_tokens: 8192
command: |
  vllm serve {TARGET_WEIGHTS} \\
    --host {{host}} \\
    --port {{port}} \\
    --served-model-name laguna-s-2.1-dflash \\
    --tensor-parallel-size {{tensor_parallel}} \\
    --trust-remote-code \\
    --kv-cache-dtype auto \\
    --attention-backend flashinfer \\
    --moe-backend {moe} \\
    --enable-auto-tool-choice \\
    --tool-call-parser poolside_v1 \\
    --reasoning-parser poolside_v1 \\
    --default-chat-template-kwargs '{{{{"enable_thinking": true}}}}' \\
    --override-generation-config '{{{{"temperature": 0.7, "top_p": 0.95}}}}' \\
    --gpu-memory-utilization {{gpu_memory_utilization}} \\
    --max-model-len {{max_model_len}} \\
    --max-num-seqs {{max_num_seqs}} \\
    --max-num-batched-tokens {{max_num_batched_tokens}} \\
    --enable-chunked-prefill \\
    --load-format auto \\
    --speculative-config '{{{{"method": "dflash", "model": "{DRAFT_WEIGHTS}", "num_speculative_tokens": {n_spec}}}}}'
"""
    EUGR_PATH.write_text(content)


def patch_recipe(*, n_spec: int) -> None:
    recipe = _load_yaml(RECIPE_PATH)
    spec = recipe.setdefault("speculative", {})
    spec["num_speculative_tokens"] = int(n_spec)
    recipe["speculative"] = spec
    _save_yaml(RECIPE_PATH, recipe)


def run(cmd: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def wait_ready(*, timeout_s: int = 2400) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        cp = run(["curl", "-sf", "http://127.0.0.1:8000/v1/models"], timeout=10)
        if cp.returncode == 0 and "laguna-s-2.1-dflash" in (cp.stdout or ""):
            print("ready: /v1/models ok", flush=True)
            return
        time.sleep(5)
    raise SystemExit(f"engine not ready after {timeout_s}s")


def scrape_accept_metrics() -> dict[str, Any] | None:
    cp = run(
        ["docker", "logs", "--tail", "200", "vllm_node"],
        timeout=30,
    )
    blob = (cp.stdout or "") + "\n" + (cp.stderr or "")
    matches = list(SPEC_ACCEPT_RE.finditer(blob))
    if not matches:
        # looser line-oriented scrape
        lines = [ln for ln in blob.splitlines() if "SpecDecoding metrics" in ln]
        if not lines:
            return None
        last = lines[-1]
        out: dict[str, Any] = {"raw": last}
        m = re.search(r"Mean acceptance length:\s*([\d.]+)", last)
        if m:
            out["mean_accept_len"] = float(m.group(1))
        m = re.search(r"Accepted throughput:\s*([\d.]+)", last)
        if m:
            out["accepted_tok_s"] = float(m.group(1))
        m = re.search(r"Drafted throughput:\s*([\d.]+)", last)
        if m:
            out["drafted_tok_s"] = float(m.group(1))
        m = re.search(r"Avg Draft acceptance rate:\s*([\d.]+)%", last)
        if m:
            out["avg_accept_pct"] = float(m.group(1))
        return out
    m = matches[-1]
    return {
        "mean_accept_len": float(m.group(1)),
        "accepted_tok_s": float(m.group(2)),
        "drafted_tok_s": float(m.group(3)),
        "avg_accept_pct": float(m.group(4)),
        "raw": m.group(0)[:240],
    }


def up_profile() -> None:
    run(["spark", "inference", "down"], timeout=180)
    time.sleep(3)
    cp = run(
        ["spark", "inference", "up", PROFILE, "--preset", "golden"],
        timeout=120,
    )
    if cp.returncode != 0:
        print(cp.stdout)
        print(cp.stderr, file=sys.stderr)
        raise SystemExit(f"inference up failed rc={cp.returncode}")
    wait_ready()


def run_pbm(*, fills: str) -> dict[str, Any]:
    py = ROOT / "venv" / "bin" / "python3"
    script = ROOT / "scripts" / "spark-inference-perfbench-metrics.py"
    timeout = 7200 if "," in fills else 3600
    cp = run(
        [str(py), str(script), "--profile", PROFILE, "--fills", fills],
        timeout=timeout,
    )
    print(cp.stdout)
    if cp.stderr:
        print(cp.stderr, file=sys.stderr)
    if cp.returncode != 0:
        raise SystemExit(f"PBM failed rc={cp.returncode} fills={fills}")
    pbm = _load_yaml(ROOT / "data" / "perfbench-metrics.yaml")
    entry = (pbm.get("profiles") or {}).get(PROFILE) or {}
    fill_map = entry.get("fills") or {}
    out: dict[str, Any] = {
        "pbm_note": entry.get("note"),
        "loaded_ctx": entry.get("loaded_ctx"),
        "stdout": (cp.stdout or "").strip(),
        "fills_requested": fills,
    }
    for key in ("4096", "50000", "100000"):
        cell = fill_map.get(key) or fill_map.get(int(key)) or {}
        if cell.get("tok_s") is not None:
            out[f"tok_s_{key}"] = cell.get("tok_s")
    # Back-compat alias used by the 4k-only sweep
    if "tok_s_4096" in out:
        out["tok_s_4k"] = out["tok_s_4096"]
    return out


def run_pbm_4k() -> dict[str, Any]:
    return run_pbm(fills="4096")


def run_pbm_full() -> dict[str, Any]:
    return run_pbm(fills="4096,50000,100000")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ns",
        nargs="+",
        type=int,
        default=[2, 3, 5, 7, 10, 15],
        help="num_speculative_tokens values to sweep",
    )
    parser.add_argument("--moe", default="marlin", help="moe-backend (marlin|flashinfer_cutlass)")
    parser.add_argument("--max-num-seqs", type=int, default=1)
    parser.add_argument(
        "--full-each",
        action="store_true",
        help="Run full PBM ladder (4k/50k/100k) for every n_spec (not just winner)",
    )
    parser.add_argument(
        "--full-pbm-on",
        type=int,
        default=None,
        help="After 4k sweep, run full PBM ladder on this n (default: winner). Ignored with --full-each.",
    )
    parser.add_argument(
        "--no-winner-full",
        action="store_true",
        help="Skip post-sweep winner full PBM (4k-only mode)",
    )
    parser.add_argument(
        "--skip-up-if-current",
        action="store_true",
        help="Skip restart when eugr already matches (debug)",
    )
    args = parser.parse_args()

    if not RECIPE_PATH.is_file() or not EUGR_PATH.is_file():
        raise SystemExit(f"missing recipe/service under {ROOT}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FULL_LADDER_PATH if args.full_each else RESULTS_PATH
    results: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "profile": PROFILE,
        "moe": args.moe,
        "max_num_seqs": args.max_num_seqs,
        "mode": "full_ladder" if args.full_each else "4k_then_winner_full",
        "runs": [],
    }

    for n in args.ns:
        mode = "full" if args.full_each else "4k"
        print(
            f"\n===== n_spec={n} moe={args.moe} max_num_seqs={args.max_num_seqs} pbm={mode} =====",
            flush=True,
        )
        write_eugr(n_spec=n, max_num_seqs=args.max_num_seqs, moe=args.moe)
        patch_recipe(n_spec=n)
        up_profile()
        pbm = run_pbm_full() if args.full_each else run_pbm_4k()
        accept = scrape_accept_metrics()
        row = {
            "n_spec": n,
            "moe": args.moe,
            "max_num_seqs": args.max_num_seqs,
            "measured_at": datetime.now(timezone.utc).isoformat(),
            **pbm,
            "accept": accept,
        }
        results["runs"].append(row)
        out_path.write_text(json.dumps(results, indent=2) + "\n")
        print(
            f"RESULT n={n}: 4k={pbm.get('tok_s_4k') or pbm.get('tok_s_4096')} "
            f"50k={pbm.get('tok_s_50000')} 100k={pbm.get('tok_s_100000')} accept={accept}",
            flush=True,
        )

    # Pick winner by tok_s_4k / tok_s_4096
    ranked = sorted(
        (
            r
            for r in results["runs"]
            if (r.get("tok_s_4k") is not None or r.get("tok_s_4096") is not None)
        ),
        key=lambda r: float(r.get("tok_s_4k") or r.get("tok_s_4096") or 0),
        reverse=True,
    )
    winner_n = int(ranked[0]["n_spec"]) if ranked else None
    results["winner_n"] = winner_n
    results["baseline_note"] = "no-DFlash PBM 4k was 18.9; prior golden n=15 was 25.6"

    if not args.full_each and not args.no_winner_full:
        full_n = args.full_pbm_on if args.full_pbm_on is not None else winner_n
        if full_n is not None:
            print(f"\n===== full PBM on winner n={full_n} =====", flush=True)
            write_eugr(n_spec=full_n, max_num_seqs=args.max_num_seqs, moe=args.moe)
            patch_recipe(n_spec=full_n)
            up_profile()
            results["winner_full_pbm"] = run_pbm_full()
            results["winner_accept"] = scrape_accept_metrics()
    elif winner_n is not None:
        # Leave recipe on the 4k/overall winner after a full-each sweep
        write_eugr(n_spec=winner_n, max_num_seqs=args.max_num_seqs, moe=args.moe)
        patch_recipe(n_spec=winner_n)

    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
