#!/opt/spark/venv/bin/python3
"""Phase 5 inference control plane — recipe-driven profile switch."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import yaml

ROOT = Path("/opt/spark")
RECIPES_DIR = ROOT / "recipes"
PROFILES_INDEX = ROOT / "data" / "inference-profiles.yaml"
STATE_FILE = ROOT / "run" / "inference-active.json"
SPARK_EUGR = ROOT / "scripts" / "spark-eugr"
SPARK_LLAMA = ROOT / "scripts" / "spark-llama"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"invalid yaml root in {path}")
    return data


def enabled_profiles() -> list[str]:
    data = load_yaml(PROFILES_INDEX)
    profiles = data.get("profiles") or []
    return [p for p in profiles if isinstance(p, str) and p]


def load_recipe(profile_id: str) -> dict[str, Any]:
    path = RECIPES_DIR / f"{profile_id}.yaml"
    if not path.is_file():
        raise SystemExit(f"unknown profile: {profile_id} (missing {path})")
    recipe = load_yaml(path)
    if recipe.get("id") and recipe["id"] != profile_id:
        print(f"warning: recipe id {recipe['id']!r} != filename {profile_id!r}", file=sys.stderr)
    recipe.setdefault("id", profile_id)
    return recipe


def recipe_path(profile_id: str) -> Path:
    return RECIPES_DIR / f"{profile_id}.yaml"


def curl_json(url: str, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def eugr_running() -> bool:
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return any(name in {"vllm_node", "spark-vllm-qwen36"} for name in out.splitlines())


def llama_running() -> bool:
    pid_file = ROOT / "run" / "llama-server.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def served_name_from_port(port: int) -> str | None:
    payload = curl_json(f"http://127.0.0.1:{port}/v1/models")
    if not payload:
        return None
    models = payload.get("data") or payload.get("models") or []
    if not models:
        return None
    first = models[0]
    return first.get("id") or first.get("name")


def detect_active_profile() -> dict[str, Any] | None:
    if STATE_FILE.is_file():
        try:
            state = json.loads(STATE_FILE.read_text())
            profile_id = state.get("profile")
            if profile_id:
                recipe = load_recipe(profile_id)
                engine = recipe.get("engine")
                if engine == "eugr" and eugr_running():
                    return {"profile": profile_id, "recipe": recipe, "state": state}
                if engine == "llamacpp" and llama_running():
                    return {"profile": profile_id, "recipe": recipe, "state": state}
        except (json.JSONDecodeError, OSError, SystemExit):
            pass

    for profile_id in enabled_profiles():
        recipe = load_recipe(profile_id)
        engine = recipe.get("engine")
        port = int(recipe.get("port") or 0)
        if engine == "eugr" and eugr_running():
            return {"profile": profile_id, "recipe": recipe, "state": None}
        if engine == "llamacpp" and llama_running():
            served = served_name_from_port(port) if port else None
            if served == recipe.get("served_name"):
                return {"profile": profile_id, "recipe": recipe, "state": None}
    return None


def write_state(profile_id: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {
                "profile": profile_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n"
    )


def clear_state() -> None:
    STATE_FILE.unlink(missing_ok=True)


def run_script(script: Path, *args: str, env: dict[str, str] | None = None) -> None:
    if not script.is_file():
        raise SystemExit(f"missing script: {script}")
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run([str(script), *args], check=True, env=merged)


def cmd_list() -> int:
    active = detect_active_profile()
    active_id = active["profile"] if active else None
    print(f"{'PROFILE':<22} {'ENGINE':<10} {'TIER':<12} {'PORT':<6} ACTIVE")
    print("-" * 60)
    for profile_id in enabled_profiles():
        recipe = load_recipe(profile_id)
        mark = "*" if profile_id == active_id else ""
        print(
            f"{profile_id:<22} "
            f"{recipe.get('engine', '?'):<10} "
            f"{recipe.get('tier', '?'):<12} "
            f"{recipe.get('port', '?'):<6} {mark}"
        )
    return 0


def cmd_status() -> int:
    active = detect_active_profile()
    if not active:
        print("Active profile: none")
        print("Engines: eugr down, llama.cpp down")
        return 0

    recipe = active["recipe"]
    profile_id = active["profile"]
    lines = [
        f"Active profile: {profile_id}",
        f"  name:   {recipe.get('name', '')}",
        f"  engine: {recipe.get('engine', '')}",
        f"  tier:   {recipe.get('tier', '')}",
        f"  port:   {recipe.get('port', '')}",
        f"  model:  {recipe.get('served_name', '')}",
    ]
    if active.get("state") and active["state"].get("started_at"):
        lines.append(f"  since:  {active['state']['started_at']}")
    lines.append("---")
    print("\n".join(lines), flush=True)
    if recipe.get("engine") == "eugr":
        run_script(SPARK_EUGR, "status")
    else:
        run_script(SPARK_LLAMA, "status")
    return 0


def cmd_down() -> int:
    errors = 0
    for script, args in ((SPARK_EUGR, ("down",)), (SPARK_LLAMA, ("down",))):
        try:
            run_script(script, *args)
        except subprocess.CalledProcessError:
            errors += 1
    clear_state()
    return errors


def cmd_up(profile_id: str) -> int:
    if profile_id not in enabled_profiles():
        raise SystemExit(
            f"profile {profile_id!r} is not enabled — edit {PROFILES_INDEX}"
        )

    recipe = load_recipe(profile_id)
    active = detect_active_profile()
    if active and active["profile"] == profile_id:
        print(f"Already active: {profile_id}")
        return cmd_status()

    print("Stopping current engines (if any)...")
    cmd_down()

    path = str(recipe_path(profile_id))
    engine = recipe.get("engine")
    print(f"Starting {profile_id} ({engine})...")

    if engine == "eugr":
        run_script(
            SPARK_EUGR,
            "up",
            env={"SPARK_EUGR_RECIPE": recipe.get("eugr_recipe", "")},
        )
    elif engine == "llamacpp":
        run_script(SPARK_LLAMA, "up", env={"SPARK_LLAMA_RECIPE": path})
    else:
        raise SystemExit(f"unsupported engine: {engine!r}")

    write_state(profile_id)
    print(f"Profile {profile_id} started — run: spark-inference status")
    return 0


def cmd_logs(profile_id: str | None) -> int:
    active = detect_active_profile()
    target = profile_id or (active["profile"] if active else None)
    if not target:
        raise SystemExit("no active profile — pass: spark-inference logs <profile>")

    recipe = load_recipe(target)
    if recipe.get("engine") == "eugr":
        run_script(SPARK_EUGR, "logs")
    else:
        run_script(SPARK_LLAMA, "logs")
    return 0


def usage() -> None:
    print(
        """Usage: spark-inference {list|status|up <profile>|down|logs [profile]}

Recipe-driven inference control (Phase 5). One GPU workload at a time.
Profiles: see data/inference-profiles.yaml and recipes/*.yaml"""
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        usage()
        return 1

    cmd = argv[1]
    if cmd == "list":
        return cmd_list()
    if cmd == "status":
        return cmd_status()
    if cmd == "down":
        return cmd_down()
    if cmd == "up":
        if len(argv) < 3:
            raise SystemExit("usage: spark-inference up <profile>")
        return cmd_up(argv[2])
    if cmd == "logs":
        return cmd_logs(argv[2] if len(argv) > 2 else None)

    usage()
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc