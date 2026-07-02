#!/usr/bin/env python3
"""Portable Benchmaster intel worker — runs Harbor on Mac/techno, model on Sparky.

Config: ~/.config/sparkbench/worker.yaml (or env vars).

  spark_base: http://sparky.vimba-turtle.ts.net
  gateway_url: http://sparky.vimba-turtle.ts.net:9000/v1
  worker_id: macbook-air
  benchmark: terminal-bench@2.1
  agent: terminus-2
  harbor_timeout_s: 7200
  poll_interval_s: 30
  n_concurrent: 1

Env overrides: SPARK_BENCHMASTER_URL, SPARK_GATEWAY_URL, BENCHMASTER_WORKER_ID

Usage:
  python3 spark-benchmaster-worker.py --once     # claim one job if available
  python3 spark-benchmaster-worker.py --loop     # poll until stopped
  python3 spark-benchmaster-worker.py status     # show available intel jobs
"""
from __future__ import annotations

import argparse
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


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.is_file():
        raw = config_path.read_text()
        if yaml is not None:
            cfg = yaml.safe_load(raw) or {}
        else:
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, val = line.split(":", 1)
                cfg[key.strip()] = val.strip().strip('"').strip("'")
    spark_base = os.environ.get("SPARK_BENCHMASTER_URL") or cfg.get("spark_base") or "http://sparky"
    gateway = os.environ.get("SPARK_GATEWAY_URL") or cfg.get("gateway_url") or f"{spark_base.rstrip('/')}:9000/v1"
    return {
        "spark_base": spark_base.rstrip("/"),
        "gateway_url": gateway.rstrip("/"),
        "worker_id": os.environ.get("BENCHMASTER_WORKER_ID") or cfg.get("worker_id") or "intel-worker",
        "benchmark": cfg.get("benchmark") or "terminal-bench@2.1",
        "agent": cfg.get("agent") or "terminus-2",
        "harbor_timeout_s": int(cfg.get("harbor_timeout_s") or 7200),
        "poll_interval_s": int(cfg.get("poll_interval_s") or 30),
        "n_concurrent": int(cfg.get("n_concurrent") or 1),
        "openai_api_key": os.environ.get("OPENAI_API_KEY") or cfg.get("openai_api_key") or "local",
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

    def claim(self, job_id: str, *, lease_secs: int = 7200) -> dict[str, Any]:
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


def log(msg: str) -> None:
    print(msg, flush=True)


def wait_prereq(client: SparkClient, job_id: str, *, timeout_s: int = 3600) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
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
        return metrics
    m = re.search(r"pass[_ -]?rate[:=\s]+([0-9.]+)", text, re.I)
    if m:
        metrics["pass_rate"] = float(m.group(1))
    return metrics


def run_harbor(
    *,
    dataset: str,
    agent: str,
    model: str,
    gateway_url: str,
    api_key: str,
    n_concurrent: int,
    task_limit: int | None,
    timeout_s: int,
    work_dir: Path,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
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
    ]
    if task_limit is not None:
        cmd.extend(["-l", str(task_limit)])

    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", api_key)

    log(f"RUN: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        cwd=str(work_dir),
        env=env,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    metrics = parse_harbor_metrics(combined)
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "harbor_returncode": proc.returncode,
        "harbor_log_tail": combined[-8000:],
        **metrics,
    }


def run_job(client: SparkClient, cfg: dict[str, Any], job: dict[str, Any]) -> None:
    job_id = str(job["id"])
    log(f"claiming {job_id} profile={job.get('profile_id')}")
    claim = client.claim(job_id)
    if not claim.get("ok"):
        log(f"claim failed: {claim.get('error')}")
        return

    try:
        log(f"waiting for Sparky prereq {job_id}…")
        ready = wait_prereq(client, job_id, timeout_s=3600)
        served = str(ready.get("served_name") or claim.get("served_name") or job.get("profile_id"))
        dataset = str(claim.get("dataset") or job.get("harness") or cfg["benchmark"])
        agent = str(claim.get("agent") or cfg["agent"])
        task_limit = claim.get("task_limit")
        if task_limit is None:
            task_limit = job.get("task_limit")

        model = f"openai/{served}"
        work_dir = Path.home() / ".cache" / "sparkbench" / "harbor" / job_id
        client.renew(job_id, extend_secs=cfg["harbor_timeout_s"])

        result = run_harbor(
            dataset=dataset,
            agent=agent,
            model=model,
            gateway_url=cfg["gateway_url"],
            api_key=str(cfg["openai_api_key"]),
            n_concurrent=int(cfg["n_concurrent"]),
            task_limit=int(task_limit) if task_limit is not None else None,
            timeout_s=int(cfg["harbor_timeout_s"]),
            work_dir=work_dir,
        )
        result["agent"] = agent
        result["dataset"] = dataset
        result["model"] = model
        result["gateway_url"] = cfg["gateway_url"]

        log(f"complete {job_id} ok={result.get('ok')} pass_rate={result.get('pass_rate')}")
        done = client.complete(job_id, result)
        if not done.get("ok"):
            log(f"complete API error: {done.get('error')}")
    except Exception as exc:
        log(f"job {job_id} failed: {exc}")
        try:
            client.complete(
                job_id,
                {"ok": False, "error": str(exc)[:500]},
            )
        except Exception:
            client.release(job_id, reason=str(exc)[:200])


def cmd_status(client: SparkClient) -> int:
    data = client.available()
    print(json.dumps(data, indent=2))
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
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="List claimable intel jobs on Sparky")
    sub.add_parser("once", help="Claim and run one job if available")
    sub.add_parser("loop", help="Poll until interrupted")

    args = parser.parse_args()
    cfg = load_config(args.config)
    client = SparkClient(cfg["spark_base"], str(cfg["worker_id"]))

    if args.cmd == "status":
        return cmd_status(client)
    if args.cmd == "once":
        return cmd_once(client, cfg)
    if args.cmd == "loop":
        return cmd_loop(client, cfg)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
