#!/usr/bin/env python3
"""Spark Operator API: safe Portal v2 bridge to a Hermes agent.

The service is intentionally dependency-free and loopback-bound. Hermes is
invoked with argv arrays (never a shell), and mutations are constrained to the
allowlisted actions in ``execute_action``. The MCP process can only write
proposals into the operator state directory; it cannot execute those actions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(os.environ.get("SPARK_ROOT", "/opt/spark")).resolve()
STATE_DIR = Path(os.environ.get("SPARK_OPERATOR_STATE", ROOT / "run" / "operator"))
HERMES_ROOT = Path(os.environ.get("SPARK_HERMES_ROOT", "/opt/hermes"))
HERMES_DATA = Path(
    os.environ.get("SPARK_HERMES_DATA", HERMES_ROOT / "data" / "spark-bot" / "data")
)
HERMES_CONTAINER = os.environ.get("SPARK_HERMES_CONTAINER", "spark-bot")
HERMES_BIN = os.environ.get("SPARK_HERMES_BIN", "/opt/hermes/.venv/bin/hermes")
DOCKER_BIN = os.environ.get("SPARK_DOCKER_BIN", "/usr/bin/docker")
INSTALL_TOKEN_PATH = Path(
    os.environ.get("SPARK_INSTALL_TOKEN_PATH", "/etc/spark/install-token")
)
PORT = int(os.environ.get("SPARK_OPERATOR_API_PORT", "8772"))
BIND = os.environ.get("SPARK_OPERATOR_API_BIND", "127.0.0.1")
API_BASE = os.environ.get("SPARK_OPERATOR_API_BASE", "http://127.0.0.1").rstrip("/")
MAX_MESSAGE = 12_000
MAX_OUTPUT = 80_000
TURN_TIMEOUT = int(os.environ.get("SPARK_OPERATOR_TURN_TIMEOUT", "900"))
PROPOSAL_TTL = int(os.environ.get("SPARK_OPERATOR_PROPOSAL_TTL", "1800"))
SHARED_UID = int(os.environ.get("SPARK_OPERATOR_SHARED_UID", "-1"))
SHARED_GID = int(os.environ.get("SPARK_OPERATOR_SHARED_GID", "-1"))

TURNS_DIR = STATE_DIR / "turns"
PROPOSALS_DIR = STATE_DIR / "proposals"
GOALS_PATH = STATE_DIR / "goals.json"
AUDIT_PATH = STATE_DIR / "audit.jsonl"

LOCK = threading.RLock()

READ_ONLY_TOOLS = [
    "sparkbench:get_system_status",
    "sparkbench:list_recipes",
    "sparkbench:search_inventory",
    "sparkbench:get_benchmaster_queue",
    "sparkbench:get_recent_activity",
    "sparkbench:get_operator_goals",
    "sparkbench:get_scheduled_checks",
]
PROPOSAL_TOOLS = [
    "sparkbench:propose_inference_switch",
    "sparkbench:propose_inference_stop",
    "sparkbench:propose_benchmaster_control",
    "sparkbench:propose_benchmaster_job",
    "sparkbench:propose_recipe_change",
    "sparkbench:propose_shelf_action",
    "sparkbench:propose_install",
    "sparkbench:propose_goal",
    "sparkbench:propose_scheduled_check",
    "sparkbench:propose_check_action",
]

ACTION_META: dict[str, tuple[str, str]] = {
    "inference_switch": ("Serve inference profile", "Evicts the active engine and loads another profile."),
    "inference_stop": ("Stop inference", "Stops the active GPU inference engine."),
    "benchmaster_control": ("Control Benchmaster", "Changes automated benchmark queue execution."),
    "benchmaster_add": ("Add Benchmaster job", "Adds a benchmark job to the shared queue."),
    "recipe_promote": ("Publish recipe", "Promotes a tested recipe to production."),
    "recipe_discard": ("Discard recipe", "Removes a draft recipe."),
    "recipe_testing": ("Mark recipe testing", "Moves a draft recipe into testing."),
    "shelf_pull": ("Pull from model shelf", "Copies model weights from the NAS shelf."),
    "shelf_push": ("Push to model shelf", "Copies local model weights to the NAS shelf."),
    "shelf_remove": ("Remove local weights", "Deletes the local copy of model weights."),
    "install": ("Run install target", "Runs an allowlisted privileged SparkBench installer."),
    "goal_save": ("Save operator goal", "Creates or updates durable context for Spark."),
    "goal_delete": ("Delete operator goal", "Permanently removes a saved operator goal."),
    "check_create": ("Create scheduled check", "Adds a persistent Hermes cron job."),
    "check_pause": ("Pause scheduled check", "Stops a Hermes cron job from running."),
    "check_resume": ("Resume scheduled check", "Re-enables a Hermes cron job."),
    "check_run": ("Run scheduled check now", "Queues a Hermes cron job for the next scheduler tick."),
    "check_delete": ("Delete scheduled check", "Permanently removes a Hermes cron job."),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_state() -> None:
    for path in (STATE_DIR, TURNS_DIR, PROPOSALS_DIR):
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o770)
            if SHARED_UID >= 0 and SHARED_GID >= 0:
                os.chown(path, SHARED_UID, SHARED_GID)
        except OSError:
            pass


def atomic_json(path: Path, payload: Any) -> None:
    ensure_state()
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o660)
        if SHARED_UID >= 0 and SHARED_GID >= 0:
            os.chown(tmp, SHARED_UID, SHARED_GID)
    except OSError:
        pass
    os.replace(tmp, path)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def public_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return "Spark did not finish before the turn timeout."
    if isinstance(exc, FileNotFoundError):
        return "Hermes or Docker is not installed."
    text = str(exc).strip()
    return text[:1000] if text else exc.__class__.__name__


SECRET_KEYS = {
    "api_key",
    "token",
    "password",
    "authorization",
    "openrouter_api_key",
    "glm_api_key",
    "openai_api_key",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if key.lower() in SECRET_KEYS else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def audit(event: str, **fields: Any) -> None:
    ensure_state()
    record = {"at": now(), "event": event, **redact(fields)}
    line = json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
    with LOCK:
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line)
        try:
            AUDIT_PATH.chmod(0o660)
            if SHARED_UID >= 0 and SHARED_GID >= 0:
                os.chown(AUDIT_PATH, SHARED_UID, SHARED_GID)
        except OSError:
            pass


def run_command(argv: list[str], timeout: int = 60, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def docker_running() -> bool:
    try:
        proc = run_command(
            [DOCKER_BIN, "inspect", "-f", "{{.State.Running}}", HERMES_CONTAINER],
            timeout=8,
        )
        return proc.returncode == 0 and proc.stdout.strip() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return False


def docker_exec(
    args: list[str],
    *,
    timeout: int = 60,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = [DOCKER_BIN, "exec"]
    for key, value in (environment or {}).items():
        argv.extend(["-e", f"{key}={value}"])
    argv.extend([HERMES_CONTAINER, *args])
    proc = run_command(argv, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail[:2000] or f"docker exec exited {proc.returncode}")
    return proc


def api_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
            **(headers or {}),
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_OUTPUT).decode("utf-8", "replace")
            return json.loads(raw) if raw else {"ok": True}
    except HTTPError as exc:
        detail = exc.read(4000).decode("utf-8", "replace")
        try:
            payload = json.loads(detail)
            detail = str(payload.get("error") or payload.get("detail") or detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"{exc.code}: {detail[:1000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"SparkBench API unavailable: {exc.reason}") from exc


def validate_id(value: Any, label: str = "id") -> str:
    text = str(value or "").strip()
    if (
        not re.fullmatch(r"[A-Za-z0-9._:/+-]{1,220}", text)
        or ".." in text
        or text.startswith("/")
        or "//" in text
    ):
        raise ValueError(f"invalid {label}")
    return text


def validate_action(action: str, args: dict[str, Any]) -> dict[str, Any]:
    action = validate_id(action, "action")
    if action not in ACTION_META:
        raise ValueError("action is not allowlisted")
    clean: dict[str, Any] = {}
    if action == "inference_switch":
        clean["profile"] = validate_id(args.get("profile"), "profile")
    elif action == "inference_stop":
        pass
    elif action == "benchmaster_control":
        control = str(args.get("action") or "")
        allowed = {"pause", "resume", "stop_after_current", "abort_current_requeue_front"}
        if control not in allowed:
            raise ValueError("invalid Benchmaster control action")
        clean["action"] = control
    elif action == "benchmaster_add":
        job_type = str(args.get("type") or "")
        allowed = {"perf_sweep", "ctx_ladder", "kv_sweep", "golden_workflow", "intel_eval"}
        if job_type not in allowed:
            raise ValueError("invalid Benchmaster job type")
        clean.update(
            {
                "type": job_type,
                "profile_id": validate_id(args.get("profile_id"), "profile_id"),
                "front": bool(args.get("front", False)),
            }
        )
        if args.get("inventory_path"):
            clean["inventory_path"] = validate_id(args["inventory_path"], "inventory_path")
        if args.get("note"):
            clean["note"] = str(args["note"])[:500]
    elif action in {"recipe_promote", "recipe_discard", "recipe_testing"}:
        clean["profile"] = validate_id(args.get("profile"), "profile")
    elif action in {"shelf_pull", "shelf_push", "shelf_remove"}:
        clean["path"] = validate_id(args.get("path"), "path")
        if action == "shelf_remove":
            clean["force"] = bool(args.get("force", False))
    elif action == "install":
        target = str(args.get("target") or "")
        if target not in {"hermes", "gateway", "openwebui", "nas", "engine"}:
            raise ValueError("install target is not available to Spark")
        install_args = [str(item) for item in (args.get("args") or [])]
        if target == "engine":
            if install_args not in (["eugr"], ["llama"], ["ds4"]):
                raise ValueError("invalid engine install arguments")
        elif install_args:
            raise ValueError("target does not accept arguments")
        clean.update({"target": target, "args": install_args})
    elif action == "goal_save":
        title = str(args.get("title") or "").strip()[:200]
        if not title:
            raise ValueError("goal title is required")
        status = str(args.get("status") or "active")
        if status not in {"active", "paused", "done"}:
            raise ValueError("invalid goal status")
        clean.update(
            {
                "title": title,
                "notes": str(args.get("notes") or "")[:4000],
                "status": status,
            }
        )
        if args.get("goal_id"):
            clean["goal_id"] = validate_id(args["goal_id"], "goal_id")
    elif action == "goal_delete":
        clean["goal_id"] = validate_id(args.get("goal_id"), "goal_id")
    elif action == "check_create":
        name = str(args.get("name") or "").strip()[:120]
        prompt = str(args.get("prompt") or "").strip()[:8000]
        schedule = str(args.get("schedule") or "").strip()[:100]
        if not name or not prompt or not schedule:
            raise ValueError("name, prompt, and schedule are required")
        clean.update({"name": name, "prompt": prompt, "schedule": schedule})
        if args.get("goal_id"):
            clean["goal_id"] = validate_id(args["goal_id"], "goal_id")
    elif action in {"check_pause", "check_resume", "check_run", "check_delete"}:
        clean["job_id"] = validate_id(args.get("job_id"), "job_id")
    return clean


def proposal_summary(action: str, args: dict[str, Any]) -> str:
    label, impact = ACTION_META[action]
    safe_args = ", ".join(f"{key}={value}" for key, value in args.items())
    return f"{label}: {safe_args or 'no parameters'}. {impact}"


def create_proposal(
    action: str,
    args: dict[str, Any],
    *,
    turn_id: str | None = None,
    source: str = "portal",
) -> dict[str, Any]:
    clean = validate_action(action, args)
    proposal_id = uuid.uuid4().hex[:16]
    created = time.time()
    item = {
        "id": proposal_id,
        "turn_id": turn_id,
        "action": action,
        "args": clean,
        "title": ACTION_META[action][0],
        "impact": ACTION_META[action][1],
        "summary": proposal_summary(action, clean),
        "state": "pending",
        "source": source,
        "created_at": now(),
        "expires_at": datetime.fromtimestamp(created + PROPOSAL_TTL, timezone.utc).isoformat(),
        "created_epoch": created,
    }
    atomic_json(PROPOSALS_DIR / f"{proposal_id}.json", item)
    audit("proposal.created", proposal_id=proposal_id, turn_id=turn_id, action=action, args=clean)
    return public_proposal(item)


def public_proposal(item: dict[str, Any]) -> dict[str, Any]:
    copy = {key: value for key, value in item.items() if key != "created_epoch"}
    return redact(copy)


def get_proposal(proposal_id: str) -> dict[str, Any]:
    proposal_id = validate_id(proposal_id, "proposal id")
    item = load_json(PROPOSALS_DIR / f"{proposal_id}.json", None)
    if not isinstance(item, dict):
        raise KeyError(proposal_id)
    return item


def install_token_ok(candidate: str | None) -> bool:
    try:
        expected = INSTALL_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(candidate) and secrets.compare_digest(candidate.strip(), expected)


def hermes_cron(subcommand: str, *args: str, timeout: int = 60) -> str:
    proc = docker_exec([HERMES_BIN, "cron", subcommand, *args], timeout=timeout)
    return proc.stdout.strip()


def read_checks() -> list[dict[str, Any]]:
    jobs_path = HERMES_DATA / "cron" / "jobs.json"
    payload = load_json(jobs_path, {"jobs": []})
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    result = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        prompt = str(job.get("prompt") or "")
        marker = re.match(r"^\[spark-operator(?:\s+goal=([A-Za-z0-9._:+/-]+))?\]\s*", prompt)
        if not marker and not job.get("profile") == "spark-operator":
            continue
        result.append(
            {
                "id": job.get("id"),
                "name": job.get("name") or "Scheduled check",
                "prompt": prompt[marker.end():].strip() if marker else prompt,
                "schedule": job.get("schedule_display")
                or (job.get("schedule") or {}).get("display")
                or (job.get("schedule") or {}).get("expr"),
                "enabled": bool(job.get("enabled", True)),
                "state": job.get("state"),
                "last_status": job.get("last_status"),
                "last_run_at": job.get("last_run_at"),
                "next_run_at": job.get("next_run_at"),
                "goal_id": marker.group(1) if marker and marker.group(1) else job.get("context_from"),
            }
        )
    return result


def execute_action(action: str, args: dict[str, Any]) -> Any:
    clean = validate_action(action, args)
    if action == "inference_switch":
        return api_request("POST", "/api/inference/switch", {"profile": clean["profile"], "confirm": True}, timeout=300)
    if action == "inference_stop":
        return api_request("POST", "/api/inference/down", {"confirm": True}, timeout=120)
    if action == "benchmaster_control":
        return api_request("POST", "/api/benchmaster/control", {"action": clean["action"]})
    if action == "benchmaster_add":
        return api_request("POST", "/api/benchmaster/queue/add", clean)
    if action.startswith("recipe_"):
        verb = action.removeprefix("recipe_")
        return api_request(
            "POST",
            f"/api/inference/recipes/{verb}",
            {"profile": clean["profile"], "confirm": True},
        )
    if action.startswith("shelf_"):
        verb = {"shelf_pull": "pull", "shelf_push": "push", "shelf_remove": "remove-local"}[action]
        return api_request("POST", f"/api/shelf/{verb}", {**clean, "confirm": True}, timeout=300)
    if action == "install":
        token = INSTALL_TOKEN_PATH.read_text(encoding="utf-8").strip()
        return api_request(
            "POST",
            "/api/install/jobs",
            {"target": clean["target"], "args": clean["args"]},
            {"X-Spark-Install-Token": token},
        )
    if action == "goal_save":
        return upsert_goal(clean, clean.get("goal_id"))
    if action == "goal_delete":
        delete_goal(clean["goal_id"])
        return {"ok": True}
    if action == "check_create":
        marker = "[spark-operator"
        if clean.get("goal_id"):
            marker += f" goal={clean['goal_id']}"
        marker += "]"
        check_prompt = clean["prompt"]
        if clean.get("goal_id"):
            goal = next((item for item in load_goals() if item.get("id") == clean["goal_id"]), None)
            if goal:
                check_prompt += (
                    f"\n\nRelated operator goal: {goal.get('title')}"
                    f"\nSuccess notes: {goal.get('notes') or 'none'}"
                )
        output = hermes_cron(
            "create",
            clean["schedule"],
            f"{marker}\n{check_prompt}",
            "--name",
            clean["name"],
            "--deliver",
            "local",
            "--workdir",
            str(ROOT),
        )
        return {"ok": True, "output": output}
    cron_command = {
        "check_pause": "pause",
        "check_resume": "resume",
        "check_run": "run",
        "check_delete": "remove",
    }.get(action)
    if cron_command:
        return {"ok": True, "output": hermes_cron(cron_command, clean["job_id"])}
    raise ValueError("action is not executable")


def confirm_proposal(proposal_id: str, install_token: str | None = None) -> dict[str, Any]:
    with LOCK:
        item = get_proposal(proposal_id)
        if item.get("state") != "pending":
            raise RuntimeError(f"proposal is already {item.get('state')}")
        if item.get("action") == "install" and not install_token_ok(install_token):
            raise RuntimeError("install confirmation requires a valid install token")
        if time.time() > float(item.get("created_epoch") or 0) + PROPOSAL_TTL:
            item["state"] = "expired"
            item["finished_at"] = now()
            atomic_json(PROPOSALS_DIR / f"{proposal_id}.json", item)
            raise RuntimeError("proposal expired")
        item["state"] = "running"
        item["confirmed_at"] = now()
        atomic_json(PROPOSALS_DIR / f"{proposal_id}.json", item)
    audit("proposal.confirmed", proposal_id=proposal_id, action=item["action"])
    try:
        result = execute_action(item["action"], item.get("args") or {})
        item["state"] = "succeeded"
        item["result"] = redact(result)
        audit("proposal.succeeded", proposal_id=proposal_id, action=item["action"])
    except Exception as exc:
        item["state"] = "failed"
        item["error"] = public_error(exc)
        audit("proposal.failed", proposal_id=proposal_id, action=item["action"], error=public_error(exc))
    item["finished_at"] = now()
    atomic_json(PROPOSALS_DIR / f"{proposal_id}.json", item)
    return public_proposal(item)


def cancel_proposal(proposal_id: str) -> dict[str, Any]:
    with LOCK:
        item = get_proposal(proposal_id)
        if item.get("state") == "pending":
            item["state"] = "cancelled"
            item["finished_at"] = now()
            atomic_json(PROPOSALS_DIR / f"{proposal_id}.json", item)
            audit("proposal.cancelled", proposal_id=proposal_id, action=item["action"])
    return public_proposal(item)


def list_proposals(turn_id: str | None = None) -> list[dict[str, Any]]:
    ensure_state()
    items = []
    for path in PROPOSALS_DIR.glob("*.json"):
        item = load_json(path, None)
        if isinstance(item, dict) and (not turn_id or item.get("turn_id") == turn_id):
            items.append(public_proposal(item))
    return sorted(items, key=lambda item: item.get("created_at") or "", reverse=True)


def load_goals() -> list[dict[str, Any]]:
    payload = load_json(GOALS_PATH, {"goals": []})
    return payload.get("goals", []) if isinstance(payload, dict) else []


def save_goals(goals: list[dict[str, Any]]) -> None:
    atomic_json(GOALS_PATH, {"goals": goals, "updated_at": now()})


def upsert_goal(body: dict[str, Any], goal_id: str | None = None) -> dict[str, Any]:
    title = str(body.get("title") or "").strip()[:200]
    if not title:
        raise ValueError("goal title is required")
    status = str(body.get("status") or "active")
    if status not in {"active", "paused", "done"}:
        raise ValueError("invalid goal status")
    with LOCK:
        goals = load_goals()
        existing = next((goal for goal in goals if goal.get("id") == goal_id), None)
        if existing is None:
            existing = {"id": uuid.uuid4().hex[:12], "created_at": now()}
            goals.append(existing)
        existing.update(
            {
                "title": title,
                "notes": str(body.get("notes") or "")[:4000],
                "status": status,
                "updated_at": now(),
            }
        )
        save_goals(goals)
    audit("goal.saved", goal_id=existing["id"], status=status)
    return existing


def delete_goal(goal_id: str) -> None:
    goal_id = validate_id(goal_id, "goal id")
    with LOCK:
        goals = load_goals()
        next_goals = [goal for goal in goals if goal.get("id") != goal_id]
        if len(next_goals) == len(goals):
            raise KeyError(goal_id)
        save_goals(next_goals)
    audit("goal.deleted", goal_id=goal_id)


def provider_settings() -> dict[str, Any]:
    config_path = HERMES_DATA / "config.yaml"
    env_path = HERMES_DATA / ".env"
    text = config_path.read_text(encoding="utf-8", errors="replace") if config_path.is_file() else ""
    provider = ""
    model = ""
    base_url = ""
    in_model = False
    for line in text.splitlines():
        if line and not line.startswith((" ", "\t", "#")):
            in_model = line.strip() == "model:"
            continue
        if not in_model:
            continue
        match = re.match(r"\s+(provider|default|model|base_url):\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip("'\"")
        if key == "provider":
            provider = value
        elif key in {"default", "model"}:
            model = value
        elif key == "base_url":
            base_url = value
    keys: set[str] = set()
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                keys.add(line.split("=", 1)[0].strip())
    return {
        "provider": provider or None,
        "model": model or None,
        "base_url": base_url or None,
        "api_key_configured": bool(
            keys & {"OPENROUTER_API_KEY", "GLM_API_KEY", "OPENAI_API_KEY"}
        ),
        "oauth_configured": (HERMES_DATA / "auth.json").is_file(),
        "dashboard_url": f"http://{os.environ.get('SPARK_HOST', 'sparky')}:9119/",
    }


def hermes_model_catalog(provider: str = "", refresh: bool = False) -> dict[str, Any]:
    provider = provider.strip().lower()
    if provider and not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", provider):
        raise ValueError("invalid provider")
    script = r"""
import json
import sys
from hermes_cli.inventory import build_models_payload, load_picker_context

wanted = sys.argv[1].strip().lower()
refresh = sys.argv[2] == "1"
payload = build_models_payload(
    load_picker_context(),
    include_unconfigured=True,
    picker_hints=True,
    canonical_order=True,
    pricing=True,
    capabilities=True,
    refresh=refresh,
)
providers = []
models = []
selected = None
for item in payload.get("providers", []):
    slug = str(item.get("slug") or "").strip().lower()
    row = {
        "id": slug,
        "name": item.get("name") or slug,
        "authenticated": bool(item.get("authenticated")),
        "auth_type": item.get("auth_type"),
        "key_env": item.get("key_env"),
        "warning": item.get("warning"),
        "source": item.get("source"),
        "total_models": item.get("total_models") or len(item.get("models") or []),
        "is_user_defined": bool(item.get("is_user_defined")),
    }
    providers.append(row)
    if slug != wanted:
        continue
    selected = row
    for model in item.get("models") or []:
        if isinstance(model, str):
            models.append({"id": model, "name": model})
        elif isinstance(model, dict):
            model_id = str(model.get("id") or model.get("model") or model.get("slug") or "")
            if model_id:
                models.append({
                    "id": model_id,
                    "name": model.get("name") or model.get("label") or model_id,
                    "description": model.get("description"),
                    "context_window": model.get("context_window") or model.get("context_length"),
                    "pricing": model.get("pricing"),
                    "capabilities": model.get("capabilities"),
                })
print(json.dumps({
    "provider": wanted or None,
    "selected": selected,
    "providers": providers,
    "models": models,
    "current_provider": payload.get("provider"),
    "current_model": payload.get("model"),
}))
"""
    proc = docker_exec(
        [
            "/opt/hermes/.venv/bin/python",
            "-c",
            script,
            provider,
            "1" if refresh else "0",
        ],
        timeout=180 if refresh else 90,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Hermes returned an invalid model catalog") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Hermes returned an invalid model catalog")
    return result


def update_provider(body: dict[str, Any], install_token: str | None = None) -> dict[str, Any]:
    if body.get("confirm") is not True:
        raise ValueError("provider change requires confirm=true")
    if not install_token_ok(install_token):
        raise ValueError("provider change requires a valid install token")
    provider = str(body.get("provider") or "").strip()
    model = str(body.get("model") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", provider):
        raise ValueError("invalid provider")
    if not model or len(model) > 220:
        raise ValueError("model is required")
    catalog = hermes_model_catalog(provider)
    selected = catalog.get("selected")
    if not isinstance(selected, dict):
        raise ValueError("provider is not available in Hermes")
    if not selected.get("authenticated"):
        raise ValueError("configure this provider in the Hermes dashboard first")
    assignment_script = r"""
import sys
from hermes_cli.web_server import _apply_model_assignment_sync

_apply_model_assignment_sync("main", sys.argv[1], sys.argv[2], "", "", "")
"""
    docker_exec(
        [
            "/opt/hermes/.venv/bin/python",
            "-c",
            assignment_script,
            provider,
            model,
        ],
        timeout=60,
    )
    compose_path = HERMES_ROOT / "sparkbench-compose.yml"
    if not compose_path.is_file():
        raise RuntimeError("managed Hermes compose is missing; run spark-install hermes first")
    compose_env = os.environ.copy()
    data_stat = HERMES_DATA.stat()
    compose_env.update(
        {
            "HERMES_DATA_DIR": str(HERMES_DATA),
            "HERMES_WORKSPACE_DIR": str(HERMES_ROOT / "data" / "workspace"),
            "SPARK_OPERATOR_STATE": str(STATE_DIR),
            "SPARK_ROOT": str(ROOT),
            "HERMES_UID": str(data_stat.st_uid),
            "HERMES_GID": str(data_stat.st_gid),
        }
    )
    restart = run_command(
        [
            DOCKER_BIN,
            "compose",
            "-f",
            str(compose_path),
            "up",
            "-d",
            "--force-recreate",
            "spark-bot",
        ],
        timeout=180,
        env=compose_env,
    )
    if restart.returncode != 0:
        raise RuntimeError((restart.stderr or restart.stdout).strip()[:1000])
    audit(
        "provider.updated",
        provider=provider,
        model=model,
    )
    return provider_settings()


def turn_path(turn_id: str) -> Path:
    return TURNS_DIR / f"{validate_id(turn_id, 'turn id')}.json"


SESSION_RE = re.compile(
    r"(?:session(?:[\s_]+id)?|resume)[\s:=#`*]+([A-Za-z0-9_-]{6,})",
    re.IGNORECASE,
)
SESSION_LINE_RE = re.compile(
    r"(?im)^\s*session(?:[\s_]+id)?\s*:\s*[A-Za-z0-9_-]{6,}\s*$"
)


def run_turn(turn_id: str, message: str, session_id: str | None) -> None:
    path = turn_path(turn_id)
    item = load_json(path, {})
    item.update({"state": "running", "started_at": now()})
    atomic_json(path, item)
    try:
        toolsets = ",".join([*READ_ONLY_TOOLS, *PROPOSAL_TOOLS])
        args = [
            HERMES_BIN,
            "chat",
            "--quiet",
            "--pass-session-id",
            "--source",
            "tool",
            "--max-turns",
            "24",
            "--toolsets",
            toolsets,
            "--skills",
            "sparkbench",
        ]
        if session_id:
            args.extend(["--resume", session_id])
        active_goals = [goal for goal in load_goals() if goal.get("status") == "active"]
        goal_context = ""
        if active_goals:
            lines = [
                f"- {goal.get('title')}: {goal.get('notes') or 'no success notes'}"
                for goal in active_goals[:20]
            ]
            goal_context = "\n\nActive Spark operator goals:\n" + "\n".join(lines)
        args.extend(["--query", f"{message}{goal_context}"])
        proc = docker_exec(
            args,
            timeout=TURN_TIMEOUT,
            environment={
                "SPARK_OPERATOR_TURN_ID": turn_id,
                "SPARK_OPERATOR_STATE": "/operator-state",
                "SPARK_API_BASE": "http://host.docker.internal",
            },
        )
        output = proc.stdout.strip()
        if len(output) > MAX_OUTPUT:
            output = output[-MAX_OUTPUT:]
        session_matches = SESSION_RE.findall(output)
        next_session = session_matches[-1] if session_matches else session_id
        response = SESSION_LINE_RE.sub("", output).strip()
        item.update(
            {
                "state": "succeeded",
                "response": response,
                "session_id": next_session,
                "finished_at": now(),
                "proposals": list_proposals(turn_id),
            }
        )
        audit(
            "turn.succeeded",
            turn_id=turn_id,
            session_id=next_session,
            response_chars=len(output),
            proposals=len(item["proposals"]),
        )
    except Exception as exc:
        item.update({"state": "failed", "error": public_error(exc), "finished_at": now()})
        audit("turn.failed", turn_id=turn_id, error=public_error(exc))
    atomic_json(path, item)


def create_turn(body: dict[str, Any]) -> dict[str, Any]:
    message = str(body.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    if len(message) > MAX_MESSAGE:
        raise ValueError(f"message exceeds {MAX_MESSAGE} characters")
    session_id = body.get("session_id")
    if session_id:
        session_id = validate_id(session_id, "session id")
    turn_id = uuid.uuid4().hex[:16]
    item = {
        "id": turn_id,
        "state": "queued",
        "session_id": session_id,
        "message": message,
        "created_at": now(),
        "response": None,
        "error": None,
        "proposals": [],
    }
    atomic_json(turn_path(turn_id), item)
    audit(
        "turn.created",
        turn_id=turn_id,
        session_id=session_id,
        prompt_chars=len(message),
        prompt_sha256=hashlib.sha256(message.encode("utf-8")).hexdigest(),
    )
    threading.Thread(target=run_turn, args=(turn_id, message, session_id), daemon=True).start()
    return item


def public_turn(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key in {
            "id",
            "state",
            "session_id",
            "message",
            "created_at",
            "started_at",
            "finished_at",
            "response",
            "error",
            "proposals",
        }
    }


def operator_status() -> dict[str, Any]:
    running = docker_running()
    settings = provider_settings()
    return {
        "ok": True,
        "available": running,
        "name": "Spark",
        "runtime": "hermes",
        "container": HERMES_CONTAINER,
        "container_running": running,
        "configured": bool(settings.get("provider") and settings.get("model")),
        "provider": settings.get("provider"),
        "model": settings.get("model"),
        "goals": len([g for g in load_goals() if g.get("status") == "active"]),
        "checks": len(read_checks()),
        "pending_actions": len([p for p in list_proposals() if p.get("state") == "pending"]),
    }


def read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length > 1_000_000:
        raise ValueError("request body too large")
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


def send_json(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    body = json.dumps(redact(payload)).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "SparkOperator/1"

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if route == "/api/operator/status":
                send_json(self, 200, operator_status())
                return
            if route == "/api/operator/settings":
                send_json(self, 200, provider_settings())
                return
            if route == "/api/operator/models":
                provider = (query.get("provider") or [""])[0]
                refresh = (query.get("refresh") or ["0"])[0] in {"1", "true", "yes"}
                send_json(self, 200, hermes_model_catalog(provider, refresh))
                return
            if route == "/api/operator/goals":
                send_json(self, 200, {"goals": load_goals()})
                return
            if route == "/api/operator/checks":
                send_json(self, 200, {"checks": read_checks()})
                return
            if route == "/api/operator/proposals":
                turn_id = (query.get("turn_id") or [None])[0]
                send_json(self, 200, {"proposals": list_proposals(turn_id)})
                return
            if route.startswith("/api/operator/proposals/"):
                proposal_id = route.rsplit("/", 1)[-1]
                send_json(self, 200, public_proposal(get_proposal(proposal_id)))
                return
            if route.startswith("/api/operator/turns/") and route.endswith("/stream"):
                turn_id = route.split("/")[4]
                self.stream_turn(turn_id)
                return
            if route.startswith("/api/operator/turns/"):
                turn_id = route.rsplit("/", 1)[-1]
                item = load_json(turn_path(turn_id), None)
                if not isinstance(item, dict):
                    send_json(self, 404, {"ok": False, "error": "turn not found"})
                    return
                send_json(self, 200, public_turn(item))
                return
            if route == "/api/operator/audit":
                limit = min(max(int((query.get("limit") or ["50"])[0]), 1), 200)
                records = []
                if AUDIT_PATH.is_file():
                    for line in AUDIT_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                send_json(self, 200, {"events": records})
                return
            send_json(self, 404, {"ok": False, "error": "not found"})
        except KeyError:
            send_json(self, 404, {"ok": False, "error": "not found"})
        except (ValueError, RuntimeError) as exc:
            send_json(self, 400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            send_json(self, 500, {"ok": False, "error": public_error(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        try:
            body = read_body(self)
            if route == "/api/operator/turns":
                send_json(self, 202, public_turn(create_turn(body)))
                return
            if route == "/api/operator/goals":
                send_json(self, 200, upsert_goal(body))
                return
            if route.startswith("/api/operator/goals/"):
                parts = route.split("/")
                goal_id = parts[4]
                if route.endswith("/delete"):
                    delete_goal(goal_id)
                    send_json(self, 200, {"ok": True})
                else:
                    send_json(self, 200, upsert_goal(body, goal_id))
                return
            if route == "/api/operator/proposals":
                send_json(
                    self,
                    200,
                    create_proposal(
                        str(body.get("action") or ""),
                        body.get("args") if isinstance(body.get("args"), dict) else {},
                        source="portal",
                    ),
                )
                return
            if route.startswith("/api/operator/proposals/") and route.endswith("/confirm"):
                proposal_id = route.split("/")[4]
                send_json(
                    self,
                    200,
                    confirm_proposal(
                        proposal_id,
                        self.headers.get("X-Spark-Install-Token"),
                    ),
                )
                return
            if route.startswith("/api/operator/proposals/") and route.endswith("/cancel"):
                proposal_id = route.split("/")[4]
                send_json(self, 200, cancel_proposal(proposal_id))
                return
            if route == "/api/operator/settings":
                send_json(
                    self,
                    200,
                    update_provider(body, self.headers.get("X-Spark-Install-Token")),
                )
                return
            send_json(self, 404, {"ok": False, "error": "not found"})
        except json.JSONDecodeError:
            send_json(self, 400, {"ok": False, "error": "invalid JSON"})
        except KeyError:
            send_json(self, 404, {"ok": False, "error": "not found"})
        except (ValueError, RuntimeError) as exc:
            send_json(self, 400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            send_json(self, 500, {"ok": False, "error": public_error(exc)})

    def stream_turn(self, turn_id: str) -> None:
        path = turn_path(turn_id)
        if not path.is_file():
            send_json(self, 404, {"ok": False, "error": "turn not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        previous = ""
        deadline = time.time() + TURN_TIMEOUT + 30
        while time.time() < deadline:
            item = load_json(path, {})
            serialized = json.dumps(public_turn(item), separators=(",", ":"))
            if serialized != previous:
                try:
                    self.wfile.write(f"event: turn\ndata: {serialized}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                previous = serialized
            if item.get("state") in {"succeeded", "failed", "cancelled"}:
                return
            time.sleep(0.5)


def main() -> None:
    ensure_state()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"spark-operator-api listening on http://{BIND}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
