#!/usr/bin/env python3
"""Restricted SparkBench MCP tools for Hermes portal sessions.

This process runs inside the Hermes container. Read tools call the LAN-local
SparkBench HTTP API. Write tools only persist proposals for the Operator API;
they never invoke a mutation endpoint.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

API_BASE = os.environ.get("SPARK_API_BASE", "http://host.docker.internal").rstrip("/")
STATE_DIR = Path(os.environ.get("SPARK_OPERATOR_STATE", "/operator-state"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
TURN_ID = os.environ.get("SPARK_OPERATOR_TURN_ID", "").strip() or None
MAX_RESPONSE = 80_000

mcp = FastMCP("sparkbench")

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


def audit(event: str, **fields: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    record = {"at": now(), "event": event, "turn_id": TURN_ID, **fields}
    with (STATE_DIR / "audit.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def fetch(path: str, timeout: int = 20) -> Any:
    audit("tool.read", path=path)
    request = Request(f"{API_BASE}{path}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE).decode("utf-8", "replace")
            return json.loads(raw) if raw else {"ok": True}
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", "replace")
        raise RuntimeError(f"SparkBench API returned {exc.code}: {detail[:1000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"SparkBench API is unavailable: {exc.reason}") from exc


def valid_id(value: str, label: str) -> str:
    text = str(value or "").strip()
    if (
        not re.fullmatch(r"[A-Za-z0-9._:/+-]{1,220}", text)
        or ".." in text
        or text.startswith("/")
        or "//" in text
    ):
        raise ValueError(f"invalid {label}")
    return text


def write_proposal(action: str, args: dict[str, Any]) -> dict[str, Any]:
    if action not in ACTION_META:
        raise ValueError("action is not allowlisted")
    proposal_id = uuid.uuid4().hex[:16]
    title, impact = ACTION_META[action]
    created = time.time()
    safe_args = ", ".join(f"{key}={value}" for key, value in args.items())
    payload = {
        "id": proposal_id,
        "turn_id": TURN_ID,
        "action": action,
        "args": args,
        "title": title,
        "impact": impact,
        "summary": f"{title}: {safe_args or 'no parameters'}. {impact}",
        "state": "pending",
        "source": "hermes",
        "created_at": now(),
        "expires_at": datetime.fromtimestamp(created + 1800, timezone.utc).isoformat(),
        "created_epoch": created,
    }
    proposals = STATE_DIR / "proposals"
    proposals.mkdir(parents=True, exist_ok=True)
    path = proposals / f"{proposal_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    audit("proposal.created", proposal_id=proposal_id, action=action, args=args)
    return {
        "proposal_id": proposal_id,
        "state": "pending_user_confirmation",
        "title": title,
        "summary": payload["summary"],
        "instruction": "Tell the user this action is waiting for confirmation in the Spark portal. Do not claim it ran.",
    }


@mcp.tool()
def get_system_status() -> dict[str, Any]:
    """Read current GPU, inference, shelf, install, and Benchmaster health."""
    result: dict[str, Any] = {}
    paths = {
        "gpu": "/api/gpu",
        "inference": "/api/inference/status?lite=1",
        "shelf": "/api/shelf/status",
        "install": "/api/install/status",
        "benchmaster": "/api/benchmaster/status",
    }
    for key, path in paths.items():
        try:
            result[key] = fetch(path)
        except RuntimeError as exc:
            result[key] = {"ok": False, "error": str(exc)}
    return result


@mcp.tool()
def list_recipes(query: str = "", lifecycle: str = "", limit: int = 40) -> dict[str, Any]:
    """List inference recipes, optionally filtered by text and lifecycle."""
    payload = fetch("/api/inference/recipes")
    recipes = payload.get("recipes", []) if isinstance(payload, dict) else []
    query_lower = query.strip().lower()
    lifecycle_lower = lifecycle.strip().lower()
    matches = []
    for recipe in recipes:
        if not isinstance(recipe, dict):
            continue
        haystack = " ".join(
            str(recipe.get(key) or "") for key in ("id", "name", "engine", "inventory_path", "notes")
        ).lower()
        if query_lower and query_lower not in haystack:
            continue
        if lifecycle_lower and str(recipe.get("lifecycle") or "").lower() != lifecycle_lower:
            continue
        matches.append(
            {
                key: recipe.get(key)
                for key in (
                    "id",
                    "name",
                    "engine",
                    "lifecycle",
                    "inventory_path",
                    "tok_s",
                    "context",
                    "enabled",
                    "switchable",
                )
            }
        )
        if len(matches) >= max(1, min(limit, 100)):
            break
    return {"count": len(matches), "recipes": matches}


@mcp.tool()
def search_inventory(query: str = "", limit: int = 30) -> dict[str, Any]:
    """Search locally indexed model inventory by name, path, repo, or architecture."""
    payload = fetch("/models.json", timeout=30)
    models = payload.get("models", []) if isinstance(payload, dict) else []
    query_lower = query.strip().lower()
    matches = []
    for model in models:
        if not isinstance(model, dict):
            continue
        haystack = " ".join(
            str(model.get(key) or "")
            for key in ("id", "name", "path", "rel_path", "hf_repo", "architecture", "summary")
        ).lower()
        if query_lower and query_lower not in haystack:
            continue
        matches.append(
            {
                key: model.get(key)
                for key in (
                    "id",
                    "name",
                    "rel_path",
                    "hf_repo",
                    "status",
                    "size_human",
                    "is_golden",
                    "golden_profile",
                    "best_bench_tok_s",
                    "architecture",
                    "param_b",
                    "param_active_b",
                    "max_context",
                )
            }
        )
        if len(matches) >= max(1, min(limit, 100)):
            break
    return {"count": len(matches), "models": matches}


@mcp.tool()
def get_benchmaster_queue() -> dict[str, Any]:
    """Read Benchmaster status and queued jobs."""
    return {
        "status": fetch("/api/benchmaster/status"),
        "queue": fetch("/api/benchmaster/queue"),
    }


@mcp.tool()
def get_recent_activity(window: str = "1h") -> dict[str, Any]:
    """Read recent gateway client activity for the last 1h or 24h."""
    if window not in {"1h", "24h"}:
        raise ValueError("window must be 1h or 24h")
    return fetch(f"/api/activity?window={quote(window)}")


@mcp.tool()
def get_operator_goals() -> dict[str, Any]:
    """Read durable Spark operator goals."""
    path = STATE_DIR / "goals.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = {"goals": []}
    goals = payload.get("goals", []) if isinstance(payload, dict) else []
    return {"goals": goals[:100]}


@mcp.tool()
def get_scheduled_checks() -> dict[str, Any]:
    """Read Spark-owned Hermes cron checks."""
    path = HERMES_HOME / "cron" / "jobs.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = {"jobs": []}
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    checks = []
    for job in jobs:
        if not isinstance(job, dict) or not str(job.get("prompt") or "").startswith("[spark-operator"):
            continue
        checks.append(
            {
                key: job.get(key)
                for key in (
                    "id",
                    "name",
                    "enabled",
                    "state",
                    "schedule_display",
                    "last_status",
                    "last_run_at",
                    "next_run_at",
                )
            }
        )
    return {"checks": checks}


@mcp.tool()
def propose_inference_switch(profile: str) -> dict[str, Any]:
    """Propose loading an inference profile. Requires portal confirmation."""
    return write_proposal("inference_switch", {"profile": valid_id(profile, "profile")})


@mcp.tool()
def propose_inference_stop() -> dict[str, Any]:
    """Propose stopping active inference. Requires portal confirmation."""
    return write_proposal("inference_stop", {})


@mcp.tool()
def propose_benchmaster_control(action: str) -> dict[str, Any]:
    """Propose pause/resume/stop-after-current/abort control. Requires confirmation."""
    allowed = {"pause", "resume", "stop_after_current", "abort_current_requeue_front"}
    if action not in allowed:
        raise ValueError(f"action must be one of {sorted(allowed)}")
    return write_proposal("benchmaster_control", {"action": action})


@mcp.tool()
def propose_benchmaster_job(
    job_type: str,
    profile_id: str,
    inventory_path: str = "",
    note: str = "",
    front: bool = False,
) -> dict[str, Any]:
    """Propose adding a Benchmaster job. Requires portal confirmation."""
    allowed = {"perf_sweep", "ctx_ladder", "kv_sweep", "golden_workflow", "intel_eval"}
    if job_type not in allowed:
        raise ValueError(f"job_type must be one of {sorted(allowed)}")
    args: dict[str, Any] = {
        "type": job_type,
        "profile_id": valid_id(profile_id, "profile_id"),
        "front": bool(front),
    }
    if inventory_path:
        args["inventory_path"] = valid_id(inventory_path, "inventory_path")
    if note:
        args["note"] = note[:500]
    return write_proposal("benchmaster_add", args)


@mcp.tool()
def propose_recipe_change(action: str, profile: str) -> dict[str, Any]:
    """Propose promote, discard, or testing lifecycle change for a recipe."""
    mapping = {
        "promote": "recipe_promote",
        "discard": "recipe_discard",
        "testing": "recipe_testing",
    }
    if action not in mapping:
        raise ValueError("action must be promote, discard, or testing")
    return write_proposal(mapping[action], {"profile": valid_id(profile, "profile")})


@mcp.tool()
def propose_shelf_action(action: str, path: str, force: bool = False) -> dict[str, Any]:
    """Propose pull, push, or remove of model weights. Requires confirmation."""
    mapping = {"pull": "shelf_pull", "push": "shelf_push", "remove": "shelf_remove"}
    if action not in mapping:
        raise ValueError("action must be pull, push, or remove")
    args: dict[str, Any] = {"path": valid_id(path, "path")}
    if action == "remove":
        args["force"] = bool(force)
    return write_proposal(mapping[action], args)


@mcp.tool()
def propose_install(target: str, engine: str = "") -> dict[str, Any]:
    """Propose an allowlisted optional install. Requires portal confirmation."""
    allowed = {"hermes", "gateway", "openwebui", "nas", "engine"}
    if target not in allowed:
        raise ValueError(f"target must be one of {sorted(allowed)}")
    args: list[str] = []
    if target == "engine":
        if engine not in {"eugr", "llama", "ds4"}:
            raise ValueError("engine must be eugr, llama, or ds4")
        args = [engine]
    return write_proposal("install", {"target": target, "args": args})


@mcp.tool()
def propose_goal(
    title: str,
    notes: str = "",
    status: str = "active",
    goal_id: str = "",
    delete: bool = False,
) -> dict[str, Any]:
    """Propose creating, updating, completing, pausing, or deleting an operator goal."""
    if delete:
        if not goal_id:
            raise ValueError("goal_id is required to delete a goal")
        return write_proposal("goal_delete", {"goal_id": valid_id(goal_id, "goal_id")})
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    if status not in {"active", "paused", "done"}:
        raise ValueError("status must be active, paused, or done")
    args: dict[str, Any] = {"title": title[:200], "notes": notes[:4000], "status": status}
    if goal_id:
        args["goal_id"] = valid_id(goal_id, "goal_id")
    return write_proposal("goal_save", args)


@mcp.tool()
def propose_scheduled_check(
    name: str,
    schedule: str,
    prompt: str,
    goal_id: str = "",
) -> dict[str, Any]:
    """Propose a persistent Hermes cron check. Requires portal confirmation."""
    if not name.strip() or not schedule.strip() or not prompt.strip():
        raise ValueError("name, schedule, and prompt are required")
    args: dict[str, Any] = {
        "name": name.strip()[:120],
        "schedule": schedule.strip()[:100],
        "prompt": prompt.strip()[:8000],
    }
    if goal_id:
        args["goal_id"] = valid_id(goal_id, "goal_id")
    return write_proposal("check_create", args)


@mcp.tool()
def propose_check_action(action: str, job_id: str) -> dict[str, Any]:
    """Propose run, pause, resume, or delete for a scheduled check."""
    mapping = {
        "run": "check_run",
        "pause": "check_pause",
        "resume": "check_resume",
        "delete": "check_delete",
    }
    if action not in mapping:
        raise ValueError("action must be run, pause, resume, or delete")
    return write_proposal(mapping[action], {"job_id": valid_id(job_id, "job_id")})


if __name__ == "__main__":
    mcp.run(transport="stdio")
