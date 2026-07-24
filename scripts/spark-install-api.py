#!/usr/bin/env python3
"""Privileged SparkBench install agent (LAN / loopback only).

Allowlisted spark-install targets with job + SSE log streaming.
Mutations require X-Spark-Install-Token matching /etc/spark/install-token.
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(os.environ.get("SPARK_ROOT", "/opt/spark")).resolve()
TOKEN_PATH = Path(os.environ.get("SPARK_INSTALL_TOKEN_PATH", "/etc/spark/install-token"))
JOBS_DIR = ROOT / "run" / "install-jobs"
PORT = int(os.environ.get("SPARK_INSTALL_API_PORT", "8771"))
BIND = os.environ.get("SPARK_INSTALL_API_BIND", "127.0.0.1")

ALLOWLIST: dict[str, dict[str, Any]] = {
    "quickstart": {
        "label": "Quickstart",
        "description": "Bootstrap + core (portal, APIs, CLI)",
        "argv": ["quickstart"],
    },
    "core": {
        "label": "Core",
        "description": "Portal, APIs, CLI, model inventory",
        "argv": ["core"],
    },
    "gateway": {
        "label": "Gateway",
        "description": "OpenAI gateway on :9000",
        "argv": ["gateway"],
    },
    "openwebui": {
        "label": "Open WebUI",
        "description": "Chat UI add-on",
        "argv": ["openwebui"],
    },
    "hermes": {
        "label": "Spark operator",
        "description": "Hermes-powered embedded operator with OOB inference",
        "argv": ["hermes"],
    },
    "nas": {
        "label": "NAS shelf",
        "description": "CIFS model shelf mount",
        "argv": ["nas"],
    },
    "engine": {
        "label": "Engine",
        "description": "Install one inference engine",
        "argv": ["engine"],
        "allowed_args": {"eugr", "llama", "ds4"},
        "requires_args": True,
    },
}

_LOCK = threading.Lock()
_ACTIVE: dict[str, Any] | None = None
_JOBS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_token() -> str:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return token


def token_ok(handler: BaseHTTPRequestHandler) -> bool:
    expected = ensure_token()
    got = handler.headers.get("X-Spark-Install-Token", "").strip()
    return bool(got) and secrets.compare_digest(got, expected)


def probe(url: str, timeout: float = 1.5) -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def install_status() -> dict[str, Any]:
    services = [
        ("portal", "http://127.0.0.1/"),
        ("gpu-api", "http://127.0.0.1:8765/api/gpu"),
        ("shelf-api", "http://127.0.0.1:8766/api/shelf/status"),
        ("inference-api", "http://127.0.0.1:8767/api/inference/status?lite=1"),
        ("hf-api", "http://127.0.0.1:8768/api/hf/status"),
        ("activity", "http://127.0.0.1:8769/api/activity?window=1h"),
        ("benchmaster", "http://127.0.0.1:8770/api/benchmaster/status"),
        ("install-api", f"http://127.0.0.1:{PORT}/api/install/status"),
        ("operator", "http://127.0.0.1:8772/api/operator/status"),
        ("gateway", "http://127.0.0.1:9000/v1/models"),
    ]
    out = []
    for name, url in services:
        if name == "install-api":
            out.append({"name": name, "healthy": True})
            continue
        healthy = probe(url)
        detail = None if healthy else "unreachable"
        out.append({"name": name, "healthy": healthy, "detail": detail})
    with _LOCK:
        active = dict(_ACTIVE) if _ACTIVE else None
    return {
        "ok": True,
        "services": out,
        "install_token_configured": TOKEN_PATH.is_file(),
        "active_job": active,
    }


def list_targets() -> list[dict[str, Any]]:
    items = []
    for tid, meta in ALLOWLIST.items():
        if tid == "engine":
            for eng in sorted(meta["allowed_args"]):
                items.append(
                    {
                        "id": tid,
                        "label": f"Engine: {eng}",
                        "description": f"Install {eng} inference engine",
                        "args": [eng],
                    }
                )
        else:
            items.append(
                {
                    "id": tid,
                    "label": meta["label"],
                    "description": meta["description"],
                    "args": [],
                }
            )
    return items


def job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "target": job["target"],
        "args": job.get("args") or [],
        "state": job["state"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "exit_code": job.get("exit_code"),
        "log_path": job.get("log_path"),
    }


def start_job(target: str, args: list[str]) -> dict[str, Any]:
    global _ACTIVE
    meta = ALLOWLIST.get(target)
    if not meta:
        raise ValueError(f"target not allowlisted: {target}")
    args = [str(a) for a in args]
    if meta.get("requires_args"):
        if not args or args[0] not in meta["allowed_args"]:
            raise ValueError(f"engine requires one of: {sorted(meta['allowed_args'])}")
        argv = list(meta["argv"]) + [args[0]]
    else:
        if args:
            raise ValueError(f"{target} does not accept args")
        argv = list(meta["argv"])

    spark_install = ROOT / "install" / "spark-install"
    if not spark_install.is_file():
        raise RuntimeError(f"missing {spark_install}")

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    log_path = JOBS_DIR / f"{job_id}.log"
    job = {
        "id": job_id,
        "target": target,
        "args": args,
        "state": "running",
        "started_at": _now(),
        "finished_at": None,
        "exit_code": None,
        "log_path": str(log_path),
        "pid": None,
    }

    with _LOCK:
        if _ACTIVE and _ACTIVE.get("state") == "running":
            raise RuntimeError("another install job is already running")
        _JOBS[job_id] = job
        _ACTIVE = job_public(job)

    def runner() -> None:
        global _ACTIVE
        cmd = ["sudo", "-n", "bash", str(spark_install), *argv]
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"==> install {' '.join(argv)} {_now()}\n")
            log.flush()
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=str(ROOT),
                    start_new_session=True,
                )
            except Exception as exc:
                log.write(f"failed to spawn: {exc}\n")
                with _LOCK:
                    job["state"] = "failed"
                    job["exit_code"] = 127
                    job["finished_at"] = _now()
                    _ACTIVE = job_public(job)
                return
            with _LOCK:
                job["pid"] = proc.pid
            code = proc.wait()
            with _LOCK:
                job["exit_code"] = code
                job["finished_at"] = _now()
                job["state"] = "succeeded" if code == 0 else "failed"
                _ACTIVE = job_public(job)

    threading.Thread(target=runner, daemon=True).start()
    return job_public(job)


def cancel_job(job_id: str) -> dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job["state"] != "running":
            return job_public(job)
        pid = job.get("pid")
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                subprocess.run(["sudo", "-n", "kill", "-TERM", f"-{pid}"], check=False)
        job["state"] = "cancelled"
        job["finished_at"] = _now()
        global _ACTIVE
        _ACTIVE = job_public(job)
        return job_public(job)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def send_json(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/api/install/status":
            send_json(self, 200, install_status())
            return
        if route == "/api/install/targets":
            send_json(self, 200, {"ok": True, "targets": list_targets()})
            return

        if route.startswith("/api/install/jobs/") and route.endswith("/stream"):
            job_id = route.split("/")[4]
            self._stream_log(job_id)
            return

        if route.startswith("/api/install/jobs/"):
            job_id = route.rsplit("/", 1)[-1]
            with _LOCK:
                job = _JOBS.get(job_id)
            if not job:
                send_json(self, 404, {"ok": False, "error": "job not found"})
                return
            send_json(self, 200, job_public(job))
            return

        send_json(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not token_ok(self):
            send_json(self, 401, {"ok": False, "error": "invalid or missing install token"})
            return
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        try:
            body = read_json(self)
        except json.JSONDecodeError:
            send_json(self, 400, {"ok": False, "error": "invalid json"})
            return

        if route == "/api/install/jobs":
            target = str(body.get("target") or "").strip()
            args = body.get("args") or []
            if not isinstance(args, list):
                send_json(self, 400, {"ok": False, "error": "args must be a list"})
                return
            try:
                job = start_job(target, args)
            except ValueError as exc:
                send_json(self, 400, {"ok": False, "error": str(exc)})
                return
            except RuntimeError as exc:
                send_json(self, 409, {"ok": False, "error": str(exc)})
                return
            send_json(self, 200, job)
            return

        if route.startswith("/api/install/jobs/") and route.endswith("/cancel"):
            job_id = route.split("/")[4]
            try:
                job = cancel_job(job_id)
            except KeyError:
                send_json(self, 404, {"ok": False, "error": "job not found"})
                return
            send_json(self, 200, job)
            return

        send_json(self, 404, {"ok": False, "error": "not found"})

    def _stream_log(self, job_id: str) -> None:
        with _LOCK:
            job = _JOBS.get(job_id)
        if not job:
            send_json(self, 404, {"ok": False, "error": "job not found"})
            return
        log_path = Path(job["log_path"])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        pos = 0
        idle = 0
        while idle < 120:
            if log_path.is_file():
                data = log_path.read_text(encoding="utf-8", errors="replace")
                if len(data) > pos:
                    chunk = data[pos:]
                    pos = len(data)
                    for line in chunk.splitlines():
                        self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    idle = 0
            with _LOCK:
                state = _JOBS.get(job_id, {}).get("state")
            if state and state != "running":
                self.wfile.write(f"event: done\ndata: {state}\n\n".encode("utf-8"))
                self.wfile.flush()
                break
            time.sleep(0.5)
            idle += 1


def main() -> None:
    ensure_token()
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"spark-install-api listening on {BIND}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
