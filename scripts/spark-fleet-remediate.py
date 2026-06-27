#!/opt/spark/venv/bin/python3
"""Fleet remediation — golden audit, ctx ladder, draft benches, shelf push queue.

Runs GPU-bound steps sequentially. Shelf pushes can overlap in background.
Skip: 0xsero/deepseek-v4-flash-spark, z-lab/* (auxiliary).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
LOG = ROOT / "logs" / "fleet-remediate.log"
REPORT = ROOT / "run" / "fleet-remediate-report.json"
PY = ROOT / "venv/bin/python3"
WORKFLOW = ROOT / "scripts/spark-golden-workflow.py"
LADDER = ROOT / "scripts/spark-ctx-ladder.py"
SPARK = "/usr/local/bin/spark"
SKIP_INVENTORY = {"0xsero/deepseek-v4-flash-spark"}

# Golden re-bench at long-ctx preset (viability notes, low-ctx bench only)
REBENCH_LONG_CTX = [
    "empero-ai/qwythos-9b-claude-mythos-5-1m",
    "qwen/qwen-agentworld-35b-a3b",
]

# Draft profiles to bench (same inventory — not golden replacements)
DRAFT_BENCH = [
    "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr-2",
    "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr-3",
    "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr-4",
    "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr-5",
    "empero-ai-qwythos-9b-claude-mythos-5-1m-eugr-6",
    "empero-ai-qwythos-9b-claude-mythos-5-1m-mtp-llama",
]

CTX_LADDER_PROFILES: list[str] = []


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd: list[str], *, timeout: int = 7200, env: dict | None = None) -> subprocess.CompletedProcess:
    log(f"RUN {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def load_golden() -> dict[str, str]:
    data = yaml.safe_load((ROOT / "data/golden-recipes.yaml").read_text()) or {}
    return dict(data.get("golden") or {})


def load_recipe(profile_id: str) -> dict[str, Any]:
    for sub in ("", "drafts"):
        p = ROOT / "recipes" / sub / f"{profile_id}.yaml" if sub else ROOT / "recipes" / f"{profile_id}.yaml"
        if p.is_file():
            return yaml.safe_load(p.read_text()) or {}
    return {}


def needs_ctx_ladder(profile_id: str) -> bool:
    recipe = load_recipe(profile_id)
    ctx = recipe.get("context") or {}
    native = ctx.get("native")
    golden = (ctx.get("presets") or {}).get("golden", {})
    gctx = golden.get("ctx") or ctx.get("default")
    if ctx.get("ctx_ladder"):
        return False
    if not native or not gctx:
        return False
    return int(native) > int(gctx) * 1.1


def discover_ctx_ladder_profiles() -> list[str]:
    golden = load_golden()
    out = []
    for inv, prof in golden.items():
        if inv in SKIP_INVENTORY:
            continue
        if needs_ctx_ladder(prof):
            out.append(prof)
    return out


def shelf_missing() -> list[str]:
    models = json.loads((ROOT / "portal/models.json").read_text()).get("models", [])
    out = []
    for m in models:
        inv = m.get("rel_path") or m.get("id")
        if inv in SKIP_INVENTORY or inv.startswith("z-lab/"):
            continue
        if not (m.get("shelf") or {}).get("present"):
            out.append(inv)
    return out


def golden_workflow(paths: list[str], *, skip_shelf: bool) -> dict[str, Any]:
    if not paths:
        return {"status": "skipped", "paths": []}
    only = ",".join(paths)
    args = [str(PY), str(WORKFLOW), "--only", only, "--resume"]
    if skip_shelf:
        args.append("--skip-shelf")
    r = run(args, timeout=604800)  # up to 7 days for full matrix fleet
    ok = r.returncode == 0
    if not ok:
        log(f"golden workflow failed: {r.stderr[-2000:]}")
    return {"status": "ok" if ok else "failed", "paths": paths, "stderr": r.stderr[-1500:]}


def bench_draft_profile(profile_id: str) -> dict[str, Any]:
    """Load + bench v2 a draft/testing profile; do not promote."""
    result: dict[str, Any] = {"profile_id": profile_id, "status": "pending"}
    draft = ROOT / "recipes" / "drafts" / f"{profile_id}.yaml"
    if not draft.is_file():
        result["status"] = "missing_draft"
        return result
    recipe = yaml.safe_load(draft.read_text()) or {}
    ctx_block = recipe.get("context") or {}
    golden = (ctx_block.get("presets") or {}).get("golden", {})
    ctx = golden.get("ctx") or ctx_block.get("default") or 32768
    kv = golden.get("kv") or ctx_block.get("kv_default") or "q8_0"
    engine = recipe.get("engine") or "llamacpp"
    if engine == "eugr":
        kv = golden.get("kv") or ctx_block.get("kv_default") or "fp8"

    run([SPARK, "inference", "down"], timeout=180)
    up = run(
        [SPARK, "inference", "up", profile_id, "--ctx", str(ctx), "--kv", kv],
        timeout=3600,
    )
    if up.returncode != 0:
        result["status"] = "up_failed"
        result["error"] = (up.stderr or up.stdout)[-800:]
        return result

    bench = run(
        [str(PY), str(ROOT / "scripts/spark-inference.py"), "bench", "--write-result"],
        timeout=7200,
        env={"BENCH_STANDARD": "v2"},
    )
    if bench.returncode != 0:
        result["status"] = "bench_failed"
        result["error"] = bench.stderr[-800:]
        return result
    try:
        br = json.loads((ROOT / "run/inference-bench-result.json").read_text())
        result["bench"] = br
        result["tok_s"] = br.get("tok_s")
        result["status"] = "ok" if br.get("ok") else "bench_failed"
    except Exception as exc:
        result["status"] = "bench_failed"
        result["error"] = str(exc)
    return result


def ctx_ladder(profile_id: str) -> dict[str, Any]:
    r = run([str(PY), str(LADDER), profile_id], timeout=14400)
    ok = r.returncode == 0
    return {
        "profile_id": profile_id,
        "status": "ok" if ok else "failed",
        "stderr": r.stderr[-1500:],
    }


def start_shelf_push(paths: list[str]) -> dict[str, Any]:
    if not paths:
        return {"status": "skipped", "paths": []}
    # Push sequentially in one background job via shell
    rels = " ".join(paths)
    script = f"""
set -euo pipefail
LOG={ROOT}/logs/shelf-push-fleet.log
echo "=== fleet shelf push $(date -Is) ===" >> "$LOG"
for p in {rels}; do
  echo "==> $p" | tee -a "$LOG"
  {SPARK} shelf push "$p" >> "$LOG" 2>&1 || echo "FAIL $p" | tee -a "$LOG"
done
echo "=== fleet shelf push done $(date -Is) ===" >> "$LOG"
"""
    proc = subprocess.Popen(
        ["bash", "-c", script],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"status": "background", "pid": proc.pid, "paths": paths}


def preflight_inference() -> None:
    """Ensure no orphan engines block golden audit."""
    run([SPARK, "inference", "down"], timeout=180)
    # Orphan llama-server not tracked by spark inference state
    subprocess.run(
        ["pkill", "-f", "llama-server.*--port 8081"],
        capture_output=True,
    )
    time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fleet remediation orchestrator")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no execution")
    parser.add_argument("--skip-shelf", action="store_true", help="Skip shelf push phase")
    parser.add_argument("--skip-drafts", action="store_true", help="Skip qwythos draft benches")
    parser.add_argument("--only-phase", choices=["audit", "ladder", "drafts", "shelf", "all"], default="all")
    args = parser.parse_args()

    golden = load_golden()
    new_models = [
        "deepreinforce-ai/ornith-1.0-35b",
        "jackrong/qwopus3.6-27b-coder-compat",
    ]
    audit_paths = [p for p in new_models if p in golden] + REBENCH_LONG_CTX
    ladder_profiles = discover_ctx_ladder_profiles()
    shelf_paths = shelf_missing()

    plan = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "audit": audit_paths,
        "ctx_ladder": ladder_profiles,
        "draft_bench": [] if args.skip_drafts else DRAFT_BENCH,
        "shelf_push": [] if args.skip_shelf else shelf_paths,
        "phases": {},
    }
    log(f"PLAN {json.dumps(plan, indent=2)}")

    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0

    preflight_inference()
    report = plan.copy()
    report["phases"] = {}

    if args.only_phase in ("all", "audit"):
        log("=== PHASE: golden workflow ===")
        report["phases"]["audit"] = golden_workflow(audit_paths, skip_shelf=True)

    if args.only_phase == "ladder":
        log("=== PHASE: ctx ladder only ===")
        ladder_results = []
        for prof in ladder_profiles:
            ladder_results.append(ctx_ladder(prof))
        report["phases"]["ladder"] = ladder_results

    if args.only_phase in ("all", "drafts") and not args.skip_drafts:
        log("=== PHASE: draft profile benches ===")
        draft_results = []
        for pid in DRAFT_BENCH:
            draft_results.append(bench_draft_profile(pid))
        report["phases"]["drafts"] = draft_results

    if args.only_phase in ("all", "shelf") and not args.skip_shelf:
        log("=== PHASE: shelf push (background) ===")
        # Refresh shelf list after audits may have pushed some
        shelf_paths = shelf_missing()
        report["phases"]["shelf"] = start_shelf_push(shelf_paths)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    run([SPARK, "models", "inventory"], timeout=300)
    log(f"DONE report={REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
