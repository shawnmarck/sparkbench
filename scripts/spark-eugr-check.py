#!/opt/spark/venv/bin/python3
"""Compare deployed eugr vLLM stack pins against upstream prebuilt releases."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path("/opt/spark")
VENDOR = ROOT / "vendor" / "spark-vllm-docker"
WHEELS = VENDOR / "wheels"
STATE_FILE = ROOT / "run" / "eugr-stack-state.json"
PENDING_STATE_FILE = ROOT / "run" / "eugr-stack-state.pending.json"
CACHE_FILE = ROOT / "run" / "eugr-check-cache.json"
RUNBOOK = "docs/runbooks/eugr-vllm-upgrade.md"
WHEELS_REPO = "eugr/spark-vllm-docker"
VLLM_RELEASE_TAG = "prebuilt-vllm-current"
FLASHINFER_RELEASE_TAG = "prebuilt-flashinfer-current"
CACHE_TTL_S = 3600
IMAGE_TAG = "vllm-node:latest"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_commit(path: Path) -> str:
    return read_text(path)


def fetch_url(url: str, timeout: float = 15.0) -> str:
    req = Request(url, headers={"User-Agent": "spark-eugr-check/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_vllm_commit(html: str) -> str:
    match = re.search(r"\+g([0-9a-f]{6,})\.", html, re.IGNORECASE)
    return match.group(1) if match else ""


def parse_flashinfer_commit(html: str) -> str:
    match = re.search(
        r"\([\d.]+\w*-([0-9a-f]{6,})-d\d{8}\)", html, re.IGNORECASE
    )
    return match.group(1) if match else ""


def commits_match(local: str, remote: str) -> bool:
    if not local or not remote:
        return False
    return local == remote or local.startswith(remote) or remote.startswith(local)


def vllm_version_from_wheels() -> str:
    for path in sorted(WHEELS.glob("vllm-*.whl")):
        name = path.name
        if name.startswith("vllm-"):
            return name.removeprefix("vllm-").split("-", 1)[0]
    return ""


def docker_image_info() -> dict[str, str]:
    try:
        proc = subprocess.run(
            [
                "docker",
                "inspect",
                IMAGE_TAG,
                "--format",
                "{{.Id}} {{.Created}}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    line = (proc.stdout or "").strip()
    if not line:
        return {}
    image_id, created = line.split(" ", 1)
    short_id = image_id.removeprefix("sha256:")[:12]
    return {"image_id": short_id, "image_created": created, "image_tag": IMAGE_TAG}


def load_state() -> dict[str, Any]:
    for path in (STATE_FILE, PENDING_STATE_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2) + "\n"
    PENDING_STATE_FILE.write_text(payload, encoding="utf-8")
    try:
        STATE_FILE.write_text(payload, encoding="utf-8")
    except OSError:
        pass


def seed_state_if_missing() -> dict[str, Any]:
    state = load_state()
    if state.get("vllm_commit") or state.get("flashinfer_commit"):
        return state

    image = docker_image_info()
    state = {
        "promoted_at": image.get("image_created") or utc_now(),
        "image_id": image.get("image_id", ""),
        "image_tag": image.get("image_tag", IMAGE_TAG),
        "vllm_commit": read_commit(WHEELS / ".vllm-commit"),
        "flashinfer_commit": read_commit(WHEELS / ".flashinfer-commit"),
        "vllm_version": vllm_version_from_wheels(),
        "seeded": True,
        "seeded_at": utc_now(),
    }
    save_state(state)
    return state


def load_cache() -> dict[str, Any]:
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")


def fetch_upstream(force: bool = False) -> tuple[dict[str, str], dict[str, Any]]:
    cache = load_cache()
    fetched_at = cache.get("fetched_at")
    upstream = cache.get("upstream") if isinstance(cache.get("upstream"), dict) else {}
    if (
        not force
        and fetched_at
        and upstream.get("vllm_commit")
        and upstream.get("flashinfer_commit")
    ):
        try:
            age = time.time() - datetime.fromisoformat(fetched_at).timestamp()
        except ValueError:
            age = CACHE_TTL_S + 1
        if age < CACHE_TTL_S:
            return upstream, {"fetched_at": fetched_at, "cache_age_s": int(age), "cached": True}

    errors: list[str] = []
    vllm_commit = ""
    flashinfer_commit = ""
    try:
        html = fetch_url(
            f"https://github.com/{WHEELS_REPO}/releases/tag/{VLLM_RELEASE_TAG}"
        )
        vllm_commit = parse_vllm_commit(html)
    except (URLError, TimeoutError, OSError) as exc:
        errors.append(f"vllm release: {exc}")

    try:
        html = fetch_url(
            f"https://github.com/{WHEELS_REPO}/releases/tag/{FLASHINFER_RELEASE_TAG}"
        )
        flashinfer_commit = parse_flashinfer_commit(html)
    except (URLError, TimeoutError, OSError) as exc:
        errors.append(f"flashinfer release: {exc}")

    upstream = {
        "vllm_commit": vllm_commit,
        "flashinfer_commit": flashinfer_commit,
        "vllm_release": VLLM_RELEASE_TAG,
        "flashinfer_release": FLASHINFER_RELEASE_TAG,
        "repo": WHEELS_REPO,
    }
    if errors:
        upstream["errors"] = errors

    fetched_at = utc_now()
    save_cache({"fetched_at": fetched_at, "upstream": upstream})
    return upstream, {"fetched_at": fetched_at, "cache_age_s": 0, "cached": False}


def component_status(deployed: str, upstream: str) -> str:
    if not upstream:
        return "unknown"
    if not deployed:
        return "unknown"
    if commits_match(deployed, upstream):
        return "current"
    return "behind"


def build_check_payload(force: bool = False) -> dict[str, Any]:
    deployed = seed_state_if_missing()
    upstream, meta = fetch_upstream(force=force)

    components: dict[str, Any] = {}
    behind: list[str] = []
    for key, label in (("vllm", "vLLM"), ("flashinfer", "FlashInfer")):
        dep = str(deployed.get(f"{key}_commit") or "")
        up = str(upstream.get(f"{key}_commit") or "")
        status = component_status(dep, up)
        components[key] = {
            "status": status,
            "deployed": dep or None,
            "upstream": up or None,
        }
        if status == "behind":
            behind.append(label)

    update_available = bool(behind)
    message = ""
    if update_available:
        parts = []
        if components["vllm"]["status"] == "behind":
            parts.append(
                f"vLLM {components['vllm']['upstream']} (deployed {components['vllm']['deployed']})"
            )
        if components["flashinfer"]["status"] == "behind":
            parts.append(
                "FlashInfer "
                f"{components['flashinfer']['upstream']} "
                f"(deployed {components['flashinfer']['deployed']})"
            )
        message = "New eugr prebuilt wheels: " + "; ".join(parts)
    elif upstream.get("errors"):
        message = "Could not reach upstream release pages — showing last known pins"
    else:
        message = "vLLM stack matches upstream prebuilt releases"

    wheels = {
        "vllm_commit": read_commit(WHEELS / ".vllm-commit") or None,
        "flashinfer_commit": read_commit(WHEELS / ".flashinfer-commit") or None,
        "vllm_version": vllm_version_from_wheels() or None,
    }
    wheels_staged = any(
        wheels.get(f"{key}_commit")
        and deployed.get(f"{key}_commit")
        and not commits_match(
            str(wheels.get(f"{key}_commit")),
            str(deployed.get(f"{key}_commit")),
        )
        for key in ("vllm", "flashinfer")
    )

    return {
        "update_available": update_available,
        "message": message,
        "checked_at": utc_now(),
        "runbook": RUNBOOK,
        "cli": "spark engine eugr check",
        "deployed": deployed,
        "upstream": upstream,
        "components": components,
        "wheels": wheels,
        "wheels_staged": wheels_staged,
        "check_meta": meta,
    }


def record_promoted() -> dict[str, Any]:
    image = docker_image_info()
    state = {
        "promoted_at": utc_now(),
        "image_id": image.get("image_id", ""),
        "image_tag": image.get("image_tag", IMAGE_TAG),
        "image_created": image.get("image_created", ""),
        "vllm_commit": read_commit(WHEELS / ".vllm-commit"),
        "flashinfer_commit": read_commit(WHEELS / ".flashinfer-commit"),
        "vllm_version": vllm_version_from_wheels(),
    }
    save_state(state)
    return state


def cmd_check(args: argparse.Namespace) -> int:
    payload = build_check_payload(force=args.refresh)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(payload["message"])
    if payload["update_available"]:
        print(f"Runbook: {payload['runbook']}")
        print("Tell an agent: upgrade the eugr vLLM stack during a maintenance window.")
        return 1
    if payload["wheels_staged"]:
        print("Note: local wheels differ from deployed image — rebuild may be pending.")
    return 0


def cmd_record(_args: argparse.Namespace) -> int:
    state = record_promoted()
    print(json.dumps(state, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eugr vLLM stack version check")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="Compare deployed stack vs upstream prebuilts")
    check.add_argument("--json", action="store_true", help="Emit JSON")
    check.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass upstream cache (default TTL 1h)",
    )
    check.set_defaults(func=cmd_check)

    record = sub.add_parser(
        "record",
        help="Record deployed pins after a successful promote (agent step)",
    )
    record.set_defaults(func=cmd_record)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())