#!/opt/spark/venv/bin/python3
"""Golden workflow — full layered bench per model (golden + kv sweep + ctx ladder + shelf).

When the user says "do the golden workflow on a model", run this script.

Layers (sequential, GPU-bound):
  1. Golden cell — optimize ctx/kv, full bench v2, promote, verify works
  2. KV sweep — golden ctx × supported KV quants @ 75% fill
  3. Context ladder — golden kv × ctx rungs above golden @ 75% fill
  4. Shelf push — optional NAS backup

Reports: /opt/spark/run/golden-workflow-report.json
Logs:    /opt/spark/logs/golden-workflow.log
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/opt/spark")
PY = ROOT / "venv/bin/python3"
AUDIT = ROOT / "scripts/golden-inventory-audit.py"
KV_SWEEP = ROOT / "scripts/spark-kv-sweep.py"
CTX_LADDER = ROOT / "scripts/spark-ctx-ladder.py"
GOLDEN_FILE = ROOT / "data/golden-recipes.yaml"
REPORT_FILE = ROOT / "run/golden-workflow-report.json"
LOG_FILE = ROOT / "logs/golden-workflow.log"
SPARK = "/usr/local/bin/spark"

SKIP_INVENTORY = {
    "0xsero/deepseek-v4-flash-spark",
}


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd: list[str], *, timeout: int = 86400, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    log(f"RUN: {' '.join(cmd)}")
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
        env=merged,
    )


def load_golden_map() -> dict[str, str]:
    data = yaml.safe_load(GOLDEN_FILE.read_text()) or {}
    from_audit = {}
    spec = importlib.util.spec_from_file_location("audit", AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from_audit = dict(getattr(mod, "DEFAULT_GOLDEN", {}))
    merged = dict(from_audit)
    merged.update(data.get("golden") or {})
    return merged


def load_recipe(profile_id: str) -> dict[str, Any]:
    path = ROOT / "recipes" / f"{profile_id}.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def needs_ctx_ladder(profile_id: str) -> bool:
    recipe = load_recipe(profile_id)
    ctx = recipe.get("context") or {}
    if ctx.get("ctx_ladder"):
        return False
    native = ctx.get("native")
    golden = (ctx.get("presets") or {}).get("golden", {})
    gctx = golden.get("ctx") or ctx.get("default")
    if not native or not gctx:
        return False
    return int(native) > int(gctx) * 1.1


def golden_cell_from_audit_result(audit_entry: dict[str, Any]) -> dict[str, Any] | None:
    bench = audit_entry.get("bench") or {}
    if not bench.get("ok") and audit_entry.get("status") != "ok":
        return None
    return {
        "ctx": audit_entry.get("ctx"),
        "kv": audit_entry.get("kv"),
        "tok_s": bench.get("tok_s") or audit_entry.get("bench_tok_s"),
        "tool_ok": bench.get("tool_roundtrip_ok"),
        "method": bench.get("method") or "bench-agent-v2",
        "bench_standard": bench.get("bench_standard_version") or "2.0",
        "fill_target": bench.get("context_fill_target_tokens"),
    }


def run_golden_phase(
    path: str,
    profile_id: str,
    *,
    skip_shelf: bool,
    resume: bool,
) -> dict[str, Any]:
    args = [str(PY), str(AUDIT), "--only", path]
    if skip_shelf:
        args.append("--skip-shelf")
    if resume:
        args.append("--resume")
    r = run(args, timeout=86400)
    entry: dict[str, Any] = {
        "status": "ok" if r.returncode == 0 else "failed",
        "returncode": r.returncode,
    }
    if r.stderr:
        entry["stderr"] = r.stderr[-1500:]
    try:
        audit_report = json.loads((ROOT / "run/golden-audit-report.json").read_text())
        for m in audit_report.get("models") or []:
            if m.get("inventory_path") == path:
                entry.update(
                    {
                        "audit_status": m.get("status"),
                        "ctx": m.get("ctx"),
                        "kv": m.get("kv"),
                        "bench_tok_s": m.get("bench_tok_s"),
                        "bench": m.get("bench"),
                    }
                )
                if m.get("status") != "ok":
                    entry["status"] = "failed"
                break
    except Exception as exc:
        entry["parse_error"] = str(exc)
    if entry.get("status") == "ok":
        cell = golden_cell_from_audit_result(entry)
        if cell:
            _merge_golden_cell(profile_id, cell)
    return entry


def _load_golden_bench():
    spec = importlib.util.spec_from_file_location(
        "golden_bench", ROOT / "scripts/spark-golden-bench.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _merge_golden_cell(profile_id: str, cell: dict[str, Any]) -> None:
    gb = _load_golden_bench()
    gb.merge_bench_matrix(profile_id, golden_cell=cell)


def run_kv_sweep_phase(profile_id: str, *, force: bool) -> dict[str, Any]:
    args = [str(PY), str(KV_SWEEP), profile_id]
    if force:
        args.append("--force")
    r = run(args, timeout=14400)
    out: dict[str, Any] = {"status": "ok" if r.returncode == 0 else "failed", "returncode": r.returncode}
    try:
        rep = json.loads((ROOT / "run/kv-sweep-report.json").read_text())
        out["kv_results"] = len(rep.get("results") or [])
        out["kv_ok"] = sum(1 for x in rep.get("results") or [] if x.get("status") == "ok")
        if rep.get("status") == "skipped":
            out["status"] = "skipped"
    except Exception:
        pass
    if r.stderr:
        out["stderr"] = r.stderr[-800:]
    return out


def run_ctx_ladder_phase(profile_id: str, *, force: bool) -> dict[str, Any]:
    if not force and not needs_ctx_ladder(profile_id):
        return {"status": "skipped", "reason": "native <= golden or ctx_ladder exists"}
    args = [str(PY), str(CTX_LADDER), profile_id]
    r = run(args, timeout=28800)
    out: dict[str, Any] = {"status": "ok" if r.returncode == 0 else "failed", "returncode": r.returncode}
    try:
        rep = json.loads((ROOT / "run/ctx-ladder-report.json").read_text())
        out["max_viable_ctx"] = rep.get("max_viable_ctx")
        out["rungs"] = len(rep.get("results") or [])
        gb = _load_golden_bench()
        if rep.get("results") is not None:
            recipe = gb.load_recipe(profile_id)
            ladder = (recipe.get("context") or {}).get("ctx_ladder")
            if ladder:
                gb.merge_bench_matrix(profile_id, ctx_ladder=ladder)
    except Exception:
        pass
    if r.stderr:
        out["stderr"] = r.stderr[-800:]
    return out


def run_shelf_phase(path: str) -> dict[str, Any]:
    models = json.loads((ROOT / "portal/models.json").read_text()).get("models") or []

    def inv_path(m: dict) -> str:
        return (m.get("path") or "").replace("/models/", "").strip("/")

    m = next((x for x in models if inv_path(x) == path), None)
    if m and (m.get("shelf") or {}).get("present"):
        return {"status": "skipped", "reason": "already on shelf"}
    r = run([SPARK, "shelf", "push", path], timeout=86400)
    return {
        "status": "ok" if r.returncode == 0 else "failed",
        "returncode": r.returncode,
        "stderr": (r.stderr or "")[-500:] if r.returncode != 0 else None,
    }


def phase_done(prior: dict[str, Any] | None, phase: str) -> bool:
    if not prior:
        return False
    ph = (prior.get("phases") or {}).get(phase) or {}
    return ph.get("status") in ("ok", "skipped")


def process_model(
    path: str,
    profile_id: str,
    *,
    skip_shelf: bool,
    skip_kv_sweep: bool,
    skip_ctx_ladder: bool,
    resume: bool,
    force: bool,
    only_phase: str,
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "inventory_path": path,
        "golden_profile": profile_id,
        "phases": {},
        "status": "pending",
    }
    log(f"=== golden workflow {path} -> {profile_id} ===")

    golden_ok = False
    if only_phase in ("kv_sweep", "ctx_ladder", "shelf"):
        golden_ok = phase_done(prior, "golden") or bool(load_recipe(profile_id).get("context", {}).get("presets", {}).get("golden"))
    elif only_phase in ("all", "golden"):
        if resume and phase_done(prior, "golden"):
            result["phases"]["golden"] = prior["phases"]["golden"]  # type: ignore[index]
            log("resume: skip golden (already ok)")
            golden_ok = True
        else:
            result["phases"]["golden"] = run_golden_phase(
                path, profile_id, skip_shelf=True, resume=resume
            )
            golden_ok = result["phases"]["golden"].get("status") == "ok"
    if only_phase == "golden":
        result["status"] = "ok" if golden_ok else "failed"
        return result

    if not golden_ok:
        result["status"] = "failed"
        result["error"] = "golden phase failed — skipping kv sweep and ctx ladder"
        return result

    if only_phase in ("all", "kv_sweep") and not skip_kv_sweep:
        if resume and not force and phase_done(prior, "kv_sweep"):
            result["phases"]["kv_sweep"] = prior["phases"]["kv_sweep"]  # type: ignore[index]
            log("resume: skip kv_sweep")
        else:
            result["phases"]["kv_sweep"] = run_kv_sweep_phase(profile_id, force=force)

    if only_phase in ("all", "ctx_ladder") and not skip_ctx_ladder:
        if resume and not force and phase_done(prior, "ctx_ladder"):
            result["phases"]["ctx_ladder"] = prior["phases"]["ctx_ladder"]  # type: ignore[index]
            log("resume: skip ctx_ladder")
        else:
            result["phases"]["ctx_ladder"] = run_ctx_ladder_phase(profile_id, force=force)

    if only_phase in ("all", "shelf") and not skip_shelf:
        if resume and phase_done(prior, "shelf"):
            result["phases"]["shelf"] = prior["phases"]["shelf"]  # type: ignore[index]
        else:
            result["phases"]["shelf"] = run_shelf_phase(path)

    phases = result["phases"]
    if phases.get("golden", {}).get("status") != "ok":
        result["status"] = "failed"
    elif any(
        phases.get(p, {}).get("status") == "failed"
        for p in ("kv_sweep", "ctx_ladder", "shelf")
        if p in phases
    ):
        result["status"] = "partial"
    else:
        result["status"] = "complete"
    return result


def write_report(report: dict[str, Any]) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2) + "\n")


def workflow(
    *,
    only: set[str] | None = None,
    all_models: bool = False,
    skip_shelf: bool = False,
    skip_kv_sweep: bool = False,
    skip_ctx_ladder: bool = False,
    resume: bool = False,
    force: bool = False,
    only_phase: str = "all",
    dry_run: bool = False,
) -> dict[str, Any]:
    golden_map = load_golden_map()
    targets = []
    if all_models:
        for path in sorted(golden_map):
            if path in SKIP_INVENTORY:
                continue
            targets.append((path, golden_map[path]))
    elif only:
        for path in sorted(only):
            prof = golden_map.get(path)
            if not prof:
                log(f"WARN no golden profile for {path}")
                continue
            targets.append((path, prof))
    else:
        raise SystemExit("specify --only path[,path] or --all")

    prior_by_path: dict[str, dict[str, Any]] = {}
    if resume and REPORT_FILE.is_file():
        prior = json.loads(REPORT_FILE.read_text())
        for entry in prior.get("models") or []:
            p = str(entry.get("inventory_path") or "")
            if p:
                prior_by_path[p] = entry

    plan = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "bench_standard": "2.0",
        "fill_ratio": 0.75,
        "layers": ["golden", "kv_sweep", "ctx_ladder", "shelf"],
        "targets": [{"path": p, "profile": prof} for p, prof in targets],
    }
    log(f"PLAN {json.dumps(plan, indent=2)}")

    if dry_run:
        return plan

    report: dict[str, Any] = {
        **plan,
        "models": [],
    }

    for path, profile_id in targets:
        if path in SKIP_INVENTORY:
            report["models"].append(
                {"inventory_path": path, "status": "skipped", "reason": "load_blocked"}
            )
            write_report(report)
            continue
        entry = process_model(
            path,
            profile_id,
            skip_shelf=skip_shelf,
            skip_kv_sweep=skip_kv_sweep,
            skip_ctx_ladder=skip_ctx_ladder,
            resume=resume,
            force=force,
            only_phase=only_phase,
            prior=prior_by_path.get(path),
        )
        report["models"].append(entry)
        write_report(report)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    complete = sum(1 for m in report["models"] if m.get("status") == "complete")
    partial = sum(1 for m in report["models"] if m.get("status") == "partial")
    failed = sum(1 for m in report["models"] if m.get("status") == "failed")
    report["summary"] = {"complete": complete, "partial": partial, "failed": failed, "total": len(report["models"])}
    write_report(report)
    run([SPARK, "models", "inventory"], timeout=300)
    log(f"DONE complete={complete} partial={partial} failed={failed}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Full golden workflow (golden + kv sweep + ctx ladder)")
    parser.add_argument("--only", help="Comma-separated inventory paths")
    parser.add_argument("--all", action="store_true", help="All models in golden-recipes.yaml")
    parser.add_argument("--skip-shelf", action="store_true")
    parser.add_argument("--skip-kv-sweep", action="store_true")
    parser.add_argument("--skip-ctx-ladder", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Skip phases already ok in report")
    parser.add_argument("--force", action="store_true", help="Re-run kv sweep / ctx ladder")
    parser.add_argument(
        "--only-phase",
        choices=["all", "golden", "kv_sweep", "ctx_ladder", "shelf"],
        default="all",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    only = {x.strip() for x in args.only.split(",")} if args.only else None
    if not only and not args.all:
        parser.error("use --only <paths> or --all")

    report = workflow(
        only=only,
        all_models=args.all,
        skip_shelf=args.skip_shelf,
        skip_kv_sweep=args.skip_kv_sweep,
        skip_ctx_ladder=args.skip_ctx_ladder,
        resume=args.resume,
        force=args.force,
        only_phase=args.only_phase,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(json.dumps(report, indent=2))
        return 0
    summary = report.get("summary") or {}
    print(json.dumps({"report": str(REPORT_FILE), "summary": summary}, indent=2))
    return 0 if summary.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
