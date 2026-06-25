#!/usr/bin/env python3
"""Context ladder test: reload Sparky inference at increasing ctx, stress-fill, OpenCode smoke.

Usage:
  ./scripts/ctx-ladder-test.py
  ./scripts/ctx-ladder-test.py --steps 131072,163840
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GATEWAY = "http://sparky:9000/v1"
MODEL = "qwen3.6-35b-a3b-nvfp4"
SPARKY_SSH = "sparky"
PROFILE = "qwen36-nvfp4"
KV = "fp8"
OPENCODE = Path.home() / ".opencode/bin/opencode"
SYNC = Path.home() / ".config/opencode/sync-sparky-models.py"
WORKDIR = Path.home() / "projects/sparky"
RESULTS_ROOT = Path(__file__).resolve().parent.parent / "ctx-ladder-results"

# target fill ≈ 94% of ceiling (leave room for output + tools)
LADDER: list[tuple[int, float]] = [
    (131_072, 0.92),   # 128k → ~120k fill
    (163_840, 0.92),   # 160k → ~150k fill
    (194_560, 0.92),   # 190k → ~179k fill
    (256_000, 0.90),   # 250k → ~230k fill
]

FILL_CHUNK_TOKENS = 12_000  # per synthetic user turn via API
OPencode_TURNS = 3          # short agent turns after fill


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


def ssh(cmd: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", SPARKY_SSH, cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def http_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def estimate_tokens(text: str) -> int:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def paragraph(seed: int) -> str:
    return (
        f"Context block {seed}: describe repository layout, dependency graphs, "
        f"and refactoring tradeoffs for module {seed}. "
        f"Include error handling, test strategy, and API versioning notes. "
        * 8
    )


def build_fill_text(target_tokens: int) -> str:
    parts: list[str] = []
    total = 0
    i = 0
    while total < target_tokens:
        chunk = paragraph(i)
        parts.append(chunk)
        total += estimate_tokens(chunk)
        i += 1
    return "\n\n".join(parts)


@dataclass
class StepResult:
    ctx: int
    target_fill_tokens: int
    reload_ok: bool
    reload_seconds: float
    max_model_len: int | None = None
    spark_mem_pct: float | None = None
    kv_pool_tokens: int | None = None
    api_fill_ok: bool = False
    api_fill_prompt_tokens: int | None = None
    api_fill_seconds: float | None = None
    api_fill_error: str | None = None
    opencode_ok: bool = False
    opencode_seconds: float | None = None
    opencode_error: str | None = None
    opencode_turns: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def reload_inference(ctx: int) -> tuple[bool, float, str]:
    log(f"Reloading {PROFILE} ctx={ctx} kv={KV} (down + up)")
    t0 = time.monotonic()
    r = ssh(
        f"spark inference down && spark inference up {PROFILE} --ctx {ctx} --kv {KV}",
        timeout=900,
    )
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return False, time.monotonic() - t0, out[-4000:]

    # vLLM cold start on GB10 often takes 3–6 minutes
    for attempt in range(72):
        try:
            models = http_json(f"{GATEWAY}/models", timeout=15)
            data = models.get("data") or []
            mlen = int(data[0].get("max_model_len") or 0) if data else 0
            if mlen == ctx:
                elapsed = time.monotonic() - t0
                return True, elapsed, out[-800:] + f"\nready after {attempt * 10}s, max_model_len={mlen}"
            if mlen and attempt % 6 == 0:
                log(f"  waiting… max_model_len={mlen} (want {ctx})")
        except Exception:
            if attempt % 6 == 0:
                log("  waiting… gateway not ready")
        time.sleep(10)
    return False, time.monotonic() - t0, out[-4000:] + "\ngateway never reported target max_model_len"


def sync_opencode() -> None:
    if SYNC.is_file():
        subprocess.run([sys.executable, str(SYNC)], check=True, capture_output=True, text=True)


def spark_metrics() -> dict:
    r = ssh("spark gpu 2>/dev/null || spark status 2>/dev/null", timeout=30)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"raw": (r.stdout or r.stderr or "")[:500]}


def vllm_kv_stats() -> dict:
    r = ssh(
        "docker logs vllm_node 2>&1 | grep -E 'GPU KV cache size:|Available KV cache memory:|max_model_len' | tail -5",
        timeout=30,
    )
    text = r.stdout or ""
    kv_tokens = None
    m = re.search(r"GPU KV cache size:\s*([\d,]+)\s*tokens", text)
    if m:
        kv_tokens = int(m.group(1).replace(",", ""))
    return {"log_excerpt": text.strip(), "kv_pool_tokens": kv_tokens}


def api_fill_test(target_tokens: int, max_output: int = 32) -> tuple[bool, dict]:
    """Build context over multiple turns (like an agent session), then verify."""
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": "You are a concise assistant. Acknowledge each chunk with OK.",
        }
    ]
    turn_log: list[dict] = []
    total_est = estimate_tokens(messages[0]["content"])
    chunk_idx = 0
    t0 = time.monotonic()

    while total_est < target_tokens:
        chunk = build_fill_text(FILL_CHUNK_TOKENS)
        messages.append(
            {
                "role": "user",
                "content": f"Turn {chunk_idx + 1}: store this context.\n\n{chunk}",
            }
        )
        body = {
            "model": MODEL,
            "messages": messages,
            "max_tokens": 8,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            turn_t0 = time.monotonic()
            resp = http_json(f"{GATEWAY}/chat/completions", method="POST", body=body, timeout=900)
            turn_s = round(time.monotonic() - turn_t0, 2)
            usage = resp.get("usage") or {}
            reply = (
                ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or "OK"
            )
            messages.append({"role": "assistant", "content": reply[:200]})
            total_est = usage.get("prompt_tokens") or (total_est + FILL_CHUNK_TOKENS)
            turn_log.append(
                {
                    "turn": chunk_idx + 1,
                    "seconds": turn_s,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                }
            )
            log(f"  fill turn {chunk_idx + 1}: ~{total_est} prompt tokens ({turn_s}s)")
            chunk_idx += 1
        except Exception as exc:
            return False, {
                "seconds": round(time.monotonic() - t0, 2),
                "turns": turn_log,
                "error": f"fill turn {chunk_idx + 1}: {exc}"[:500],
            }

    messages.append(
        {"role": "user", "content": "Reply with exactly: CONTEXT_OK if you still have context."}
    )
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_output,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        resp = http_json(f"{GATEWAY}/chat/completions", method="POST", body=body, timeout=900)
        elapsed = time.monotonic() - t0
        usage = resp.get("usage") or {}
        content = (
            ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        )
        ok = "CONTEXT_OK" in content or len(content.strip()) > 0
        return ok, {
            "seconds": round(elapsed, 2),
            "turns": turn_log,
            "turn_count": len(turn_log),
            "reported_prompt_tokens": usage.get("prompt_tokens"),
            "reported_completion_tokens": usage.get("completion_tokens"),
            "reply_preview": content[:200],
        }
    except Exception as exc:
        return False, {
            "seconds": round(time.monotonic() - t0, 2),
            "turns": turn_log,
            "error": str(exc)[:500],
        }


def opencode_session_test() -> tuple[bool, dict]:
    """Three short agent turns; verifies OpenCode + sparky path after large API fill."""
    model = f"sparky/{MODEL}"
    turns: list[dict] = []
    session_id: str | None = None
    t0 = time.monotonic()

    prompts = [
        "List 3 files in this repo root (names only, one line).",
        "Run: wc -l README.md 2>/dev/null || wc -l AGENTS.md 2>/dev/null || echo no-readme",
        "Say DONE in one word if you can still respond.",
    ]

    for i, prompt in enumerate(prompts):
        cmd = [
            str(OPENCODE),
            "run",
            "-m",
            model,
            "--dir",
            str(WORKDIR),
            "--format",
            "json",
            "--log-level",
            "WARN",
        ]
        if session_id:
            cmd.extend(["-s", session_id])
        cmd.append(prompt)

        try:
            tr = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired as exc:
            turns.append({"turn": i + 1, "timeout": True, "stderr_tail": str(exc)[-400:]})
            return False, {
                "seconds": round(time.monotonic() - t0, 2),
                "turns": turns,
                "error": f"opencode turn {i + 1} timed out after 900s",
            }
        turn: dict = {
            "turn": i + 1,
            "exit_code": tr.returncode,
            "stdout_bytes": len(tr.stdout or ""),
            "stderr_tail": (tr.stderr or "")[-400:],
        }
        if tr.returncode != 0:
            turns.append(turn)
            return False, {
                "seconds": round(time.monotonic() - t0, 2),
                "turns": turns,
                "error": turn["stderr_tail"],
            }

        # extract session id from json events
        for line in (tr.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = ev.get("sessionID") or ev.get("session", {}).get("id")
            if isinstance(sid, str) and sid.startswith("ses_"):
                session_id = sid
            if ev.get("type") == "error":
                turn["event_error"] = str(ev)[:300]

        turns.append(turn)

    return True, {"seconds": round(time.monotonic() - t0, 2), "session_id": session_id, "turns": turns}


def run_step(ctx: int, fill_ratio: float, out_dir: Path) -> StepResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    target_fill = int(ctx * fill_ratio)
    res = StepResult(ctx=ctx, target_fill_tokens=target_fill, reload_ok=False, reload_seconds=0)

    ok, elapsed, detail = reload_inference(ctx)
    res.reload_ok = ok
    res.reload_seconds = round(elapsed, 1)
    (out_dir / "reload.log").write_text(detail, encoding="utf-8")
    if not ok:
        res.notes.append("reload failed")
        return res

    sync_opencode()

    try:
        models = http_json(f"{GATEWAY}/models")
        res.max_model_len = int((models["data"][0].get("max_model_len") or 0))
    except Exception as exc:
        res.notes.append(f"models fetch: {exc}")

    metrics = spark_metrics()
    (out_dir / "spark_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    res.spark_mem_pct = metrics.get("memory_used_pct")

    kv = vllm_kv_stats()
    (out_dir / "vllm_kv.log").write_text(kv.get("log_excerpt", ""), encoding="utf-8")
    res.kv_pool_tokens = kv.get("kv_pool_tokens")

    log(f"API fill test ~{target_fill} tokens (ctx={ctx})")
    api_ok, api_info = api_fill_test(target_fill)
    res.api_fill_ok = api_ok
    res.api_fill_seconds = api_info.get("seconds")
    res.api_fill_prompt_tokens = api_info.get("reported_prompt_tokens") or api_info.get(
        "estimated_prompt_tokens"
    )
    res.api_fill_error = api_info.get("error")
    (out_dir / "api_fill.json").write_text(json.dumps(api_info, indent=2), encoding="utf-8")

    if api_ok:
        log("OpenCode multi-turn smoke test")
        oc_ok, oc_info = opencode_session_test()
        res.opencode_ok = oc_ok
        res.opencode_seconds = oc_info.get("seconds")
        res.opencode_error = oc_info.get("error")
        res.opencode_turns = oc_info.get("turns") or []
        (out_dir / "opencode.json").write_text(json.dumps(oc_info, indent=2), encoding="utf-8")
    else:
        res.notes.append("skipped opencode — API fill failed")

    return res


def write_summary(run_dir: Path, results: list[StepResult]) -> None:
    md = [
        f"# Context ladder test — {run_dir.name}",
        "",
        f"Profile: `{PROFILE}` · KV: `{KV}` · Model: `{MODEL}`",
        "",
        "| ctx | max_model_len | mem% | KV pool | fill target | API fill | OpenCode | reload s |",
        "|-----|---------------|------|---------|-------------|----------|----------|----------|",
    ]
    for r in results:
        md.append(
            f"| {r.ctx} | {r.max_model_len or '—'} | {r.spark_mem_pct or '—'} | "
            f"{r.kv_pool_tokens or '—'} | {r.target_fill_tokens} | "
            f"{'✓' if r.api_fill_ok else '✗'} | {'✓' if r.opencode_ok else '✗'} | {r.reload_seconds} |"
        )
    md.extend(["", "## Details", ""])
    for r in results:
        md.append(f"### ctx={r.ctx}")
        md.append(f"```json\n{json.dumps(asdict(r), indent=2)}\n```")
        md.append("")
    (run_dir / "SUMMARY.md").write_text("\n".join(md), encoding="utf-8")
    (run_dir / "results.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--steps",
        help="Comma-separated ctx values (default: full ladder)",
    )
    args = parser.parse_args()

    if args.steps:
        steps = [(int(x.strip()), 0.92) for x in args.steps.split(",") if x.strip()]
    else:
        steps = LADDER

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"Run directory: {run_dir}")

    results: list[StepResult] = []
    for ctx, ratio in steps:
        step_dir = run_dir / f"ctx_{ctx}"
        log(f"=== STEP ctx={ctx} (fill ~{int(ctx*ratio)} tokens) ===")
        res = run_step(ctx, ratio, step_dir)
        results.append(res)
        write_summary(run_dir, results)
        if not res.reload_ok:
            log(f"STOP: reload failed at ctx={ctx}")
            break
        if not res.api_fill_ok:
            log(f"STOP: API fill failed at ctx={ctx}")
            break

    write_summary(run_dir, results)
    log(f"Done. Summary: {run_dir / 'SUMMARY.md'}")
    return 0 if all(r.reload_ok and r.api_fill_ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
