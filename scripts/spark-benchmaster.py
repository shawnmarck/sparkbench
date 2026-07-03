#!/opt/spark/venv/bin/python3
"""Benchmaster — queue engine for perf sweeps with pause/abort/yield control.

Storage:
  run/benchmaster/queue.yaml
  run/benchmaster/events.jsonl
  run/benchmaster/runs/<job_id>/

Job types:
  ctx_ladder, kv_sweep, golden_workflow, perf_sweep  — Sparky GPU worker
  intel_eval — remote worker (Mac/techno) over Tailscale + Harbor
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path("/opt/spark")
RUN_DIR = ROOT / "run" / "benchmaster"
QUEUE_FILE = RUN_DIR / "queue.yaml"
EVENTS_FILE = RUN_DIR / "events.jsonl"
LOG_FILE = ROOT / "logs" / "benchmaster.log"
PY = ROOT / "venv/bin/python3"
SPARK = "/usr/local/bin/spark"

JOB_TYPES = frozenset({"ctx_ladder", "kv_sweep", "golden_workflow", "perf_sweep", "intel_eval"})
GPU_JOB_TYPES = frozenset({"ctx_ladder", "kv_sweep", "golden_workflow", "perf_sweep"})
PERF_SWEEP_PHASES = ("golden_workflow", "kv_sweep", "ctx_ladder")
DEFAULT_INTEL_LEASE_SECS = 28800
MAX_INTEL_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_INTEL_ARTIFACT_TOTAL_BYTES = 25 * 1024 * 1024
HARNESS_DATASETS: dict[str, str] = {
    "terminal-bench@2.1": "terminal-bench/terminal-bench-2-1",
}
RESULTS_FILE = ROOT / "data" / "benchmaster-results.yaml"

_QUEUE_LOCK = threading.RLock()
_WORKER_LOCK = threading.Lock()
_ACTIVE_PROC: subprocess.Popen[str] | None = None
_WORKER_THREAD: threading.Thread | None = None
_SHUTDOWN = False
_INTEL_PREREQ_LOCK = threading.Lock()
_RUNNING_JOB_ID: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    line = f"[{utc_now()}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def emit_agent_event(payload: dict[str, Any]) -> None:
    print(f"AGENT_BENCHMASTER_EVENT {json.dumps(payload, separators=(',', ':'))}", flush=True)


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    os.replace(tmp, path)


def default_control() -> dict[str, Any]:
    return {
        "mode": "paused",
        "current_job_id": None,
        "stop_after_current": False,
        "abort_requested": False,
        "schedule": {
            "enabled": False,
            "start_hour": 23,
            "end_hour": 7,
        },
        "updated_at": utc_now(),
    }


def default_queue() -> dict[str, Any]:
    return {
        "version": "1.0",
        "updated_at": utc_now(),
        "control": default_control(),
        "items": [],
    }


def load_queue() -> dict[str, Any]:
    if not QUEUE_FILE.is_file():
        return default_queue()
    data = yaml.safe_load(QUEUE_FILE.read_text()) or {}
    if not isinstance(data, dict):
        return default_queue()
    data.setdefault("version", "1.0")
    data.setdefault("items", [])
    data.setdefault("control", default_control())
    if not isinstance(data["items"], list):
        data["items"] = []
    return data


def save_queue(data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now()
    _atomic_write_yaml(QUEUE_FILE, data)


def append_event(event: str, **fields: Any) -> dict[str, Any]:
    row = {"ts": utc_now(), "event": event, **fields}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    emit_agent_event(row)
    return row


def new_job_id() -> str:
    return f"bm-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"


def find_job(items: list[dict[str, Any]], job_id: str) -> dict[str, Any] | None:
    for item in items:
        if str(item.get("id")) == job_id:
            return item
    return None


def schedule_allows(ctrl: dict[str, Any]) -> bool:
    sched = ctrl.get("schedule") or {}
    if not sched.get("enabled"):
        return True
    start = int(sched.get("start_hour", 23))
    end = int(sched.get("end_hour", 7))
    hour = datetime.now().hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def inference_down() -> None:
    try:
        subprocess.run(
            [SPARK, "inference", "down"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
        )
    except Exception as exc:
        log(f"WARN inference down: {exc}")


def _set_active_proc(proc: subprocess.Popen[str] | None) -> None:
    global _ACTIVE_PROC
    with _WORKER_LOCK:
        _ACTIVE_PROC = proc


def _terminate_active() -> None:
    with _WORKER_LOCK:
        proc = _ACTIVE_PROC
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def run_cmd(
    cmd: list[str],
    *,
    timeout: int = 86400,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    with _QUEUE_LOCK:
        abort = bool(load_queue().get("control", {}).get("abort_requested"))
    if abort:
        raise RuntimeError("abort requested before start")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(cwd or ROOT),
        env=env,
    )
    _set_active_proc(proc)
    lines: list[str] = []
    deadline = time.time() + timeout
    try:
        assert proc.stdout is not None
        while True:
            if time.time() > deadline:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, timeout)
            with _QUEUE_LOCK:
                abort = bool(load_queue().get("control", {}).get("abort_requested"))
            if abort:
                proc.terminate()
                raise RuntimeError("abort requested")
            line = proc.stdout.readline()
            if line:
                lines.append(line)
                if on_line:
                    on_line(line.rstrip("\n"))
            elif proc.poll() is not None:
                break
            else:
                time.sleep(0.2)
        rc = proc.wait(timeout=5)
    finally:
        _set_active_proc(None)

    out = "".join(lines)
    return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")


def _job_run_dir(job_id: str) -> Path:
    d = RUN_DIR / "runs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_golden_bench():
    spec = importlib.util.spec_from_file_location(
        "spark_golden_bench", ROOT / "scripts" / "spark-golden-bench.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_golden_cell_phase(
    profile_id: str,
    *,
    job_id: str,
    on_line: Callable[[str], None],
) -> dict[str, Any]:
    """Bench golden cell for profile_id (perf_sweep phase — not inventory golden map)."""
    gb = _load_golden_bench()
    ctxmod = gb.load_ctxmod()
    recipe = gb.load_recipe(profile_id)
    golden_ctx, kv = gb.golden_ctx_and_kv(recipe, ctxmod)
    on_line(f"golden cell: profile={profile_id} ctx={golden_ctx} kv={kv}")
    progress_path = _job_run_dir(job_id) / gb.LIVE_PROBE_FILE
    row = gb.probe_cell(
        profile_id,
        recipe,
        ctx=golden_ctx,
        kv=kv,
        progress_path=progress_path,
        phase="golden_workflow",
    )
    on_line(json.dumps(row, indent=2))
    if row.get("status") != "ok":
        return {
            "phase": "golden_workflow",
            "ok": False,
            "error": row.get("error") or f"probe status={row.get('status')}",
            "cell": row,
        }
    gb.merge_bench_matrix(profile_id, golden_cell=row, skip_site_publish=True)
    return {
        "phase": "golden_workflow",
        "returncode": 0,
        "ok": True,
        "cell": row,
    }


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def harness_dataset(harness: str) -> str:
    return HARNESS_DATASETS.get(harness, harness)


def _resolve_served_name(profile_id: str) -> str:
    gb = _load_golden_bench()
    recipe = gb.load_recipe(profile_id)
    return str(recipe.get("served_name") or profile_id)


def _gpu_busy(data: dict[str, Any]) -> bool:
    cid = (data.get("control") or {}).get("current_job_id")
    return bool(cid)


def _reap_expired_intel_claims() -> None:
    now = datetime.now(timezone.utc)
    changed = False
    with _QUEUE_LOCK:
        data = load_queue()
        ctrl = data.get("control") or {}
        for item in data.get("items") or []:
            if str(item.get("type")) != "intel_eval":
                continue
            if str(item.get("state")) != "running":
                continue
            expires = _parse_ts(item.get("lease_expires_at"))
            if expires is None or now <= expires:
                continue
            job_id = str(item.get("id"))
            log(f"intel lease expired — requeue {job_id} (was {item.get('claimed_by')})")
            item["state"] = "queued"
            item["claimed_by"] = None
            item["claimed_at"] = None
            item["lease_expires_at"] = None
            item["prereq"] = {"status": "pending", "updated_at": utc_now()}
            item["progress"] = {
                "phase": None,
                "step": 0,
                "total_steps": 1,
                "message": "queued (lease expired)",
                "updated_at": utc_now(),
            }
            if ctrl.get("current_job_id") == job_id:
                ctrl["current_job_id"] = None
            changed = True
        if changed:
            save_queue(data)
    if changed:
        inference_down()
        append_event("intel_lease_reaped")


def _intel_prereq_thread(job_id: str, profile_id: str) -> None:
    gb = _load_golden_bench()
    run_dir = _job_run_dir(job_id)
    probe_path = run_dir / gb.LIVE_PROBE_FILE
    substeps = [
        {"id": "down", "label": "Stop prior inference", "state": "pending"},
        {"id": "up", "label": "Load model (inference up)", "state": "pending"},
        {"id": "ready", "label": "Wait for engine ready", "state": "pending"},
    ]

    def tick(step_id: str, state: str, detail: str | None = None) -> None:
        for row in substeps:
            if row["id"] == step_id:
                row["state"] = state
                if detail:
                    row["detail"] = detail
        gb.write_live_probe(probe_path, substeps, phase="prereq", extra={"profile_id": profile_id})

    prereq: dict[str, Any] = {"status": "loading", "started_at": utc_now()}
    _update_job(job_id, prereq=prereq)
    try:
        ctxmod = gb.load_ctxmod()
        recipe = gb.load_recipe(profile_id)
        golden_ctx, kv = gb.golden_ctx_and_kv(recipe, ctxmod)
        port = int(recipe.get("port") or 8000)
        served = str(recipe.get("served_name") or profile_id)
        prereq.update({"ctx": golden_ctx, "kv": kv, "port": port, "served_name": served})
        _update_job(job_id, prereq={**prereq, "updated_at": utc_now()})

        tick("down", "running")
        inference_down()
        tick("down", "done")
        tick("up", "running", f"ctx={golden_ctx} kv={kv}")
        up = subprocess.run(
            [
                SPARK,
                "inference",
                "up",
                profile_id,
                "--ctx",
                str(golden_ctx),
                "--kv",
                kv,
            ],
            capture_output=True,
            text=True,
            timeout=3600,
            cwd=str(ROOT),
        )
        if up.returncode != 0:
            tick("up", "failed", (up.stderr or up.stdout or "failed")[-120:])
            raise RuntimeError((up.stderr or up.stdout or "inference up failed")[-500:])
        tick("up", "done")

        timeout = 7200 if golden_ctx >= 1_048_576 else 3600 if golden_ctx >= 524_288 else 1800 if golden_ctx >= 262144 else 1200 if golden_ctx >= 131072 else 900
        tick("ready", "running", f"up to {timeout}s")
        if not gb.wait_ready(port, expected_ctx=golden_ctx, timeout=timeout):
            tick("ready", "failed", f"timeout {timeout}s")
            raise RuntimeError(f"model not ready at ctx={golden_ctx} kv={kv} within {timeout}s")
        tick("ready", "done", f"ctx={golden_ctx}")

        _update_job(
            job_id,
            prereq={
                **prereq,
                "status": "ready",
                "ready_at": utc_now(),
                "updated_at": utc_now(),
            },
            progress={
                "phase": "harbor",
                "step": 1,
                "total_steps": 1,
                "message": "model ready — waiting for Harbor worker",
                "updated_at": utc_now(),
            },
        )
        append_event("intel_prereq_ready", job_id=job_id, profile_id=profile_id)
    except Exception as exc:
        err = str(exc)[:500]
        log(f"intel prereq failed {job_id}: {err}")
        _update_job(
            job_id,
            state="failed",
            finished_at=utc_now(),
            error=err,
            prereq={"status": "failed", "error": err, "updated_at": utc_now()},
            progress={
                "phase": None,
                "message": "prereq failed",
                "updated_at": utc_now(),
            },
        )
        with _QUEUE_LOCK:
            data = load_queue()
            ctrl = data.get("control") or {}
            if ctrl.get("current_job_id") == job_id:
                ctrl["current_job_id"] = None
                save_queue(data)
        inference_down()
        append_event("intel_prereq_fail", job_id=job_id, error=err)


def _start_intel_prereq(job_id: str, profile_id: str) -> None:
    with _INTEL_PREREQ_LOCK:
        item = find_job(load_queue()["items"], job_id)
        if not item:
            return
        prereq = item.get("prereq") or {}
        if prereq.get("status") in {"loading", "ready"}:
            return
        thread = threading.Thread(
            target=_intel_prereq_thread,
            args=(job_id, profile_id),
            daemon=True,
            name=f"intel-prereq-{job_id}",
        )
        thread.start()


def claim_job(job_id: str, worker_id: str, *, lease_secs: int | None = None) -> dict[str, Any]:
    if not worker_id:
        raise ValueError("worker_id required")
    lease_secs = int(lease_secs or DEFAULT_INTEL_LEASE_SECS)
    with _QUEUE_LOCK:
        data = load_queue()
        item = find_job(data.get("items") or [], job_id)
        if not item:
            raise ValueError(f"unknown job: {job_id}")
        if str(item.get("type")) != "intel_eval":
            raise ValueError("only intel_eval jobs can be claimed")
        state = str(item.get("state") or "queued")
        if state != "queued":
            raise ValueError(f"job not claimable (state={state})")
        if _gpu_busy(data):
            raise ValueError("gpu_busy — wait for current Sparky job to finish")
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_secs)).isoformat()
        item["state"] = "running"
        item["claimed_by"] = worker_id
        item["claimed_at"] = now
        item["lease_expires_at"] = expires
        item["started_at"] = item.get("started_at") or now
        item["attempts"] = int(item.get("attempts") or 0) + 1
        item["prereq"] = {"status": "pending", "updated_at": now}
        item["progress"] = {
            "phase": "prereq",
            "step": 0,
            "total_steps": 1,
            "message": "claimed — loading model on Sparky",
            "updated_at": now,
        }
        data["control"]["current_job_id"] = job_id
        save_queue(data)
    append_event("intel_claim", job_id=job_id, worker_id=worker_id, lease_secs=lease_secs)
    profile_id = str(item.get("profile_id") or "")
    _start_intel_prereq(job_id, profile_id)
    served = _resolve_served_name(profile_id)
    harness = str(item.get("harness") or "terminal-bench@2.1")
    return {
        "ok": True,
        "job": item,
        "served_name": served,
        "dataset": harness_dataset(harness),
        "harness": harness,
        "agent": str(item.get("agent") or "terminus-2"),
        "task_limit": item.get("task_limit"),
    }


def release_job(job_id: str, worker_id: str, *, reason: str | None = None) -> dict[str, Any]:
    with _QUEUE_LOCK:
        data = load_queue()
        item = find_job(data.get("items") or [], job_id)
        if not item:
            raise ValueError(f"unknown job: {job_id}")
        if str(item.get("type")) != "intel_eval":
            raise ValueError("not an intel_eval job")
        claimed = str(item.get("claimed_by") or "")
        if claimed and claimed != worker_id:
            expires = _parse_ts(item.get("lease_expires_at"))
            if expires is None or datetime.now(timezone.utc) <= expires:
                raise ValueError("job claimed by another worker")
        item["state"] = "queued"
        item["claimed_by"] = None
        item["claimed_at"] = None
        item["lease_expires_at"] = None
        item["prereq"] = {"status": "pending", "updated_at": utc_now()}
        item["progress"] = {
            "phase": None,
            "step": 0,
            "total_steps": 1,
            "message": "queued" + (f" ({reason})" if reason else ""),
            "updated_at": utc_now(),
        }
        ctrl = data.get("control") or {}
        if ctrl.get("current_job_id") == job_id:
            ctrl["current_job_id"] = None
        save_queue(data)
    inference_down()
    append_event("intel_release", job_id=job_id, worker_id=worker_id, reason=reason or "")
    return {"ok": True, "job_id": job_id}


def renew_job_lease(job_id: str, worker_id: str, *, extend_secs: int | None = None) -> dict[str, Any]:
    extend_secs = int(extend_secs or DEFAULT_INTEL_LEASE_SECS)
    with _QUEUE_LOCK:
        data = load_queue()
        item = find_job(data.get("items") or [], job_id)
        if not item:
            raise ValueError(f"unknown job: {job_id}")
        if str(item.get("claimed_by") or "") != worker_id:
            raise ValueError("job not claimed by this worker")
        expires = datetime.now(timezone.utc) + timedelta(seconds=extend_secs)
        item["lease_expires_at"] = expires.isoformat()
        save_queue(data)
    return {"ok": True, "job_id": job_id, "lease_expires_at": item["lease_expires_at"]}


def intel_progress_update(
    job_id: str,
    worker_id: str,
    *,
    stage: str,
    detail: str | None = None,
    harbor_cmd: str | None = None,
    worker_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _QUEUE_LOCK:
        item = find_job(load_queue()["items"], job_id)
        if not item:
            raise ValueError(f"unknown job: {job_id}")
        if str(item.get("claimed_by") or "") != worker_id:
            raise ValueError("job not claimed by this worker")
    run_dir = _job_run_dir(job_id)
    payload: dict[str, Any] = {
        "updated_at": utc_now(),
        "stage": stage,
        "worker_id": worker_id,
    }
    if detail:
        payload["detail"] = detail
    if harbor_cmd:
        payload["harbor_cmd"] = harbor_cmd
    if worker_config:
        payload["worker_config"] = worker_config
    (run_dir / "intel-progress.json").write_text(json.dumps(payload, indent=2) + "\n")
    msg = f"intel {stage}" + (f" — {detail}" if detail else "")
    _update_job(
        job_id,
        progress={
            "phase": "harbor" if stage.startswith("harbor") else "prereq",
            "message": msg,
            "updated_at": utc_now(),
        },
    )
    append_event("intel_progress", job_id=job_id, worker_id=worker_id, stage=stage)
    return {"ok": True, "job_id": job_id, "stage": stage}


def _safe_artifact_name(name: str) -> str:
    name = str(name or "").replace("\\", "/").lstrip("/")
    parts = [p for p in name.split("/") if p and p not in {".", ".."}]
    if not parts:
        raise ValueError("invalid artifact name")
    return "/".join(parts)


def intel_upload_artifacts(
    job_id: str,
    worker_id: str,
    files: dict[str, Any],
) -> dict[str, Any]:
    with _QUEUE_LOCK:
        item = find_job(load_queue()["items"], job_id)
        if not item:
            raise ValueError(f"unknown job: {job_id}")
        if str(item.get("type")) != "intel_eval":
            raise ValueError("not an intel_eval job")
        state = str(item.get("state") or "")
        claimed = str(item.get("claimed_by") or "")
        if state not in {"done", "failed"}:
            if claimed != worker_id:
                raise ValueError("job not claimed by this worker")

    run_dir = _job_run_dir(job_id)
    dest_root = run_dir / "mac-artifacts"
    dest_root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    total_bytes = 0

    for raw_name, payload in (files or {}).items():
        safe_name = _safe_artifact_name(raw_name)
        if isinstance(payload, str):
            encoding = "base64"
            data_b64 = payload
        elif isinstance(payload, dict):
            encoding = str(payload.get("encoding") or "base64")
            data_b64 = str(payload.get("data") or "")
        else:
            raise ValueError(f"invalid payload for {safe_name}")

        try:
            raw = base64.b64decode(data_b64, validate=True)
        except Exception as exc:
            raise ValueError(f"invalid base64 for {safe_name}: {exc}") from exc

        if encoding == "gzip+base64":
            import gzip

            try:
                raw = gzip.decompress(raw)
            except Exception as exc:
                raise ValueError(f"invalid gzip for {safe_name}: {exc}") from exc
        elif encoding != "base64":
            raise ValueError(f"unsupported encoding: {encoding}")

        if len(raw) > MAX_INTEL_ARTIFACT_BYTES:
            raise ValueError(f"{safe_name} exceeds {MAX_INTEL_ARTIFACT_BYTES} byte limit")
        total_bytes += len(raw)
        if total_bytes > MAX_INTEL_ARTIFACT_TOTAL_BYTES:
            raise ValueError(f"artifact batch exceeds {MAX_INTEL_ARTIFACT_TOTAL_BYTES} byte limit")

        dest = dest_root / safe_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        manifest.append(
            {
                "name": safe_name,
                "path": str(dest),
                "bytes": len(raw),
                "encoding": encoding,
            }
        )

    manifest_doc = {
        "updated_at": utc_now(),
        "worker_id": worker_id,
        "job_id": job_id,
        "files": manifest,
        "total_bytes": total_bytes,
    }
    (run_dir / "mac-artifacts.json").write_text(json.dumps(manifest_doc, indent=2) + "\n")
    append_event(
        "intel_artifacts_uploaded",
        job_id=job_id,
        worker_id=worker_id,
        count=len(manifest),
        total_bytes=total_bytes,
    )
    return {"ok": True, "job_id": job_id, "uploaded": manifest, "total_bytes": total_bytes}


def intel_prereq_status(job_id: str) -> dict[str, Any]:
    with _QUEUE_LOCK:
        item = find_job(load_queue()["items"], job_id)
    if not item:
        return {"ok": False, "error": "job not found"}
    prereq = item.get("prereq") or {}
    return {
        "ok": True,
        "job_id": job_id,
        "state": item.get("state"),
        "claimed_by": item.get("claimed_by"),
        "prereq": prereq,
        "served_name": prereq.get("served_name") or _resolve_served_name(str(item.get("profile_id") or "")),
        "dataset": harness_dataset(str(item.get("harness") or "terminal-bench@2.1")),
    }


def _load_results() -> dict[str, Any]:
    if not RESULTS_FILE.is_file():
        return {"version": "1.0", "models": {}}
    data = yaml.safe_load(RESULTS_FILE.read_text()) or {}
    if not isinstance(data, dict):
        return {"version": "1.0", "models": {}}
    data.setdefault("version", "1.0")
    data.setdefault("models", {})
    return data


def _save_results(data: dict[str, Any]) -> None:
    data["updated_at"] = utc_now()
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_yaml(RESULTS_FILE, data)


def _merge_intel_result(job: dict[str, Any], result: dict[str, Any]) -> None:
    profile_id = str(job.get("profile_id") or "")
    inventory_path = str(job.get("inventory_path") or "")
    model_key = inventory_path or profile_id
    harness = str(job.get("harness") or "terminal-bench@2.1")
    agent = str(result.get("agent") or job.get("agent") or "terminus-2")
    quant = str(job.get("quant") or "")

    data = _load_results()
    models = data.setdefault("models", {})
    block = models.setdefault(model_key, {"quants": []})
    quants = block.setdefault("quants", [])
    entry = {
        "quant": quant,
        "profile_id": profile_id,
        "intel": {
            harness.split("@")[0]: {
                "version": harness.split("@")[-1] if "@" in harness else harness,
                "harness": harness,
                "agent": agent,
                "worker_id": result.get("worker_id") or job.get("claimed_by"),
                "pass_rate": result.get("pass_rate"),
                "passed": result.get("passed"),
                "total": result.get("total"),
                "reward_mean": result.get("reward_mean"),
                "harbor_runtime": result.get("harbor_runtime"),
                "primary_exception": result.get("primary_exception"),
                "exception_counts": result.get("exception_counts"),
                "task_ok": result.get("task_ok"),
                "infrastructure_ok": result.get("infrastructure_ok"),
                "timing": result.get("timing"),
                "measured_at": result.get("measured_at") or utc_now(),
                "job_id": job.get("id"),
            }
        },
    }
    replaced = False
    for idx, row in enumerate(quants):
        if str(row.get("profile_id")) == profile_id:
            quants[idx] = {**row, **entry, "intel": {**(row.get("intel") or {}), **entry["intel"]}}
            replaced = True
            break
    if not replaced:
        quants.append(entry)
    _save_results(data)


def complete_intel_job(job_id: str, worker_id: str, result: dict[str, Any]) -> dict[str, Any]:
    with _QUEUE_LOCK:
        data = load_queue()
        item = find_job(data.get("items") or [], job_id)
        if not item:
            raise ValueError(f"unknown job: {job_id}")
        if str(item.get("type")) != "intel_eval":
            raise ValueError("not an intel_eval job")
        if str(item.get("claimed_by") or "") != worker_id:
            raise ValueError("job not claimed by this worker")
        if str(item.get("state")) != "running":
            raise ValueError(f"job not running (state={item.get('state')})")

    run_dir = _job_run_dir(job_id)
    result = dict(result)
    result.setdefault("measured_at", utc_now())
    result.setdefault("worker_id", worker_id)
    result.setdefault("job_id", job_id)
    result.setdefault("profile_id", item.get("profile_id"))
    result.setdefault("harness", item.get("harness"))
    result.setdefault("agent", item.get("agent"))
    (run_dir / "intel-result.json").write_text(json.dumps(result, indent=2) + "\n")

    eval_ok = result.get("task_ok")
    if eval_ok is None:
        eval_ok = not result.get("exception_counts") and (result.get("reward_mean") or 0) > 0
    summary = {
        "job_id": job_id,
        "type": "intel_eval",
        "profile_id": item.get("profile_id"),
        "inventory_path": item.get("inventory_path"),
        "started_at": item.get("started_at"),
        "finished_at": utc_now(),
        "ok": bool(eval_ok),
        "infrastructure_ok": bool(result.get("infrastructure_ok", result.get("harbor_returncode") == 0)),
        "result": result,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    try:
        _merge_intel_result(item, result)
    except Exception as exc:
        log(f"WARN intel results merge {job_id}: {exc}")

    failed = not eval_ok
    fail_err = result.get("error")
    if failed and not fail_err:
        fail_err = result.get("primary_exception") or "intel eval failed"
    _update_job(
        job_id,
        state="failed" if failed else "done",
        finished_at=utc_now(),
        result_ref=str(run_dir / "summary.json"),
        error=fail_err if failed else None,
        progress={
            "phase": None,
            "message": "failed" if failed else "complete",
            "updated_at": utc_now(),
        },
    )
    with _QUEUE_LOCK:
        data = load_queue()
        ctrl = data.get("control") or {}
        if ctrl.get("current_job_id") == job_id:
            ctrl["current_job_id"] = None
            save_queue(data)
    inference_down()
    append_event(
        "intel_complete",
        job_id=job_id,
        worker_id=worker_id,
        ok=not failed,
        pass_rate=result.get("pass_rate"),
    )
    return {"ok": True, "job_id": job_id, "result_ref": str(run_dir / "summary.json")}


def list_available_intel() -> dict[str, Any]:
    _reap_expired_intel_claims()
    with _QUEUE_LOCK:
        data = load_queue()
        gpu_busy = _gpu_busy(data)
        rows = []
        for item in data.get("items") or []:
            if str(item.get("type")) != "intel_eval":
                continue
            if str(item.get("state")) != "queued":
                continue
            rows.append(
                {
                    "id": item.get("id"),
                    "profile_id": item.get("profile_id"),
                    "inventory_path": item.get("inventory_path"),
                    "harness": item.get("harness"),
                    "agent": item.get("agent"),
                    "task_limit": item.get("task_limit"),
                    "note": item.get("note"),
                    "claimable": not gpu_busy,
                }
            )
    return {"ok": True, "gpu_busy": gpu_busy, "jobs": rows}


def _update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    with _QUEUE_LOCK:
        data = load_queue()
        item = find_job(data["items"], job_id)
        if not item:
            return None
        if "progress" in fields and isinstance(fields["progress"], dict):
            progress = dict(item.get("progress") or {})
            progress.update(fields["progress"])
            fields["progress"] = progress
        if "prereq" in fields and isinstance(fields["prereq"], dict):
            prereq = dict(item.get("prereq") or {})
            prereq.update(fields["prereq"])
            fields["prereq"] = prereq
        item.update(fields)
        save_queue(data)
        return item


def _execute_phase(job: dict[str, Any], phase: str) -> dict[str, Any]:
    profile_id = str(job.get("profile_id") or "")
    inventory_path = str(job.get("inventory_path") or "")
    job_id = str(job["id"])
    run_dir = _job_run_dir(job_id)
    phase_log = run_dir / f"{phase}.log"

    def on_line(line: str) -> None:
        with phase_log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    _update_job(
        job_id,
        progress={
            "phase": phase,
            "message": f"running {phase}",
            "updated_at": utc_now(),
        },
    )
    append_event(
        "phase_start",
        job_id=job_id,
        profile_id=profile_id,
        inventory_path=inventory_path,
        phase=phase,
    )

    phase_env = os.environ.copy()
    phase_env["BENCHMASTER_RUN_DIR"] = str(run_dir)

    try:
        if phase == "ctx_ladder":
            r = run_cmd(
                [
                    str(PY),
                    str(ROOT / "scripts/spark-ctx-ladder.py"),
                    profile_id,
                    "--force",
                ],
                timeout=28800,
                on_line=on_line,
                env=phase_env,
            )
        elif phase == "kv_sweep":
            r = run_cmd(
                [str(PY), str(ROOT / "scripts/spark-kv-sweep.py"), profile_id],
                timeout=14400,
                on_line=on_line,
                env=phase_env,
            )
        elif phase == "golden_workflow":
            if not profile_id:
                raise ValueError("golden_workflow requires profile_id")
            result = _run_golden_cell_phase(profile_id, job_id=job_id, on_line=on_line)
            (run_dir / f"{phase}.json").write_text(json.dumps(result, indent=2) + "\n")
            append_event(
                "phase_done",
                job_id=job_id,
                phase=phase,
                ok=result["ok"],
                returncode=result.get("returncode"),
            )
            return result
        else:
            raise ValueError(f"unknown phase {phase}")

        result = {
            "phase": phase,
            "returncode": r.returncode,
            "ok": r.returncode == 0,
            "tail": (r.stdout or "")[-2000:],
        }
        (run_dir / f"{phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        append_event(
            "phase_done",
            job_id=job_id,
            phase=phase,
            ok=result["ok"],
            returncode=r.returncode,
        )
        return result
    except RuntimeError:
        raise
    except Exception as exc:
        result = {"phase": phase, "ok": False, "error": str(exc)[:500]}
        (run_dir / f"{phase}.json").write_text(json.dumps(result, indent=2) + "\n")
        append_event("phase_fail", job_id=job_id, phase=phase, error=str(exc)[:500])
        return result


def _phases_for_job(job: dict[str, Any]) -> list[str]:
    jtype = str(job.get("type") or "")
    if jtype == "intel_eval":
        return []
    if jtype == "perf_sweep":
        return list(PERF_SWEEP_PHASES)
    if jtype in JOB_TYPES:
        return [jtype]
    return []


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    global _RUNNING_JOB_ID
    if str(job.get("type") or "") == "intel_eval":
        raise RuntimeError("intel_eval jobs run on Mac/techno worker — not GPU worker")
    job_id = str(job["id"])
    _RUNNING_JOB_ID = job_id
    try:
        return _run_job_impl(job)
    finally:
        _RUNNING_JOB_ID = None


def _run_job_impl(job: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job["id"])
    phases = _phases_for_job(job)
    run_dir = _job_run_dir(job_id)
    summary: dict[str, Any] = {
        "job_id": job_id,
        "type": job.get("type"),
        "profile_id": job.get("profile_id"),
        "inventory_path": job.get("inventory_path"),
        "started_at": utc_now(),
        "phases": [],
    }

    with _QUEUE_LOCK:
        data = load_queue()
        ctrl = data["control"]
        ctrl["current_job_id"] = job_id
        ctrl["abort_requested"] = False
        save_queue(data)

    item = find_job(load_queue()["items"], job_id)
    if item:
        item["state"] = "running"
        item["started_at"] = item.get("started_at") or utc_now()
        item["attempts"] = int(item.get("attempts") or 0) + 1
        item["progress"] = {
            "phase": phases[0] if phases else None,
            "step": 0,
            "total_steps": len(phases),
            "message": "starting",
            "updated_at": utc_now(),
        }
        with _QUEUE_LOCK:
            q = load_queue()
            qitem = find_job(q["items"], job_id)
            if qitem:
                qitem.update(item)
                save_queue(q)

    append_event(
        "job_start",
        job_id=job_id,
        type=job.get("type"),
        profile_id=job.get("profile_id"),
        inventory_path=job.get("inventory_path"),
        phases=phases,
    )

    aborted = False
    failed = False
    for idx, phase in enumerate(phases):
        with _QUEUE_LOCK:
            if load_queue().get("control", {}).get("abort_requested"):
                aborted = True
                break
        _update_job(
            job_id,
            progress={
                "phase": phase,
                "step": idx + 1,
                "total_steps": len(phases),
                "message": f"phase {idx + 1}/{len(phases)}: {phase}",
                "updated_at": utc_now(),
            },
        )
        try:
            phase_result = _execute_phase(job, phase)
        except RuntimeError as exc:
            if "abort" in str(exc).lower():
                aborted = True
                break
            phase_result = {"phase": phase, "ok": False, "error": str(exc)}
        summary["phases"].append(phase_result)
        if not phase_result.get("ok"):
            failed = True
            break

    inference_down()

    summary["finished_at"] = utc_now()
    summary["aborted"] = aborted
    summary["failed"] = failed and not aborted
    summary["ok"] = not failed and not aborted
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    if aborted:
        state = "queued"
        finished_at = None
    elif failed:
        state = "failed"
        finished_at = utc_now()
    else:
        state = "done"
        finished_at = utc_now()

    err = None
    if failed and summary["phases"]:
        err = summary["phases"][-1].get("error") or summary["phases"][-1].get("tail")

    _update_job(
        job_id,
        state=state,
        finished_at=finished_at,
        result_ref=str(run_dir / "summary.json"),
        progress={
            "phase": None,
            "message": "aborted — requeued" if aborted else ("failed" if failed else "complete"),
            "updated_at": utc_now(),
        },
        error=err,
    )

    with _QUEUE_LOCK:
        data = load_queue()
        ctrl = data["control"]
        ctrl["current_job_id"] = None
        if aborted:
            ctrl["abort_requested"] = False
            ctrl["mode"] = "paused"
            item = find_job(data["items"], job_id)
            if item:
                data["items"] = [item] + [x for x in data["items"] if x.get("id") != job_id]
        if ctrl.get("stop_after_current"):
            ctrl["mode"] = "paused"
            ctrl["stop_after_current"] = False
        save_queue(data)

    append_event(
        "job_done",
        job_id=job_id,
        state=state,
        ok=summary.get("ok"),
        aborted=aborted,
    )
    return summary


def add_job(
    *,
    job_type: str,
    profile_id: str,
    inventory_path: str | None = None,
    quant: str | None = None,
    note: str | None = None,
    front: bool = False,
    harness: str | None = None,
    agent: str | None = None,
    task_limit: int | None = None,
) -> dict[str, Any]:
    if job_type not in JOB_TYPES:
        raise ValueError(f"unsupported job type: {job_type}")
    if not profile_id:
        raise ValueError("profile_id required")

    item: dict[str, Any] = {
        "id": new_job_id(),
        "type": job_type,
        "profile_id": profile_id,
        "inventory_path": inventory_path or "",
        "quant": quant or "",
        "note": note or "",
        "state": "queued",
        "created_at": utc_now(),
        "started_at": None,
        "finished_at": None,
        "attempts": 0,
        "progress": {
            "phase": None,
            "step": 0,
            "total_steps": len(_phases_for_job({"type": job_type})),
            "message": "queued",
            "updated_at": utc_now(),
        },
        "result_ref": None,
        "error": None,
    }
    if job_type == "intel_eval":
        item["harness"] = harness or "terminal-bench@2.1"
        item["agent"] = agent or "terminus-2"
        item["task_limit"] = int(task_limit) if task_limit is not None else None
        item["claimed_by"] = None
        item["claimed_at"] = None
        item["lease_expires_at"] = None
        item["prereq"] = {"status": "pending"}
        item["progress"]["total_steps"] = 1

    with _QUEUE_LOCK:
        data = load_queue()
        if front:
            data["items"].insert(0, item)
        else:
            data["items"].append(item)
        save_queue(data)

    append_event(
        "job_queued",
        job_id=item["id"],
        type=job_type,
        profile_id=profile_id,
        inventory_path=inventory_path,
        front=front,
    )
    if job_type == "intel_eval":
        log(
            f"intel job queued {item['id']} profile={profile_id} — "
            "awaiting Mac/techno worker claim (not picked up by Sparky GPU worker)"
        )
    return item


def reorder_queue(job_ids: list[str]) -> dict[str, Any]:
    with _QUEUE_LOCK:
        data = load_queue()
        by_id = {str(x.get("id")): x for x in data["items"]}
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for jid in job_ids:
            if jid in by_id and jid not in seen:
                ordered.append(by_id[jid])
                seen.add(jid)
        for item in data["items"]:
            jid = str(item.get("id"))
            if jid not in seen:
                ordered.append(item)
        data["items"] = ordered
        save_queue(data)
    append_event("queue_reorder", job_ids=job_ids)
    return {"ok": True, "count": len(ordered)}


def remove_job(job_id: str) -> dict[str, Any]:
    with _QUEUE_LOCK:
        data = load_queue()
        item = find_job(data["items"], job_id)
        if not item:
            raise ValueError(f"unknown job: {job_id}")
        if item.get("state") == "running":
            raise ValueError("cannot remove running job — abort first")
        data["items"] = [x for x in data["items"] if x.get("id") != job_id]
        save_queue(data)
    append_event("job_removed", job_id=job_id)
    return {"ok": True, "job_id": job_id}


def control_action(action: str, **opts: Any) -> dict[str, Any]:
    action = action.strip().lower()
    valid = {
        "pause",
        "resume",
        "stop_after_current",
        "abort_current_requeue_front",
        "shutdown",
    }
    if action not in valid:
        raise ValueError(f"unknown action: {action}")

    global _SHUTDOWN

    with _QUEUE_LOCK:
        data = load_queue()
        ctrl = data["control"]

        if action == "pause":
            ctrl["mode"] = "paused"
            ctrl["stop_after_current"] = False
        elif action == "resume":
            ctrl["mode"] = "running"
            ctrl["abort_requested"] = False
        elif action == "stop_after_current":
            ctrl["stop_after_current"] = True
            if not ctrl.get("current_job_id"):
                ctrl["mode"] = "paused"
                ctrl["stop_after_current"] = False
        elif action == "abort_current_requeue_front":
            ctrl["abort_requested"] = True
            _terminate_active()
        elif action == "shutdown":
            ctrl["mode"] = "stopped"
            ctrl["abort_requested"] = True
            _terminate_active()
            _SHUTDOWN = True

        if "schedule" in opts and isinstance(opts["schedule"], dict):
            ctrl["schedule"] = {**(ctrl.get("schedule") or {}), **opts["schedule"]}

        ctrl["updated_at"] = utc_now()
        save_queue(data)

    append_event("control", action=action, **{k: v for k, v in opts.items() if k != "schedule"})
    if action in {"pause", "shutdown"}:
        inference_down()
    elif action == "stop_after_current" and not load_queue()["control"].get("current_job_id"):
        inference_down()
    return status()


def _queue_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        st = str(item.get("state") or "queued")
        counts[st] = counts.get(st, 0) + 1
        jtype = str(item.get("type") or "")
        if jtype == "intel_eval" and st == "queued":
            counts["intel_queued"] = counts.get("intel_queued", 0) + 1
        elif jtype in GPU_JOB_TYPES and st == "queued":
            counts["gpu_queued"] = counts.get("gpu_queued", 0) + 1
    return counts


def _attention_job(items: list[dict[str, Any]], current: dict[str, Any] | None) -> dict[str, Any] | None:
    """Surface intel jobs in status when GPU worker is idle but Mac hasn't claimed yet."""
    if current is not None:
        return None
    for item in items:
        if str(item.get("type")) != "intel_eval":
            continue
        st = str(item.get("state") or "")
        if st not in {"queued", "running"}:
            continue
        row = dict(item)
        row["live_phases"] = live_phases_for_job(item)
        if st == "queued":
            row["awaiting"] = "remote_worker"
        return row
    return None


def live_phases_for_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Phase checklist for portal — reads completed phase JSON from run dir."""
    gb = _load_golden_bench()
    jtype = str(job.get("type") or "")
    job_id = str(job.get("id") or "")
    run_dir = RUN_DIR / "runs" / job_id
    progress = job.get("progress") or {}
    current_phase = str(progress.get("phase") or "")
    job_state = str(job.get("state") or "queued")

    labels = {
        "golden_workflow": "Golden cell",
        "kv_sweep": "KV sweep",
        "ctx_ladder": "Context ladder",
        "prereq": "Load model (Sparky)",
        "harbor": "Harbor eval",
    }
    hints = {
        "golden_workflow": "Load + bench @ golden ctx/kv (75% fill)",
        "kv_sweep": "KV dtype comparison at golden ctx",
        "ctx_ladder": "Tok/s at each context rung",
        "prereq": "spark inference up on Sparky",
        "harbor": "Remote worker — terminal-bench tasks",
    }

    if jtype == "intel_eval":
        phase_ids = ["prereq", "harbor"]
    else:
        phase_ids = _phases_for_job(job)

    rows: list[dict[str, Any]] = []
    for phase in phase_ids:
        entry: dict[str, Any] = {
            "id": phase,
            "label": labels.get(phase, phase.replace("_", " ")),
            "hint": hints.get(phase, ""),
            "state": "pending",
        }
        if jtype == "intel_eval" and phase == "prereq":
            prereq = job.get("prereq") or {}
            ps = str(prereq.get("status") or "pending")
            if ps == "ready":
                entry["state"] = "done"
                entry["detail"] = f"ctx={prereq.get('ctx')} kv={prereq.get('kv')}"
            elif ps == "loading":
                entry["state"] = "running"
                probe = gb.read_live_probe(run_dir / gb.LIVE_PROBE_FILE)
                if probe and probe.get("substeps"):
                    entry["substeps"] = probe["substeps"]
            elif ps == "failed":
                entry["state"] = "failed"
                entry["detail"] = str(prereq.get("error") or "failed")[:120]
            elif ps == "pending" and job_state == "queued":
                entry["detail"] = "Waiting for Mac worker claim"
            rows.append(entry)
            continue
        if jtype == "intel_eval" and phase == "harbor":
            prereq = job.get("prereq") or {}
            if str(prereq.get("status")) == "ready":
                if current_phase == "harbor" or job_state == "running":
                    entry["state"] = "running"
                    if job.get("claimed_by"):
                        entry["detail"] = f"worker {job['claimed_by']}"
            elif job_state == "queued":
                entry["detail"] = "spark-benchmaster-worker.py once on Mac"
            rows.append(entry)
            continue

        path = run_dir / f"{phase}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                data = {}
            if data.get("ok"):
                entry["state"] = "done"
                cell = data.get("cell") or {}
                if cell.get("tok_s") is not None:
                    entry["detail"] = (
                        f"{cell['tok_s']} tok/s · ctx {cell.get('ctx')} · "
                        f"fill ~{cell.get('fill_estimated') or cell.get('fill_target')}"
                    )
            else:
                entry["state"] = "failed"
                entry["detail"] = str(data.get("error") or data.get("tail") or "failed")[:120]
        elif phase == current_phase:
            entry["state"] = "running"
            msg = str(progress.get("message") or "")
            if msg:
                entry["detail"] = msg
        rows.append(entry)

    probe_live = gb.read_live_probe(run_dir / gb.LIVE_PROBE_FILE) if job_id else None
    if probe_live and probe_live.get("substeps"):
        for entry in rows:
            if entry.get("state") == "running":
                entry["substeps"] = probe_live.get("substeps")
                if probe_live.get("rung_ctx"):
                    entry["detail"] = (
                        f"rung {probe_live.get('rung_index')}/{probe_live.get('rung_total')} "
                        f"ctx={probe_live.get('rung_ctx')}"
                    )
                break
    return rows


def status() -> dict[str, Any]:
    with _QUEUE_LOCK:
        data = load_queue()
    items = data.get("items") or []
    counts = _queue_counts(items)
    current = None
    cid = (data.get("control") or {}).get("current_job_id")
    if cid:
        raw = find_job(items, str(cid))
        if raw:
            current = dict(raw)
            current["live_phases"] = live_phases_for_job(raw)
    attention = _attention_job(items, current)
    intel_avail = list_available_intel()
    return {
        "ok": True,
        "version": data.get("version", "1.0"),
        "updated_at": data.get("updated_at"),
        "control": data.get("control") or default_control(),
        "schedule_open": schedule_allows(data.get("control") or {}),
        "counts": counts,
        "queue_length": len(items),
        "current_job": current,
        "attention_job": attention,
        "intel_claimable": bool(intel_avail.get("jobs")),
        "worker_alive": _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
    }


def list_queue() -> dict[str, Any]:
    with _QUEUE_LOCK:
        data = load_queue()
    return {"ok": True, "control": data.get("control"), "items": data.get("items") or []}


def list_runs(limit: int = 50) -> dict[str, Any]:
    runs_dir = RUN_DIR / "runs"
    rows: list[dict[str, Any]] = []
    if runs_dir.is_dir():
        for path in sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_dir():
                continue
            summary_path = path / "summary.json"
            if summary_path.is_file():
                try:
                    row = json.loads(summary_path.read_text())
                    row["run_dir"] = str(path)
                    rows.append(row)
                except json.JSONDecodeError:
                    continue
            if len(rows) >= limit:
                break
    return {"ok": True, "runs": rows}


def get_run(job_id: str) -> dict[str, Any]:
    run_dir = RUN_DIR / "runs" / job_id
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        return {"ok": False, "error": "run not found"}
    summary = json.loads(summary_path.read_text())
    with _QUEUE_LOCK:
        item = find_job(load_queue()["items"], job_id)
    artifacts_manifest = run_dir / "mac-artifacts.json"
    artifacts = None
    if artifacts_manifest.is_file():
        try:
            artifacts = json.loads(artifacts_manifest.read_text())
        except json.JSONDecodeError:
            artifacts = None
    return {"ok": True, "job": item, "summary": summary, "run_dir": str(run_dir), "artifacts": artifacts}


def tail_events(since: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    if not EVENTS_FILE.is_file():
        return []
    lines = EVENTS_FILE.read_text().splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines[since:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(rows) >= limit:
            break
    return rows


def _next_gpu_job(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if str(item.get("state")) != "queued":
            continue
        if str(item.get("type")) not in GPU_JOB_TYPES:
            continue
        return item
    return None


def worker_loop() -> None:
    log("benchmaster worker started")
    append_event("worker_start")
    while not _SHUTDOWN:
        try:
            with _QUEUE_LOCK:
                data = load_queue()
                ctrl = data.get("control") or default_control()
                mode = str(ctrl.get("mode") or "paused")

            if mode != "running":
                time.sleep(2)
                continue

            if not schedule_allows(ctrl):
                time.sleep(30)
                continue

            cid = ctrl.get("current_job_id")
            if cid:
                if _RUNNING_JOB_ID == str(cid):
                    time.sleep(2)
                    continue
                with _QUEUE_LOCK:
                    data = load_queue()
                    orphan = find_job(data.get("items") or [], str(cid))
                if orphan and str(orphan.get("state")) == "running":
                    if str(orphan.get("type")) == "intel_eval":
                        # Claimed by Mac/techno worker — prereq thread runs on API process.
                        time.sleep(5)
                        continue
                    log(f"resuming orphaned job {cid}")
                    run_job(orphan)
                    continue
                log(f"WARN clearing stale current_job_id={cid}")
                with _QUEUE_LOCK:
                    data = load_queue()
                    data["control"]["current_job_id"] = None
                    save_queue(data)
                continue

            _reap_expired_intel_claims()

            with _QUEUE_LOCK:
                data = load_queue()
                job = _next_gpu_job(data.get("items") or [])
            if not job:
                time.sleep(5)
                continue

            log(f"running job {job.get('id')} type={job.get('type')} profile={job.get('profile_id')}")
            run_job(job)
        except Exception as exc:
            log(f"worker error: {exc}")
            append_event("worker_error", error=str(exc)[:500])
            time.sleep(5)

    log("benchmaster worker stopped")
    append_event("worker_stop")


def start_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = threading.Thread(target=worker_loop, daemon=True, name="benchmaster-worker")
        _WORKER_THREAD.start()


def api_dispatch(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]] | None:
    body = body or {}
    path = path.split("?", 1)[0].rstrip("/") or "/"

    if method == "GET" and path == "/api/benchmaster/status":
        return 200, status()
    if method == "GET" and path == "/api/benchmaster/queue":
        return 200, list_queue()
    if method == "GET" and path == "/api/benchmaster/runs":
        return 200, list_runs(limit=50)
    if method == "GET" and path.startswith("/api/benchmaster/runs/"):
        job_id = path.split("/api/benchmaster/runs/", 1)[1]
        if not job_id or "/" in job_id:
            return 400, {"ok": False, "error": "invalid run id"}
        return 200, get_run(job_id)
    if method == "GET" and path == "/api/benchmaster/events":
        return 200, {"ok": True, "events": tail_events()}
    if method == "GET" and path == "/api/benchmaster/jobs/available":
        return 200, list_available_intel()

    job_action = None
    job_id = None
    if path.startswith("/api/benchmaster/jobs/"):
        rest = path[len("/api/benchmaster/jobs/") :]
        if "/" in rest:
            job_id, job_action = rest.split("/", 1)
        elif rest:
            job_id = rest
            job_action = ""

    if method == "GET" and job_id and job_action == "prereq":
        payload = intel_prereq_status(job_id)
        return (404, payload) if not payload.get("ok") else (200, payload)

    if method == "POST" and job_id and job_action == "progress":
        try:
            return 200, intel_progress_update(
                job_id,
                str(body.get("worker_id") or ""),
                stage=str(body.get("stage") or "unknown"),
                detail=body.get("detail"),
                harbor_cmd=body.get("harbor_cmd"),
                worker_config=body.get("worker_config"),
            )
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}

    if method == "POST" and job_id and job_action == "claim":
        worker_id = str(body.get("worker_id") or "")
        try:
            return 200, claim_job(
                job_id,
                worker_id,
                lease_secs=body.get("lease_secs"),
            )
        except ValueError as exc:
            msg = str(exc)
            code = 409 if "gpu_busy" in msg or "not claimable" in msg else 400
            return code, {"ok": False, "error": msg}

    if method == "POST" and job_id and job_action == "release":
        try:
            return 200, release_job(
                job_id,
                str(body.get("worker_id") or ""),
                reason=body.get("reason"),
            )
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}

    if method == "POST" and job_id and job_action == "renew":
        try:
            return 200, renew_job_lease(
                job_id,
                str(body.get("worker_id") or ""),
                extend_secs=body.get("extend_secs"),
            )
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}

    if method == "POST" and job_id and job_action == "upload":
        try:
            return 200, intel_upload_artifacts(
                job_id,
                str(body.get("worker_id") or ""),
                body.get("files") or {},
            )
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}

    if method == "POST" and job_id and job_action == "complete":
        try:
            return 200, complete_intel_job(
                job_id,
                str(body.get("worker_id") or ""),
                body.get("result") or body,
            )
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}

    if method == "POST" and path == "/api/benchmaster/queue/add":
        try:
            item = add_job(
                job_type=str(body.get("type") or "perf_sweep"),
                profile_id=str(body.get("profile_id") or ""),
                inventory_path=body.get("inventory_path"),
                quant=body.get("quant"),
                note=body.get("note"),
                front=bool(body.get("front")),
                harness=body.get("harness"),
                agent=body.get("agent"),
                task_limit=body.get("task_limit"),
            )
            return 200, {"ok": True, "item": item}
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}

    if method == "POST" and path == "/api/benchmaster/queue/reorder":
        ids = body.get("job_ids") or body.get("ids") or []
        if not isinstance(ids, list):
            return 400, {"ok": False, "error": "job_ids must be a list"}
        return 200, reorder_queue([str(x) for x in ids])

    if method == "POST" and path == "/api/benchmaster/queue/remove":
        job_id = str(body.get("job_id") or "")
        if not job_id:
            return 400, {"ok": False, "error": "job_id required"}
        try:
            return 200, remove_job(job_id)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}

    if method == "POST" and path == "/api/benchmaster/control":
        action = str(body.get("action") or "")
        if not action:
            return 400, {"ok": False, "error": "action required"}
        try:
            sched = body.get("schedule")
            opts = {"schedule": sched} if isinstance(sched, dict) else {}
            return 200, control_action(action, **opts)
        except ValueError as exc:
            return 400, {"ok": False, "error": str(exc)}

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmaster queue engine")
    parser.add_argument("--worker", action="store_true", help="Run worker loop (foreground)")
    parser.add_argument("--status", action="store_true", help="Print status JSON")
    parser.add_argument("--init", action="store_true", help="Initialize queue file")
    args = parser.parse_args()

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if args.init or not QUEUE_FILE.is_file():
        save_queue(default_queue())
        log("initialized queue")

    if args.status:
        print(json.dumps(status(), indent=2))
        return 0

    if args.worker:
        with _QUEUE_LOCK:
            data = load_queue()
            if data["control"].get("mode") == "paused":
                data["control"]["mode"] = "running"
                save_queue(data)
        worker_loop()
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
