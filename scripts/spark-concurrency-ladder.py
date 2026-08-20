#!/usr/bin/env python3
"""Short concurrent decode ladder against a live OpenAI /v1 endpoint.

Mirrors the Mia Ornith-1.5 SparkDash-style table: N streams × max_tokens,
report TTFT, aggregate tok/s, per-stream tok/s. Counts completion_tokens
from usage, not SSE events.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


PROMPT = "Write a numbered list of {n} short facts about mixture-of-experts models."


def one_request(url: str, model: str, max_tokens: int, prompt: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:
        payload = json.loads(resp.read().decode())
    elapsed = time.perf_counter() - t0
    usage = payload.get("usage") or {}
    completion = int(usage.get("completion_tokens") or 0)
    prompt_tok = int(usage.get("prompt_tokens") or 0)
    return {
        "elapsed_s": elapsed,
        "completion_tokens": completion,
        "prompt_tokens": prompt_tok,
        "tok_s": (completion / elapsed) if elapsed > 0 and completion else 0.0,
    }


def run_wave(url: str, model: str, streams: int, max_tokens: int) -> dict:
    prompt = PROMPT.format(n=max(8, max_tokens // 16))
    t0 = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=streams) as pool:
        futs = [
            pool.submit(one_request, url, model, max_tokens, prompt)
            for _ in range(streams)
        ]
        for fut in as_completed(futs):
            results.append(fut.result())
    wall = time.perf_counter() - t0
    total_out = sum(r["completion_tokens"] for r in results)
    per_stream = [r["tok_s"] for r in results]
    return {
        "streams": streams,
        "wall_s": round(wall, 3),
        "ttft_proxy_s": round(min(r["elapsed_s"] for r in results), 3),
        "aggregate_tok_s": round(total_out / wall, 2) if wall else 0.0,
        "per_stream_mean": round(statistics.mean(per_stream), 2) if per_stream else 0.0,
        "per_stream_min": round(min(per_stream), 2) if per_stream else 0.0,
        "completion_tokens": total_out,
        "ok": len(results),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    ap.add_argument("--model", default="ornith-1.5-35b-a3b-nvfp4")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--streams", default="1,2,4,8,12,24")
    args = ap.parse_args()
    waves = [int(x) for x in args.streams.split(",") if x.strip()]
    print(f"# concurrency ladder  model={args.model}  max_tokens={args.max_tokens}")
    print(f"{'N':>4}  {'wall_s':>8}  {'agg_tok/s':>10}  {'per_mean':>9}  {'out_tok':>8}")
    rows = []
    for n in waves:
        row = run_wave(args.url, args.model, n, args.max_tokens)
        rows.append(row)
        print(
            f"{row['streams']:>4}  {row['wall_s']:8.2f}  {row['aggregate_tok_s']:10.2f}  "
            f"{row['per_stream_mean']:9.2f}  {row['completion_tokens']:8d}"
        )
    print(json.dumps({"ok": True, "rows": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
