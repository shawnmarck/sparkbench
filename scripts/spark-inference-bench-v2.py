#!/opt/spark/venv/bin/python3
"""Spark benchmark standard v2 — long-context fill + tool roundtrip + agent turns."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable
from urllib.request import Request, urlopen

BENCH_V2_VERSION = "2.0"
BENCH_V2_TARGET_CTX = int(os.environ.get("BENCH_V2_TARGET_CTX", "50000"))
BENCH_V2_WARMUP_SESSIONS = 1
BENCH_V2_MEASURED_SESSIONS = 2
BENCH_V2_GEN_MAX_TOKENS = 384
BENCH_V2_MIN_COMPLETION_TOKENS = 64
BENCH_V2_TEMPERATURE = 0.0
BENCH_V2_FILL_CHARS_PER_TOKEN = 4

BENCH_V2_SYSTEM = (
    "You are running a standardized throughput benchmark. "
    "Follow instructions precisely. Use tools when requested."
)

BENCH_V2_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "record_inventory_delta",
            "description": "Record a change to the model inventory index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["add", "update", "remove"]},
                    "note": {"type": "string"},
                },
                "required": ["model_id", "action"],
            },
        },
    }
]

BENCH_V2_AGENT_TURNS = [
    (
        "Summarize the prior context in exactly 6 numbered bullets. "
        "Each bullet must mention architecture, KV cache, or inference routing."
    ),
    (
        "Propose a minimal REST API with 5 endpoints for recipe lifecycle. "
        "Return markdown with endpoint, method, and one-sentence purpose each."
    ),
]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // BENCH_V2_FILL_CHARS_PER_TOKEN)


def _fill_paragraph(seed: int) -> str:
    return (
        f"Context block {seed}: repository layout, dependency graphs, service boundaries, "
        f"KV cache sizing, gateway routing, benchmark methodology, and rollout checklists "
        f"for module {seed}. Include failure modes, observability hooks, and test plans. "
    ) * 6


def build_context_fill_text(target_tokens: int) -> str:
    parts: list[str] = []
    total = 0
    i = 0
    while total < target_tokens:
        chunk = _fill_paragraph(i)
        parts.append(chunk)
        total += _estimate_tokens(chunk)
        i += 1
    return "\n\n".join(parts)


def _chat_completion(
    port: int,
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict | None = None,
    timeout: float = 600.0,
    engine: str | None = None,
) -> tuple[dict[str, Any], float]:
    req_body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": BENCH_V2_TEMPERATURE,
    }
    if tools:
        req_body["tools"] = tools
    if tool_choice is not None:
        req_body["tool_choice"] = tool_choice
    if (engine or "").strip().lower() == "ds4":
        req_body["thinking"] = {"type": "disabled"}
    body = json.dumps(req_body).encode()
    req = Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    return payload, time.perf_counter() - start


def _completion_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    if completion_tokens is not None:
        return int(completion_tokens)
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = msg.get("content") or choice.get("text") or ""
    tool_calls = msg.get("tool_calls") or []
    if tool_calls:
        return max(32, len(json.dumps(tool_calls)) // 4)
    return max(1, len(text.split()))


def _prompt_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") or {}
    val = usage.get("prompt_tokens")
    return int(val) if val is not None else 0


def _assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    return {
        "role": "assistant",
        "content": msg.get("content") or "",
        "tool_calls": msg.get("tool_calls"),
    }


def _bench_v2_session(
    port: int,
    model: str,
    *,
    fill_target_tokens: int,
    engine: str | None = None,
) -> dict[str, Any]:
    fill_text = build_context_fill_text(fill_target_tokens)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": BENCH_V2_SYSTEM},
        {
            "role": "user",
            "content": (
                "Read the following context for a later benchmark. Do not summarize yet.\n\n"
                + fill_text
            ),
        },
    ]

    # Acknowledgement turn (included in prefill stats, not decode rate).
    ack_payload, ack_elapsed = _chat_completion(
        port,
        model,
        messages,
        max_tokens=64,
        engine=engine,
    )
    messages.append(_assistant_message(ack_payload))
    prefill_prompt = _prompt_tokens(ack_payload)
    prefill_completion = _completion_tokens(ack_payload)

    decode_completion = 0
    decode_elapsed = 0.0
    tool_ok = False

    # Tool roundtrip
    messages.append(
        {
            "role": "user",
            "content": (
                "Call record_inventory_delta for model_id='qwen/qwen3.6-27b' action='update' "
                "note='golden recipe audit'. Then explain the call in one sentence."
            ),
        }
    )
    tool_payload, tool_elapsed = _chat_completion(
        port,
        model,
        messages,
        max_tokens=BENCH_V2_GEN_MAX_TOKENS,
        tools=BENCH_V2_TOOLS,
        tool_choice="auto",
        engine=engine,
    )
    tool_msg = _assistant_message(tool_payload)
    tool_calls = tool_msg.get("tool_calls") or []
    tool_ok = bool(tool_calls)
    decode_completion += _completion_tokens(tool_payload)
    decode_elapsed += tool_elapsed
    messages.append(tool_msg)
    if tool_calls:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_calls[0].get("id") or "call_bench_v2",
                "content": json.dumps({"ok": True, "recorded": True}),
            }
        )
        follow_payload, follow_elapsed = _chat_completion(
            port,
            model,
            messages,
            max_tokens=BENCH_V2_GEN_MAX_TOKENS,
            engine=engine,
        )
        decode_completion += _completion_tokens(follow_payload)
        decode_elapsed += follow_elapsed
        messages.append(_assistant_message(follow_payload))

    # Agent turns
    for user_text in BENCH_V2_AGENT_TURNS:
        messages.append({"role": "user", "content": user_text})
        payload, elapsed = _chat_completion(
            port,
            model,
            messages,
            max_tokens=BENCH_V2_GEN_MAX_TOKENS,
            engine=engine,
        )
        ct = _completion_tokens(payload)
        if ct < BENCH_V2_MIN_COMPLETION_TOKENS:
            raise RuntimeError(f"v2 bench turn too short ({ct} tok)")
        decode_completion += ct
        decode_elapsed += elapsed
        messages.append(_assistant_message(payload))

    if decode_elapsed <= 0:
        raise RuntimeError("v2 bench decode elapsed was zero")

    return {
        "context_fill_target_tokens": fill_target_tokens,
        "context_fill_estimated_tokens": _estimate_tokens(fill_text),
        "prefill_prompt_tokens": prefill_prompt,
        "prefill_completion_tokens": prefill_completion,
        "prefill_elapsed_s": ack_elapsed,
        "decode_completion_tokens": decode_completion,
        "decode_elapsed_s": decode_elapsed,
        "decode_tok_s": decode_completion / decode_elapsed,
        "tool_roundtrip_ok": tool_ok,
    }


def resolve_fill_target(recipe: dict[str, Any]) -> int:
    ctx_block = recipe.get("context") or {}
    recipe_ctx = int(ctx_block.get("default") or ctx_block.get("effective") or 32768)
    cap = min(BENCH_V2_TARGET_CTX, int(recipe_ctx * 0.85))
    return max(8192, cap)


def run_benchmark_v2(
    *,
    profile_id: str,
    recipe: dict[str, Any],
    engine_ready: Callable[[dict[str, Any]], bool],
    record_benchmark: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if not engine_ready(recipe):
        raise RuntimeError("active profile not ready — wait for /v1/models")

    port = int(recipe.get("port") or 0)
    served = str(recipe.get("served_name") or "")
    engine = recipe.get("engine")
    fill_target = resolve_fill_target(recipe)

    for _ in range(BENCH_V2_WARMUP_SESSIONS):
        _bench_v2_session(port, served, fill_target_tokens=fill_target, engine=engine)

    rates: list[float] = []
    totals: dict[str, Any] = {
        "decode_completion_tokens": 0,
        "decode_elapsed_s": 0.0,
        "tool_roundtrip_ok": True,
        "context_fill_target_tokens": fill_target,
    }
    for _ in range(BENCH_V2_MEASURED_SESSIONS):
        stats = _bench_v2_session(port, served, fill_target_tokens=fill_target, engine=engine)
        rates.append(stats["decode_tok_s"])
        totals["decode_completion_tokens"] += stats["decode_completion_tokens"]
        totals["decode_elapsed_s"] += stats["decode_elapsed_s"]
        totals["tool_roundtrip_ok"] = totals["tool_roundtrip_ok"] and stats["tool_roundtrip_ok"]

    tok_s = sum(rates) / len(rates)
    note = (
        f"bench-v2 avg {tok_s:.1f} decode tok/s ({BENCH_V2_MEASURED_SESSIONS} sessions, "
        f"~{fill_target // 1000}k ctx fill, tool_ok={totals['tool_roundtrip_ok']})"
    )
    bench = record_benchmark(
        profile_id,
        recipe,
        tok_s,
        method="bench-agent-v2",
        completion_tokens=totals["decode_completion_tokens"],
        prompt_tokens=0,
        elapsed_s=totals["decode_elapsed_s"],
        tok_s_min=min(rates),
        tok_s_max=max(rates),
        sessions=BENCH_V2_MEASURED_SESSIONS,
        turns_per_session=len(BENCH_V2_AGENT_TURNS) + 2,
        run_tok_s=rates,
        note=note,
        bench_standard_version=BENCH_V2_VERSION,
        context_fill_target_tokens=fill_target,
        tool_roundtrip_ok=totals["tool_roundtrip_ok"],
    )
    return {
        "profile": profile_id,
        "served_name": served,
        "tok_s": bench["tok_s"],
        "tok_s_min": bench.get("tok_s_min"),
        "tok_s_max": bench.get("tok_s_max"),
        "bench_standard_version": BENCH_V2_VERSION,
        "context_fill_target_tokens": fill_target,
        "tool_roundtrip_ok": totals["tool_roundtrip_ok"],
        "method": "bench-agent-v2",
    }
