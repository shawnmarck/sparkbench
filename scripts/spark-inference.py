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
from urllib.request import Request, urlopen

import yaml

ROOT = Path("/opt/spark")
RECIPES_DIR = ROOT / "recipes"
PROFILES_INDEX = ROOT / "data" / "inference-profiles.yaml"
STATE_FILE = ROOT / "run" / "inference-active.json"
SWITCH_PID_FILE = ROOT / "run" / "inference-switch.pid"
SWITCH_LOG_FILE = ROOT / "logs" / "inference-switch-latest.log"
LOG_DIR = ROOT / "logs"
BENCHMARKS_FILE = ROOT / "data" / "inference-benchmarks.yaml"
VERIFY_FILE = ROOT / "data" / "model-verification.yaml"
SPARK_EUGR = ROOT / "scripts" / "spark-eugr"
SPARK_LLAMA = ROOT / "scripts" / "spark-llama"
PROFILE_ID_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9._-]*$")


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
                if engine == "eugr" and not eugr_running() and not llama_running():
                    clear_state()
                elif engine == "llamacpp" and not llama_running() and not eugr_running():
                    clear_state()
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
    print(f"{'PROFILE':<22} {'ENGINE':<10} {'TIER':<12} {'PORT':<6} {'TOK/S':<8} ACTIVE")
    print("-" * 70)
    for profile_id in enabled_profiles():
        recipe = load_recipe(profile_id)
        mark = "*" if profile_id == active_id else ""
        bench = benchmark_for_profile(profile_id) or {}
        tok = bench.get("tok_s")
        tok_s = f"{tok:.0f}" if isinstance(tok, (int, float)) else "—"
        print(
            f"{profile_id:<22} "
            f"{recipe.get('engine', '?'):<10} "
            f"{recipe.get('tier', '?'):<12} "
            f"{recipe.get('port', '?'):<6} "
            f"{tok_s:<8} {mark}"
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


def validate_profile_id(profile_id: str) -> str | None:
    profile_id = profile_id.strip()
    if not profile_id or not PROFILE_ID_RE.match(profile_id):
        return None
    if profile_id not in enabled_profiles():
        return None
    return profile_id


def load_benchmarks() -> dict[str, Any]:
    if not BENCHMARKS_FILE.is_file():
        return {}
    data = load_yaml(BENCHMARKS_FILE)
    profiles = data.get("profiles") or {}
    return profiles if isinstance(profiles, dict) else {}


def save_benchmarks(profiles: dict[str, Any]) -> None:
    BENCHMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BENCHMARKS_FILE.write_text(
        yaml.safe_dump({"profiles": profiles}, sort_keys=False, default_flow_style=False)
    )


def benchmark_for_profile(profile_id: str) -> dict[str, Any] | None:
    entry = load_benchmarks().get(profile_id)
    return entry if isinstance(entry, dict) else None


def recipe_public(recipe: dict[str, Any]) -> dict[str, Any]:
    profile_id = recipe.get("id")
    bench = benchmark_for_profile(profile_id) if profile_id else None
    out = {
        "id": profile_id,
        "name": recipe.get("name"),
        "engine": recipe.get("engine"),
        "tier": recipe.get("tier"),
        "port": recipe.get("port"),
        "served_name": recipe.get("served_name"),
        "inventory_path": recipe.get("inventory_path") or recipe.get("catalog_id"),
        "tags": recipe.get("tags") or [],
        "notes": (recipe.get("notes") or "").strip(),
    }
    if bench and bench.get("tok_s") is not None:
        out["tok_s"] = bench.get("tok_s")
        out["tok_s_method"] = bench.get("method")
        out["tok_s_measured_at"] = bench.get("measured_at")
    return out


def record_benchmark(
    profile_id: str,
    recipe: dict[str, Any],
    tok_s: float,
    *,
    method: str,
    completion_tokens: int | None = None,
    prompt_tokens: int | None = None,
    elapsed_s: float | None = None,
    note: str | None = None,
    tok_s_min: float | None = None,
    tok_s_max: float | None = None,
    sessions: int | None = None,
    turns_per_session: int | None = None,
    run_tok_s: list[float] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    engine = recipe.get("engine")
    profiles = load_benchmarks()
    entry = {
        "tok_s": round(float(tok_s), 1),
        "engine": engine,
        "method": method,
        "measured_at": now,
    }
    if completion_tokens is not None:
        entry["completion_tokens"] = completion_tokens
    if prompt_tokens is not None:
        entry["prompt_tokens"] = prompt_tokens
    if elapsed_s is not None:
        entry["elapsed_s"] = round(elapsed_s, 2)
    if tok_s_min is not None:
        entry["tok_s_min"] = round(float(tok_s_min), 1)
    if tok_s_max is not None:
        entry["tok_s_max"] = round(float(tok_s_max), 1)
    if sessions is not None:
        entry["sessions"] = sessions
    if turns_per_session is not None:
        entry["turns_per_session"] = turns_per_session
    if run_tok_s:
        entry["run_tok_s"] = [round(float(v), 1) for v in run_tok_s]
    if note:
        entry["note"] = note
    profiles[profile_id] = entry
    save_benchmarks(profiles)

    inv_path = recipe.get("inventory_path") or recipe.get("catalog_id")
    if inv_path:
        if VERIFY_FILE.is_file():
            store = load_yaml(VERIFY_FILE)
        else:
            store = {"models": {}}
        models = store.setdefault("models", {})
        model_entry = models.setdefault(str(inv_path), {})
        model_entry["tok_s"] = entry["tok_s"]
        model_entry["tok_s_engine"] = engine
        model_entry["tok_s_profile"] = profile_id
        model_entry["updated_at"] = now
        if note:
            model_entry["note"] = note
        VERIFY_FILE.write_text(
            yaml.safe_dump(store, sort_keys=False, default_flow_style=False)
        )

    subprocess.Popen(
        [str(ROOT / "scripts" / "spark-inventory-build")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return entry


BENCH_WARMUP_SESSIONS = 1
BENCH_MEASURED_SESSIONS = 3
BENCH_TURNS_PER_SESSION = 3
BENCH_MAX_TOKENS = 256
BENCH_MIN_COMPLETION_TOKENS = 48
BENCH_TEMPERATURE = 0.0
BENCH_SYSTEM = (
    "You are a helpful assistant running a throughput benchmark. "
    "Follow instructions precisely and write substantive responses."
)
BENCH_USER_TURNS = [
    (
        "Task: design a small REST API for a model inventory service. "
        "Reply with exactly 8 numbered bullets; each bullet must be one full sentence."
    ),
    (
        "Expand bullets 3 and 4 into Python pseudocode with comments. "
        "Include at least 20 lines of code total."
    ),
    (
        "List 6 edge cases this API must handle and one pytest idea for each. "
        "Use a numbered list with two sentences per item."
    ),
]


def _chat_completion(
    port: int,
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    min_tokens: int,
    timeout: float = 180.0,
) -> tuple[dict[str, Any], float]:
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "min_tokens": min_tokens,
            "temperature": BENCH_TEMPERATURE,
        }
    ).encode()
    req = Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    elapsed = time.perf_counter() - start
    return payload, elapsed


def _completion_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    if completion_tokens is not None:
        return int(completion_tokens)
    choice = (payload.get("choices") or [{}])[0]
    text = choice.get("message", {}).get("content") or choice.get("text") or ""
    return max(1, len(text.split()))


def _assistant_text(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    return (choice.get("message", {}).get("content") or choice.get("text") or "").strip()


def _bench_agent_session(
    port: int,
    model: str,
    turn_prompts: list[str],
) -> tuple[int, int, float]:
    messages: list[dict[str, str]] = [{"role": "system", "content": BENCH_SYSTEM}]
    total_completion = 0
    total_prompt = 0
    total_elapsed = 0.0

    for user_text in turn_prompts:
        messages.append({"role": "user", "content": user_text})
        payload, elapsed = _chat_completion(
            port,
            model,
            messages,
            max_tokens=BENCH_MAX_TOKENS,
            min_tokens=BENCH_MIN_COMPLETION_TOKENS,
        )
        completion_tokens = _completion_tokens(payload)
        if completion_tokens < BENCH_MIN_COMPLETION_TOKENS:
            retry_text = user_text + " Write a longer, more detailed response."
            payload, retry_elapsed = _chat_completion(
                port,
                model,
                messages[:-1] + [{"role": "user", "content": retry_text}],
                max_tokens=BENCH_MAX_TOKENS,
                min_tokens=BENCH_MIN_COMPLETION_TOKENS,
            )
            elapsed += retry_elapsed
            completion_tokens = _completion_tokens(payload)
        if completion_tokens < BENCH_MIN_COMPLETION_TOKENS:
            raise RuntimeError(
                f"benchmark turn too short ({completion_tokens} tok) — model stopped early"
            )

        usage = payload.get("usage") or {}
        total_completion += completion_tokens
        total_prompt += int(usage.get("prompt_tokens") or 0)
        total_elapsed += elapsed
        messages.append({"role": "assistant", "content": _assistant_text(payload)})

    return total_completion, total_prompt, total_elapsed


def run_benchmark(
    *,
    warmup_sessions: int = BENCH_WARMUP_SESSIONS,
    measured_sessions: int = BENCH_MEASURED_SESSIONS,
    turns_per_session: int = BENCH_TURNS_PER_SESSION,
) -> dict[str, Any]:
    active = detect_active_profile()
    if not active:
        raise RuntimeError("no active profile")
    recipe = active["recipe"]
    profile_id = active["profile"]
    if not engine_ready(recipe):
        raise RuntimeError("active profile not ready — wait for /v1/models")

    port = int(recipe.get("port") or 0)
    served = recipe.get("served_name")
    turn_prompts = BENCH_USER_TURNS[:turns_per_session]
    if len(turn_prompts) < turns_per_session:
        raise RuntimeError("benchmark turn prompts misconfigured")

    for _ in range(warmup_sessions):
        _bench_agent_session(port, served, turn_prompts)

    run_rates: list[float] = []
    total_completion = 0
    total_prompt = 0
    total_elapsed = 0.0
    for _ in range(measured_sessions):
        completion_tokens, prompt_tokens, elapsed = _bench_agent_session(
            port, served, turn_prompts
        )
        if elapsed <= 0:
            raise RuntimeError("benchmark elapsed time was zero")
        run_rates.append(completion_tokens / elapsed)
        total_completion += completion_tokens
        total_prompt += prompt_tokens
        total_elapsed += elapsed

    tok_s = sum(run_rates) / len(run_rates)
    bench = record_benchmark(
        profile_id,
        recipe,
        tok_s,
        method="bench-agent",
        completion_tokens=total_completion,
        prompt_tokens=total_prompt,
        elapsed_s=total_elapsed,
        tok_s_min=min(run_rates),
        tok_s_max=max(run_rates),
        sessions=measured_sessions,
        turns_per_session=turns_per_session,
        run_tok_s=run_rates,
        note=(
            f"agent bench avg {tok_s:.1f} tok/s over {measured_sessions} sessions "
            f"× {turns_per_session} turns ({total_completion} tok in {total_elapsed:.1f}s)"
        ),
    )
    return {
        "profile": profile_id,
        "served_name": served,
        "tok_s": bench["tok_s"],
        "tok_s_min": bench.get("tok_s_min"),
        "tok_s_max": bench.get("tok_s_max"),
        "run_tok_s": run_rates,
        "sessions": measured_sessions,
        "turns_per_session": turns_per_session,
        "completion_tokens": total_completion,
        "prompt_tokens": total_prompt,
        "elapsed_s": round(total_elapsed, 2),
        "benchmark": bench,
    }


def engine_ready(recipe: dict[str, Any]) -> bool:
    port = int(recipe.get("port") or 0)
    if not port:
        return False
    served = served_name_from_port(port)
    return served == recipe.get("served_name")


def read_pid_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        path.unlink(missing_ok=True)
        return None
    return pid


def tail_log(path: Path, lines: int = 12) -> list[str]:
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-lines:]


def active_switch_job() -> dict[str, Any]:
    pid = read_pid_file(SWITCH_PID_FILE)
    if not pid:
        SWITCH_PID_FILE.unlink(missing_ok=True)
        return {"running": False}
    return {
        "running": True,
        "pid": pid,
        "log": SWITCH_LOG_FILE.name,
        "log_tail": tail_log(SWITCH_LOG_FILE),
    }


def engine_log_file(recipe: dict[str, Any] | None) -> Path:
    if not recipe:
        return LOG_DIR / "llama-server.log"
    if recipe.get("engine") == "eugr":
        return SWITCH_LOG_FILE
    return LOG_DIR / "llama-server.log"


def api_profiles(active_id: str | None = None) -> list[dict[str, Any]]:
    profiles = []
    for profile_id in enabled_profiles():
        recipe = load_recipe(profile_id)
        item = recipe_public(recipe)
        item["active"] = profile_id == active_id
        if active_id == profile_id:
            item["ready"] = engine_ready(recipe)
            item["starting"] = not item["ready"] and (
                (recipe.get("engine") == "llamacpp" and llama_running())
                or (recipe.get("engine") == "eugr" and eugr_running())
            )
        else:
            item["ready"] = False
            item["starting"] = False
        profiles.append(item)
    return profiles


def api_status() -> dict[str, Any]:
    active = detect_active_profile()
    active_id = active["profile"] if active else None
    recipe = active["recipe"] if active else None
    ready = engine_ready(recipe) if recipe else False
    port = int(recipe.get("port") or 0) if recipe else None

    payload: dict[str, Any] = {
        "active": None,
        "profiles": api_profiles(active_id),
        "engines": {"eugr": eugr_running(), "llamacpp": llama_running()},
        "switch": active_switch_job(),
        "urls": {
            "openwebui": "http://sparky:3000",
            "portal": "http://sparky/",
        },
    }

    if active and recipe:
        starting = not ready and (
            (recipe.get("engine") == "llamacpp" and llama_running())
            or (recipe.get("engine") == "eugr" and eugr_running())
        )
        payload["active"] = {
            **recipe_public(recipe),
            "started_at": (active.get("state") or {}).get("started_at"),
            "ready": ready,
            "starting": starting,
            "api_url": f"http://sparky:{port}/v1" if port else None,
            "log_file": engine_log_file(recipe).name,
        }
        payload["urls"]["api"] = payload["active"]["api_url"]
        bench = benchmark_for_profile(active_id)
        if bench:
            payload["active"]["benchmark"] = bench

    payload["benchmarks"] = load_benchmarks()
    return payload


def start_switch_job(profile_id: str) -> tuple[bool, str, dict[str, Any]]:
    profile_id = validate_profile_id(profile_id)
    if not profile_id:
        return False, "unknown or disabled profile", {}

    if active_switch_job().get("running"):
        return False, "profile switch already running", active_switch_job()

    active = detect_active_profile()
    if active and active["profile"] == profile_id and engine_ready(active["recipe"]):
        return False, "profile already active", api_status()

    SWITCH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    SWITCH_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SWITCH_LOG_FILE.open("w", encoding="utf-8") as log:
        log.write(f"==> switch to {profile_id} {datetime.now(timezone.utc).isoformat()}\n")
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "spark-inference.py"), "up", profile_id],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    SWITCH_PID_FILE.write_text(str(proc.pid))
    job = active_switch_job()
    job["profile"] = profile_id
    job["started_at"] = datetime.now(timezone.utc).isoformat()
    return True, "started", job


def api_down() -> dict[str, Any]:
    if active_switch_job().get("running"):
        raise RuntimeError("profile switch in progress")
    cmd_down()
    return api_status()


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


def cmd_bench() -> int:
    try:
        result = run_benchmark()
    except (RuntimeError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    runs = ", ".join(f"{v:.1f}" for v in result.get("run_tok_s") or [])
    print(
        f"Benchmark {result['profile']}: {result['tok_s']:.1f} tok/s avg "
        f"({result['sessions']} sessions × {result['turns_per_session']} turns, "
        f"{result['completion_tokens']} tokens in {result['elapsed_s']:.1f}s)"
    )
    if runs:
        print(f"  session tok/s: {runs}")
    if result.get("tok_s_min") is not None and result.get("tok_s_max") is not None:
        print(
            f"  range: {result['tok_s_min']:.1f}–{result['tok_s_max']:.1f} tok/s"
        )
    return 0


def usage() -> None:
    print(
        """Usage: spark-inference {list|status|up <profile>|down|logs [profile]|bench}

Recipe-driven inference control (Phase 5). One GPU workload at a time.
bench — multi-turn agent-style timing on the active profile (avg of 3 sessions).
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
    if cmd == "bench":
        return cmd_bench()

    usage()
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc