#!/usr/bin/env python3
"""Portable Benchmaster intel worker — runs Harbor on Mac/techno, model on Sparky.

Config: ~/.config/sparkbench/worker.yaml (or env vars).

  spark_base: http://sparky.vimba-turtle.ts.net
  gateway_url: http://sparky.vimba-turtle.ts.net:9000/v1
  worker_id: macbook-air
  benchmark: terminal-bench@2.1
  agent: terminus-2
  harbor_timeout_s: 14400
  poll_interval_s: 30
  n_concurrent: 1

Env overrides: SPARK_BENCHMASTER_URL, SPARK_GATEWAY_URL, BENCHMASTER_WORKER_ID

Usage:
  python3 spark-benchmaster-worker.py once      # claim one job if available
  python3 spark-benchmaster-worker.py --once    # same (compat alias)
  python3 spark-benchmaster-worker.py upload-only --job-id bm-...
  python3 spark-benchmaster-worker.py loop      # poll until stopped
  python3 spark-benchmaster-worker.py status    # list claimable jobs
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "sparkbench" / "worker.yaml"
WORKER_VERSION = "20260703f"


def parse_harbor_job_results(work_dir: Path) -> dict[str, Any]:
    """Aggregate pass/total from Harbor job result.json when present."""
    jobs_root = work_dir / "jobs"
    if not jobs_root.is_dir():
        return {}
    job_dirs = sorted(jobs_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for job_dir in job_dirs:
        if not job_dir.is_dir():
            continue
        result_path = job_dir / "result.json"
        if not result_path.is_file():
            continue
        try:
            doc = json.loads(result_path.read_text())
        except json.JSONDecodeError:
            continue
        stats = doc.get("stats") or {}
        total = stats.get("n_total_trials")
        if total is None:
            total = (stats.get("n_completed_trials") or 0) + (stats.get("n_errored_trials") or 0)
        total = int(total or 0)
        if total <= 0:
            continue
        passed = 0
        for eval_block in (stats.get("evals") or {}).values():
            reward_stats = (eval_block or {}).get("reward_stats") or {}
            rewards = (reward_stats.get("reward") or {})
            for reward_val, trial_ids in rewards.items():
                try:
                    if float(reward_val) > 0:
                        passed += len(trial_ids or [])
                except (TypeError, ValueError):
                    pass
        if passed == 0 and stats.get("n_errored_trials") is not None:
            passed = max(0, total - int(stats.get("n_errored_trials") or 0))
        metrics: dict[str, Any] = {
            "passed": passed,
            "total": total,
            "pass_rate": round(passed / max(total, 1), 4),
        }
        if stats.get("n_errored_trials") is not None:
            metrics["errored"] = int(stats.get("n_errored_trials"))
        return metrics
    return {}


def normalize_harbor_task_name(name: str, harness: str = "terminal-bench@2.1") -> str:
    name = str(name or "").strip()
    if not name or "/" in name:
        return name
    org = str(harness or "terminal-bench@2.1").split("@", 1)[0]
    return f"{org}/{name}"


def normalize_harbor_task_names(names: list[str] | None, harness: str) -> list[str]:
    if isinstance(names, str):
        names = [names]
    out: list[str] = []
    for raw in names or []:
        norm = normalize_harbor_task_name(raw, harness)
        if norm and norm not in out:
            out.append(norm)
    return out


def _clean_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _normalize_base_url(raw: str) -> str:
    url = _clean_str(raw, "http://sparky")
    if not url:
        url = "http://sparky"
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = f"http://{url.lstrip('/')}"
    return url.rstrip("/")


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.is_file():
        raw = config_path.read_text()
        if yaml is not None:
            loaded = yaml.safe_load(raw) or {}
            cfg = {str(k): v for k, v in loaded.items()}
        else:
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, val = line.split(":", 1)
                val = val.split("#", 1)[0].strip().strip('"').strip("'")
                cfg[key.strip()] = val
    spark_base = _normalize_base_url(
        os.environ.get("SPARK_BENCHMASTER_URL") or cfg.get("spark_base") or "http://sparky"
    )
    gateway_raw = os.environ.get("SPARK_GATEWAY_URL") or cfg.get("gateway_url") or ""
    gateway = _normalize_base_url(gateway_raw) if _clean_str(gateway_raw) else f"{spark_base}:9000/v1"
    return {
        "spark_base": spark_base,
        "gateway_url": gateway,
        "worker_id": _clean_str(os.environ.get("BENCHMASTER_WORKER_ID") or cfg.get("worker_id"), "intel-worker"),
        "benchmark": _clean_str(cfg.get("benchmark"), "terminal-bench@2.1"),
        "agent": _clean_str(cfg.get("agent"), "terminus-2"),
        "harbor_timeout_s": int(_clean_str(cfg.get("harbor_timeout_s"), "14400") or 14400),
        "poll_interval_s": int(_clean_str(cfg.get("poll_interval_s"), "30") or 30),
        "n_concurrent": int(_clean_str(cfg.get("n_concurrent"), "1") or 1),
        "openai_api_key": _clean_str(os.environ.get("OPENAI_API_KEY") or cfg.get("openai_api_key"), "local"),
        "prereq_wait_s": int(_clean_str(cfg.get("prereq_wait_s"), "10800") or 10800),
        "intel_lease_secs": int(_clean_str(cfg.get("intel_lease_secs"), "28800") or 28800),
        "timeout_multiplier": float(_clean_str(cfg.get("timeout_multiplier"), "8") or 8),
        "agent_timeout_multiplier": float(_clean_str(cfg.get("agent_timeout_multiplier"), "8") or 8),
    }


class SparkClient:
    def __init__(self, base: str, worker_id: str) -> None:
        self.base = base.rstrip("/")
        self.worker_id = worker_id

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: int = 120,
    ) -> dict[str, Any]:
        url = f"{self.base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if "control characters" in str(reason).lower() or "InvalidURL" in type(reason).__name__:
                raise RuntimeError(
                    f"invalid spark_base URL {self.base!r} — check ~/.config/sparkbench/worker.yaml "
                    "(no trailing spaces; use http://hostname)"
                ) from exc
            raise
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode()
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                parsed = {"ok": False, "error": payload or exc.reason}
            parsed.setdefault("ok", False)
            parsed["_http_status"] = exc.code
            return parsed

    def available(self) -> dict[str, Any]:
        return self._request("GET", "/api/benchmaster/jobs/available")

    def claim(self, job_id: str, *, lease_secs: int = 28800) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/benchmaster/jobs/{job_id}/claim",
            {"worker_id": self.worker_id, "lease_secs": lease_secs},
        )

    def prereq(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/benchmaster/jobs/{job_id}/prereq")

    def renew(self, job_id: str, *, extend_secs: int = 7200) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/benchmaster/jobs/{job_id}/renew",
            {"worker_id": self.worker_id, "extend_secs": extend_secs},
        )

    def release(self, job_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/benchmaster/jobs/{job_id}/release",
            {"worker_id": self.worker_id, "reason": reason},
        )

    def complete(self, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/benchmaster/jobs/{job_id}/complete",
            {"worker_id": self.worker_id, "result": result},
        )

    def progress(
        self,
        job_id: str,
        *,
        stage: str,
        detail: str | None = None,
        harbor_cmd: str | None = None,
        worker_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"worker_id": self.worker_id, "stage": stage}
        if detail:
            body["detail"] = detail
        if harbor_cmd:
            body["harbor_cmd"] = harbor_cmd
        if worker_config:
            body["worker_config"] = worker_config
        return self._request("POST", f"/api/benchmaster/jobs/{job_id}/progress", body)

    def upload(self, job_id: str, files: dict[str, dict[str, str]]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/benchmaster/jobs/{job_id}/upload",
            {"worker_id": self.worker_id, "files": files},
            timeout=300,
        )


def log(msg: str) -> None:
    print(msg, flush=True)


def wait_prereq(
    client: SparkClient,
    job_id: str,
    *,
    timeout_s: int = 10800,
    lease_secs: int = 28800,
    renew_every_s: int = 600,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_renew = 0.0
    while time.time() < deadline:
        if time.time() - last_renew >= renew_every_s:
            client.renew(job_id, extend_secs=lease_secs)
            last_renew = time.time()
        st = client.prereq(job_id)
        if not st.get("ok"):
            raise RuntimeError(st.get("error") or "prereq status failed")
        prereq = st.get("prereq") or {}
        status = str(prereq.get("status") or "")
        if status == "ready":
            return st
        if status == "failed":
            raise RuntimeError(prereq.get("error") or "prereq failed on Sparky")
        time.sleep(10)
    raise TimeoutError(f"prereq not ready within {timeout_s}s")


def parse_harbor_metrics(text: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    m = re.search(r"(\d+)\s*/\s*(\d+)\s+passed", text, re.I)
    if m:
        metrics["passed"] = int(m.group(1))
        metrics["total"] = int(m.group(2))
        metrics["pass_rate"] = round(int(m.group(1)) / max(int(m.group(2)), 1), 4)
    m = re.search(r"pass[_ -]?rate[:=\s]+([0-9.]+)", text, re.I)
    if m:
        metrics["pass_rate"] = float(m.group(1))
    # Harbor summary tables (unicode box-drawing or ASCII pipes)
    m = re.search(
        r"Trials\s*[|│]\s*Exceptions\s*[|│]\s*Mean[\s\S]*?"
        r"[|│]\s*(\d+)\s*[|│]\s*(\d+)\s*[|│]\s*([0-9.]+)",
        text,
    )
    if m:
        metrics.setdefault("trials", int(m.group(1)))
        metrics.setdefault("exceptions", int(m.group(2)))
        metrics.setdefault("reward_mean", float(m.group(3)))
        if metrics.get("trials") and "total" not in metrics:
            metrics["total"] = int(m.group(1))
        if metrics.get("exceptions") == 0 and metrics.get("reward_mean", 0) > 0:
            metrics.setdefault("passed", 1)
            metrics.setdefault("pass_rate", metrics["reward_mean"])
    m = re.search(
        r"Reward\s*[|│]\s*Count[\s\S]*?[|│]\s*([0-9.]+)\s*[|│]\s*(\d+)",
        text,
    )
    if m:
        metrics.setdefault("reward_mean", float(m.group(1)))
        metrics.setdefault("reward_count", int(m.group(2)))
    exc: dict[str, int] = {}
    for name in ("AgentTimeoutError", "VerifierTimeoutError", "RewardFileNotFoundError"):
        em = re.search(rf"{re.escape(name)}\s*[|│]\s*(\d+)", text)
        if em:
            exc[name] = int(em.group(1))
    if exc:
        metrics["exception_counts"] = exc
        metrics["primary_exception"] = next(iter(exc))
    m = re.search(r"Total runtime:\s*([^\n]+)", text)
    if m:
        metrics["harbor_runtime"] = m.group(1).strip()
    m = re.search(r"(\d+)/(\d+)\s+Mean:\s*([0-9.]+)", text)
    if m:
        metrics.setdefault("trials", int(m.group(2)))
        metrics.setdefault("reward_mean", float(m.group(3)))
    return metrics


def _encode_artifact(raw: bytes, *, gzip_min: int = 65536) -> dict[str, str]:
    if len(raw) >= gzip_min:
        packed = gzip.compress(raw)
        return {"encoding": "gzip+base64", "data": base64.b64encode(packed).decode("ascii")}
    return {"encoding": "base64", "data": base64.b64encode(raw).decode("ascii")}


def collect_harbor_artifacts(work_dir: Path, combined_log: str) -> dict[str, dict[str, str]]:
    """Gather Harbor logs/results from Mac work dir for upload to Sparky."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, str]] = {}

    log_path = work_dir / "harbor-full.log"
    if combined_log:
        log_bytes = combined_log.encode("utf-8", errors="replace")
    elif log_path.is_file():
        log_bytes = log_path.read_bytes()
    else:
        log_bytes = b""
    if log_bytes:
        out["harbor-full.log"] = _encode_artifact(log_bytes)

    jobs_root = work_dir / "jobs"
    if jobs_root.is_dir():
        job_dirs = sorted(jobs_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for job_dir in job_dirs[:3]:
            if not job_dir.is_dir():
                continue
            prefix = f"jobs/{job_dir.name}"
            result_path = job_dir / "result.json"
            if result_path.is_file():
                rel = f"{prefix}/result.json"
                out[rel] = _encode_artifact(result_path.read_bytes())
            for path in sorted(job_dir.rglob("*")):
                if not path.is_file():
                    continue
                if path.name.endswith((".log", ".txt", ".json")) and path.stat().st_size <= 512_000:
                    rel = f"{prefix}/{path.relative_to(job_dir).as_posix()}"
                    if rel not in out:
                        out[rel] = _encode_artifact(path.read_bytes(), gzip_min=999999999)

    return out


def upload_harbor_artifacts(client: SparkClient, job_id: str, work_dir: Path, combined_log: str) -> dict[str, Any]:
    files = collect_harbor_artifacts(work_dir, combined_log)
    if not files:
        return {"ok": True, "uploaded": [], "total_bytes": 0}
    log(f"uploading {len(files)} artifact(s) to Sparky for {job_id}")
    resp = client.upload(job_id, files)
    if not resp.get("ok"):
        log(f"artifact upload warning: {resp.get('error')}")
    else:
        log(f"uploaded {len(resp.get('uploaded') or [])} file(s), {resp.get('total_bytes')} bytes")
    return resp


def run_harbor(
    *,
    dataset: str,
    agent: str,
    model: str,
    gateway_url: str,
    api_key: str,
    n_concurrent: int,
    task_limit: int | None,
    task_names: list[str] | None,
    timeout_s: int,
    work_dir: Path,
    timeout_multiplier: float = 1.0,
    agent_timeout_multiplier: float = 1.0,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    tm = float(timeout_multiplier or 1.0)
    atm = float(agent_timeout_multiplier or 1.0)
    cmd = [
        "harbor",
        "run",
        "-d",
        dataset,
        "-a",
        agent,
        "-m",
        model,
        "--ak",
        f"api_base={gateway_url}",
        "-n",
        str(n_concurrent),
        "--timeout-multiplier",
        str(tm),
        "--agent-timeout-multiplier",
        str(atm),
    ]
    for name in task_names or []:
        if str(name).strip():
            cmd.extend(["--include-task-name", str(name).strip()])
    if task_limit is not None:
        cmd.extend(["-l", str(task_limit)])

    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", api_key)

    harbor_cmd = " ".join(cmd)
    log(f"RUN: {harbor_cmd}")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(work_dir),
            env=env,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        harbor_returncode = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        combined = (exc.stdout or "") + "\n" + (exc.stderr or "")
        harbor_returncode = -1
        timed_out = True
    (work_dir / "harbor-full.log").write_text(combined, encoding="utf-8", errors="replace")
    metrics = parse_harbor_metrics(combined)
    infra_ok = harbor_returncode == 0 and not timed_out
    task_ok = infra_ok and not metrics.get("exception_counts") and (metrics.get("reward_mean") or 0) > 0
    out: dict[str, Any] = {
        "ok": task_ok,
        "infrastructure_ok": infra_ok,
        "task_ok": task_ok,
        "harbor_returncode": harbor_returncode,
        "harbor_cmd": harbor_cmd,
        "harbor_log_tail": combined[-8000:],
        "harbor_log_bytes": len(combined),
        "_harbor_combined": combined,
        **metrics,
    }
    if timed_out:
        out["error"] = f"harbor subprocess timed out after {timeout_s}s"
        out["primary_exception"] = "HarborSubprocessTimeout"
    job_metrics = parse_harbor_job_results(work_dir)
    if job_metrics:
        out.update(job_metrics)
    if out.get("total") and int(out["total"]) > 1:
        out["task_ok"] = infra_ok
        out["ok"] = infra_ok
    return out


def run_job(client: SparkClient, cfg: dict[str, Any], job: dict[str, Any]) -> None:
    job_id = str(job["id"])
    lease_secs = int(job.get("intel_lease_secs") or cfg.get("intel_lease_secs") or 28800)
    harbor_timeout_s = int(job.get("harbor_timeout_s") or cfg.get("harbor_timeout_s") or 14400)
    prereq_wait_s = int(cfg.get("prereq_wait_s") or 10800)
    t0 = time.time()
    log(f"claiming {job_id} profile={job.get('profile_id')}")
    claim = client.claim(job_id, lease_secs=lease_secs)
    if not claim.get("ok"):
        log(f"claim failed: {claim.get('error')}")
        return
    lease_secs = int(claim.get("intel_lease_secs") or job.get("intel_lease_secs") or lease_secs)
    harbor_timeout_s = int(claim.get("harbor_timeout_s") or job.get("harbor_timeout_s") or harbor_timeout_s)
    t_claim = time.time()

    try:
        log(f"waiting for Sparky prereq {job_id} (up to {prereq_wait_s}s)…")
        ready = wait_prereq(
            client,
            job_id,
            timeout_s=prereq_wait_s,
            lease_secs=lease_secs,
        )
        t_prereq = time.time()
        prereq = ready.get("prereq") or {}
        served = str(ready.get("served_name") or claim.get("served_name") or job.get("profile_id"))
        dataset = str(claim.get("dataset") or job.get("harness") or cfg["benchmark"])
        agent = str(claim.get("agent") or cfg["agent"])
        task_limit = claim.get("task_limit")
        if task_limit is None:
            task_limit = job.get("task_limit")
        task_names = claim.get("task_names") or job.get("task_names") or []
        if isinstance(task_names, str):
            task_names = [task_names]
        task_names = normalize_harbor_task_names(
            [str(x) for x in task_names],
            str(claim.get("harness") or job.get("harness") or cfg["benchmark"]),
        )

        model = f"openai/{served}"
        work_dir = Path.home() / ".cache" / "sparkbench" / "harbor" / job_id
        client.renew(job_id, extend_secs=lease_secs)

        log(
            f"prereq ready in {t_prereq - t_claim:.0f}s "
            f"(ctx={prereq.get('ctx')} kv={prereq.get('kv')}) — starting Harbor"
        )
        worker_cfg_audit = {
            "worker_version": WORKER_VERSION,
            "timeout_multiplier": float(cfg.get("timeout_multiplier") or 8),
            "agent_timeout_multiplier": float(cfg.get("agent_timeout_multiplier") or 8),
            "prereq_wait_s": prereq_wait_s,
            "harbor_timeout_s": harbor_timeout_s,
            "intel_lease_secs": lease_secs,
        }
        t_harbor_start = time.time()
        harbor_preview_cmd = (
            f"harbor run -d {dataset} -a {agent} -m openai/{served} "
            f"--timeout-multiplier {worker_cfg_audit['timeout_multiplier']} "
            f"--agent-timeout-multiplier {worker_cfg_audit['agent_timeout_multiplier']} ..."
        )
        client.progress(
            job_id,
            stage="harbor_start",
            detail=f"worker {WORKER_VERSION}",
            harbor_cmd=harbor_preview_cmd,
            worker_config=worker_cfg_audit,
        )
        result = run_harbor(
            dataset=dataset,
            agent=agent,
            model=model,
            gateway_url=cfg["gateway_url"],
            api_key=str(cfg["openai_api_key"]),
            n_concurrent=int(cfg["n_concurrent"]),
            task_limit=int(task_limit) if task_limit is not None else None,
            task_names=[str(x) for x in task_names],
            timeout_s=harbor_timeout_s,
            work_dir=work_dir,
            timeout_multiplier=float(cfg.get("timeout_multiplier") or 8),
            agent_timeout_multiplier=float(cfg.get("agent_timeout_multiplier") or 8),
        )
        t_harbor_end = time.time()
        result["agent"] = agent
        result["dataset"] = dataset
        result["model"] = model
        result["gateway_url"] = cfg["gateway_url"]
        result["worker_version"] = WORKER_VERSION
        result["timing"] = {
            "claim_to_prereq_ready_s": round(t_prereq - t_claim, 1),
            "harbor_elapsed_s": round(t_harbor_end - t_harbor_start, 1),
            "total_elapsed_s": round(t_harbor_end - t0, 1),
            "prereq_started_at": prereq.get("started_at"),
            "prereq_ready_at": prereq.get("ready_at"),
            "timeout_multiplier": float(cfg.get("timeout_multiplier") or 8),
            "agent_timeout_multiplier": float(cfg.get("agent_timeout_multiplier") or 8),
            "prereq_wait_cap_s": prereq_wait_s,
            "harbor_timeout_cap_s": harbor_timeout_s,
        }

        upload_resp = upload_harbor_artifacts(
            client,
            job_id,
            work_dir,
            str(result.pop("_harbor_combined", "") or ""),
        )
        if upload_resp.get("ok"):
            result["artifacts_uploaded"] = upload_resp.get("uploaded")
            result["artifacts_total_bytes"] = upload_resp.get("total_bytes")

        log(
            f"complete {job_id} task_ok={result.get('task_ok')} "
            f"reward={result.get('reward_mean')} exception={result.get('primary_exception')} "
            f"prereq={result['timing']['claim_to_prereq_ready_s']}s "
            f"harbor={result['timing']['harbor_elapsed_s']}s "
            f"total={result['timing']['total_elapsed_s']}s"
        )
        done = client.complete(job_id, result)
        if not done.get("ok"):
            log(f"complete API error: {done.get('error')}")
    except Exception as exc:
        log(f"job {job_id} failed: {exc}")
        work_dir = Path.home() / ".cache" / "sparkbench" / "harbor" / job_id
        fail_body: dict[str, Any] = {"ok": False, "error": str(exc)[:500]}
        if work_dir.is_dir():
            try:
                upload_harbor_artifacts(client, job_id, work_dir, "")
            except Exception as upload_exc:
                log(f"artifact upload on failure: {upload_exc}")
        try:
            client.complete(job_id, fail_body)
        except Exception:
            client.release(job_id, reason=str(exc)[:200])


def cmd_status(client: SparkClient) -> int:
    data = client.available()
    print(json.dumps(data, indent=2))
    return 0


def cmd_upload_only(client: SparkClient, job_id: str) -> int:
    work_dir = Path.home() / ".cache" / "sparkbench" / "harbor" / job_id
    if not work_dir.is_dir():
        log(f"no local harbor cache for {job_id}: {work_dir}")
        return 1
    log(f"backfill upload for {job_id} from {work_dir}")
    resp = upload_harbor_artifacts(client, job_id, work_dir, "")
    if not resp.get("ok"):
        log(f"upload failed: {resp.get('error')}")
        return 1
    return 0


def cmd_once(client: SparkClient, cfg: dict[str, Any]) -> int:
    data = client.available()
    jobs = [j for j in data.get("jobs") or [] if j.get("claimable")]
    if not jobs:
        log("no claimable intel jobs (gpu_busy or queue empty)")
        return 0
    run_job(client, cfg, jobs[0])
    return 0


def cmd_loop(client: SparkClient, cfg: dict[str, Any]) -> int:
    log(f"worker {cfg['worker_id']} polling {cfg['spark_base']} every {cfg['poll_interval_s']}s")
    while True:
        try:
            data = client.available()
            jobs = [j for j in data.get("jobs") or [] if j.get("claimable")]
            if jobs:
                run_job(client, cfg, jobs[0])
            else:
                if data.get("gpu_busy"):
                    log("gpu busy on Sparky — waiting")
                time.sleep(int(cfg["poll_interval_s"]))
        except KeyboardInterrupt:
            log("stopped")
            return 0
        except Exception as exc:
            log(f"loop error: {exc}")
            time.sleep(int(cfg["poll_interval_s"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmaster intel worker (Harbor on Mac/techno)")
    parser.add_argument("--config", type=Path, default=None, help="worker.yaml path")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim and run one job if available (alias for 'once' subcommand)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Poll until interrupted (alias for 'loop' subcommand)",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="List claimable intel jobs on Sparky")
    sub.add_parser("once", help="Claim and run one job if available")
    sub.add_parser("loop", help="Poll until interrupted")
    upload_p = sub.add_parser("upload-only", help="Upload Harbor artifacts for a finished job (backfill)")
    upload_p.add_argument("--job-id", required=True, help="Benchmaster job id")

    args = parser.parse_args()
    cfg = load_config(args.config)
    client = SparkClient(cfg["spark_base"], str(cfg["worker_id"]))

    if args.cmd == "upload-only":
        return cmd_upload_only(client, str(args.job_id))
    if args.once or args.cmd == "once":
        return cmd_once(client, cfg)
    if args.loop or args.cmd == "loop":
        return cmd_loop(client, cfg)
    if args.cmd == "status":
        return cmd_status(client)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
